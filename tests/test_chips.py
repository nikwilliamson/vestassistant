"""Chip strings. No Home Assistant harness required."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)

from vesta.chars import encode

from core.chips import (
    BLUE,
    GREEN,
    PALETTE,
    RED,
    bar,
    escape,
    gradient,
    pattern,
    row,
)
from core.layout import FLAGSHIP, NOTE, fit


def codes(text: str, geometry):
    """Render through the real pipeline and return the first non-blank row."""
    result = fit(text, geometry, valign="top")
    assert result.error == "", result.error
    return result.grid[0]


def cells(text: str) -> int:
    """How many board cells a builder's output actually occupies."""
    return len(encode(text))


class TestPalette:
    def test_is_the_six_safe_hues(self):
        assert PALETTE == (63, 64, 65, 66, 67, 68)

    def test_excludes_white_black_and_filled(self):
        # 71 is unavailable on the local API; 69 and 70 invert with the
        # board's physical colour, which neither API reports.
        assert not ({69, 70, 71} & set(PALETTE))


class TestEscape:
    def test_wraps_a_code_in_braces(self):
        assert escape(RED) == "{63}"


class TestRow:
    def test_pads_to_full_width(self):
        output = row([RED, BLUE], NOTE.cols)
        assert cells(output) == NOTE.cols
        assert len(codes(output, NOTE)) == NOTE.cols

    def test_places_the_codes_in_order(self):
        assert codes(row([RED, BLUE], NOTE.cols), NOTE)[:2] == [63, 67]

    def test_pads_with_blanks(self):
        assert codes(row([RED], NOTE.cols), NOTE)[1:] == [0] * (NOTE.cols - 1)

    def test_truncates_codes_beyond_the_width(self):
        output = row([RED] * 40, NOTE.cols)
        assert cells(output) == NOTE.cols
        assert len(codes(output, NOTE)) == NOTE.cols


class TestBar:
    def test_empty_bar_is_all_blank(self):
        assert codes(bar(0.0, FLAGSHIP.cols), FLAGSHIP) == [0] * FLAGSHIP.cols

    def test_full_bar_is_all_colour(self):
        assert codes(bar(1.0, FLAGSHIP.cols), FLAGSHIP) == [GREEN] * FLAGSHIP.cols

    def test_half_bar_fills_half(self):
        filled = [c for c in codes(bar(0.5, FLAGSHIP.cols), FLAGSHIP) if c == GREEN]
        assert len(filled) == 11

    def test_clamps_above_one(self):
        assert codes(bar(4.0, NOTE.cols), NOTE) == [GREEN] * NOTE.cols

    def test_clamps_below_zero(self):
        assert codes(bar(-1.0, NOTE.cols), NOTE) == [0] * NOTE.cols

    def test_takes_a_colour(self):
        assert codes(bar(1.0, NOTE.cols, colour=RED), NOTE) == [RED] * NOTE.cols

    def test_never_uses_filled(self):
        # 71 would work on cloud and silently do nothing on local.
        assert 71 not in codes(bar(1.0, FLAGSHIP.cols), FLAGSHIP)


class TestGradient:
    def test_fills_the_full_width(self):
        output = gradient([RED, BLUE], FLAGSHIP.cols)
        assert cells(output) == FLAGSHIP.cols
        assert len(codes(output, FLAGSHIP)) == 22

    def test_starts_and_ends_on_the_stops(self):
        result = codes(gradient([RED, BLUE], FLAGSHIP.cols), FLAGSHIP)
        assert result[0] == RED
        assert result[-1] == BLUE

    def test_a_single_stop_is_a_solid_row(self):
        assert codes(gradient([RED], NOTE.cols), NOTE) == [RED] * NOTE.cols


class TestPattern:
    def test_covers_the_whole_board(self):
        output = pattern(7, FLAGSHIP)
        lines = output.split('\n')
        assert len(lines) == FLAGSHIP.rows
        assert all(cells(line) == FLAGSHIP.cols for line in lines)
        result = fit(output, FLAGSHIP, valign="top")
        assert result.error == ""
        assert len(result.grid) == FLAGSHIP.rows
        assert all(len(r) == FLAGSHIP.cols for r in result.grid)

    def test_is_deterministic(self):
        assert pattern(7, NOTE) == pattern(7, NOTE)

    def test_differs_by_seed(self):
        assert pattern(7, NOTE) != pattern(8, NOTE)

    def test_only_uses_the_palette(self):
        result = fit(pattern(3, NOTE), NOTE, valign="top")
        assert all(c in PALETTE for r in result.grid for c in r)
