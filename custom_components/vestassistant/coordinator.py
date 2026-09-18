"""The runtime: timers, persistence, and the single write path to the board.

Everything that decides *what* to show lives in scheduler.py and is tested
without Home Assistant. This module is the part that has to care about clocks,
restarts, rate limits and other people touching the board.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import enum
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    POLL_INTERVAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .core.layout import Geometry, blank, decode, fit
from .core.models import (
    CursorState,
    Decision,
    Item,
    SchedulerConfig,
    Trigger,
    resolve_chrome,
)
from .core.scheduler import decide
from .transport.base import Transport, VestaboardAuthError, VestaboardError

_LOGGER = logging.getLogger(__name__)

#: How long to wait before trying again after the board refuses a write.
WRITE_RETRY = timedelta(seconds=30)


class WriteOutcome(enum.StrEnum):
    """What happened to an attempted write."""

    WRITTEN = "written"
    DEFERRED = "deferred"
    """Held back to respect the board's minimum spacing between messages."""

    FAILED = "failed"
    """The board refused it - rate limited, offline, or still flipping."""

    SKIPPED = "skipped"
    """The card could not be encoded. Not retried - the text will not
    improve on its own, and retrying it would loop until the item leaves."""


VestassistantConfigEntry = ConfigEntry["VestassistantCoordinator"]


