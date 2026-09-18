# Colour and Fitting Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fit()` total rather than raising, teach it to shorten a message instead of truncating it, and add colour chips plus a per-tier severity signature around every card.

**Architecture:** Colours are character codes. `vesta.encode()` already parses `{63}` escapes and `_wrap` runs after encoding, so a row of chips is just a string and needs no new types. Two pure modules are added beside the existing `core/layout.py` and `core/phrasing.py` - `core/fitting.py` for the abbreviation ladder and `core/chips.py` for chip strings - and `fit()` grows a `chrome=` argument, which is the one thing a string cannot express because the text sits inside it.

**Tech Stack:** Python 3.13, Home Assistant 2025.12.0, `vesta==0.14.0` (character table only), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-17-colour-and-fitting-design.md`

## Global Constraints

- **Palette is 63-68 only** - red 63, orange 64, yellow 65, green 66, blue 67, violet 68. Never emit 69, 70 or 71. Verbatim from the Vestaboard character code table, 71 is "not available for the local API", and 69 and 70 invert with the board's physical colour, which neither API reports.
- **`custom_components/vestassistant/core/` must never import `homeassistant`.** This is what lets the test suite run with no HA harness. Tests import it directly via a `sys.path` insert.
- Single runtime dependency: `vesta==0.14.0`. Do not add others.
- Text on the board is uppercase. `encode()` uppercases internally; `fit()` also uppercases.
- Blank is character code `0`, written as a literal space inside chip strings.
- Run the suite with `pytest -q` from the repo root.
- **Commit messages must not contain `Co-Authored-By` or any session trailer.**

---

## File Structure

| File | Responsibility |
| --- | --- |
| `custom_components/vestassistant/core/layout.py` | Modify. `FitResult` gains `error` and `shortened`; `fit()` stops raising, gains `shorten=` and `chrome=`; new `Chrome` dataclass. |
| `custom_components/vestassistant/core/fitting.py` | Create. Pure abbreviation ladder. No imports beyond stdlib. |
| `custom_components/vestassistant/core/chips.py` | Create. Pure chip-string builders and the palette constants. |
| `custom_components/vestassistant/core/models.py` | Modify. `TierPolicy` gains `chrome` and `colour`; `Item` gains `colour`; new `resolve_chrome()`. |
| `custom_components/vestassistant/coordinator.py` | Modify. `_async_render` passes chrome and `shorten=True`, and skips unrenderable cards. |
| `custom_components/vestassistant/config_flow.py` | Modify. Colour picker on the three source subentry steps; distinguish bad characters from overflow. |
| `custom_components/vestassistant/sources/base.py`, `sources/dynamic.py` | Modify. Carry the configured colour onto the items they produce. |
| `custom_components/vestassistant/__init__.py` | Modify. `validate` service reports `error` and `shortened`; pass colour through `_source_from_subentry`. |
| `tests/test_layout.py` | Modify. Error and chrome cases. |
| `tests/test_fitting.py` | Create. |
| `tests/test_chips.py` | Create. |

Test files import the framework-free core directly, matching the existing header in `tests/test_phrasing.py`:

```python
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)
```

---

### Task 1: `fit()` reports bad characters instead of raising

`encode()` raises `ValueError` on any unsupported character - confirmed with `*`, `>` and `{99}`. `fit()` calls it unguarded on three paths: list validation in the config flow, `_async_render` in the tick, and the `validate` service. A message containing `*` currently crashes rather than reporting a problem.

**Files:**
- Modify: `custom_components/vestassistant/core/layout.py:56-66` (`FitResult`), `:108-124` (`fit`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FitResult.error: str` - empty when the text encoded cleanly, otherwise the reason. When set, `fits` is `False` and `grid` is a blank grid of the right geometry.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_layout.py`:

```python
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
        result = fit("{63}{66}AB", NOTE)
        assert result.error == ""
        assert result.grid[1][:4] == [63, 66, 1, 2] or 63 in result.grid[1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_layout.py::TestEncodingErrors -v`
Expected: FAIL - `AttributeError: 'FitResult' object has no attribute 'error'`, and the first two error out of `fit()` with `ValueError`.

- [ ] **Step 3: Add the field**

In `custom_components/vestassistant/core/layout.py`, add to `FitResult` after `overflow`:

```python
    error: str = ""
    """Why the text could not be encoded at all, if it could not.

    ``encode`` raises on an unsupported character or an unknown code in
    braces. Callers sit on three different paths - authoring, rendering and
    the validate service - and each wants to react differently, so this is
    reported rather than thrown.
    """
```

- [ ] **Step 4: Guard the encode call**

Replace the loop at the top of `fit()`:

```python
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
```

`blank()` is defined further down the module; Python resolves it at call time, so no reordering is needed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_layout.py -v`
Expected: PASS, including the pre-existing cases.

- [ ] **Step 6: Commit**

```bash
git add custom_components/vestassistant/core/layout.py tests/test_layout.py
git commit -m "Report unencodable text rather than raising out of fit()"
```

---

### Task 2: Callers handle an unencodable card

A blank grid must never reach the board - writing it would clear the wall. The render path skips the card instead, and does not retry it, because retrying an unencodable string loops forever.

**Files:**
- Modify: `custom_components/vestassistant/coordinator.py:44-52` (`WriteOutcome`), `:215-232` (`async_tick`), `:255-275` (`_async_render`)
- Modify: `custom_components/vestassistant/__init__.py` (the `_validate` service body)
- Modify: `custom_components/vestassistant/config_flow.py:~300` (`async_step_list`)
- Modify: `custom_components/vestassistant/strings.json`, `custom_components/vestassistant/translations/en.json`

**Interfaces:**
- Consumes: `FitResult.error` from Task 1.
- Produces: `WriteOutcome.SKIPPED` - the card could not be rendered; do not write, do not retry, let the dwell run normally.

- [ ] **Step 1: Add the outcome**

In `coordinator.py`, add to `WriteOutcome`:

```python
    SKIPPED = "skipped"
    """The card could not be encoded. Not retried - the text will not
    improve on its own, and retrying it would loop until the item leaves."""
```

- [ ] **Step 2: Skip rather than write in `_async_render`**

In `_async_render`, replace the `if not result.fits:` block with:

```python
            if result.error:
                _LOGGER.warning(
                    "cannot render %r on a %s: %s",
                    decision.text,
                    geometry.name,
                    result.error,
                )
                return WriteOutcome.SKIPPED
            if not result.fits:
                _LOGGER.warning(
                    "message does not fit a %s and was truncated: %r (dropped %r)",
                    geometry.name,
                    decision.text,
                    result.overflow,
                )
```

- [ ] **Step 3: Do not roll the cursor back on a skip**

In `async_tick`, replace the rollback condition:

```python
        if decision.write:
            outcome = await self._async_render(decision, now)
            if outcome in (WriteOutcome.FAILED, WriteOutcome.DEFERRED):
                # The board did NOT change, so the cursor must not claim it
                # did. SKIPPED is deliberately excluded: the card is
                # unrenderable, so leaving last_rendered set is what stops
                # the scheduler offering it again every retry.
                self.cursor = self.cursor.with_(last_rendered=previously_rendered)
                wake = self._retry_at(now, outcome)
```

- [ ] **Step 4: Surface it from the validate service**

In `__init__.py`, in `_validate`, add both new fields to the returned mapping:

```python
        return {
            "fits": result.fits,
            "error": result.error,
            "rows_needed": result.rows_needed,
            "rows_available": geometry.rows,
            "columns": geometry.cols,
            "board": geometry.name,
            "preview": result.preview,
            "overflow": result.overflow,
        }
```

- [ ] **Step 5: Distinguish the two failures in the config flow**

In `config_flow.py`, in `async_step_list`, replace the validation block:

```python
            geometry = self._geometry()
            results = [
                fit(card.strip(), geometry)
                for line in entries
                for card in line.split("|")
            ]
            if any(r.error for r in results):
                errors[CONF_ENTRIES] = "invalid_character"
            elif any(not r.fits for r in results):
                errors[CONF_ENTRIES] = "does_not_fit"
            else:
                return self.async_create_entry(
```

- [ ] **Step 6: Add the error string**

In both `strings.json` and `translations/en.json`, beside the existing `does_not_fit` entry under the `list` step's `error` block:

```json
"invalid_character": "That message uses a character the board cannot show, or a character code that does not exist. Colour chips are written as {63} through {68}."
```

- [ ] **Step 7: Run the suite**

Run: `pytest -q && ruff check custom_components tests`
Expected: PASS, no lint errors.

- [ ] **Step 8: Commit**

```bash
git add custom_components/vestassistant tests
git commit -m "Skip unrenderable cards instead of blanking the board"
```

---

### Task 3: The abbreviation ladder

Pure, stdlib only, tested directly. The ladder shortens; deciding whether the result fits stays in `fit()`.

**Files:**
- Create: `custom_components/vestassistant/core/fitting.py`
- Test: `tests/test_fitting.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `variants(text: str) -> Iterator[tuple[str, str]]`, yielding `(rung_name, text)` pairs from longest to shortest, always starting with `("", text)` for the text as written. Rung names are `""`, `"abbreviations"` and `"articles"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fitting.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_fitting.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'core.fitting'`.

- [ ] **Step 3: Write the module**

Create `custom_components/vestassistant/core/fitting.py`:

```python
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
    pattern = r"\b(?:" + "|".join(sorted(map(re.escape, table), key=len, reverse=True)) + r")\b"
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_fitting.py -v`
Expected: PASS, all fourteen.

- [ ] **Step 5: Commit**

```bash
git add custom_components/vestassistant/core/fitting.py tests/test_fitting.py
git commit -m "Add the abbreviation ladder"
```

---

### Task 4: Wire shortening into `fit()`

Opt-in, so no existing caller or test changes behaviour until it asks.

**Files:**
- Modify: `custom_components/vestassistant/core/layout.py` (`FitResult`, `fit`)
- Modify: `custom_components/vestassistant/coordinator.py` (`_async_render`)
- Modify: `custom_components/vestassistant/__init__.py` (`_validate`)
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: `variants()` from Task 3, `FitResult.error` from Task 1.
- Produces: `fit(text, geometry, *, align=, valign=, shorten: bool = False)` and `FitResult.shortened: str` - the rung that made it fit, `""` if the text fit as written or if nothing worked.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_layout.py`:

```python
class TestShortening:
    def test_leaves_a_message_that_already_fits_alone(self):
        result = fit("BINS OUT", NOTE, shorten=True)
        assert result.fits
        assert result.shortened == ""

    def test_abbreviates_to_make_it_fit(self):
        # 'TAKE THE BINS OUT TOMORROW MORNING' overflows a Note as written.
        long = "TAKE THE BINS OUT TOMORROW MORNING"
        assert not fit(long, NOTE).fits
        result = fit(long, NOTE, shorten=True)
        assert result.fits
        assert result.shortened in ("abbreviations", "articles")

    def test_records_which_rung_was_used(self):
        result = fit("TAKE THE BINS OUT TOMORROW MORNING", NOTE, shorten=True)
        assert result.shortened != ""

    def test_falls_back_to_truncation_when_nothing_fits(self):
        result = fit("SUPERCALIFRAGILISTIC " * 6, NOTE, shorten=True)
        assert not result.fits
        assert result.overflow

    def test_shortening_is_off_by_default(self):
        long = "TAKE THE BINS OUT TOMORROW MORNING"
        assert fit(long, NOTE).shortened == ""

    def test_an_encoding_error_is_not_masked_by_shortening(self):
        result = fit("HELLO*WORLD", NOTE, shorten=True)
        assert result.error
        assert not result.fits
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_layout.py::TestShortening -v`
Expected: FAIL - `fit() got an unexpected keyword argument 'shorten'`.

- [ ] **Step 3: Add the field and the import**

At the top of `layout.py`, beside the existing `vesta.chars` import:

```python
from .fitting import variants
```

Add to `FitResult`, after `error`:

```python
    shortened: str = ""
    """Which rung of the abbreviation ladder made it fit, if any.

    Empty when the text fit as written, and also when nothing worked and it
    had to be truncated after all.
    """
```

- [ ] **Step 4: Rename the existing body and add the wrapper**

Rename the current `fit` to `_fit_once`, keeping its signature but adding nothing, then add the public `fit` above it:

```python
def fit(
    text: str,
    geometry: Geometry,
    *,
    align: str = "center",
    valign: str = "middle",
    shorten: bool = False,
) -> FitResult:
    """Lay ``text`` out on a board of the given geometry.

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
    return last if last is not None else _fit_once(text, geometry, align=align, valign=valign)
```

Add `replace` to the existing dataclasses import at the top of the module:

```python
from dataclasses import dataclass, replace
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_layout.py -v`
Expected: PASS, including every pre-existing case.

- [ ] **Step 6: Turn it on at the two call sites that want it**

In `coordinator.py`, in `_async_render`:

```python
            result = fit(
                decision.text or "",
                geometry,
                align=self.scheduler_config_align,
                valign=self.scheduler_config_valign,
                shorten=True,
            )
```

In `__init__.py`, in `_validate`:

```python
        result = fit(call.data[ATTR_MESSAGE], geometry, shorten=True)
```

and add `shortened` to the response mapping:

```python
            "shortened": result.shortened,
```

The config flow deliberately keeps `shorten=False`: an author should be told their message is too long while they can still rewrite it, rather than have it silently abbreviated.

- [ ] **Step 7: Run the suite**

Run: `pytest -q && ruff check custom_components tests`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/vestassistant tests
git commit -m "Shorten messages before truncating them"
```

---

### Task 5: Chip strings

**Files:**
- Create: `custom_components/vestassistant/core/chips.py`
- Test: `tests/test_chips.py`

**Interfaces:**
- Consumes: `Geometry` from `core.layout`.
- Produces:
  - `PALETTE: tuple[int, ...]` and the names `RED`, `ORANGE`, `YELLOW`, `GREEN`, `BLUE`, `VIOLET`
  - `escape(code: int) -> str`
  - `row(codes: Sequence[int], cols: int) -> str`
  - `bar(fraction: float, cols: int, colour: int = GREEN) -> str`
  - `gradient(stops: Sequence[int], cols: int) -> str`
  - `pattern(seed: int, geometry: Geometry) -> str`

  Every one of these pads to exactly `cols` cells, so alignment is a no-op and a caller never has to think about it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chips.py`:

```python
"""Chip strings. No Home Assistant harness required."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)

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
        assert len(codes(row([RED, BLUE], NOTE.cols), NOTE)) == NOTE.cols

    def test_places_the_codes_in_order(self):
        assert codes(row([RED, BLUE], NOTE.cols), NOTE)[:2] == [63, 67]

    def test_pads_with_blanks(self):
        assert codes(row([RED], NOTE.cols), NOTE)[1:] == [0] * (NOTE.cols - 1)

    def test_truncates_codes_beyond_the_width(self):
        assert len(codes(row([RED] * 40, NOTE.cols), NOTE)) == NOTE.cols


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
        assert len(codes(gradient([RED, BLUE], FLAGSHIP.cols), FLAGSHIP)) == 22

    def test_starts_and_ends_on_the_stops(self):
        result = codes(gradient([RED, BLUE], FLAGSHIP.cols), FLAGSHIP)
        assert result[0] == RED
        assert result[-1] == BLUE

    def test_a_single_stop_is_a_solid_row(self):
        assert codes(gradient([RED], NOTE.cols), NOTE) == [RED] * NOTE.cols


class TestPattern:
    def test_covers_the_whole_board(self):
        result = fit(pattern(7, FLAGSHIP), FLAGSHIP, valign="top")
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_chips.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'core.chips'`.

- [ ] **Step 3: Write the module**

Create `custom_components/vestassistant/core/chips.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_chips.py -v`
Expected: PASS, all twenty-one.

- [ ] **Step 5: Commit**

```bash
git add custom_components/vestassistant/core/chips.py tests/test_chips.py
git commit -m "Add colour chip builders"
```

---

### Task 6: Chrome

The one thing a string cannot express, because the text sits inside it.

**Files:**
- Modify: `custom_components/vestassistant/core/layout.py`
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: `Geometry`, `_fit_once` from Task 4.
- Produces:
  - `Chrome(colour: int, weight: str)` - a frozen dataclass; `weight` is `"border"` or `"rule"`.
  - `fit(..., chrome: Chrome | None = None)` - reserves cells at the edges and insets the text into what is left.

  On a board with four or more rows, `"border"` is a full ring one cell deep. On a shallower board a ring would leave a single usable row, so it degrades to two edge columns. `"rule"` is always one column on the left edge.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_layout.py`:

```python
from core.layout import Chrome


class TestChrome:
    def test_border_rings_a_flagship(self):
        result = fit("HI", FLAGSHIP, chrome=Chrome(colour=63, weight="border"))
        assert all(c == 63 for c in result.grid[0])
        assert all(c == 63 for c in result.grid[-1])
        assert all(r[0] == 63 and r[-1] == 63 for r in result.grid)

    def test_border_degrades_to_edge_columns_on_a_note(self):
        result = fit("HI", NOTE, chrome=Chrome(colour=63, weight="border"))
        assert all(r[0] == 63 and r[-1] == 63 for r in result.grid)
        # The top row is not consumed - a Note has only three.
        assert not all(c == 63 for c in result.grid[0])

    def test_rule_takes_one_column(self):
        result = fit("HI", NOTE, chrome=Chrome(colour=64, weight="rule"))
        assert all(r[0] == 64 for r in result.grid)
        assert not any(r[-1] == 64 for r in result.grid)

    def test_text_is_inset_and_never_overwrites_the_chrome(self):
        result = fit("X" * 200, FLAGSHIP, chrome=Chrome(colour=63, weight="border"))
        assert all(r[0] == 63 and r[-1] == 63 for r in result.grid)

    def test_chrome_reduces_the_room_available(self):
        plain = fit("TAKE THE BINS OUT", NOTE)
        ringed = fit("TAKE THE BINS OUT", NOTE, chrome=Chrome(colour=63, weight="rule"))
        assert ringed.rows_needed >= plain.rows_needed

    def test_no_chrome_is_unchanged(self):
        assert fit("HI", NOTE, chrome=None).grid == fit("HI", NOTE).grid

    def test_chrome_composes_with_shortening(self):
        result = fit(
            "TAKE THE BINS OUT TOMORROW",
            NOTE,
            chrome=Chrome(colour=63, weight="rule"),
            shorten=True,
        )
        assert all(r[0] == 63 for r in result.grid)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_layout.py::TestChrome -v`
Expected: FAIL - `ImportError: cannot import name 'Chrome'`.

- [ ] **Step 3: Add the dataclass and the inset helpers**

In `layout.py`, after `Geometry`:

```python
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

    def inset(self, geometry: Geometry) -> tuple[int, int]:
        """Cells reserved at each edge, as ``(rows, cols)``."""
        if self.weight == "rule":
            return (0, 1)
        if geometry.rows >= RING_MIN_ROWS:
            return (1, 1)
        return (0, 1)
```

Add `Final` to the `typing` import at the top of the module, creating the import if it is not there:

```python
from typing import Final
```

- [ ] **Step 4: Paint it in `fit()`**

In the public `fit()` from Task 4, add the parameter and the composition. The full replacement:

```python
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

    pad_rows, pad_cols = chrome.inset(geometry)
    inner = Geometry(
        rows=max(1, geometry.rows - pad_rows * 2),
        cols=max(1, geometry.cols - pad_cols * 2),
    )
    result = _fit_text(text, inner, align=align, valign=valign, shorten=shorten)
    if result.error:
        return result
    return replace(result, grid=_frame(result.grid, geometry, chrome))


def _frame(inner: list[list[int]], geometry: Geometry, chrome: Chrome) -> list[list[int]]:
    """Paint the frame and drop the laid-out text into the middle of it."""
    pad_rows, pad_cols = chrome.inset(geometry)
    grid = [[chrome.colour] * geometry.cols for _ in range(geometry.rows)]
    for r, source in enumerate(inner):
        for c, code in enumerate(source):
            grid[r + pad_rows][c + pad_cols] = code
    return grid
```

Rename the `shorten` wrapper body from Task 4 to `_fit_text`, taking `shorten` as a keyword and calling `_fit_once` as before. `fit` is now the outermost of three: `fit` handles chrome, `_fit_text` handles the ladder, `_fit_once` does the layout.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_layout.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/vestassistant/core/layout.py tests/test_layout.py
git commit -m "Add chrome: a coloured frame the text sits inside"
```

---

### Task 7: Tiers carry a signature, items can override the hue

**Files:**
- Modify: `custom_components/vestassistant/core/models.py:56-100` (`TierPolicy`, `DEFAULT_TIERS`), `:149-180` (`Item`)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Chrome` from Task 6.
- Produces:
  - `TierPolicy.chrome: str = "none"` and `TierPolicy.colour: int | None = None`
  - `Item.colour: int | None = None`
  - `resolve_chrome(item: Item, tiers: TierSet) -> Chrome | None` - returns `None` when the tier's weight is `"none"`; otherwise a `Chrome` whose colour is the item's override if it set one, and the tier's default if not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
from core.layout import Chrome
from core.models import resolve_chrome


class TestChromeResolution:
    def test_critical_gets_a_red_border(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CRITICAL)
        assert resolve_chrome(item, TierSet()) == Chrome(colour=63, weight="border")

    def test_task_gets_an_orange_rule(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_TASK)
        assert resolve_chrome(item, TierSet()) == Chrome(colour=64, weight="rule")

    def test_content_gets_nothing(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CONTENT)
        assert resolve_chrome(item, TierSet()) is None

    def test_an_item_can_override_the_hue(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_TASK, colour=66)
        assert resolve_chrome(item, TierSet()) == Chrome(colour=66, weight="rule")

    def test_an_override_does_not_give_content_a_frame(self):
        # Severity decides whether there is a frame at all; the colour only
        # decides what hue it is.
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CONTENT, colour=66)
        assert resolve_chrome(item, TierSet()) is None
```

Make sure `TIER_CRITICAL`, `TIER_TASK`, `TIER_CONTENT`, `Item` and `TierSet` are in the file's existing imports from `core.models`; add any that are missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scheduler.py::TestChromeResolution -v`
Expected: FAIL - `ImportError: cannot import name 'resolve_chrome'`.

- [ ] **Step 3: Add the fields**

In `models.py`, add to `TierPolicy` after `quiet_hours`:

```python
    chrome: str = "none"
    """How loud this tier's frame is: ``border``, ``rule`` or ``none``.

    Severity decides the weight and the item decides the hue, so a green
    critical card is still a full border - it just is not red.
    """

    colour: int | None = None
    """The default hue for this tier's frame, overridable per item."""
```

Update `DEFAULT_TIERS`:

```python
    TierPolicy(
        name=TIER_CRITICAL,
        rank=30,
        exclusive=True,
        attention=True,
        preempts=True,
        quiet_hours=QuietHours.IGNORE,
        chrome="border",
        colour=63,
    ),
    TierPolicy(
        name=TIER_TASK,
        rank=20,
        exclusive=False,
        attention=True,
        preempts=True,
        quiet_hours=QuietHours.DEFER,
        chrome="rule",
        colour=64,
    ),
    TierPolicy(
        name=TIER_CONTENT,
        rank=10,
        exclusive=False,
        attention=False,
        preempts=False,
        quiet_hours=QuietHours.DEFER,
    ),
```

Add to `Item`, after `refresh`:

```python
    colour: int | None = None
    """Overrides the tier's default hue for this item's frame.

    One of 63-68. Whether there is a frame at all is the tier's decision.
    """
```

- [ ] **Step 4: Add the resolver**

At the end of `models.py`:

```python
def resolve_chrome(item: Item, tiers: TierSet) -> Chrome | None:
    """The frame for an item, or None when its tier does not draw one.

    Severity sets the weight, the item sets the hue. Kept here rather than in
    layout so that layout stays ignorant of tiers, and here rather than in
    the scheduler so that it can be tested without a decision.
    """
    tier = tiers.get(item.tier)
    if tier.chrome == "none":
        return None
    colour = item.colour if item.colour is not None else tier.colour
    if colour is None:
        return None
    return Chrome(colour=colour, weight=tier.chrome)
```

Add the import at the top of `models.py`:

```python
from .layout import Chrome
```

`layout` imports `fitting` and `vesta.chars`, never `models`, so this introduces no cycle. Add `Chrome` and `resolve_chrome` to `__all__`.

- [ ] **Step 5: Run the suite**

Run: `pytest -q`
Expected: PASS. The existing scheduler tests construct `TierPolicy` positionally in places - if any break, the new fields have defaults, so the fix is to leave those call sites alone and confirm the failure is genuinely elsewhere.

- [ ] **Step 6: Commit**

```bash
git add custom_components/vestassistant/core/models.py tests/test_scheduler.py
git commit -m "Give tiers a severity signature and items a hue override"
```

---

### Task 8: Draw the signature on the board

**Files:**
- Modify: `custom_components/vestassistant/coordinator.py` (`_async_render`)

**Interfaces:**
- Consumes: `resolve_chrome` from Task 7, `fit(chrome=)` from Task 6.
- Produces: nothing new.

- [ ] **Step 1: Import the resolver**

In `coordinator.py`, add `resolve_chrome` to the existing `from .core.models import (...)` block.

- [ ] **Step 2: Pass it through**

In `_async_render`, in the `else` branch that calls `fit`:

```python
        else:
            chrome = (
                resolve_chrome(decision.item, self.scheduler_config.tiers)
                if decision.item is not None
                else None
            )
            result = fit(
                decision.text or "",
                geometry,
                align=self.scheduler_config_align,
                valign=self.scheduler_config_valign,
                shorten=True,
                chrome=chrome,
            )
```

- [ ] **Step 3: Run the suite**

Run: `pytest -q && ruff check custom_components tests`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/vestassistant/coordinator.py
git commit -m "Draw the severity signature on the board"
```

---

### Task 9: Pick a colour when adding a source

**Files:**
- Modify: `custom_components/vestassistant/const.py`
- Modify: `custom_components/vestassistant/config_flow.py` (the three subentry steps)
- Modify: `custom_components/vestassistant/__init__.py` (`_source_from_subentry`, `ADD_ITEM_SCHEMA`, `_add_item`)
- Modify: `custom_components/vestassistant/sources/base.py` (`ListSource`), `sources/dynamic.py` (`TodoSource`, `DeclaredSource`, `ServiceSource`)
- Modify: `custom_components/vestassistant/strings.json`, `translations/en.json`, `services.yaml`

**Interfaces:**
- Consumes: `Item.colour` from Task 7, `PALETTE` from Task 5.
- Produces: `CONF_COLOUR = "colour"` and `ATTR_COLOUR = "colour"`; every source constructor gains `colour: int | None = None` and sets it on the items it produces.

- [ ] **Step 1: Add the constants**

In `const.py`, beside `CONF_TIER`:

```python
CONF_COLOUR: Final = "colour"
```

and beside `ATTR_TIER`:

```python
ATTR_COLOUR: Final = "colour"
```

- [ ] **Step 2: Add the selector**

In `config_flow.py`, beside `TIER_SELECTOR`:

```python
#: Only the six hues that behave identically on both transports and both
#: models. 71 is unavailable on the local API and 69 and 70 invert with the
#: board's physical colour, which neither API reports.
COLOUR_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=["63", "64", "65", "66", "67", "68"],
        translation_key="colour",
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)
```

Add `CONF_COLOUR` to the imports from `.const`.

- [ ] **Step 3: Offer it on all three steps**

In each of `async_step_list`, `async_step_todo` and `async_step_declared`, add to the schema after the tier field:

```python
                    vol.Optional(
                        CONF_COLOUR,
                        description={"suggested_value": None},
                    ): COLOUR_SELECTOR,
