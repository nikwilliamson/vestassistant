"""Decorative fills: colour on the board when there is nothing to say.

A pattern is a function from a geometry, a palette and a seed to a board's
worth of text - rows of ``{63}``-style chips joined by newlines. Because
``vesta.encode`` already parses brace codes, a pattern travels through the
same ``fit`` as any message and needs no new type above this module.

Every row is padded to the full width, so alignment never shifts anything.

Two rules keep an idle board still. A pattern must be a pure function of its
arguments: the scheduler rewrites the board whenever an item's text changes,
so anything that varied between ticks would flap the flaps for no reason.
And the seed is coarse - the source bumps it hourly - so a pattern drifts
over the day rather than churning.

Pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
import random
from typing import Final

from .layout import Geometry

__all__ = ["BLACK", "CONTRAST", "HUES", "PATTERNS", "WHITE", "Pattern", "render"]

RED: Final = 63
ORANGE: Final = 64
YELLOW: Final = 65
GREEN: Final = 66
BLUE: Final = 67
VIOLET: Final = 68
WHITE: Final = 69
BLACK: Final = 70

#: The six hues that read the same on both transports and both board
#: colours. 71 does nothing over the local API and is never emitted.
HUES: Final[tuple[int, ...]] = (RED, ORANGE, YELLOW, GREEN, BLUE, VIOLET)

#: The seventh "hue": whichever of white and black shows against the board.
#: A blank tile is the board's own colour, so white is invisible on a white
#: board and black on a black one - and neither API says which you have. The
#: source resolves this from the board-colour option.
CONTRAST: Final = "contrast"

BLANK_CELL: Final = " "

type Grid = list[list[int | None]]
"""Rows of hue codes; None is a blank tile."""

type Pattern = Callable[[Geometry, Sequence[int], int, int, datetime], Grid]
"""``(geometry, palette, contrast, seed, now) -> Grid``.

``contrast`` is the tile code that shows against the board (69 or 70).
"""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _chip(code: int | None) -> str:
    return BLANK_CELL if code is None else f"{{{code}}}"


def _text(grid: Grid, geometry: Geometry) -> str:
    rows = []
    for row in grid[: geometry.rows]:
        cells = list(row)[: geometry.cols]
        cells += [None] * (geometry.cols - len(cells))
        rows.append("".join(_chip(c) for c in cells))
    return "\n".join(rows)


def _stop(stops: Sequence[int], position: float) -> int:
    """Nearest stop for ``position`` in 0..1. Six hues leave nothing to blend."""
    if len(stops) == 1:
        return stops[0]
    return stops[round(position * (len(stops) - 1))]


def _rows(
    geometry: Geometry, fill: Callable[[int, int], int | None]
) -> list[list[int | None]]:
    return [[fill(r, c) for c in range(geometry.cols)] for r in range(geometry.rows)]


# --------------------------------------------------------------------------
# patterns
# --------------------------------------------------------------------------


def rainbow(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """One hue per row, walking through the palette. The seed rotates the
    starting hue, so a Note - which only has room for three - shows a
    different three each hour."""
    return _rows(geometry, lambda r, _c: palette[(r + seed) % len(palette)])


def stripes(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """Diagonal stripes, two tiles wide, drifting one step per seed."""
    return _rows(geometry, lambda r, c: palette[((r + c + seed) // 2) % len(palette)])


def wash(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """A left-to-right gradient through the palette, reversed on odd seeds."""
    stops = list(palette) if seed % 2 == 0 else list(reversed(palette))
    last = max(1, geometry.cols - 1)
    return _rows(geometry, lambda _r, c: _stop(stops, c / last))


def checkerboard(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """Two hues from the palette, chosen by the seed."""
    a = palette[seed % len(palette)]
    b = palette[(seed + 1) % len(palette)] if len(palette) > 1 else None
    return _rows(geometry, lambda r, c: a if (r + c) % 2 == 0 else b)


def frame(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """A one-tile border in one hue, blank inside."""
    hue = palette[seed % len(palette)]
    edge = {0, geometry.rows - 1}
    side = {0, geometry.cols - 1}
    return _rows(geometry, lambda r, c: hue if r in edge or c in side else None)


def confetti(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """A sparse sprinkle - about one tile in five - over a blank board."""
    rng = random.Random(seed)
    return _rows(
        geometry, lambda _r, _c: rng.choice(palette) if rng.random() < 0.2 else None
    )


def mosaic(
    geometry: Geometry,
    palette: Sequence[int],
    _contrast: int,
    seed: int,
    _now: datetime,
):
    """Every tile a hue, chosen at random but reproducibly."""
    rng = random.Random(seed)
    return _rows(geometry, lambda _r, _c: rng.choice(palette))


def sun(
    geometry: Geometry,
    _palette: Sequence[int],
    contrast: int,
    seed: int,
    now: datetime,
):
    """A fill that follows the sun: dawn, day, dusk and night.

    Ignores the palette on purpose - a sunset is not a sunset in green. The
    hour decides the scene; the seed only scatters the stars, most of which
    are the contrast colour, because stars are white.
    """
    hour = now.hour + now.minute / 60
    last = max(1, geometry.rows - 1)
    if 5.5 <= hour < 8.5:  # dawn: violet sky down to a yellow horizon
        stops = (VIOLET, BLUE, RED, ORANGE, YELLOW)
        return _rows(geometry, lambda r, _c: _stop(stops, r / last))
    if 8.5 <= hour < 17.5:  # day: sky, a band of sun, ground
        stops = (BLUE, BLUE, YELLOW, GREEN)
        return _rows(geometry, lambda r, _c: _stop(stops, r / last))
    if 17.5 <= hour < 20.5:  # dusk: yellow horizon burning down through red
        stops = (BLUE, VIOLET, RED, ORANGE, YELLOW)
        return _rows(geometry, lambda r, _c: _stop(stops, r / last))
    rng = random.Random(seed)  # night: a few stars, mostly white
    stars = (contrast, contrast, contrast, BLUE, YELLOW)
    return _rows(
        geometry, lambda _r, _c: rng.choice(stars) if rng.random() < 0.08 else None
    )


PATTERNS: Final[dict[str, Pattern]] = {
    "rainbow": rainbow,
    "stripes": stripes,
    "wash": wash,
    "checkerboard": checkerboard,
    "frame": frame,
    "confetti": confetti,
    "mosaic": mosaic,
    "sun": sun,
}

#: Patterns whose look depends on the clock rather than only the seed, and
#: so want rewriting while they are on the board.
TIME_OF_DAY: Final[frozenset[str]] = frozenset({"sun"})


def render(
    name: str,
    geometry: Geometry,
    palette: Sequence[int | str] = (),
    *,
    contrast: int = WHITE,
    seed: int = 0,
    now: datetime,
) -> str:
    """The named pattern as board text.

    ``palette`` is hue codes, optionally including ``CONTRAST``, which is
    resolved to ``contrast``. Empty means all six hues plus contrast, which
    is what makes a mosaic on a black board carry some white.
    """
    resolved = tuple(contrast if h == CONTRAST else h for h in palette)
    resolved = tuple(h for h in resolved if isinstance(h, int)) or (*HUES, contrast)
    pattern = PATTERNS[name]
    return _text(pattern(geometry, resolved, contrast, seed, now), geometry)
