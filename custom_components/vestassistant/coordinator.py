"""The runtime: timers, persistence, and the single write path to the board.

Everything that decides *what* to show lives in scheduler.py and is tested
without Home Assistant. This module is the part that has to care about clocks,
restarts, rate limits and other people touching the board.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
)
from .core.scheduler import decide
from .transport.base import Transport, VestaboardAuthError, VestaboardError

_LOGGER = logging.getLogger(__name__)

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

    @callback
    def _source_changed(self) -> None:
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
        self.cursor = decision.state
        self.decision = decision

        if decision.write:
            await self._async_render(decision, now)

        self._schedule_wake(decision.next_wake)
        self.async_update_listeners()
        await self._async_save()

    async def _async_render(self, decision: Decision, now: datetime) -> None:
        geometry = self.geometry
        if geometry is None:
            return

        # The cloud silently drops anything sent inside its write window, so a
        # burst of arrivals has to be spaced rather than fired.
        gap = self.transport.min_write_interval
        if gap and self._last_write_at is not None:
            earliest = self._last_write_at + gap
            if now < earliest:
                self._schedule_wake(earliest, Trigger.MANUAL)
                return

        if decision.blank:
            grid = blank(geometry)
        else:
            result = fit(
                decision.text or "",
                geometry,
                align=self.scheduler_config_align,
                valign=self.scheduler_config_valign,
            )
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
            _LOGGER.error("could not write to the board: %s", err)
            return

        self._last_written_grid = grid
        self._last_write_at = now

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
        """Take the board now, then hand it back to the rotation."""
        now = dt_util.now()
        self.paused_until = now + duration
        geometry = self.geometry
        if geometry is None:
            return
        result = fit(message, geometry, align="center", valign="middle")
        try:
            await self.transport.write(result.grid)
        except VestaboardError as err:
            _LOGGER.error("could not pin message: %s", err)
            return
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
        if self.decision is None:
            return None
        return self.decision.text

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