```

and to each `data={...}` mapping:

```python
                    CONF_COLOUR: user_input.get(CONF_COLOUR),
```

- [ ] **Step 4: Carry it onto the items**

In `sources/base.py`, `ListSource.__init__` gains `colour: int | None = None`, stores `self.colour = colour`, and passes `colour=self.colour` into each `Item(...)`.

In `sources/dynamic.py`, do the same for `TodoSource` and `DeclaredSource`. `DeclaredSource` additionally lets an entity override it, beside the existing tier attribute:

```python
ATTR_COLOUR = "colour"
```

```python
                    colour=_as_colour(state.attributes.get(ATTR_COLOUR), self.colour),
```

with, at module level:

```python
def _as_colour(value: object, default: int | None) -> int | None:
    """A declared colour, or the source's default if it is not usable."""
    try:
        code = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return code if 63 <= code <= 68 else default
```

`ServiceSource.add` gains a `colour: int | None = None` parameter, stores it in the item dict, and passes it through in `items()`.

- [ ] **Step 5: Wire the subentries and the service**

In `__init__.py`, in `_source_from_subentry`, read it once at the top beside `tier`:

```python
    colour = data.get(CONF_COLOUR)
    colour = int(colour) if colour is not None else None
```

and pass `colour` to all three constructors.

Add to `ADD_ITEM_SCHEMA`:

```python
        vol.Optional(ATTR_COLOUR): vol.All(
            vol.Coerce(int), vol.Range(min=63, max=68)
        ),
