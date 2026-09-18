"""The runtime: timers, persistence, and the single write path to the board.

Everything that decides *what* to show lives in scheduler.py and is tested
without Home Assistant. This module is the part that has to care about clocks,
restarts, rate limits and other people touching the board.
"""

from __future__ import annotations

import asyncio
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

from .const import POLL_INTERVAL, STORAGE_KEY, STORAGE_VERSION
from .core.layout import Geometry, blank, decode, fit
from .core.models import (
    CursorState,
    Decision,
    Item,
    SchedulerConfig,
    Trigger,
    resolve_band,
)
from .core.scheduler import decide
from .sources.base import Source
from .sources.dynamic import ServiceSource
from .transport.base import Transport, VestaboardError

_LOGGER = logging.getLogger(__name__)

#: How long to wait before trying again after the board refuses a write, and
#: how long after our own write a read-back difference is still the board
#: catching up rather than somebody else posting.
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


type VestassistantConfigEntry = ConfigEntry[VestassistantCoordinator]


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
        self.sources: list[Source] = []
        self.service_source: ServiceSource | None = None
        self.geometry: Geometry | None = transport.geometry

        self.cursor = CursorState()
        self.decision: Decision | None = None
        self.queue: list[Item] = []
        """The items collected on the last tick, for the sensor's attributes.

        Snapshotted rather than re-collected on demand: collecting has side
        effects (a satisfied ``expire_when`` removes its item) and must not
        happen from an entity's state-attribute property.
        """
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
        """While set, the rotation leaves the board alone: a pin, a typed
        message, or a human posting from the Vestaboard app."""
        self.typed_message: str = ""
        """The last message typed straight at the board, for the text entity."""

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self._cancel_wake: CALLBACK_TYPE | None = None
        self._last_written_grid: list[list[int]] | None = None
        self._last_write_at: datetime | None = None
        self._pending_trigger: Trigger | None = None
        self._tick_lock = asyncio.Lock()
        self._queued_tick: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def async_prepare(self) -> None:
        """Restore persisted state and start every source."""
        stored = await self._store.async_load() or {}
        self.cursor = _cursor_from_dict(stored.get("cursor"))
        self.rotation_enabled = stored.get("rotation_enabled", True)
        self.typed_message = stored.get("typed_message", "")
        if written := stored.get("last_write_at"):
            # Survives a reload. Adding a source reloads the config entry and
            # builds a fresh coordinator; without this the spacing guard reset
            # and the next write landed inside the board's flip window.
            self._last_write_at = datetime.fromisoformat(written)
        if paused := stored.get("paused_until"):
            # Likewise: a settings change mid-pin reloads the entry, and the
            # pin must outlive that or the START tick overwrites it.
            self.paused_until = datetime.fromisoformat(paused)
        if self.service_source is not None:
            self.service_source.restore(stored.get("service_items"))

        if self.geometry is None:
            self.geometry = await self.transport.async_detect_geometry()

        for source in self.sources:
            source.set_notifier(self._source_changed)
            await source.async_setup()

    def register_source(self, source: Source) -> None:
        self.sources.append(source)
        if isinstance(source, ServiceSource):
            self.service_source = source

    async def async_shutdown(self) -> None:
        self._cancel_timer()
        if self._queued_tick is not None:
            self._queued_tick.cancel()
            self._queued_tick = None
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
            await self.async_hold(self.scheduler_config.foreign_write_grace)

        return grid

    def _within_write_settling(self, now: datetime) -> bool:
        """Ignore read-back differences right after our own write."""
        if self._last_write_at is None:
            return False
        return now - self._last_write_at < WRITE_RETRY

    # ------------------------------------------------------------------
    # the scheduling loop
    # ------------------------------------------------------------------

    @callback
    def _source_changed(self) -> None:
        """Ask for a re-evaluation. Coalesces a burst of changes into one tick."""
        if self._queued_tick is not None:
            return
        self._queued_tick = self.hass.async_create_task(self._async_queued_tick())

    async def _async_queued_tick(self) -> None:
        # Cleared before the tick runs, so a change that lands while this
        # tick is collecting queues another rather than being lost.
        self._queued_tick = None
        await self.async_tick(Trigger.ITEMS_CHANGED)

    def collect(self, now: datetime) -> list[Item]:
        items: list[Item] = []
        for source in self.sources:
            try:
                items.extend(source.items(now))
            except Exception:  # one bad source must not stop the rest
                _LOGGER.exception("source %s failed", source.source_id)
        return items

    async def async_tick(self, trigger: Trigger = Trigger.DWELL) -> None:
        """Re-evaluate and, if the answer changed, write to the board.

        Serialised: a poll noticing a foreign write, a timer and a source
        change can all arrive at once, and two ticks interleaving across the
        write would each act on the same cursor and both flip the board.
        """
        async with self._tick_lock:
            await self._async_tick(trigger)

    async def _async_tick(self, trigger: Trigger) -> None:
        now = dt_util.now()

        if self.paused_until:
            if now < self.paused_until:
                self._schedule_wake(self.paused_until, Trigger.START)
                return
            # The hold has run out. Clear the typed message with it, so the
            # text box stops claiming something the board no longer shows.
            self.paused_until = None
            self.typed_message = ""

        if not self.rotation_enabled:
            self._cancel_timer()
            return

        items = self.collect(now)
        self.queue = items
        previous = self.cursor
        decision = decide(
            items,
            now=now,
            state=previous,
            config=self.scheduler_config,
            trigger=trigger,
        )
        self.cursor = decision.state
        self.decision = decision

        wake = decision.next_wake
        wake_trigger = decision.wake_trigger
        if decision.write:
            outcome = await self._async_render(decision, now)
            if outcome in (WriteOutcome.FAILED, WriteOutcome.DEFERRED):
                # The board did NOT change, so nothing about the cursor may
                # claim it did. Put the whole pre-decision state back and
                # replay the same trigger later: decide is deterministic, so
                # the retry re-picks this card instead of advancing past it.
                # SKIPPED is deliberately excluded: the card is unrenderable,
                # and leaving last_rendered set is what stops the scheduler
                # offering it again every retry.
                self.cursor = previous
                wake, wake_trigger = self._retry_at(now, outcome), trigger
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
            if not self.transport.supports_blank:
                # The cloud refuses a blank message. Leave the last card up:
                # a stale card beats a warning every thirty seconds forever.
                _LOGGER.debug("nothing to show; a %s cannot be blanked", geometry.name)
                return WriteOutcome.WRITTEN
            grid = blank(geometry)
        else:
            item = decision.item
            band = (
                resolve_band(item.tier, item.colour, self.scheduler_config.tiers)
                if item is not None
                else None
            )
            result = fit(decision.text or "", geometry, shorten=True, band=band)
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

        if not await self._async_write(grid, now):
            return WriteOutcome.FAILED
        return WriteOutcome.WRITTEN

    async def _async_write(self, grid: list[list[int]], now: datetime) -> bool:
        """The one place a grid goes to the board. True if it landed."""
        try:
            await self.transport.write(grid)
        except VestaboardError as err:
            _LOGGER.warning("could not write to the board (will retry): %s", err)
            # Treat a refused write as though it had just happened, so the
            # retry still respects the spacing the board wants.
            self._last_write_at = now
            return False
        self._last_written_grid = grid
        self._last_write_at = now
        # Hand the grid to the entities now rather than when the next poll
        # reads it back, so the preview image and board text do not lag the
        # wall by up to a minute.
        self.async_set_updated_data(grid)
        return True

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

    async def async_pin(self, message: str, duration: timedelta) -> bool:
        """Take the board now, then hand it back to the rotation.

        Nothing about the board or the scheduler changes until the write has
        actually landed: a message that cannot be encoded, or a board that
        refuses the write, must leave the rotation exactly as it was rather
        than pausing it for ``duration`` while showing nothing. Returns
        whether it landed.
        """
        geometry = self.geometry
        if geometry is None:
            return False
        # shorten=True to match what the text entity validated against;
        # without it a message that fit only by abbreviation gets truncated.
        result = fit(message, geometry, shorten=True)
        if result.error:
            _LOGGER.error("cannot pin %r: %s", message, result.error)
            return False
        async with self._tick_lock:
            now = dt_util.now()
            if not await self._async_write(result.grid, now):
                return False
            self._hold_until(now + duration)
        return True

    async def async_hold(self, duration: timedelta) -> None:
        """Leave whatever is on the board alone for ``duration``.

        Used when a person posts from the Vestaboard app: yield to people,
        not to robots.
        """
        async with self._tick_lock:
            self._hold_until(dt_util.now() + duration)

    def _hold_until(self, when: datetime) -> None:
        self.paused_until = when
        # Forget what we last rendered: the board no longer shows it, and
        # when the hold ends the resumed card must be rewritten even if it
        # is the same text as before.
        self.cursor = self.cursor.with_(last_rendered=None)
        self._schedule_wake(when, Trigger.START)
        self.async_update_listeners()

    async def async_release(self) -> None:
        """Hand the board back to the rotation before a hold has run out."""
        if self.paused_until is None:
            return
        self.paused_until = None
        await self.async_tick(Trigger.START)

    @callback
    def async_set_option(self, key: str, value: Any) -> None:
        """Write one option and let the entry reload apply it.

        The entry's options are the single source of truth: a value set from
        an entity reads back the same in Settings, and survives a restart,
        which in-memory state did not. Reloading rebuilds the scheduler and
        the source list; the board is undisturbed, because the rotation
        cursor and any hold are persisted.
        """
        entry = self.config_entry
        if entry.options.get(key) == value:
            return
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, key: value}
        )

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "cursor": _cursor_to_dict(self.cursor),
                "rotation_enabled": self.rotation_enabled,
                "typed_message": self.typed_message,
                "paused_until": (
                    self.paused_until.isoformat() if self.paused_until else None
                ),
                "last_write_at": (
                    self._last_write_at.isoformat() if self._last_write_at else None
                ),
                "service_items": (
                    self.service_source.as_dict() if self.service_source else {}
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


def _cursor_to_dict(cursor: CursorState) -> dict[str, Any]:
    return {
        "current_key": cursor.current_key,
        "shown_at": cursor.shown_at.isoformat() if cursor.shown_at else None,
        "last_rendered": cursor.last_rendered,
        "attention_key": cursor.attention_key,
        "content_key": cursor.content_key,
        "last_was_attention": cursor.last_was_attention,
        "known_keys": list(cursor.known_keys),
    }


def _cursor_from_dict(data: dict[str, Any] | None) -> CursorState:
    if not data:
        return CursorState()
    shown = data.get("shown_at")
    return CursorState(
        current_key=data.get("current_key"),
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
