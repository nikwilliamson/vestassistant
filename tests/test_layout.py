"""Layout and fitting, against both board geometries."""

from __future__ import annotations

from pathlib import Path
import sys

# Import the framework-free core directly: it must never need Home Assistant.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)

from core.layout import (
    FLAGSHIP,
    NOTE,
    Geometry,
    fit,
    geometry_from_grid,
)


def test_note_grid_is_three_by_fifteen():
    r = fit("HELLO", NOTE)
    assert len(r.grid) == 3
    assert all(len(row) == 15 for row in r.grid)
    assert r.fits


def test_flagship_grid_is_six_by_twentytwo():
    r = fit("HELLO", FLAGSHIP)
    assert len(r.grid) == 6
    assert all(len(row) == 22 for row in r.grid)


def test_wraps_at_word_boundaries():
    r = fit("PUT THE CLOTHES IN THE DRYER.", NOTE, align="left", valign="top")
    lines = [line.rstrip() for line in r.preview.splitlines() if line.strip()]
    # Matches the wrapping documented in the original laundry.yaml comment.
    assert lines == ["PUT THE CLOTHES", "IN THE DRYER."]
    assert r.fits


def test_real_messages_fit_the_note():
    """Every message currently hardcoded in the YAML packages."""
    for message in [
        "PUT THE CLOTHES IN THE DRYER.",
        "WASHER DONE. DRYER IS STILL GOING.",
        "DRYER IS DONE. SWAP THE LOADS.",
        "LAUNDRY IS DONE.",
        "TAKE THE RECYCLING OUT.",
        "TAKE THE TRASH OUT.",
        "EMPTY THE LITTER DRAWER.",
        "STOVE LEFT ON. GO CHECK IT.",
        "OVEN LEFT ON. GO CHECK IT.",
        "AC NOT COOLING. CONDENSER IS OFF.",
        "AC IS ON BUT NOT COOLING.",
        "AC IS COOLING AGAIN.",
    ]:
        assert fit(message, NOTE).fits, f"{message!r} does not fit a Note"


def test_summary_card_fits_the_note():
    assert fit("YOU HAVE 3 THINGS THAT NEED YOU.", NOTE).fits


def test_overflow_is_reported_not_raised():
    joke = "I AM READING A BOOK ABOUT ANTI GRAVITY. IT IS IMPOSSIBLE TO PUT DOWN."
    r = fit(joke, NOTE)
    assert not r.fits
    assert r.overflow
    assert r.rows_needed > NOTE.rows
    assert len(r.grid) == 3, "still returns a renderable board"


def test_long_word_is_broken_rather_than_lost():
    r = fit("SUPERCALIFRAGILISTIC", NOTE)
    assert "SUPERCALIFRAGI" in r.preview.replace(" ", "")[:20] or r.rows_needed >= 2


def test_colour_codes_pass_through():
    r = fit("{63}{64}{65}", NOTE, align="left", valign="top")
    assert r.grid[0][:3] == [63, 64, 65]


def test_lowercase_is_upcased():
    assert "HELLO" in fit("hello", NOTE).preview


def test_centred_by_default():
    r = fit("HI", NOTE)
    # Middle row, horizontally centred: six blanks, H, I, seven blanks.
    assert r.grid[0] == [0] * 15
    assert r.grid[2] == [0] * 15
    assert r.grid[1].count(0) == 13
    assert r.grid[1][6:8] != [0, 0]


def test_geometry_inferred_from_grid_shape():
    assert geometry_from_grid([[0] * 15 for _ in range(3)]) == NOTE
    assert geometry_from_grid([[0] * 22 for _ in range(6)]) == FLAGSHIP
    odd = geometry_from_grid([[0] * 9 for _ in range(2)])
    assert odd == Geometry(rows=2, cols=9)


def test_multiline_input_respects_explicit_breaks():
    r = fit("ONE\nTWO\nTHREE", NOTE, align="left", valign="top")
    assert [line.rstrip() for line in r.preview.splitlines()] == ["ONE", "TWO", "THREE"]
