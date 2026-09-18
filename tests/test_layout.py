"""Layout and fitting, against both board geometries."""

from __future__ import annotations

from core.layout import (
    FLAGSHIP,
    NOTE,
    Band,
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
    assert r.fits


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
    assert "SUPERCALIFRAGI" in r.preview.replace(" ", "")[:20]


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


def test_a_bar_is_a_row_break_and_two_bars_leave_a_blank_row():
    # The list-source form is single-line per message, so this is the only
    # way to author a break there.
    r = fit("GREAT SCOTT||- DOC BROWN", NOTE, align="left", valign="top")
    assert [line.rstrip() for line in r.preview.splitlines()] == [
        "GREAT SCOTT",
        "",
        "- DOC BROWN",
    ]
    assert r.fits


class TestEncodingErrors:
    def test_unsupported_character_is_reported_not_raised(self):
        result = fit("HELLO*WORLD", NOTE)
        assert result.fits is False
        assert "*" in result.error

    def test_unknown_character_code_is_reported(self):
        result = fit("{99}", NOTE)
        assert result.fits is False
        assert "99" in result.error

    def test_failed_fit_returns_a_blank_grid_of_the_right_shape(self):
        result = fit("HELLO*WORLD", NOTE)
        assert len(result.grid) == NOTE.rows
        assert all(len(row) == NOTE.cols for row in result.grid)
        assert all(code == 0 for row in result.grid for code in row)

    def test_valid_text_has_no_error(self):
        assert fit("HELLO", NOTE).error == ""

    def test_colour_escapes_are_valid_input(self):
        result = fit("{63}{66}AB", NOTE, align="left", valign="top")
        assert result.error == ""
        assert result.grid[0][:4] == [63, 66, 1, 2]


class TestShortening:
    def test_leaves_a_message_that_already_fits_alone(self):
        result = fit("BINS OUT", NOTE, shorten=True)
        assert result.fits
        assert result.shortened == ""

    def test_abbreviates_to_make_it_fit(self):
        # 'PLEASE TAKE THE BINS OUT TOMORROW MORNING' overflows a Note as written.
        long = "PLEASE TAKE THE BINS OUT TOMORROW MORNING"
        assert not fit(long, NOTE).fits
        result = fit(long, NOTE, shorten=True)
        assert result.fits
        assert result.shortened in ("abbreviations", "articles")

    def test_falls_back_to_truncation_when_nothing_fits(self):
        result = fit("SUPERCALIFRAGILISTIC " * 6, NOTE, shorten=True)
        assert not result.fits
        assert result.overflow

    def test_an_encoding_error_is_not_masked_by_shortening(self):
        result = fit("HELLO*WORLD", NOTE, shorten=True)
        assert result.error
        assert not result.fits


class TestBand:
    def test_critical_band_is_two_columns_on_the_left(self):
        result = fit("HI", FLAGSHIP, band=Band(colour=63, width=2))
        assert all(r[0] == 63 and r[1] == 63 for r in result.grid)
        # The third column belongs to the card. A three-wide band would pass
        # every assertion above without this one.
        assert not any(r[2] == 63 for r in result.grid)

    def test_a_band_never_touches_the_other_edges(self):
        # The whole point of a band over a ring: the card keeps its right
        # edge, its top row and its bottom row.
        result = fit("HI", FLAGSHIP, band=Band(colour=63, width=2))
        assert not any(r[-1] == 63 for r in result.grid)
        assert not all(c == 63 for c in result.grid[0])
        assert not all(c == 63 for c in result.grid[-1])

    def test_a_band_runs_the_full_height(self):
        result = fit("HI", NOTE, band=Band(colour=64, width=1))
        assert [r[0] for r in result.grid] == [64] * NOTE.rows

    def test_text_never_overwrites_the_band(self):
        result = fit("X" * 200, FLAGSHIP, band=Band(colour=63, width=2))
        assert all(r[0] == 63 and r[1] == 63 for r in result.grid)

    def test_a_band_reduces_the_room_available(self):
        # Fifteen characters with no break opportunity: one row of a Note as
        # written, two once a column goes to the band.
        token = "ABCDEFGHIJKLMNO"
        plain = fit(token, NOTE)
        banded = fit(token, NOTE, band=Band(colour=63, width=1))
        assert banded.rows_needed > plain.rows_needed

    def test_no_band_is_unchanged(self):
        assert fit("HI", NOTE, band=None).grid == fit("HI", NOTE).grid

    def test_a_band_wider_than_the_board_still_leaves_a_card(self):
        result = fit("HI", NOTE, band=Band(colour=63, width=99))
        assert result.error == ""
        assert any(code != 63 for row in result.grid for code in row)

    def test_a_band_composes_with_shortening(self):
        # Overflows the banded inner box (3 rows x 14 cols) as written - it
        # needs four rows - but the ladder brings it down to three, so the
        # ladder is load-bearing here rather than incidental.
        message = "PLEASE TAKE THE BINS OUT TOMORROW MORNING"
        band = Band(colour=63, width=1)
        assert not fit(message, NOTE, band=band).fits

        result = fit(message, NOTE, band=band, shorten=True)
        assert all(r[0] == 63 for r in result.grid)
        assert result.shortened != ""
        assert result.fits
