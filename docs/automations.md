# Automation examples

The five services are described in the Developer Tools service picker; this is
the longer-form version of the ones worth explaining.

## An item that removes itself

The removal half of an imperative API is the half that gets missed, so
`add_item` takes two guards.

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

`expire_when` is a template the integration evaluates, so removal is a *state*
rather than an event you have to catch. `ttl` is the backstop for when the
state never arrives. `item_id` is idempotent: calling `add_item` twice with
the same one updates rather than duplicating, which is the de-duplication
every caller would otherwise hand-roll.

## Choosing the colour per item

```yaml
actions:
  - action: vestassistant.add_item
    data:
      item_id: bins
      message: BINS TONIGHT
      tier: task
      colour: 66
```

Severity decides whether there is a band; the colour only decides its hue. A
`content` card with a colour still gets no band.

## Checking a message before you send it

```yaml
actions:
  - action: vestassistant.validate
    data:
      message: I AM READING A BOOK ABOUT ANTI GRAVITY
      tier: critical
    response_variable: result
```

Returns `fits`, `rows_needed`, `rows_available`, `columns`, `board`, `preview`
(an ASCII picture of the wrapping), `overflow` (anything that did not fit),
`error` (any character the board cannot encode, empty when it is all fine) and
`shortened` (which abbreviation rung was used, empty if none).

`tier` and `colour` are inputs rather than part of the response. Pass a `tier`
to check the message the way it will actually render, band and all — without
one it checks the text alone on the bare board, which will tell you something
fits when a `critical` card would not.

## Entities that declare their own card

No automation at all. Any entity that is `on` and carries a `message`
attribute becomes a card for as long as it stays on, so the wording lives next
to the thing that raises it:

```yaml
template:
  - binary_sensor:
      - name: Washing finished
        state: "{{ is_state('sensor.washer', 'complete') }}"
        attributes:
          message: "THE WASHING IS DONE"
          tier: task
          colour: "66"
```

Add the source once under **Add source → Entities that declare their own
message**, and anything matching is picked up without a restart.
