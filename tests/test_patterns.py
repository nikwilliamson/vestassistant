"""Decorative fills. No Home Assistant harness required."""

from __future__ import annotations

from datetime import datetime

from core.layout import FLAGSHIP, NOTE, fit
from core.patterns import BLACK, CONTRAST, HUES, PATTERNS, WHITE, render
import pytest

NOON = datetime(2026, 9, 17, 12, 0)


@pytest.mark.parametrize("name", list(PATTERNS))
@pytest.mark.parametrize("geometry", [NOTE, FLAGSHIP])
def test_every_pattern_fills_the_board_exactly(name, geometry):
    result = fit(render(name, geometry, now=NOON), geometry)
    assert result.error == ""
    assert result.fits
    assert len(result.grid) == geometry.rows
    assert all(len(row) == geometry.cols for row in result.grid)


@pytest.mark.parametrize("name", list(PATTERNS))
def test_a_pattern_is_a_pure_function_of_its_arguments(name):
    """Two renders with the same inputs must be identical, or the board flaps."""
    assert render(name, NOTE, seed=7, now=NOON) == render(name, NOTE, seed=7, now=NOON)


@pytest.mark.parametrize("name", ["rainbow", "stripes", "confetti", "mosaic"])
def test_the_seed_changes_the_picture(name):
    assert render(name, FLAGSHIP, seed=1, now=NOON) != render(
        name, FLAGSHIP, seed=2, now=NOON
    )


def test_only_the_six_hues_and_the_contrast_tile_are_ever_emitted():
    for name in PATTERNS:
        grid = fit(render(name, FLAGSHIP, seed=3, now=NOON), FLAGSHIP).grid
        codes = {c for row in grid for c in row}
        assert codes <= set(HUES) | {0, WHITE}, name
        assert 71 not in codes


def test_contrast_follows_the_board_colour():
    on_black = fit(render("mosaic", NOTE, seed=5, now=NOON, contrast=WHITE), NOTE)
    on_white = fit(render("mosaic", NOTE, seed=5, now=NOON, contrast=BLACK), NOTE)
    assert WHITE in {c for r in on_black.grid for c in r}
    assert BLACK in {c for r in on_white.grid for c in r}
    assert WHITE not in {c for r in on_white.grid for c in r}


def test_contrast_can_be_named_in_the_palette():
    text = render("checkerboard", NOTE, [63, CONTRAST], contrast=BLACK, now=NOON)
    assert {c for r in fit(text, NOTE).grid for c in r} == {63, BLACK}


def test_night_stars_are_mostly_the_contrast_colour():
    # Weighted 3:2 at random, so judge over enough seeds to mean it.
    lit = [
        c
        for seed in range(10)
        for r in fit(
            render("sun", FLAGSHIP, seed=seed, now=datetime(2026, 9, 17, 23, 0)),
            FLAGSHIP,
        ).grid
        for c in r
        if c
    ]
    assert lit.count(WHITE) > len(lit) / 2


def test_a_palette_restricts_the_hues():
    grid = fit(render("mosaic", FLAGSHIP, [63, 67], seed=1, now=NOON), FLAGSHIP).grid
    assert {c for row in grid for c in row} <= {63, 67}


def test_an_empty_palette_means_all_six_plus_contrast():
    assert render("rainbow", FLAGSHIP, [], now=NOON) == render(
        "rainbow", FLAGSHIP, [*HUES, CONTRAST], now=NOON
    )


def test_rainbow_shows_a_different_three_on_a_note_each_hour():
    assert render("rainbow", NOTE, seed=0, now=NOON) != render(
        "rainbow", NOTE, seed=1, now=NOON
    )


def test_frame_is_hollow():
    grid = fit(render("frame", FLAGSHIP, now=NOON), FLAGSHIP).grid
    assert grid[0][0] != 0 and grid[-1][-1] != 0
    assert grid[2][5] == 0


def test_sun_follows_the_clock_and_ignores_the_palette():
    dawn = render("sun", FLAGSHIP, [66], now=datetime(2026, 9, 17, 6, 30))
    dusk = render("sun", FLAGSHIP, [66], now=datetime(2026, 9, 17, 19, 0))
    night = render("sun", FLAGSHIP, [66], now=datetime(2026, 9, 17, 23, 0))
    assert dawn != dusk != night
    assert "{66}" not in dawn
    assert "{69}" not in dawn
    # Night is mostly dark.
    stars = fit(night, FLAGSHIP).grid
    assert sum(1 for row in stars for c in row if c) < FLAGSHIP.capacity / 3