class VestassistantCoordinator(DataUpdateCoordinator[list[list[int]]]):
    """Owns the board. Nothing else writes to it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: Transport,
        config: SchedulerConfig,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=POLL_INTERVAL,
            config_entry=entry,
        )
        self.transport = transport
        self.scheduler_config = config
        self.sources: list[Any] = []
        self.geometry: Geometry | None = transport.geometry

        self.cursor = CursorState()
        self.decision: Decision | None = None
        self._displayed_decision: Decision | None = None
        """The last decision the board actually shows.

        Distinct from ``decision``: a SKIPPED render leaves the board
        untouched, so anything reported to the user (the sensor's state) must
        keep pointing at whatever is really on the wall rather than the card
        that failed to reach it.
        """
        self._unrendered_text: str | None = None
        """The text of the most recent SKIPPED render, if any.

        ``cursor.last_rendered`` is deliberately left pointing at a SKIPPED
        card (see ``WriteOutcome.SKIPPED``), so a later, non-advancing
        re-selection of that same card reports ``write=False`` even though it
        was never actually written. ``write=False`` normally means "the board
        already shows this"; this field is how ``async_tick`` tells the two
        cases apart before trusting that assumption.
        """
        self.rotation_enabled = True
        self.paused_until: datetime | None = None

        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self._cancel_wake: CALLBACK_TYPE | None = None
        self._last_written_grid: list[list[int]] | None = None
        self._last_write_at: datetime | None = None
        self._pending_trigger: Trigger | None = None
        self._service_source: Any | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def async_prepare(self) -> None:
        """Restore persisted state and start every source."""
        stored = await self._store.async_load() or {}
        self.cursor = _cursor_from_dict(stored.get("cursor"))
        self.rotation_enabled = stored.get("rotation_enabled", True)
        if written := stored.get("last_write_at"):
            # Survives a reload. Adding a source reloads the config entry and
            # builds a fresh coordinator; without this the spacing guard reset
            # and the next write landed inside the board's flip window.
            self._last_write_at = datetime.fromisoformat(written)
        if self._service_source is not None:
            self._service_source.restore(stored.get("service_items"))

        if self.geometry is None:
            self.geometry = await self.transport.async_detect_geometry()

        for source in self.sources:
            source.set_notifier(self._source_changed)
            await source.async_setup()

    def register_source(self, source: Any) -> None:
        self.sources.append(source)
        if getattr(source, "source_id", None) == "service":
            self._service_source = source

    async def async_shutdown(self) -> None:
        self._cancel_timer()
        for source in self.sources:
            await source.async_unload()
        await self._async_save()
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # polling - the DataUpdateCoordinator half
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> list[list[int]]:
        """Read the board back.

        This is how a message posted from the Vestaboard app is noticed. A
        person deliberately writing to the board outranks the rotation; a
        competing scheduler should not be on the board at all.
        """
        try:
            grid = await self.transport.read()
        except VestaboardAuthError as err:
            raise UpdateFailed(str(err)) from err
        except VestaboardError as err:
            raise UpdateFailed(str(err)) from err

        if self.geometry is None:
            self.geometry = self.transport.geometry

        if (
            self._last_written_grid is not None
            and grid != self._last_written_grid
            and not self._within_write_settling(dt_util.now())
        ):
            _LOGGER.debug("board changed underneath us; yielding")
            self._last_written_grid = grid
            await self.async_tick(Trigger.FOREIGN_WRITE)

        return grid

    def _within_write_settling(self, now: datetime) -> bool:
        """Ignore read-back differences right after our own write."""
        if self._last_write_at is None:
            return False
        return now - self._last_write_at < timedelta(seconds=30)

    # ------------------------------------------------------------------
    # the scheduling loop
    # ------------------------------------------------------------------

    def _source_changed(self) -> None:
        """Ask for a re-evaluation. Safe to call from any thread.

        Sources are driven by state-change listeners, which usually run on the
        event loop - but not always: a registry write on a worker thread can
        reach a listener synchronously, and `async_create_task` is not thread
        safe. Home Assistant detects that and logs a RuntimeError. Hopping
        through the loop covers both cases, and costs one iteration when
        already on it.
        """
        self.hass.loop.call_soon_threadsafe(self._schedule_tick)

    @callback
    def _schedule_tick(self) -> None:
        self.hass.async_create_task(self.async_tick(Trigger.ITEMS_CHANGED))

    def collect(self, now: datetime) -> list[Item]:
        items: list[Item] = []
        for source in self.sources:
            try:
                items.extend(source.items(now))
            except Exception:
                _LOGGER.exception("source %s failed", getattr(source, "source_id", "?"))
        return items

    async def async_tick(self, trigger: Trigger = Trigger.DWELL) -> None:
        """Re-evaluate and, if the answer changed, write to the board."""
        now = dt_util.now()

        if self.paused_until and now < self.paused_until:
            self._schedule_wake(self.paused_until)
            return

        if not self.rotation_enabled:
            self._cancel_timer()
            return

        items = self.collect(now)
        decision = decide(
            items,
            now=now,
            state=self.cursor,
            config=self.scheduler_config,
            trigger=trigger,
        )
        previously_rendered = self.cursor.last_rendered
        self.cursor = decision.state
        self.decision = decision

        wake = decision.next_wake
        wake_trigger = decision.wake_trigger
        if decision.write:
            outcome = await self._async_render(decision, now)
            if outcome in (WriteOutcome.FAILED, WriteOutcome.DEFERRED):
                # The board did NOT change, so the cursor must not claim it
                # did. SKIPPED is deliberately excluded: the card is
                # unrenderable, so leaving last_rendered set is what stops
                # the scheduler offering it again every retry.
                self.cursor = self.cursor.with_(last_rendered=previously_rendered)
                wake = self._retry_at(now, outcome)
                # A retry is an ordinary tick, not a refresh: re-attempting a
                # write that failed should not also hold the board for an item
                # that may be what the board is unhappy about.
                wake_trigger = Trigger.DWELL
            elif outcome is WriteOutcome.WRITTEN:
                self._displayed_decision = decision
                self._unrendered_text = None
            else:
                # SKIPPED: nothing reached the board. last_rendered still
                # advanced (see WriteOutcome.SKIPPED), so remember the text
                # that did NOT make it, or a later write=False tick for this
                # same card would be mistaken for it being on display.
                self._unrendered_text = decision.text
            # FAILED and DEFERRED leave the board showing whatever
            # _displayed_decision already points at.
        elif decision.text != self._unrendered_text:
            # write=False usually means the board already shows this
            # decision. The exception is the card we just SKIPPED: its
            # last_rendered was left set without ever reaching the board, so
            # a non-advancing re-selection of it must not be treated as
            # displayed either.
            self._displayed_decision = decision

        self._schedule_wake(wake, wake_trigger)
        self.async_update_listeners()
        await self._async_save()

    def _retry_at(self, now: datetime, outcome: WriteOutcome) -> datetime:
        """When to come back after a write that did not land."""
        gap = self.transport.min_write_interval or WRITE_RETRY
        if outcome is WriteOutcome.DEFERRED and self._last_write_at is not None:
            return self._last_write_at + gap
        return now + max(gap, WRITE_RETRY)

    async def _async_render(self, decision: Decision, now: datetime) -> WriteOutcome:
        geometry = self.geometry
        if geometry is None:
            return WriteOutcome.FAILED

        # The cloud drops or rejects anything sent while the board is still
        # flipping, so a burst of arrivals has to be spaced rather than fired.
        gap = self.transport.min_write_interval
        if gap and self._last_write_at is not None and now < self._last_write_at + gap:
            return WriteOutcome.DEFERRED

        if decision.blank:
            grid = blank(geometry)
        else:
            chrome = (
                resolve_chrome(decision.item, self.scheduler_config.tiers)
                if decision.item is not None
                else None
            )
            result = fit(
                decision.text or "",
                geometry,
                align=self.scheduler_config_align,
                valign=self.scheduler_config_valign,
                shorten=True,
                chrome=chrome,
            )
            if result.error:
                _LOGGER.warning(
                    "cannot render %r on a %s: %s",
                    decision.text,
                    geometry.name,
                    result.error,
                )
                return WriteOutcome.SKIPPED
            if not result.fits:
                _LOGGER.warning(
                    "message does not fit a %s and was truncated: %r (dropped %r)",
                    geometry.name,
                    decision.text,
                    result.overflow,
                )
            grid = result.grid

        try:
            await self.transport.write(grid)
        except VestaboardError as err:
            _LOGGER.warning(
                "could not write to the board (will retry): %s", err
            )
            # Treat a refused write as though it had just happened, so the
            # retry still respects the spacing the board wants.
            self._last_write_at = now
            return WriteOutcome.FAILED

        self._last_written_grid = grid
        self._last_write_at = now
        return WriteOutcome.WRITTEN

    # Alignment lives on the entry options; kept as properties so the render
    # path stays readable.
    scheduler_config_align: str = "center"
    scheduler_config_valign: str = "middle"

    # ------------------------------------------------------------------
    # timers
    # ------------------------------------------------------------------

    def _cancel_timer(self) -> None:
        if self._cancel_wake is not None:
            self._cancel_wake()
            self._cancel_wake = None

    def _schedule_wake(
        self, when: datetime | None, trigger: Trigger = Trigger.DWELL
    ) -> None:
        self._cancel_timer()
        if when is None:
            return
        self._pending_trigger = trigger

        @callback
        def _fire(_now: datetime) -> None:
            self._cancel_wake = None
            self.hass.async_create_task(
                self.async_tick(self._pending_trigger or Trigger.DWELL)
            )

        self._cancel_wake = async_track_point_in_time(self.hass, _fire, when)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def async_next(self) -> None:
        await self.async_tick(Trigger.MANUAL)

    async def async_set_rotation(self, enabled: bool) -> None:
        self.rotation_enabled = enabled
        if enabled:
            await self.async_tick(Trigger.START)
        else:
            self._cancel_timer()
            await self._async_save()
            self.async_update_listeners()

    async def async_pin(self, message: str, duration: timedelta) -> None:
        """Take the board now, then hand it back to the rotation.

        Nothing about the board or the scheduler changes until the write has
        actually landed: a message that cannot be encoded, or a board that
        refuses the write, must leave the rotation exactly as it was rather
        than pausing it for ``duration`` while showing nothing.
        """
        geometry = self.geometry
        if geometry is None:
            return
        result = fit(message, geometry, align="center", valign="middle")
        if result.error:
            _LOGGER.error("cannot pin %r: %s", message, result.error)
            return
        now = dt_util.now()
        try:
            await self.transport.write(result.grid)
        except VestaboardError as err:
            _LOGGER.error("could not pin message: %s", err)
            return
        self.paused_until = now + duration
        self._last_written_grid = result.grid
        self._last_write_at = now
        self.cursor = self.cursor.with_(last_rendered=None)
        self._schedule_wake(self.paused_until, Trigger.START)
        self.async_update_listeners()

    async def async_set_dwell(self, minutes: float) -> None:
        self.scheduler_config = SchedulerConfig(
            dwell=timedelta(minutes=minutes),
            summary_threshold=self.scheduler_config.summary_threshold,
            summary_template=self.scheduler_config.summary_template,
            quiet_start=self.scheduler_config.quiet_start,
            quiet_end=self.scheduler_config.quiet_end,
            tiers=self.scheduler_config.tiers,
            blend=self.scheduler_config.blend,
            foreign_write_grace=self.scheduler_config.foreign_write_grace,
        )
        await self.async_tick(Trigger.MANUAL)

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "cursor": _cursor_to_dict(self.cursor),
                "rotation_enabled": self.rotation_enabled,
                "last_write_at": (
                    self._last_write_at.isoformat() if self._last_write_at else None
                ),
                "service_items": (
                    self._service_source.as_dict() if self._service_source else {}
                ),
            }
        )

    # ------------------------------------------------------------------
    # presentation helpers
    # ------------------------------------------------------------------

    @property
    def current_text(self) -> str | None:
        if self._displayed_decision is None:
            return None
        return self._displayed_decision.text

    @property
    def displayed_decision(self) -> Decision | None:
        """The decision that describes what the board is actually showing.

        Unlike ``decision``, this does not advance past a card the board
        rejected - see ``async_tick``.
        """
        return self._displayed_decision

    @property
    def attention_count(self) -> int:
        return self.decision.attention_count if self.decision else 0

    @property
    def board_text(self) -> str:
        return decode(self.data) if self.data else ""


def _cursor_to_dict(cursor: CursorState) -> dict:
    return {
        "current_key": cursor.current_key,
        "current_card": cursor.current_card,
        "shown_at": cursor.shown_at.isoformat() if cursor.shown_at else None,
        "last_rendered": cursor.last_rendered,
        "attention_key": cursor.attention_key,
        "content_key": cursor.content_key,
        "last_was_attention": cursor.last_was_attention,
        "known_keys": list(cursor.known_keys),
    }


def _cursor_from_dict(data: dict | None) -> CursorState:
    if not data:
        return CursorState()
    shown = data.get("shown_at")
    return CursorState(
        current_key=data.get("current_key"),
        current_card=data.get("current_card", 0),
        shown_at=datetime.fromisoformat(shown) if shown else None,
        # last_rendered is deliberately not restored: we cannot be sure the
        # board still shows it after a restart, and a redundant write is
        # cheaper than a board stuck displaying something stale.
        last_rendered=None,
        attention_key=data.get("attention_key"),
        content_key=data.get("content_key"),
        last_was_attention=data.get("last_was_attention", False),
        known_keys=tuple(data.get("known_keys") or ()),
    )
