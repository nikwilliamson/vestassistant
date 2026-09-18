"""Scheduler behaviour. No Home Assistant harness required."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
import sys

# Import the framework-free core directly: it must never need Home Assistant.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "vestassistant"),
)

from core.layout import Band
from core.models import (
    TIER_CONTENT,
    TIER_CRITICAL,
    TIER_TASK,
    CursorState,
    Item,
    QuietHours,
    SchedulerConfig,
    TierPolicy,
    TierSet,
    Trigger,
    resolve_band,
)
from core.scheduler import SUMMARY_ID, decide, in_quiet_hours

NOW = datetime(2026, 9, 17, 12, 0, 0)


def item(id_, tier=TIER_CONTENT, cards=None, source="test", **kw):
    return Item(
        id=id_,
        source=source,
        cards=tuple(cards or [id_.upper()]),
        tier=tier,
        created=kw.pop("created", NOW),
        **kw,
    )


def cfg(**kw):
    return SchedulerConfig(**kw)


def run(items, state=None, trigger=Trigger.DWELL, now=NOW, config=None):
    return decide(
        items,
        now=now,
        state=state or CursorState(),
        config=config or cfg(),
        trigger=trigger,
    )


# --------------------------------------------------------------------------
# rotation
# --------------------------------------------------------------------------


def test_single_item_is_shown():
    d = run([item("joke1")])
    assert d.text == "JOKE1"
    assert d.write is True
    assert d.next_wake == NOW + timedelta(minutes=20)


def test_unchanged_message_is_not_rewritten():
    items = [item("joke1")]
    first = run(items)
    second = run(items, state=first.state)
    assert second.text == "JOKE1"
    assert second.write is False, "re-posting the same text costs a physical flip"


def test_rotation_advances_through_content():
    items = [item("a"), item("b"), item("c")]
    state = CursorState()
    seen = []
    for _ in range(4):
        d = run(items, state=state)
        seen.append(d.text)
        state = d.state
    assert seen == ["A", "B", "C", "A"]


def test_cursor_tracks_identity_not_index():
    """Removing an earlier item must not make the board appear to skip."""
    items = [item("a"), item("b"), item("c"), item("d")]
    state = run(items).state
    state = run(items, state=state).state  # showing B
    assert state.current_key == "test:b"

    remaining = [i for i in items if i.id != "a"]
    d = run(remaining, state=state)
    assert d.text == "C", "should continue after B, not jump by index"


def test_alternation_between_attention_and_content():
    items = [
        item("trash", tier=TIER_TASK),
        item("litter", tier=TIER_TASK),
        item("joke1"),
        item("joke2"),
    ]
    state = CursorState()
    seen = []
    for _ in range(4):
        d = run(items, state=state)
        seen.append(d.text)
        state = d.state
    assert seen == ["TRASH", "JOKE1", "LITTER", "JOKE2"], seen


def test_content_only_when_no_attention():
    items = [item("joke1"), item("joke2")]
    state = CursorState()
    seen = []
    for _ in range(3):
        d = run(items, state=state)
        seen.append(d.text)
        state = d.state
    assert seen == ["JOKE1", "JOKE2", "JOKE1"]


# --------------------------------------------------------------------------
# tiers
# --------------------------------------------------------------------------


def test_exclusive_tier_suppresses_everything_below():
    items = [
        item("stove", tier=TIER_CRITICAL),
        item("trash", tier=TIER_TASK),
        item("joke1"),
    ]
    state = CursorState()
    for _ in range(3):
        d = run(items, state=state)
        assert d.text == "STOVE", "a hazard takes the whole board"
        state = d.state


def test_non_exclusive_task_still_shares_with_content():
    """The curbside window runs fifteen hours; it must not kill the fun."""
    items = [item("trash", tier=TIER_TASK), item("joke1")]
    state = CursorState()
    seen = []
    for _ in range(4):
        d = run(items, state=state)
        seen.append(d.text)
        state = d.state
    assert "JOKE1" in seen and "TRASH" in seen


def test_two_critical_items_rotate_between_themselves():
    items = [
        item("stove", tier=TIER_CRITICAL),
        item("oven", tier=TIER_CRITICAL),
        item("joke1"),
    ]
    state = CursorState()
    seen = []
    for _ in range(3):
        d = run(items, state=state)
        seen.append(d.text)
        state = d.state
    assert set(seen) == {"STOVE", "OVEN"}


# --------------------------------------------------------------------------
# preemption
# --------------------------------------------------------------------------


def test_arriving_item_preempts_same_rank():
    items = [item("trash", tier=TIER_TASK)]
    state = run(items).state
    items2 = [*items, item("litter", tier=TIER_TASK)]
    d = run(items2, state=state, trigger=Trigger.ITEMS_CHANGED)
    assert d.text == "LITTER"
    assert "preempt" in d.reason


def test_lower_tier_does_not_preempt_a_hazard():
    items = [item("stove", tier=TIER_CRITICAL)]
    state = run(items).state
    items2 = [*items, item("trash", tier=TIER_TASK)]
    d = run(items2, state=state, trigger=Trigger.ITEMS_CHANGED)
    assert d.text == "STOVE", "a trash reminder must not shove a stove alert aside"


def test_content_never_preempts():
    items = [item("trash", tier=TIER_TASK)]
    state = run(items).state
    d = run([*items, item("joke1")], state=state, trigger=Trigger.ITEMS_CHANGED)
    assert d.text == "TRASH"


def test_unrelated_queue_change_does_not_disturb_the_dwell():
    items = [item("trash", tier=TIER_TASK), item("joke1")]
    first = run(items)
    assert first.text == "TRASH"
    later = NOW + timedelta(minutes=5)
    d = decide(
        [*items, item("litter", tier=TIER_CONTENT)],
        now=later,
        state=first.state,
        config=cfg(),
        trigger=Trigger.ITEMS_CHANGED,
    )
    assert d.text == "TRASH"
    assert d.write is False
    assert d.next_wake == NOW + timedelta(minutes=20), "dwell must not be extended"


def test_removing_the_displayed_item_advances():
    items = [item("trash", tier=TIER_TASK), item("joke1")]
    state = run(items).state
    assert state.current_key == "test:trash"
    d = run([items[1]], state=state, trigger=Trigger.ITEMS_CHANGED)
    assert d.text == "JOKE1"


# --------------------------------------------------------------------------
# multi-card items
# --------------------------------------------------------------------------


def test_multi_card_item_plays_in_order_without_interruption():
    items = [item("joke", cards=["WHY THE LONG FACE", "IT IS A HORSE"]), item("other")]
    state = CursorState()
    first = run(items, state=state)
    assert first.text == "WHY THE LONG FACE"
    second = run(items, state=first.state)
    assert second.text == "IT IS A HORSE", "punchline must follow its setup"
    third = run(items, state=second.state)
    assert third.text == "OTHER"


# --------------------------------------------------------------------------
# summary card
# --------------------------------------------------------------------------


def test_summary_card_appears_at_threshold():
    items = [item(f"t{n}", tier=TIER_TASK) for n in range(3)]
    d = run(items)
    assert d.item is not None and d.item.id == SUMMARY_ID
    assert d.text == "YOU HAVE 3 THINGS THAT NEED YOU."
    assert d.attention_count == 3


def test_no_summary_below_threshold():
    items = [item("t1", tier=TIER_TASK), item("t2", tier=TIER_TASK)]
    d = run(items)
    assert d.item.id != SUMMARY_ID


def test_content_does_not_count_toward_attention():
    items = [item(f"j{n}") for n in range(5)]
    d = run(items)
    assert d.attention_count == 0
    assert d.item.id != SUMMARY_ID


# --------------------------------------------------------------------------
# expiry and emptiness
# --------------------------------------------------------------------------


def test_expired_items_are_dropped():
    stale = item("old", expires=NOW - timedelta(seconds=1))
    d = run([stale])
    assert d.blank is True


def test_blank_when_nothing_to_show():
    state = CursorState(last_rendered="SOMETHING")
    d = run([], state=state)
    assert d.blank is True
    assert d.write is True


def test_blank_board_is_not_rewritten_repeatedly():
    d = run([], state=CursorState(last_rendered=None))
    assert d.blank is True
    assert d.write is False


# --------------------------------------------------------------------------
# quiet hours
# --------------------------------------------------------------------------


def test_quiet_hours_window_wraps_midnight():
    assert in_quiet_hours(datetime(2026, 9, 17, 23, 30), time(22), time(7))
    assert in_quiet_hours(datetime(2026, 9, 17, 3, 0), time(22), time(7))
    assert not in_quiet_hours(datetime(2026, 9, 17, 12, 0), time(22), time(7))


def test_critical_ignores_quiet_hours():
    night = datetime(2026, 9, 17, 3, 0)
    d = run(
        [item("stove", tier=TIER_CRITICAL)],
        now=night,
        config=cfg(quiet_start=time(22), quiet_end=time(7)),
    )
    assert d.text == "STOVE"


def test_task_defers_during_quiet_hours_but_still_counts():
    night = datetime(2026, 9, 17, 3, 0)
    d = run(
        [item("trash", tier=TIER_TASK)],
        now=night,
        config=cfg(quiet_start=time(22), quiet_end=time(7)),
    )
    assert d.write is False, "board holds rather than flapping at 3am"
    assert d.attention_count == 1
    assert d.next_wake == datetime(2026, 9, 17, 7, 0)


def test_dropped_tier_does_not_count_during_quiet_hours():
    tiers = TierSet(
        (
            TierPolicy(
                name="ambient",
                rank=10,
                exclusive=False,
                attention=True,
                preempts=False,
                quiet_hours=QuietHours.DROP,
            ),
        )
    )
    night = datetime(2026, 9, 17, 3, 0)
    d = run(
        [item("x", tier="ambient")],
        now=night,
        config=cfg(quiet_start=time(22), quiet_end=time(7), tiers=tiers),
    )
    assert d.attention_count == 0
    assert d.blank is True


# --------------------------------------------------------------------------
# restart and foreign writes
# --------------------------------------------------------------------------


def test_restart_resumes_the_same_item():
    items = [item("a"), item("b"), item("c")]
    state = run(items).state
    state = run(items, state=state).state
    assert state.current_key == "test:b"

    resumed = run(items, state=state, trigger=Trigger.START)
    assert resumed.text == "B"
    assert resumed.write is False


def test_restart_advances_if_the_current_item_is_gone():
    items = [item("a"), item("b")]
    state = run(items).state
    d = run([items[1]], state=state, trigger=Trigger.START)
    assert d.text == "B"


def test_foreign_write_yields_for_the_grace_period():
    d = run([item("joke1")], trigger=Trigger.FOREIGN_WRITE)
    assert d.write is False
    assert d.state.frozen is True
    assert d.next_wake == NOW + timedelta(minutes=30)


# --------------------------------------------------------------------------
# dwell
# --------------------------------------------------------------------------


def test_item_dwell_overrides_the_default():
    d = run([item("a", dwell=timedelta(minutes=5))])
    assert d.next_wake == NOW + timedelta(minutes=5)


def test_tier_dwell_overrides_the_default():
    tiers = TierSet(
        (
            TierPolicy(
                name=TIER_CONTENT,
                rank=10,
                exclusive=False,
                attention=False,
                preempts=False,
                dwell=timedelta(minutes=45),
            ),
        )
    )
    d = run([item("a")], config=cfg(tiers=tiers))
    assert d.next_wake == NOW + timedelta(minutes=45)


def test_unknown_tier_falls_back_to_lowest_rather_than_crashing():
    d = run([item("a", tier="nonsense")])
    assert d.text == "A"


def test_attention_count_survives_an_exclusive_takeover():
    """A hazard owning the board does not mean the bins stopped needing doing."""
    items = [
        item("stove", tier=TIER_CRITICAL),
        item("trash", tier=TIER_TASK),
        item("litter", tier=TIER_TASK),
    ]
    d = run(items)
    assert d.text == "STOVE"
    assert d.attention_count == 3


def test_summary_is_suppressed_while_a_hazard_owns_the_board():
    items = [
        item("stove", tier=TIER_CRITICAL),
        item("trash", tier=TIER_TASK),
        item("litter", tier=TIER_TASK),
    ]
    d = run(items)
    assert d.item.id != SUMMARY_ID, "show the hazard, not a tally"


def test_summary_threshold_of_zero_disables_it():
    items = [item(f"t{n}", tier=TIER_TASK) for n in range(4)]
    d = run(items, config=cfg(summary_threshold=0))
    assert d.item.id != SUMMARY_ID


# --------------------------------------------------------------------------
# self-refreshing items (the clock)
# --------------------------------------------------------------------------

FIVE = timedelta(minutes=5)


def clock(text="11:00 PM"):
    return item("now", source="clock", cards=[text], refresh=FIVE)


def test_refresh_interval_brings_the_wake_forward():
    d = run([clock()])
    assert d.next_wake == NOW + FIVE
    assert d.wake_trigger is Trigger.REFRESH


def test_an_item_without_a_refresh_wakes_on_dwell_as_before():
    d = run([item("a")])
    assert d.next_wake == NOW + timedelta(minutes=20)
    assert d.wake_trigger is Trigger.DWELL


def test_dwell_wins_when_it_lands_before_the_next_refresh():
    d = run([item("a", dwell=timedelta(minutes=2), refresh=FIVE)])
    assert d.next_wake == NOW + timedelta(minutes=2)
    assert d.wake_trigger is Trigger.DWELL


def test_refresh_rewrites_the_current_item_with_its_new_text():
    first = run([clock("11:00 PM")])
    d = run(
        [clock("11:05 PM")],
        state=first.state,
        trigger=Trigger.REFRESH,
        now=NOW + FIVE,
    )
    assert d.write is True
    assert d.text == "11:05 PM"
    assert d.state.current_key == first.state.current_key


def test_refresh_does_not_extend_the_items_dwell():
    """A clock that rewrites itself must not renew its own lease."""
    first = run([clock("11:00 PM")])
    d = run(
        [clock("11:05 PM")],
        state=first.state,
        trigger=Trigger.REFRESH,
        now=NOW + FIVE,
    )
    assert d.state.shown_at == NOW, "still showing since it first went up"
    assert d.next_wake == NOW + FIVE + FIVE
    assert d.next_wake < NOW + timedelta(minutes=20), "inside the original dwell"


def test_refresh_with_unchanged_text_costs_no_flip():
    first = run([clock("11:00 PM")])
    d = run(
        [clock("11:00 PM")],
        state=first.state,
        trigger=Trigger.REFRESH,
        now=NOW + FIVE,
    )
    assert d.write is False


def test_the_dwell_still_expires_while_an_item_keeps_refreshing():
    first = run([clock("11:00 PM")])
    d = run(
        [clock("11:20 PM"), item("a")],
        state=first.state,
        trigger=Trigger.DWELL,
        now=NOW + timedelta(minutes=20),
    )
    assert d.item.id == "a", "the clock surrenders the board on time"


def test_refresh_after_the_refreshing_item_is_gone_advances_normally():
    first = run([clock("11:00 PM")])
    d = run([item("a")], state=first.state, trigger=Trigger.REFRESH, now=NOW + FIVE)
    assert d.text == "A"


class TestBandResolution:
    def test_critical_gets_a_two_column_red_band(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CRITICAL)
        assert resolve_band(item, TierSet()) == Band(colour=63, width=2)

    def test_task_gets_a_one_column_orange_band(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_TASK)
        assert resolve_band(item, TierSet()) == Band(colour=64, width=1)

    def test_content_gets_nothing(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CONTENT)
        assert resolve_band(item, TierSet()) is None

    def test_an_item_can_override_the_hue(self):
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_TASK, colour=66)
        assert resolve_band(item, TierSet()) == Band(colour=66, width=1)

    def test_an_override_does_not_give_content_a_band(self):
        # Severity decides whether there is a band at all; the colour only
        # decides what hue it is.
        item = Item(id="a", source="s", cards=("HI",), tier=TIER_CONTENT, colour=66)
        assert resolve_band(item, TierSet()) is None

    def test_banded_tier_without_colour_draws_nothing_until_item_supplies_one(self):
        # A tier can want a band (band > 0) but have no default hue. That must
        # fall through the *colour* guard, not the *width* gate - and an item's
        # own colour is enough to complete it.
        tiers = TierSet(
            (
                TierPolicy(
                    name="dim",
                    rank=5,
                    exclusive=False,
                    attention=False,
                    preempts=False,
                    band=1,
                ),
            )
        )
        without_colour = Item(id="a", source="s", cards=("HI",), tier="dim")
        assert resolve_band(without_colour, tiers) is None

        with_colour = Item(id="a", source="s", cards=("HI",), tier="dim", colour=65)
        assert resolve_band(with_colour, tiers) == Band(colour=65, width=1)
