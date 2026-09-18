"""Wording for the generated cards.

Lives beside the scheduler rather than on the source classes, and for the
same reason: a Source imports Home Assistant, and everything here is a
decision worth testing directly - when evening starts, what a run-together
condition is called in English, what to say when half the data is missing.

Pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["CONDITIONS", "EVENING_HOUR", "clock_text", "forecast_text"]

#: The hour at which the card stops describing today and starts describing
#: tonight. Five is early enough to be useful before dark in winter.
EVENING_HOUR = 17

#: Home Assistant's condition strings, in words a board can say. Anything
#: missing from this map is dropped rather than printed: an unrecognised
#: condition is more likely to be a new HA string than something worth
#: flipping forty tiles for, and 'EXCEPTIONAL' tells nobody anything.
CONDITIONS: dict[str, str] = {
    "clear": "CLEAR",
    "clear-night": "CLEAR",
    "cloudy": "CLOUDY",
    "fog": "FOGGY",
    "hail": "HAIL",
    "lightning": "STORMY",
    "lightning-rainy": "STORMY",
    "partlycloudy": "PARTLY CLOUDY",
    "pouring": "POURING",
    "rainy": "RAINY",
    "snowy": "SNOWY",
    "snowy-rainy": "SLEETY",
    "sunny": "SUNNY",
    "windy": "WINDY",
    "windy-variant": "WINDY",
}


def clock_text(now: datetime) -> str:
    """The clock card: weekday, date, and the time in twelve-hour form.

    No leading zero on the hour - a board is read from across a room, and
    '09:05' reads as a duration rather than a time.
    """
    weekday = now.strftime("%A").upper()
    month = now.strftime("%b").upper()
    hour = now.hour % 12 or 12
    meridiem = "AM" if now.hour < 12 else "PM"
    return f"{weekday} {month} {now.day} {hour}:{now.minute:02d} {meridiem}"


def forecast_text(
    temperature: float | None,
    condition: str | None,
    now: datetime,
    overnight: float | None = None,
) -> str | None:
    """The forecast card, or None when there is nothing worth saying.

    ``temperature`` is the daily figure - usually the high - and ``overnight``
    the low. Once the card starts saying TONIGHT it has to quote the low, or
    it reads as a promise of the afternoon it has just been through.

    Returning None rather than a half-built sentence matters: the source uses
    it to contribute no item at all, so a weather integration that is still
    starting up leaves the rotation alone instead of putting a stub on the
    wall.
    """
    evening = now.hour >= EVENING_HOUR
    period = "TONIGHT" if evening else "TODAY"
    phrase = CONDITIONS.get(condition.strip().lower()) if condition else None
    reading = overnight if evening and overnight is not None else temperature
    degrees = f"{round(reading)}" if reading is not None else None

    if degrees and phrase:
        body = f"{degrees} AND {phrase}"
    elif degrees:
        body = degrees
    elif phrase:
        body = phrase
    else:
        return None
    return f"{body} {period}."
