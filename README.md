# Vestassistant

<img src="https://raw.githubusercontent.com/nikwilliamson/vestassistant/main/brand/icon.png" align="right" width="128" alt="The Vestassistant icon: a split-flap unit reading VA">

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/nikwilliamson/vestassistant)](https://github.com/nikwilliamson/vestassistant/releases)
[![License](https://img.shields.io/github/license/nikwilliamson/vestassistant)](LICENSE)

A message scheduler for [Vestaboard](https://www.vestaboard.com/) in Home Assistant.

Most Vestaboard integrations are a way to *send* a message. This one owns the
board. A split-flap on your wall should be interesting most of the time and
serious when it needs to be, so Vestassistant treats content as the board's
resting state and alerting as an interruption layer on top of it. You give it
things worth showing; it rotates through them, lets urgent things cut in, and
gets out of the way when you post something yourself.

> Not affiliated with or endorsed by Vestaboard.

## Install

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikwilliamson&repository=vestassistant&category=integration)

Or by hand: HACS → ⋮ → Custom repositories → this repo, category
*Integration*. Then **Settings → Devices & Services → Add Integration →
Vestassistant**. Needs Home Assistant 2025.12 or later.

You will be asked for **Local** or **Cloud**:

- **Local** talks straight to the board on your network. No cloud, no rate
  limit. Needs an enablement token, which you request from Vestaboard once and
  exchange for a permanent key.
- **Cloud** works immediately with a read/write token from the developer
  console. Vestaboard drops anything sent within fifteen seconds of the last
  message, so writes are spaced automatically.

**Turn quiet hours off in the Vestaboard app** and set them here instead,
with `time.*_quiet_hours_start` and `time.*_quiet_hours_end`. The cloud
enforces its own by silently dropping posts, which would leave the board
showing something Home Assistant thinks it already replaced. To have no quiet
hours at all, set both times to the same value.

Note and Flagship are both detected automatically.

## Settings

Almost everything is an entity, so a dashboard or an automation can change it —
see [Entities](#entities). Three things have no sensible entity and live in
**Settings → Devices & Services → Vestassistant → Configure**:

| Setting | |
| --- | --- |
| Summary card text | The wording of the count card. `{n}` is the number |
| How attention and content share the board | *Alternate* one of each in turn, or *Attention first* to run content only when nothing needs you |
| Board colour | Black or white. Neither API reports it, and it decides whether pattern cards use white tiles or black ones |
| Weather entity | Which entity the forecast card reads. Without one the forecast shows nothing |

## Sources

**Settings → Devices & Services → Vestassistant → Add source.** Five kinds:

| Source | |
| --- | --- |
| **Messages you type here** | One per box, rotating in the order you write them. A `\|` starts a new row on the board, so `GREAT SCOTT\|\|- DOC BROWN` is three rows with a blank one between. This is the resting state of the board — what shows when nothing needs you. Checked against your board as you save, so you find out something does not fit while you can still reword it |
| **Items from a to-do list** | Every incomplete item becomes a message. Tick it off and it leaves the board |
| **Messages carried by other entities** | For wording that belongs next to whatever raises it. Any entity that is `on` and has a `message` attribute becomes a message while it stays on — no automation needed. See [docs/automations.md](docs/automations.md) |
| **Events from a calendar** | Upcoming events from any calendar entity, one per card — `TOMORROW 3 PM` on the first row, the event below it, `NOW` while it is on. Choose how many days ahead and how many events at most. A card leaves the board when its event ends |
| **Colours and patterns** | Decorative fills for the board between messages: rainbow, stripes, a wash, checkerboard, a frame, confetti, a mosaic, and a sun that paints dawn, day, dusk and night. Each one you tick is a content card. They drift once an hour so an idle board is not flapping |

Each source has a **tier** and an optional **colour**.

**Sources are editable.** Click one under the integration to change its
messages, tier or colour — you do not have to delete it and start again.

**One message is one boardful.** A message that will not fit is shortened, and
failing that truncated; it is never continued onto a second board.

Automations can push messages in with `vestassistant.add_item`, and you can
type one straight to the board with `text.*_message`. The clock and forecast
are switches rather than sources, because there is only ever one of each and
nothing to name.

### Tiers

| Tier | |
| --- | --- |
| `critical` | Takes the whole board. Ignores quiet hours |
| `task` | Shares the board with content. Counts toward the attention total |
| `content` | The resting state. Never interrupts |

A hazard takes the board outright; a chore shares it — which matters, because
a bin reminder running from 7pm to 10am should not cost you fifteen hours of
everything else.

### Colour

Each message carries a coloured band down its left edge: two columns for
`critical`, one for `task`, none for `content`. Severity decides whether there
is a band and how wide; you choose the hue on the source or per item. A
`content` message with a colour still gets no band, because there is nothing to
tint.

The palette is 63 red, 64 orange, 65 yellow, 66 green, 67 blue, 68 violet.
Codes 69, 70 and 71 are not offered: 71 is unavailable over the local API, and
69 and 70 mean different things on a black board than a white one, which
neither API reports.

Colours are ordinary character codes, so they work inline in any message too:

```
{63}{63} STOVE LEFT ON {63}{63}
```

### Messages that nearly fit

Rather than cutting a message off, Vestassistant shortens it — `TOMORROW`
becomes `TMRW`, `AND` becomes `&`, articles go last of all — and truncates
only when none of that is enough.

Where a message is checked depends on where it comes from. A typed list checks
every line as you save it, and the text box checks as you type — both refuse
anything that will not fit even shortened. A message pushed in by an
automation cannot refuse an automation, so it is shortened and, failing that,
truncated. `vestassistant.validate` lets you check one first.

## Entities

| Entity | |
| --- | --- |
| `text.*_message` | Type a message and it goes up now, then the rotation resumes. Clear it to hand the board back early. Rejects characters the board cannot show as you type, and is capped at your board's capacity — 45 on a Note, 132 on a Flagship |
| `sensor.*_current_message` | What is on the board, with the queue as an attribute |
| `sensor.*_needs_attention` | The count behind the summary card |
| `image.*` | A live picture of the board |
| `switch.*_rotation` | Pause without changing what is up |
| `switch.*_clock_card` | The built-in clock |
| `switch.*_forecast_card` | The built-in forecast. Unavailable until a weather entity is set |
| `number.*_dwell` | Minutes per message |
| `number.*_summary_card_threshold` | Pending items before a count card leads each pass. `0` turns it off |
| `number.*_clock_interval` | How often the clock card is rebuilt while it is up. Every rewrite is a physical flip |
| `time.*_quiet_hours_start`, `time.*_quiet_hours_end` | Set both to the same time to turn quiet hours off |
| `binary_sensor.*_quiet_hours` | Whether the window is open right now |
| `button.*_next_message` | Advance by hand |

## Services

| Service | |
| --- | --- |
| `vestassistant.add_item` | Put a message up, with an optional `ttl` and `expire_when` so it removes itself |
| `vestassistant.remove_item` | Take one down |
| `vestassistant.next` | Advance now |
| `vestassistant.pin` | Hold one message for a while, then resume |
| `vestassistant.validate` | Check a message fits before you send it |

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

Every field is described in the Developer Tools service picker. More worked
examples are in [docs/automations.md](docs/automations.md).

## Playing nicely

Vestassistant reads the board back every minute. If something else wrote to
it — you, from the Vestaboard app — it yields for thirty minutes rather than
stamping on it.

It does not coexist with a second scheduler. If you use Vestaboard+ scheduled
channels, turn them off: they have no idea what is happening in your house,
and a channel firing on schedule will overwrite a live alert.

## Troubleshooting

**The rotation has stopped and the board is showing something I did not
schedule.** It saw a write it did not make and yielded for thirty minutes. A
Vestaboard+ channel looks exactly like a person, so turn channels off.

**Messages are being dropped.** Cloud only: Vestaboard discards anything sent
within fifteen seconds of the previous message. Vestassistant spaces its own
writes, but anything else writing to the board will collide with it.

**The forecast card never appears.** It needs both the switch on *and* a
weather entity chosen in Settings.

**A message never appears and nothing seems wrong.** It probably contains a
character the board cannot show. Typed lists and the text box reject those as
you write them, but one pushed in by an automation is only caught at render
time — it is skipped rather than written over whatever is up, and the log
names the character:

```
cannot render 'HELLO*WORLD' on a Vestaboard Note: 6: unsupported character: *
```

**I set a colour and nothing changed.** Colour picks the hue of a message's
band; severity decides whether there is one. A `content` message has none.

**Quiet hours seem to apply twice.** Turn them off in the Vestaboard app.

**The local API will not enable.** The enablement token is single-use, and the
board must be reachable over IPv4.

To see what the scheduler is deciding and why:

```yaml
logger:
  logs:
    custom_components.vestassistant: debug
```

## Removing it

**Settings → Devices & Services → Vestassistant → ⋮ → Delete**, then remove
the repository from HACS.

The board keeps whatever was last on it. The saved rotation state in
`.storage/vestassistant.state.<entry_id>` is not removed automatically — it is
harmless, and it means a reinstall picks up where you left off.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
