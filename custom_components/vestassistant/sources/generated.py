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
from datetime import datetime, timedelta

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from ..core.layout import NOTE, Geometry
from ..core.models import TIER_CONTENT, Item
from ..core.patterns import CONTRAST, HUES, PATTERNS, TIME_OF_DAY, WHITE, render
from ..core.phrasing import clock_text, forecast_text
from .base import Source

#: How often a pattern's seed moves on, and how often a time-of-day pattern
#: is redrawn while it is up. Every rewrite is a physical flip.
PATTERN_DRIFT = timedelta(hours=1)
PATTERN_REFRESH = timedelta(minutes=15)

#: How often to ask the weather integration for a fresh forecast. Its own
#: entity updates are the primary trigger; this is the backstop for an
#: integration that revises a forecast without changing its state string.
FORECAST_POLL = timedelta(minutes=30)


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
