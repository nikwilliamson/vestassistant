"""Card phrasing. No Home Assistant harness required.

The wording lives here rather than on the source classes precisely so it can
be tested: a Source imports homeassistant.core, and this suite has no HA.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.layout import NOTE, fit
from core.phrasing import clock_text, event_text, forecast_text


class TestClock:
    def test_gives_weekday_date_and_twelve_hour_time(self):
        assert clock_text(datetime(2026, 9, 17, 23, 5)) == "THURSDAY SEP 17 11:05 PM"

    def test_morning_hour_has_no_leading_zero(self):
        assert clock_text(datetime(2026, 9, 17, 9, 5)) == "THURSDAY SEP 17 9:05 AM"

    def test_midnight_reads_as_twelve_am(self):
        assert clock_text(datetime(2026, 9, 17, 0, 0)) == "THURSDAY SEP 17 12:00 AM"

    def test_noon_reads_as_twelve_pm(self):
        assert clock_text(datetime(2026, 9, 17, 12, 0)) == "THURSDAY SEP 17 12:00 PM"

    def test_fits_a_note(self):
        # A Note is three rows of fifteen. The longest weekday and a
        # two-digit day is the worst case.
        assert fit(clock_text(datetime(2026, 9, 24, 23, 55)), NOTE).fits


class TestForecast:
    def test_evening_says_tonight(self):
        assert forecast_text(74, "clear", datetime(2026, 9, 17, 23, 0)) == (
            "74 AND CLEAR TONIGHT."
        )

    def test_daytime_says_today(self):
        assert forecast_text(74, "clear", datetime(2026, 9, 17, 9, 0)) == (
            "74 AND CLEAR TODAY."
        )

    def test_evening_begins_at_five(self):
        assert "TONIGHT" in forecast_text(74, "clear", datetime(2026, 9, 17, 17, 0))
        assert "TODAY" in forecast_text(74, "clear", datetime(2026, 9, 17, 16, 59))

    def test_evening_prefers_the_overnight_low(self):
        # 'TONIGHT' alongside the afternoon high is a lie by juxtaposition.
        assert forecast_text(
            74, "clear", datetime(2026, 9, 17, 23, 0), overnight=58
        ) == ("58 AND CLEAR TONIGHT.")

    def test_daytime_ignores_the_overnight_low(self):
        assert forecast_text(
            74, "clear", datetime(2026, 9, 17, 9, 0), overnight=58
        ) == ("74 AND CLEAR TODAY.")

    def test_evening_falls_back_to_the_day_figure_without_an_overnight_low(self):
        assert forecast_text(74, "clear", datetime(2026, 9, 17, 23, 0)) == (
            "74 AND CLEAR TONIGHT."
        )

    def test_spells_out_run_together_conditions(self):
        # Home Assistant reports 'partlycloudy'; nobody wants that on a wall.
        assert forecast_text(60, "partlycloudy", datetime(2026, 9, 17, 9, 0)) == (
            "60 AND PARTLY CLOUDY TODAY."
        )

    def test_clear_night_is_just_clear(self):
        # The card already says when it is; 'clear night tonight' is silly.
        assert forecast_text(60, "clear-night", datetime(2026, 9, 17, 23, 0)) == (
            "60 AND CLEAR TONIGHT."
        )

    def test_rounds_the_temperature(self):
        card = forecast_text(73.6, "sunny", datetime(2026, 9, 17, 9, 0))
        assert card.startswith("74")

    def test_unknown_condition_is_dropped_rather_than_printed_raw(self):
        # Better to say less than to flip 'EXCEPTIONAL' onto the board.
        assert forecast_text(70, "exceptional", datetime(2026, 9, 17, 9, 0)) == (
            "70 TODAY."
        )

    def test_missing_temperature_still_says_something(self):
        assert forecast_text(None, "rainy", datetime(2026, 9, 17, 9, 0)) == (
            "RAINY TODAY."
        )

    def test_nothing_to_say_returns_none(self):
        assert forecast_text(None, None, datetime(2026, 9, 17, 9, 0)) is None

    def test_fits_a_note(self):
        assert fit(
            forecast_text(100, "partlycloudy", datetime(2026, 9, 17, 23, 0)), NOTE
        ).fits


class TestEventText:
    NOW = datetime(2026, 9, 18, 12, 0)

    def event(self, start, hours=1, summary="Dentist", **kw):
        return event_text(
            summary, start, start + timedelta(hours=hours), self.NOW, **kw
        )

    def test_today_with_a_time_on_the_hour(self):
        assert self.event(datetime(2026, 9, 18, 15, 0)) == "TODAY 3 PM|Dentist"

    def test_minutes_only_when_they_matter(self):
        assert self.event(datetime(2026, 9, 18, 15, 30)) == "TODAY 3:30 PM|Dentist"

    def test_tomorrow(self):
        assert self.event(datetime(2026, 9, 19, 9, 0)) == "TOMORROW 9 AM|Dentist"

    def test_a_weekday_inside_the_week(self):
        assert self.event(datetime(2026, 9, 22, 9, 0)) == "TUE 9 AM|Dentist"

    def test_a_date_beyond_the_week(self):
        assert self.event(datetime(2026, 10, 2, 9, 0)) == "OCT 2 9 AM|Dentist"

    def test_now_while_the_event_is_on(self):
        assert self.event(datetime(2026, 9, 18, 11, 30)) == "NOW|Dentist"

    def test_all_day_has_no_time(self):
        assert self.event(datetime(2026, 9, 19), hours=24, all_day=True) == (
            "TOMORROW|Dentist"
        )

    def test_an_all_day_event_in_progress_is_still_today_not_now(self):
        assert self.event(datetime(2026, 9, 18), hours=24, all_day=True) == (
            "TODAY|Dentist"
        )

    def test_the_card_fits_a_note_after_shortening(self):
        text = self.event(datetime(2026, 9, 19, 15, 0), summary="Take the bins out")
        assert fit(text, NOTE, shorten=True).fits