```

and pass `call.data.get(ATTR_COLOUR)` into `source.add(...)` as `colour=`.

Add `CONF_COLOUR` and `ATTR_COLOUR` to the imports from `.const`.

- [ ] **Step 6: Add the copy**

In `services.yaml`, under `add_item`'s `fields`:

```yaml
    colour:
      example: 66
      selector:
        select:
          translation_key: colour
          options: ["63", "64", "65", "66", "67", "68"]
```

In `strings.json` and `translations/en.json`, add a `colour` block under `selector` alongside the existing `tier` one:

```json
"colour": {
  "options": {
    "63": "Red",
    "64": "Orange",
    "65": "Yellow",
    "66": "Green",
    "67": "Blue",
    "68": "Violet"
  }
}
```

and add a `colour` label and description to each of the three subentry steps' `data` and `data_description` blocks, matching the wording style already used for `tier`.

- [ ] **Step 7: Run the suite**

Run: `pytest -q && ruff check custom_components tests`
Expected: PASS.

- [ ] **Step 8: Verify the JSON is well formed**

Run: `python3 -c "import json;[json.load(open(p)) for p in ['custom_components/vestassistant/strings.json','custom_components/vestassistant/translations/en.json']];print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add custom_components/vestassistant tests
git commit -m "Let a source choose the colour of its signature"
```

---

### Task 10: Document it

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the section**

Add after the "Messages too long for one board" section:

```markdown
### Colour

