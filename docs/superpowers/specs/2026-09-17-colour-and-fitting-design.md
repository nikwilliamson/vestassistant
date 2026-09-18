# Colour, chips and smart fitting

Status: design approved, not yet planned.
Date: 2026-09-17

Adds colour to Vestassistant: a severity signature around every card, five
card types built out of colour chips, and a fitting pass that shortens a
message rather than truncating it.

Colours are character codes. `vesta.encode()` already parses `{63}` escapes
and `_wrap` runs after encoding, so a chip is just a cell and a row of chips
is just a string. The existing pipeline carries all of it.

## Verified

Checked against the Vestaboard docs, the `vesta` source, and this repo's own
`layout.py` before designing.

- Both transports accept raw character-code grids: `{"characters": [[...]]}`
  on cloud, a bare 2D array on local.
- The cloud's fifteen-second limit is real and documented; local documents
  none. The existing `min_write_interval` values are correct.
- `encode("{63}{66}AB")` returns `[63, 66, 1, 2]`. Escapes already work.
- Escape strings round-trip through `fit()` unchanged, confirmed by running
  it: a 22-chip gradient row, a full-board 6x22 pattern separated by
  newlines, and width-padded bars on both Flagship and Note all fit exactly.
- Code 62 is a degree sign on a Flagship and a heart on a Note.
- Note arrays are separate boards with separate keys and IPs. They arrive as
  independent 3x15 config entries, which the generic `Geometry` handles.

### Palette

Use **63-68** only: red, orange, yellow, green, blue, violet. Unrestricted on
both transports and both models.

69, 70 and 71 are avoided. Verbatim from the character code table, 71 is
"not available for the local API", and 69 and 70 invert with the board's
physical colour, which neither API reports. Restricting to the six hues means
the integration never has to ask what colour the board is.

Blank (0) is the board's own resting colour and is used for unlit cells.

## Prerequisite: `fit()` must not raise

`encode()` raises `ValueError` on any unsupported character - confirmed with
`*`, `>` and `{99}`. `fit()` calls it unguarded and sits on three paths: list
validation in the config flow, `_async_render` in the tick, and the
`validate` service. A message containing `*` currently crashes rather than
reporting that it does not fit.

Escapes turn this from rare into routine: the first thing anyone does with
`{63}` is mistype `{99}` or write `{7O}` with a letter O.

`fit()` returns a failed `FitResult` instead of raising, and `FitResult`
carries the reason. The config flow reports it as a validation error, the
render path logs and skips, `validate` returns it.

## Smart fitting

A substitution ladder, each rung tried only when the message still does not
fit:

1. As written.
2. Common abbreviations - `TOMORROW`/`TMRW`, `STREET`/`ST`, `AND`/`&`.
3. Drop articles.
4. Truncate, as today.

`FitResult` records which rung was used so `validate` can show it. The ladder
is a pure table in `core/fitting.py`, tested directly.

## Chips

`core/chips.py`, new and pure, beside `phrasing.py` and tested the same way.
Functions returning strings of escapes, each padding to full width so
alignment is a no-op:

- `bar(fraction, cols, colour)` - a filled run. A full row on a Flagship, an
  inline run beside the number on a Note.
- `row(codes, cols)` - individually coloured cells.
- `gradient(stops, cols)` - a wash across one row.
- `pattern(seed, geometry)` - deterministic generative fill, newline
  separated for a full board.

No new types, no change to `Item.cards`, no change to the scheduler. A card
that is mostly chips is still a string.

## Chrome: the severity signature

The one thing a string cannot express, because the text sits inside it.

`fit()` grows a `chrome=` argument that reserves edge columns or a rule row
and insets the text into what remains. Weight comes from the tier, hue from
the tier default unless the source overrode it:

| Tier | Weight | Default hue |
| --- | --- | --- |
| `critical` | Full border (two edge columns on a Note) | Red (63) |
| `task` | Thin rule | Orange (64) |
| `content` | None | - |

`Item` gains an optional `colour`. The subentry flows gain a colour picker
beside the existing tier picker, limited to 63-68.

On a Note a full border costs 13% of the board, so `critical` degrades from a
ring to two edge columns.

## Sources

New subentries, both taking an entity, both likely wanted more than once:

- **Progress** - a percentage entity as a bar plus a label. Fills with a hue,
  never with Filled, which would work on cloud and silently do nothing on
  local.
- **Air quality** - an AQI entity as a chip row plus a label. The standard
  AQI bands map onto the palette directly.

New options switches, one per board, configuring nothing:

- **Sky** - a gradient driven by `sun.sun` elevation, rendered smoothly. No
  text.
- **Advent** - active 1-24 December. Twenty-four chips, filling daily.

The **resting pattern** is not a source. The scheduler's existing
`blank=True` branch returns a pattern seeded by the date, so an empty queue
shows something stable for the day rather than a dark board.

The built-in cards move out of the main options form into their own sub-step;
it already holds eight fields and would not survive three more.

## Build order

1. `fit()` hardening and smart fitting. Pure, and a prerequisite.
2. `core/chips.py`, chrome, and `Item.colour` - the severity signature.
3. Progress bars.
4. Air quality, advent.
5. Sky and the resting pattern.

## Open

Geometry-aware decode - `_decode_row` renders 62 as a degree sign on every
board, which mislabels a Note's heart in the `validate` preview and in
`board_text`. Small, and adjacent to this work.
