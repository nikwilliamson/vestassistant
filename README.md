# Vestassistant

A message scheduler for [Vestaboard](https://www.vestaboard.com/) in Home Assistant.

Most Vestaboard integrations are a way to *send* a message. This one owns the
board: it holds a set of things worth showing, rotates through them, lets
urgent things interrupt, and gets out of the way when you post something
yourself. Your automations never mention the board at all — they add and
remove items, or simply raise a sensor, and the board works out the rest.

> Not affiliated with or endorsed by Vestaboard.

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
      id: stove_left_on
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
      id: joke
      cards:
        - "WHY DID THE SCARECROW"
        - "WIN AN AWARD?"
        - "HE WAS OUTSTANDING"
```

In a message list, use a pipe: `SETUP | PUNCHLINE`.

### Checking what fits

```yaml
action: vestassistant.validate
data:
  message: I AM READING A BOOK ABOUT ANTI GRAVITY
response_variable: result
```

Returns whether it fits, how many rows it needs, an ASCII preview of the
wrapping, and anything that overflowed.

## Installation

HACS → ⋮ → Custom repositories → this repo, category *Integration*. Then
**Settings → Devices & Services → Add Integration → Vestassistant**.

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
