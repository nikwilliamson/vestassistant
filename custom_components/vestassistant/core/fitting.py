"""Shortening a message so it fits, rather than cutting it off.

A board is fifteen or twenty-two characters wide and almost everything
worth saying is longer than that. Truncation loses the end of the
sentence, which is usually the part that mattered; abbreviating loses a
few letters nobody reads anyway.

The ladder only produces candidates. Whether any of them fits is
``layout.fit``'s decision, because only it knows the geometry.

Pure; no Home Assistant, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterator
import re

__all__ = ["ABBREVIATIONS", "ARTICLES", "variants"]

#: Whole-word substitutions, longest saving first. Deliberately short and
#: boring: an abbreviation nobody recognises is worse than a truncation.
ABBREVIATIONS: dict[str, str] = {
    "TOMORROW": "TMRW",
    "TONIGHT": "TNGHT",
    "MINUTES": "MIN",
    "MINUTE": "MIN",
    "STREET": "ST",
    "ROAD": "RD",
    "AVENUE": "AVE",
    "APPOINTMENT": "APPT",
    "WITHOUT": "W/O",
    "WITH": "W/",
    "AND": "&",
    "AT": "@",
    "PERCENT": "%",
    "NUMBER": "NO",
}

#: Dropped only on the last rung before truncation - a card reads worse
#: without them, so they go only when the alternative is losing words.
ARTICLES: frozenset[str] = frozenset({"THE", "A", "AN"})


def _replace_words(text: str, table: dict[str, str]) -> str:
    """Substitute whole words only, so ANDREW does not become &REW."""

    def swap(match: re.Match[str]) -> str:
        return table[match.group(0)]

    if not table:
        return text
    words = sorted(map(re.escape, table), key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(words) + r")\b"
    return re.sub(pattern, swap, text)


def _drop(text: str, words: frozenset[str]) -> str:
    kept = [w for w in text.split(" ") if w.upper() not in words]
    return " ".join(w for w in kept if w)


def variants(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(rung, text)`` from as-written to most aggressive.

    Each rung builds on the one before it, so the articles rung still
    carries the abbreviations. The caller stops at the first one that fits.
    """
    upper = text.upper()
    yield "", text

    abbreviated = _replace_words(upper, ABBREVIATIONS)
    yield "abbreviations", abbreviated

    yield "articles", _drop(abbreviated, ARTICLES)
