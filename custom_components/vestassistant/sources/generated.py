"""Sources that compute their items rather than storing or tracking them.

Both of these are built from the entry's options instead of a subentry: they
are one-per-board and have nothing to name, so a switch you can turn off
without losing its settings is a better fit than a subentry you would have to
delete. See ``base.Source`` - a generator plugs into the same contract with no
changes above this line.

The wording lives in ``core.phrasing``, which has no Home Assistant imports
and is unit tested directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..core.layout import NOTE, Geometry
from ..core.models import TIER_CONTENT, Item
from ..core.patterns import CONTRAST, HUES, PATTERNS, TIME_OF_DAY, WHITE, render
from ..core.phrasing import clock_text, event_text, forecast_text
from .base import Source

#: How often a pattern's seed moves on, and how often a time-of-day pattern
#: is redrawn while it is up. Every rewrite is a physical flip.
PATTERN_DRIFT = timedelta(hours=1)
PATTERN_REFRESH = timedelta(minutes=15)

#: How often to re-read a calendar. Its entity only changes state when the
#: current event does, so an event added for later in the day would
#: otherwise not show until something else moved.
CALENDAR_POLL = timedelta(minutes=15)

#: How often to ask the weather integration for a fresh forecast. Its own
#: entity updates are the primary trigger; this is the backstop for an
#: integration that revises a forecast without changing its state string.
FORECAST_POLL = timedelta(minutes=30)

_LOGGER = logging.getLogger(__name__)


class ClockSource(Source):
    """The date and time, rewritten in place as it goes stale.

    The only source whose text is a function of nothing but ``now``, which is
    why it needs no state tracking at all - and why it carries ``refresh``:
    without it the card would sit on the board reading whatever time it was
    when the item came up, for a full dwell.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str = "clock",
        name: str = "Clock",
        refresh: timedelta = timedelta(minutes=5),
        tier: str = TIER_CONTENT,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.refresh = refresh
        self.tier = tier

    def items(self, now: datetime) -> list[Item]:
        # A stable id, so the cursor keeps tracking the same item across
        # rewrites. Only the text changes, which is exactly what makes the
        # scheduler's last_rendered check decide to flip the board.
        return [
            Item(
                id="now",
                source=self.source_id,
                text=clock_text(now),
                tier=self.tier,
                refresh=self.refresh,
                meta={"source_name": self.name},
            )
        ]


class ForecastSource(Source):
    """Temperature and conditions for the rest of the day, or for tonight.

    Caches like ``TodoSource`` and for the same reason: the forecast comes
    from ``weather.get_forecasts``, which is async, and the scheduler runs
    synchronously.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        *,
        source_id: str = "forecast",
        name: str = "Forecast",
        tier: str = TIER_CONTENT,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_id = entity_id
        self.tier = tier
        self._temperature: float | None = None
        self._overnight: float | None = None
        self._condition: str | None = None

    async def async_setup(self) -> None:
        await self._refresh()
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self.entity_id], self._handle_state
            )
        )
        self._listeners.append(
            async_track_time_interval(self.hass, self._handle_interval, FORECAST_POLL)
        )

    @callback
    def _handle_state(self, _event: Event[EventStateChangedData]) -> None:
        self._spawn_refresh()

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._spawn_refresh()

    @callback
    def _spawn_refresh(self) -> None:
        self.hass.async_create_task(self._refresh_and_notify())

    async def _refresh_and_notify(self) -> None:
        before = (self._temperature, self._overnight, self._condition)
        await self._refresh()
        # Only disturb the rotation when the card would actually read
        # differently; a forecast that firmed up by a tenth of a degree is
        # not worth a re-evaluation.
        if (self._temperature, self._overnight, self._condition) != before:
            self._changed()

    async def _refresh(self) -> None:
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": self.entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except Exception:  # the weather integration may be down
            # Leave the previous reading in place rather than blanking the
            # card: a stale forecast is better than no forecast, and the
            # entity is about to tell us when it recovers.
            return
        forecasts = (response or {}).get(self.entity_id, {}).get("forecast") or []
        if not forecasts:
            return
        today = forecasts[0]
        self._temperature = today.get("temperature")
        # The overnight low, which is what the card quotes once it starts
        # saying TONIGHT. Not every integration reports it.
        self._overnight = today.get("templow")
        self._condition = today.get("condition")

    def items(self, now: datetime) -> list[Item]:
        text = forecast_text(
            self._temperature, self._condition, now, overnight=self._overnight
        )
        if text is None:
            return []
        return [
            Item(
                id="today",
                source=self.source_id,
                text=text,
                tier=self.tier,
                meta={"source_name": self.name, "entity_id": self.entity_id},
            )
        ]


class PatternSource(Source):
    """Decorative fills, one item per chosen pattern.

    The only source built from a subentry that is not made of words. Each
    pattern is one card in the content rotation, so the board is coloured
    between messages rather than instead of them. The wording - or rather
    the drawing - lives in ``core.patterns``.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        patterns: list[str],
        hues: list[int | str] | None = None,
        contrast: int = WHITE,
        geometry_getter: Callable[[], Geometry | None] | None = None,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.patterns = [p for p in patterns if p in PATTERNS]
        self.hues = tuple(h for h in (hues or []) if h in HUES or h == CONTRAST)
        self.contrast = contrast
        self._geometry = geometry_getter or (lambda: None)

    def items(self, now: datetime) -> list[Item]:
        geometry = self._geometry() or NOTE
        # Floored to the hour: the same seed for every tick inside it, so a
        # pattern on the board is not rewritten by an unrelated queue change.
        seed = int(now.timestamp()) // int(PATTERN_DRIFT.total_seconds())
        return [
            Item(
                id=name,
                source=self.source_id,
                text=render(
                    name,
                    geometry,
                    self.hues,
                    contrast=self.contrast,
                    seed=seed,
                    now=now,
                ),
                tier=TIER_CONTENT,
                refresh=PATTERN_REFRESH if name in TIME_OF_DAY else None,
                meta={"source_name": self.name, "label": name.title()},
            )
            for name in self.patterns
        ]


