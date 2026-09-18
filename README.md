# Vestassistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/nikwilliamson/vestassistant)](https://github.com/nikwilliamson/vestassistant/releases)
[![License](https://img.shields.io/github/license/nikwilliamson/vestassistant)](LICENSE)

A message scheduler for [Vestaboard](https://www.vestaboard.com/) in Home Assistant.

Most Vestaboard integrations are a way to *send* a message. This one owns the
board: it holds a set of things worth showing, rotates through them, lets
urgent things interrupt, and gets out of the way when you post something
yourself. Your automations never mention the board at all — they add and
remove items, or simply raise a sensor, and the board works out the rest.

- Quiet hours, a dwell you set per board, and a summary card that heads
  each pass once enough things are pending.
- Takes content from hand-typed lists, to-do lists, entities that declare
  their own cards, service calls, and built-in clock and forecast cards.
- Three severity tiers, each with a coloured frame, so you can read a card's
  importance from across the room without reading the card.
- Shortens a message that nearly fits rather than cutting the end off.
- Yields for thirty minutes when you post something from the Vestaboard app.
- Works with a Note or a Flagship, over the local API or the cloud.

> Not affiliated with or endorsed by Vestaboard.

## Installation

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikwilliamson&repository=vestassistant&category=integration)

Or by hand: HACS → ⋮ → Custom repositories → this repo, category
*Integration*. Then **Settings → Devices & Services → Add Integration →
Vestassistant**.

Needs Home Assistant 2025.12 or later.

### Local or Cloud?

Either works, and the difference is small.

**Local API** talks straight to the board on your network. No cloud
dependency, no rate limit. Needs an enablement token, which you request from
Vestaboard once and exchange for a permanent key.

**Cloud API** works immediately with a read/write token from the developer
console. Vestaboard drops anything sent within fifteen seconds of the previous
message, so Vestassistant spaces its writes automatically.

Quiet hours are applied here, not by Vestaboard. The cloud enforces its own by
silently dropping posts, which would leave the board showing something Home
Assistant believes it has already replaced — so every write goes out forced
and the policy is applied locally. **Turn off quiet hours in the Vestaboard
app** and set them in the integration's options instead.

Board geometry is detected from the board itself. Note and Flagship both work.

## Why

A split-flap on your wall should not be a status panel. It should be
interesting most of the time and serious when it needs to be. Vestassistant
treats content as the board's resting state and alerting as an interruption
layer on top of it.

## How it works

**Sources** produce items. **Tiers** decide who wins. **The scheduler** rotates.

| Tier | Behaviour |
| --- | --- |
| `critical` | Takes the whole board. Ignores quiet hours. | 
| `task` | Shares the board with content. Counts toward the attention total. |
| `content` | The resting state. Never interrupts. |

A hazard takes the board outright. A chore shares it — which matters, because
a bin reminder that runs from 7pm to 10am should not cost you fifteen hours of
everything else.

By default the board alternates: one thing that needs you, one thing that
doesn't. Once enough things are pending it heads each pass with a count —
`YOU HAVE 3 THINGS THAT NEED YOU.`

### Sources

- **List** — messages typed into the integration. Validated against your
  board's geometry when you save them, so you find out a message doesn't fit
  while you're writing it rather than when it appears garbled on the wall.
- **To-do list** — every incomplete item becomes a message. Tick it off and
  it leaves the board.
- **Declared cards** — any entity that is `on` and carries a `message`
  attribute. The message lives next to the detector that raises it, in YAML
  you can diff, and it adds and removes itself with no automation at all.
- **Service calls** — `vestassistant.add_item` / `remove_item`.
- **Clock** and **Forecast** — built in. These two are switches in the
  integration's options rather than sources you add, because there is only
  ever one of each and nothing to name: turn one off and its settings wait
  there for when you turn it back on. Both are content, so they never
  interrupt and they observe quiet hours.

The clock is the only card that rewrites itself. A split-flap that says
`11:00 PM` at twenty past is worse than one that says nothing, so while it is
up it is rebuilt every few minutes — and it still surrenders the board when
its dwell runs out, rather than renewing its own lease by refreshing. Every
rewrite is a physical flip, so the interval is yours to set and defaults to
five minutes.

If you run Vestaboard+ scheduled channels, turn them off before switching
these on. A channel posting the time on the hour reads as somebody writing to
the board by hand, which makes Vestassistant yield for thirty minutes — so
the two clocks would take it in turns rather than cooperate.

### Items that clean up after themselves

The removal half of an imperative API is the half that gets missed, so
`add_item` takes two guards:

```yaml
actions:
  - action: vestassistant.add_item
    data:
      item_id: stove_left_on
      message: STOVE LEFT ON. GO CHECK IT.
      tier: critical
      expire_when: "{{ is_state('binary_sensor.range_left_on', 'off') }}"
      ttl: "06:00:00"
```

`expire_when` is evaluated continuously, so removal is a *state* rather than
an event you have to catch. `ttl` is the backstop. And `item_id` is
idempotent — calling `add_item` twice with the same ID updates rather than
duplicating.

### Messages too long for one board

A Vestaboard Note is three rows of fifteen characters. Very little survives
that. So an item can be several cards, played in order and never interleaved
with anything else:

```yaml
  - action: vestassistant.add_item
    data:
      item_id: joke
      cards:
        - "WHY DID THE SCARECROW"
        - "WIN AN AWARD?"
        - "HE WAS OUTSTANDING"
```

In a message list, use a pipe: `SETUP | PUNCHLINE`.

### Colour

A card's frame says how much it matters. A `critical` item gets a full
border, a `task` gets a thin rule, and `content` gets none — so you can tell
a hazard from a chore from across the room without reading either. Severity
decides whether there is a frame and how loud it is; you choose the hue when
you add the source, or per item. A `content` card that names a colour still
gets no frame, because there is nothing for the colour to tint.

```yaml
  - action: vestassistant.add_item
    data:
      item_id: bins
      message: BINS TONIGHT
      tier: task
      colour: 66
```

Colours are character codes, and they work anywhere a message does — in a
list, in a declared card, in `add_item`:

```yaml
  - "{63}{63} STOVE LEFT ON {63}{63}"
```

The palette is 63 red, 64 orange, 65 yellow, 66 green, 67 blue, 68 violet.
Codes 69, 70 and 71 are deliberately not offered: 71 is unavailable over the
local API, and 69 and 70 mean different things on a black board than on a
white one, which neither API reports.

On a three-row Vestaboard Note, a `critical` card's full border becomes two
edge columns, because a full ring would leave only one row for text.

### Messages that nearly fit

Rather than cutting a message off, Vestassistant shortens it — `TOMORROW`
becomes `TMRW`, `AND` becomes `&`, and articles go last of all. Only when
none of that is enough does it truncate. A card's frame eats into the same
space, so `vestassistant.validate` (see below) only tells you which rung
will actually be used once you give it the `tier` the card will render with
— without one, it checks the text alone, on the bare board.

### Checking what fits

```yaml
action: vestassistant.validate
data:
  message: I AM READING A BOOK ABOUT ANTI GRAVITY
  tier: critical
response_variable: result
```

Returns `fits`, `rows_needed`, `rows_available`, `columns`, `board`,
`preview` (an ASCII preview of the wrapping), `overflow` (anything that did
not fit), `error` (any character that the board cannot encode, empty when all
encoded cleanly), and `shortened` (which fitting rung was used, empty if none).

`tier` and `colour` are optional inputs, not part of the response: pass a
`tier` to check the message the way it will actually be rendered, frame and
all — the same tiers used by `add_item` (`critical`, `task`, `content`).
`colour` picks the hue of that frame and is only used together with `tier`.
Leave both out to check the text on its own, exactly as before.

## Entities

| Entity | |
| --- | --- |
| `sensor.*_current_message` | What's on the board, with the full queue as an attribute |
| `sensor.*_needs_attention` | The count behind the summary card |
| `image.*` | A live picture of the board |
| `switch.*_rotation` | Pause without changing what's up |
| `number.*_dwell` | Minutes per message |
| `binary_sensor.*_quiet_hours` | |
| `button.*_next_message` | Advance by hand |

## Playing nicely

Vestassistant reads the board back every minute. If something else wrote to
it — you, from the Vestaboard app — it yields for thirty minutes rather than
stamping on it.

It does not coexist with a second scheduler. If you use Vestaboard+ scheduled
channels, turn them off: they have no idea what is happening in your house,
and a channel firing on schedule will happily overwrite a live alert.

## Troubleshooting

**The rotation has stopped, and the board is showing something I didn't
schedule.** Vestassistant reads the board back every minute and treats
anything it did not write as somebody posting by hand, then yields for thirty
minutes. A Vestaboard+ scheduled channel looks exactly like a person, so turn
channels off.

**Messages are being dropped.** Cloud only: Vestaboard discards anything sent
within fifteen seconds of the previous message. Vestassistant spaces its own
writes, but anything else writing to the same board will collide with it.

**Quiet hours seem to apply twice.** Turn them off in the Vestaboard app and
set them in the integration's options instead — see [Local or
Cloud?](#local-or-cloud).

**A card never appears, and nothing else seems wrong.** It probably contains
a character the board cannot show. Those cards are skipped rather than
written, because the alternative is writing a blank grid over whatever was
up. The log names the character:

```
cannot render 'HELLO*WORLD' on a Vestaboard Note: 6: unsupported character: *
```

**`vestassistant.pin` did nothing.** Same cause, logged as `cannot pin`. A
pin that cannot be encoded leaves the board and the rotation exactly as they
were.

**I set a colour and nothing changed.** Colour picks the hue of a card's
frame; severity decides whether there is a frame at all. A `content` card has
none, so there is nothing to tint. See [Colour](#colour).

**A message came out abbreviated.** Deliberate — see [Messages that nearly
fit](#messages-that-nearly-fit). A frame eats into the same space, so pass
the card's `tier` to `vestassistant.validate` to see what will actually be
rendered.

**The local API will not enable.** The enablement token is requested from
Vestaboard and is single-use. The board also needs to be reachable over
IPv4 — Vestaboard report inconsistent results over IPv6.

To see what the scheduler is deciding and why:

```yaml
logger:
  logs:
    custom_components.vestassistant: debug
```

Every decision is logged with its reason — `next attention item`, `summary
card`, `yielding to a message posted outside Vestassistant`.

## Removing it

**Settings → Devices & Services → Vestassistant → ⋮ → Delete**, then remove
the repository from HACS.

Deleting the integration does not clear the board. It keeps whatever was last
on it, which is usually what you want — post from the Vestaboard app if you
would rather it said something else.

The rotation's saved state lives in `.storage/vestassistant.state.<entry_id>`
and is not removed automatically. It is harmless, and it means a reinstall
picks up mid-rotation rather than starting over, but delete the file if you
want a clean slate.

## Development

The scheduler is deliberately free of Home Assistant imports, so the logic
that is easy to get wrong can be tested directly:

```bash
pip install pytest vesta
pytest -q
```

### Releasing

HACS compares the `version` in `manifest.json`, so bump it in the same commit
as the tag. Nothing stamps it for you.

```bash
# edit custom_components/vestassistant/manifest.json
git commit -am "Release 0.1.3"
git tag v0.1.3 && git push && git push --tags
gh release create v0.1.3 --title v0.1.3 --notes "..."
```

Until a release exists HACS tracks the default branch and never shows an
update badge; once one does, every later version appears as an update.

## License

MIT