Every card carries a frame that says how much it matters. A `critical` item
gets a full border, a `task` gets a thin rule, and `content` gets none - so
you can tell a hazard from a chore from across the room without reading
either.

Severity decides how loud the frame is; you choose the hue when you add the
source, or per item:

```yaml
  - action: vestassistant.add_item
    data:
      id: bins
      message: BINS TONIGHT
      tier: task
      colour: 66
```

Colours are character codes, and they work anywhere a message does - in a
list, in a declared card, in `add_item`:

```yaml
  - "{63}{63} STOVE LEFT ON {63}{63}"
```

The palette is 63 red, 64 orange, 65 yellow, 66 green, 67 blue, 68 violet.
Codes 69, 70 and 71 are deliberately not offered: 71 is unavailable over the
local API, and 69 and 70 mean different things on a black board than on a
white one, which neither API reports.

### Messages that nearly fit

Rather than cutting a message off, Vestassistant shortens it - `TOMORROW`
becomes `TMRW`, `AND` becomes `&`, and articles go last of all. Only when
none of that is enough does it truncate. `vestassistant.validate` reports
which rung it had to use, so you can see it coming while you are still
writing.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document colour and smart fitting"
```

---

## Self-Review

**Spec coverage.** Steps 1 and 2 of the build order: `fit()` hardening is Tasks 1-2, smart fitting is Tasks 3-4, `core/chips.py` is Task 5, chrome is Task 6, `Item.colour` and the tier signature are Tasks 7-9, docs are Task 10. Steps 3-5 of the spec - progress bars, air quality, advent, sky, resting pattern - are deliberately out of scope for this plan and get their own.

**Spec items not covered here, by design:** geometry-aware decode (the spec's "Open" section), and the built-in cards moving to their own options sub-step, which belongs with the plan that adds sky and advent.

**Type consistency.** `FitResult` gains `error` (Task 1) and `shortened` (Task 4), both read in Task 2 and Task 4's wiring. `Chrome(colour, weight)` is defined in Task 6 and constructed in Tasks 6, 7 and 8 with the same keyword names. `resolve_chrome(item, tiers)` is defined in Task 7 and called in Task 8 with that signature. `PALETTE` is defined in Task 5 and referenced in Task 9's selector as the same six codes. The layering is `fit` (chrome) over `_fit_text` (ladder) over `_fit_once` (layout), named consistently across Tasks 4 and 6.