@dataclass(frozen=True, slots=True)
class _Event:
    uid: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool


class CalendarSource(Source):
    """Upcoming events from a Home Assistant calendar, one card each.

    Reads ``calendar.get_events`` for a window of whole days and keeps the
    result, for the same reason ``TodoSource`` does. Each event carries its
    end as the item's expiry, so a card leaves the board when the event is
    over rather than on the next unrelated tick.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        entity_id: str,
        *,
        days: int = 2,
        max_events: int = 3,
        tier: str = TIER_CONTENT,
        colour: int | None = None,
    ) -> None:
        super().__init__(hass, source_id, name)
        self.entity_id = entity_id
        self.days = max(1, days)
        self.max_events = max(1, max_events)
        self.tier = tier
        self.colour = colour
        self._events: list[_Event] = []

    async def async_setup(self) -> None:
        await self._refresh()
        self._listeners.append(
            async_track_state_change_event(
                self.hass, [self.entity_id], self._handle_state
            )
        )
        self._listeners.append(
            async_track_time_interval(self.hass, self._handle_interval, CALENDAR_POLL)
        )

    @callback
    def _handle_state(self, _event: Event[EventStateChangedData]) -> None:
        self._spawn_refresh()

    @callback
    def _handle_interval(self, _now: datetime) -> None:
        self._spawn_refresh()

    @callback
    def _spawn_refresh(self) -> None:
        self.hass.async_create_task(self._refresh_and_notify())

    async def _refresh_and_notify(self) -> None:
        before = self._events
        await self._refresh()
        if self._events != before:
            self._changed()

    async def _refresh(self) -> None:
        now = dt_util.now()
        start = dt_util.start_of_local_day(now)
        end = start + timedelta(days=self.days)
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": self.entity_id,
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except Exception:  # the calendar integration may be down
            _LOGGER.debug("could not read %s; keeping the last events", self.entity_id)
            return
        raw = (response or {}).get(self.entity_id, {}).get("events") or []
        events = [e for e in (_parse_event(r) for r in raw) if e is not None]
        self._events = sorted(events, key=lambda e: e.start)

    def items(self, now: datetime) -> list[Item]:
        out: list[Item] = []
        for event in self._events:
            if event.end <= now:
                continue
            out.append(
                Item(
                    id=event.uid,
                    source=self.source_id,
                    text=event_text(
                        event.summary,
                        event.start,
                        event.end,
                        now,
                        all_day=event.all_day,
                    ),
                    tier=self.tier,
                    colour=self.colour,
                    expires=event.end,
                    meta={"source_name": self.name, "entity_id": self.entity_id},
                )
            )
            if len(out) >= self.max_events:
                break
        return out


def _parse_event(raw: dict[str, Any]) -> _Event | None:
    summary = str(raw.get("summary") or "").strip()
    if not summary:
        return None
    start, all_day = _parse_when(raw.get("start"))
    end, _ = _parse_when(raw.get("end"))
    if start is None or end is None:
        return None
    return _Event(
        uid=str(raw.get("uid") or f"{start.isoformat()}:{summary}"),
        summary=summary,
        start=start,
        end=end,
        all_day=all_day,
    )


def _parse_when(value: object) -> tuple[datetime | None, bool]:
    """A calendar timestamp: a datetime, or a bare date for an all-day event.

    The date is tried first: ``parse_datetime`` happily reads ``2026-09-19``
    as midnight, which would make every all-day event look timed.
    """
    if isinstance(value, dict):
        # The REST shape, {"dateTime": ...} or {"date": ...}, in case a
        # calendar platform hands it through unflattened.
        value = value.get("dateTime") or value.get("date")
    if not isinstance(value, str):
        return None, False
    if "T" not in value and (day := dt_util.parse_date(value)) is not None:
        midnight = datetime.combine(day, datetime.min.time())
        return dt_util.start_of_local_day(midnight), True
    if (when := dt_util.parse_datetime(value)) is not None:
        return dt_util.as_local(when), False
    return None, False
