"""The abbreviation ladder. No Home Assistant harness required."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)

from core.fitting import variants


def rung(text: str, name: str) -> str:
    return next(t for n, t in variants(text) if n == name)


class TestLadder:
    def test_first_rung_is_the_text_as_written(self):
        first = next(iter(variants("THE BINS ARE OUT")))
        assert first == ("", "THE BINS ARE OUT")

    def test_rungs_come_in_order(self):
        assert [n for n, _ in variants("THE BINS")] == [
            "",
            "abbreviations",
            "articles",
        ]


class TestAbbreviations:
    def test_shortens_a_known_word(self):
        assert rung("BINS OUT TOMORROW", "abbreviations") == "BINS OUT TMRW"

    def test_replaces_and_with_an_ampersand(self):
        assert rung("CHEESE AND PICKLE", "abbreviations") == "CHEESE & PICKLE"

    def test_shortens_street(self):
        assert rung("HIGH STREET", "abbreviations") == "HIGH ST"

    def test_only_matches_whole_words(self):
        # 'ANDREW' must not become '&REW'.
        assert rung("ANDREW", "abbreviations") == "ANDREW"

    def test_leaves_unknown_words_alone(self):
        assert rung("BANANA", "abbreviations") == "BANANA"


class TestArticles:
    def test_drops_articles(self):
        assert rung("THE BINS ARE OUT", "articles") == "BINS ARE OUT"

    def test_only_matches_whole_words(self):
        # 'THEATRE' must survive.
        assert rung("THE THEATRE", "articles") == "THEATRE"

    def test_keeps_abbreviations_from_the_previous_rung(self):
        assert rung("THE BINS GO OUT TOMORROW", "articles") == "BINS GO OUT TMRW"

    def test_collapses_the_gap_left_behind(self):
        assert "  " not in rung("TAKE THE BINS OUT", "articles")
