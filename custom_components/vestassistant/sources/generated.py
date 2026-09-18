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

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from ..core.models import TIER_CONTENT, Item
from ..core.phrasing import clock_text, forecast_text
from .base import Source

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
                cards=(clock_text(now),),
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
        source_id: str = "forecast",
        name: str = "Forecast",
        entity_id: str = "",
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

    def _handle_state(self, event) -> None:
        """Same thread-safety caveat as the coordinator's notifier."""
        self.hass.loop.call_soon_threadsafe(self._spawn_refresh)

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
        except Exception:
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
                cards=(text,),
                tier=self.tier,
                meta={"source_name": self.name, "entity_id": self.entity_id},
            )
        ]
