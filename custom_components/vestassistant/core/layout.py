"""Geometry-aware text layout for any Vestaboard.

``vesta.encode_text`` assumes 22 columns, so it cannot lay out a Vestaboard
Note. This module borrows vesta's character table - the fiddly part - and does
the wrapping, alignment and fitting itself against whatever geometry the board
actually reported.

Everything here is pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from vesta.chars import CHARMAP, PRINTABLE, encode

__all__ = [
    "FLAGSHIP",
    "NOTE",
    "PRINTABLE",
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


@dataclass(frozen=True, slots=True)
class FitResult:
    grid: list[list[int]]
    fits: bool
    rows_needed: int
    overflow: str = ""
    """The text that had to be dropped, if any."""

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
) -> FitResult:
    """Lay ``text`` out on a board of the given geometry.

    Never raises on overlong input - it truncates and reports, so a caller can
    decide whether that is a validation error (authoring a message) or an
    acceptable squeeze (rendering one that is already saved).
    """
    lines: list[list[int]] = []
    for source_line in text.splitlines() or [""]:
        codes = encode(source_line.upper())
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
