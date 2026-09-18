"""Colour chips, as strings.

A chip is a character code and ``vesta.encode`` already parses ``{63}``
escapes, so a row of chips is just a string and travels through the same
wrapping and alignment as any other card. No new types are needed anywhere
above this module.

Every builder pads to exactly the width it was given, which means alignment
never shifts a chip row and a caller never has to think about it.

Pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
import random
from typing import Final

from .layout import Geometry

__all__ = [
    "BLUE",
    "GREEN",
    "ORANGE",
    "PALETTE",
    "RED",
    "VIOLET",
    "YELLOW",
    "bar",
    "escape",
    "gradient",
    "pattern",
    "row",
]

RED: Final = 63
ORANGE: Final = 64
YELLOW: Final = 65
GREEN: Final = 66
BLUE: Final = 67
VIOLET: Final = 68

#: The only codes we emit. 71 is documented as "not available for the local
#: API", and 69 and 70 invert with whether the board is black or white -
#: which neither API reports. Sticking to the six hues means the integration
#: never has to ask what colour the board is.
PALETTE: Final[tuple[int, ...]] = (RED, ORANGE, YELLOW, GREEN, BLUE, VIOLET)

BLANK_CELL: Final = " "


def escape(code: int) -> str:
    """One chip, as the brace sequence ``encode`` understands."""
    return f"{{{code}}}"


def row(codes: Sequence[int], cols: int) -> str:
    """A row of chips, padded with blanks to the full width."""
    cells = list(codes)[:cols]
    return "".join(escape(c) for c in cells) + BLANK_CELL * (cols - len(cells))


def bar(fraction: float, cols: int, colour: int = GREEN) -> str:
    """A progress bar filling ``fraction`` of the width.

    Filled with a hue rather than with 71, which would work over the cloud
    and silently do nothing over the local API.
    """
    clamped = min(1.0, max(0.0, fraction))
    filled = round(clamped * cols)
    return row([colour] * filled, cols)


def gradient(stops: Sequence[int], cols: int) -> str:
    """A wash across one row, stepping between ``stops``.

    Nearest-stop rather than interpolated: there are six hues, so there is
    nothing to interpolate through.
    """
    palette = list(stops)
    if not palette:
        return row([], cols)
    if len(palette) == 1:
        return row(palette * cols, cols)
    out = []
    last = len(palette) - 1
    for i in range(cols):
        position = i * last / (cols - 1) if cols > 1 else 0
        out.append(palette[round(position)])
    return row(out, cols)


def pattern(seed: int, geometry: Geometry) -> str:
    """A deterministic full-board fill, newline separated.

    Seeded rather than random so the board holds still: the same seed gives
    the same pattern every time it is rendered, which is what stops an idle
    board flapping every time the scheduler looks at it.
    """
    rng = random.Random(seed)
    lines = [
        row([rng.choice(PALETTE) for _ in range(geometry.cols)], geometry.cols)
        for _ in range(geometry.rows)
    ]
    return "\n".join(lines)
