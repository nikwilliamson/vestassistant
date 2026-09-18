"""Geometry-aware text layout for any Vestaboard.

``vesta.encode_text`` assumes 22 columns, so it cannot lay out a Vestaboard
Note. This module borrows vesta's character table - the fiddly part - and does
the wrapping, alignment and fitting itself against whatever geometry the board
actually reported.

Everything here is pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from vesta.chars import CHARMAP, PRINTABLE, encode

from .fitting import variants

__all__ = [
    "FLAGSHIP",
    "NOTE",
    "PRINTABLE",
    "Chrome",
    "FitResult",
    "Geometry",
    "blank",
    "decode",
    "fit",
    "geometry_from_grid",
]

BLANK = 0


@dataclass(frozen=True, slots=True)
class Geometry:
    rows: int
    cols: int

    @property
    def capacity(self) -> int:
        return self.rows * self.cols

    @property
    def name(self) -> str:
        return {(3, 15): "Vestaboard Note", (6, 22): "Vestaboard"}.get(
            (self.rows, self.cols), f"Vestaboard {self.rows}x{self.cols}"
        )


NOTE = Geometry(rows=3, cols=15)
FLAGSHIP = Geometry(rows=6, cols=22)
KNOWN: dict[tuple[int, int], Geometry] = {
    (NOTE.rows, NOTE.cols): NOTE,
    (FLAGSHIP.rows, FLAGSHIP.cols): FLAGSHIP,
}


#: A board needs at least this many rows before a full ring is worth it;
#: below it, a ring would leave a single usable row.
RING_MIN_ROWS: Final = 4


@dataclass(frozen=True, slots=True)
class Chrome:
    """A coloured frame drawn around a card.

    Severity decides how loud it is, so this carries the weight rather than
    the tier: the layout has no business knowing what 'critical' means.
    """

    colour: int
    weight: str
    """``border`` or ``rule``."""

    def inset(self, geometry: Geometry) -> tuple[int, int, int, int]:
        """Cells reserved at each edge, as ``(top, right, bottom, left)``.

        A ``rule`` only ever costs the left column. A ``border`` wants a full
        ring, but on a board shorter than ``RING_MIN_ROWS`` that would leave a
        single usable row, so it degrades to edge columns only.
        """
        if self.weight == "rule":
            return (0, 0, 0, 1)
        if geometry.rows >= RING_MIN_ROWS:
            return (1, 1, 1, 1)
        return (0, 1, 0, 1)


@dataclass(frozen=True, slots=True)
class FitResult:
    grid: list[list[int]]
    fits: bool
    rows_needed: int
    overflow: str = ""
    """The text that had to be dropped, if any."""
    error: str = ""
    """Why the text could not be encoded at all, if it could not.

    ``encode`` raises on an unsupported character or an unknown code in
    braces. Callers sit on three different paths - authoring, rendering and
    the validate service - and each wants to react differently, so this is
    reported rather than thrown.
    """
    shortened: str = ""
    """Which rung of the abbreviation ladder made it fit, if any.

    Empty when the text fit as written, and also when nothing worked and it
    had to be truncated after all.
    """

    @property
    def preview(self) -> str:
        return "\n".join(_decode_row(row) for row in self.grid)


def _wrap(codes: list[int], cols: int) -> list[list[int]]:
    """Break a line of character codes into rows no wider than ``cols``.

    Breaks at blanks where it can and mid-word where it must, which is the
    same rule the board's own formatter uses.
    """
    rows: list[list[int]] = []
    remaining = codes
    while remaining:
        if len(remaining) <= cols:
            rows.append(remaining)
            break
        window = remaining[: cols + 1]
        # Prefer the last blank that lets the line end inside the width.
        try:
            cut = len(window) - 1 - window[::-1].index(BLANK)
        except ValueError:
            cut = cols
        if cut == 0:
            cut = cols
        rows.append(remaining[:cut])
        remaining = remaining[cut:]
        while remaining and remaining[0] == BLANK:
            remaining = remaining[1:]
    return rows or [[]]


def _align(row: list[int], cols: int, align: str) -> list[int]:
    pad = cols - len(row)
    if pad <= 0:
        return row[:cols]
    if align == "right":
        return [BLANK] * pad + row
    if align == "center":
        left = pad // 2
        return [BLANK] * left + row + [BLANK] * (pad - left)
    return row + [BLANK] * pad


def fit(
    text: str,
    geometry: Geometry,
    *,
    align: str = "center",
    valign: str = "middle",
    shorten: bool = False,
    chrome: Chrome | None = None,
) -> FitResult:
    """Lay ``text`` out on a board of the given geometry.

    Never raises: overlong input is truncated and reported, and text the
    board cannot encode comes back with ``error`` set.

    With ``shorten``, the abbreviation ladder is tried before truncation.
    With ``chrome``, the edges are reserved for a coloured frame and the text
    is laid out in what remains - which is the one thing a chip string cannot
    do for itself, because the text sits inside it.
    """
    if chrome is None:
        return _fit_text(text, geometry, align=align, valign=valign, shorten=shorten)

    top, right, bottom, left = chrome.inset(geometry)
    inner = Geometry(
        rows=max(1, geometry.rows - top - bottom),
        cols=max(1, geometry.cols - left - right),
    )
    result = _fit_text(text, inner, align=align, valign=valign, shorten=shorten)
    if result.error:
        return result
    return replace(result, grid=_frame(result.grid, geometry, chrome))


def _frame(
    inner: list[list[int]], geometry: Geometry, chrome: Chrome
) -> list[list[int]]:
    """Paint the frame and drop the laid-out text into the middle of it."""
    top, _right, _bottom, left = chrome.inset(geometry)
    grid = [[chrome.colour] * geometry.cols for _ in range(geometry.rows)]
    for r, source in enumerate(inner):
        for c, code in enumerate(source):
            grid[r + top][c + left] = code
    return grid


def _fit_text(
    text: str,
    geometry: Geometry,
    *,
    align: str = "center",
    valign: str = "middle",
    shorten: bool = False,
) -> FitResult:
    """Walk the abbreviation ladder, falling back to truncation.

    Never raises: overlong input is truncated and reported, and text the
    board cannot encode comes back with ``error`` set, so a caller can decide
    whether that is a validation failure (authoring a message) or something
    to skip (rendering one that is already saved).

    With ``shorten``, the abbreviation ladder is tried before truncation -
    losing a few letters beats losing the end of the sentence.
    """
    if not shorten:
        return _fit_once(text, geometry, align=align, valign=valign)

    last: FitResult | None = None
    for rung, candidate in variants(text):
        result = _fit_once(candidate, geometry, align=align, valign=valign)
        if result.error:
            # A bad character will not be fixed by abbreviating it.
            return result
        if result.fits:
            return replace(result, shortened=rung)
        last = result
    # Nothing fit. Return the most aggressive attempt, truncated as before.
    if last is not None:
        return last
    return _fit_once(text, geometry, align=align, valign=valign)


def _fit_once(
    text: str,
    geometry: Geometry,
    *,
    align: str = "center",
    valign: str = "middle",
) -> FitResult:
    """Lay ``text`` on a board of the given geometry.

    Never raises on overlong input - it truncates and reports, so a caller can
    decide whether that is a validation error (authoring a message) or an
    acceptable squeeze (rendering one that is already saved).
    """
    lines: list[list[int]] = []
    for source_line in text.splitlines() or [""]:
        try:
            codes = encode(source_line.upper())
        except ValueError as err:
            return FitResult(
                grid=blank(geometry),
                fits=False,
                rows_needed=0,
                error=str(err),
            )
        lines.extend(_wrap(codes, geometry.cols))

    rows_needed = len(lines)
    overflow = ""
    if rows_needed > geometry.rows:
        dropped = lines[geometry.rows :]
        overflow = " ".join(_decode_row(r).strip() for r in dropped).strip()
        lines = lines[: geometry.rows]

    body = [_align(row, geometry.cols, align) for row in lines]

    pad = geometry.rows - len(body)
    empty = [BLANK] * geometry.cols
    if pad > 0:
        if valign == "bottom":
            body = [list(empty) for _ in range(pad)] + body
        elif valign == "middle":
            top = pad // 2
            body = (
                [list(empty) for _ in range(top)]
                + body
                + [list(empty) for _ in range(pad - top)]
            )
        else:
            body = body + [list(empty) for _ in range(pad)]

    return FitResult(
        grid=body,
        fits=not overflow,
        rows_needed=rows_needed,
        overflow=overflow,
    )


def blank(geometry: Geometry) -> list[list[int]]:
    return [[BLANK] * geometry.cols for _ in range(geometry.rows)]


_REVERSE = {v: k for k, v in CHARMAP.items()}


def _decode_row(row: list[int]) -> str:
    out = []
    for code in row:
        if 0 <= code < len(PRINTABLE):
            out.append(PRINTABLE[code])
        else:
            out.append(f"{{{code}}}")
    return "".join(out)


def decode(grid: list[list[int]]) -> str:
    """Turn a character grid back into readable text."""
    return "\n".join(_decode_row(row).rstrip() for row in grid).strip()


def geometry_from_grid(grid: list[list[int]]) -> Geometry:
    """Infer the board model from the shape of what it returned.

    Neither API reports a model, but the grid dimensions are unambiguous.
    """
    rows = len(grid)
    cols = max((len(r) for r in grid), default=0)
    return KNOWN.get((rows, cols), Geometry(rows=rows, cols=cols))
