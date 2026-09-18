"""The Vestassistant scheduler.

Pure logic: given the current item set, the clock and the previous cursor
state, decide what the board should show and when to come back. No Home
Assistant imports, no I/O, no globals - so it can be exercised directly in
tests without a HA harness, which is where nearly all of the behaviour that
is easy to get wrong actually lives.

The blend strategy (how attention items and content items share the board) is
deliberately behind a seam. ``alternate`` ships as the default; swapping in a
weighted share is a config change, not surgery.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, time, timedelta

from .models import (
    CursorState,
    Decision,
    Item,
    QuietHours,
    SchedulerConfig,
    TierPolicy,
    TierSet,
    Trigger,
)

__all__ = ["BLENDS", "SUMMARY_ID", "SUMMARY_SOURCE", "decide", "in_quiet_hours"]

SUMMARY_SOURCE = "vestassistant"
SUMMARY_ID = "__summary__"
SUMMARY_KEY = f"{SUMMARY_SOURCE}:{SUMMARY_ID}"


# --------------------------------------------------------------------------
# quiet hours
# --------------------------------------------------------------------------


def in_quiet_hours(now: datetime, start: time | None, end: time | None) -> bool:
    """Whether ``now`` falls inside the configured quiet window.

    Handles a window that wraps past midnight, which is the normal case.
    """
    if start is None or end is None or start == end:
        return False
    current = now.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


# --------------------------------------------------------------------------
# selection helpers
# --------------------------------------------------------------------------


def _rank_of(item: Item, tiers: TierSet) -> int:
    return -tiers.get(item.tier).rank


def _order(items: Iterable[Item], tiers: TierSet) -> list[Item]:
    """Rank descending, and otherwise leave the caller's order alone.

    Python's sort is stable, so a ListSource's rotation order is the order the
    messages were written in config. Sorting by anything else here would
    silently shuffle a list somebody deliberately arranged.
    """
    return sorted(items, key=lambda i: _rank_of(i, tiers))


def _next_key(keys: Sequence[str], current: str | None) -> tuple[str, bool]:
    """Return the key after ``current``, and whether the cursor wrapped.

    Tracking by key rather than index is what stops a removal elsewhere in the
    list from making the board appear to skip an item.
    """
    if not keys:
        return "", False
    if current is None or current not in keys:
        return keys[0], True
    index = keys.index(current)
    if index + 1 >= len(keys):
        return keys[0], True
    return keys[index + 1], False


def _blend_alternate(
    attention: Sequence[Item],
    content: Sequence[Item],
    state: CursorState,
) -> bool:
    """Pick which set to draw from next. True means the attention set.

    Strict alternation: one thing that needs you, then one thing that doesn't.
    Each set keeps its own cursor, so the rotation through content is not
    disturbed by tasks coming and going.
    """
    if not attention:
        return False
    if not content:
        return True
    return not state.last_was_attention


def _blend_attention_first(
    attention: Sequence[Item],
    content: Sequence[Item],
    state: CursorState,
) -> bool:
    """Strict priority: content only runs when nothing needs attention."""
    return bool(attention)


BLENDS: dict[str, Callable[[Sequence[Item], Sequence[Item], CursorState], bool]] = {
    "alternate": _blend_alternate,
    "attention_first": _blend_attention_first,
}


# --------------------------------------------------------------------------
# the scheduler
# --------------------------------------------------------------------------


def decide(
    items: Iterable[Item],
    *,
    now: datetime,
    state: CursorState,
    config: SchedulerConfig,
    trigger: Trigger = Trigger.DWELL,
) -> Decision:
    """Work out what the board should show right now."""
    tiers = config.tiers
    quiet = in_quiet_hours(now, config.quiet_start, config.quiet_end)

    # 1. Drop anything that has aged out.
    live = [i for i in items if not i.is_expired(now)]

    # 2. Exclusivity. The highest-ranked active tier that claims the board
    #    suppresses everything below it - a hazard takes the board, a chore
    #    shares it.
    exclusive_rank: int | None = None
    for item in live:
        tier = tiers.get(item.tier)
        if tier.exclusive and (exclusive_rank is None or tier.rank > exclusive_rank):
            exclusive_rank = tier.rank
    visible = live
    if exclusive_rank is not None:
        visible = [i for i in live if tiers.get(i.tier).rank >= exclusive_rank]

    # 3. Quiet hours. DROP items behave as though they do not exist; DEFER
    #    items stay counted but do not take the board until the window ends.
    def _drops(item: Item) -> bool:
        return quiet and tiers.get(item.tier).quiet_hours is QuietHours.DROP

    counted = [i for i in visible if not _drops(i)]
    eligible = [
        i
        for i in counted
        if not (quiet and tiers.get(i.tier).quiet_hours is not QuietHours.IGNORE)
    ]

    # Counted across everything live, not just what is currently visible: a
    # hazard taking the whole board does not mean the bins stopped needing
    # taking out, and the count is what the sensor and the summary report.
    attention_count = sum(
        1 for i in live if tiers.get(i.tier).attention and not _drops(i)
    )

    # 4. The soonest anything currently live ages out. Whatever is decided
    #    below, the scheduler must be woken by then: an item with a short
    #    TTL under a long dwell would otherwise outstay it by the difference.
    expiry = min((i.expires for i in live if i.expires is not None), default=None)

    # 5. Nothing to show.
    if not eligible:
        if quiet and counted:
            # Something is pending but the window says not now. Hold the board
            # exactly as it is rather than flapping it blank at 10pm.
            return Decision(
                state=state,
                write=False,
                next_wake=_next_quiet_boundary(now, config),
                attention_count=attention_count,
                reason="quiet hours; holding",
            )
        return Decision(
            state=CursorState(),
            blank=True,
            write=state.last_rendered is not None,
            next_wake=None,
            attention_count=attention_count,
            reason="nothing to show",
        )

    ordered = _order(eligible, tiers)
    by_key = {i.key: i for i in ordered}
    attention = [i for i in ordered if tiers.get(i.tier).attention]
    content = [i for i in ordered if not tiers.get(i.tier).attention]

    current = by_key.get(state.current_key) if state.current_key else None
    known = set(state.known_keys)
    arrived = [i for i in ordered if i.key not in known]

    chosen: Item | None = None
    new_state = state
    reason = ""

    # 6. A self-refreshing item rewriting itself in place. Holding is the
    #    point: the clock rebuilding its own card must not renew its lease on
    #    the board, or an item that refreshes would never rotate away.
    if trigger is Trigger.REFRESH and current is not None:
        return _render(
            current,
            new_state.with_(known_keys=tuple(by_key)),
            now=now,
            config=config,
            tiers=tiers,
            attention_count=attention_count,
            reason="refreshed the current item",
            hold=True,
            expiry=expiry,
        )

    # 7. Preemption. An arriving item takes the board if it ranks at least as
    #    high as whatever is currently up.
    if trigger is Trigger.ITEMS_CHANGED:
        current_rank = tiers.get(current.tier).rank if current else -1
        candidates = [
            i
            for i in arrived
            if tiers.get(i.tier).preempts and tiers.get(i.tier).rank >= current_rank
        ]
        if candidates:
            chosen = _order(candidates, tiers)[0]
            reason = "new item preempted the rotation"
        elif current is not None:
            # Something changed elsewhere in the queue but nothing earned the
            # board. Hold the current item and, critically, do not restart its
            # dwell - an item appearing or disappearing further down the
            # rotation must not silently extend what is already up.
            return _render(
                current,
                new_state.with_(known_keys=tuple(by_key)),
                now=now,
                config=config,
                tiers=tiers,
                attention_count=attention_count,
                reason="queue changed; holding the current item",
                hold=True,
                expiry=expiry,
            )

    # 8. Coming back from a restart, resume rather than jump.
    if chosen is None and trigger is Trigger.START and current is not None:
        chosen = current
        reason = "resumed after restart"

    # 9. Otherwise advance through the blend.
    if chosen is None:
        blend = BLENDS.get(config.blend, _blend_alternate)
        take_attention = blend(attention, content, state)

        if take_attention and attention:
            keys = [i.key for i in attention]
            next_key, wrapped = _next_key(keys, state.attention_key)
            # Gated on what is actually in the rotation, not the global count:
            # during a hazard the board shows the hazard, not a tally. Zero
            # turns the summary card off.
            if (
                wrapped
                and config.summary_threshold > 0
                and len(attention) >= config.summary_threshold
            ):
                # Head each pass through the attention set with the count.
                summary = _summary_item(attention_count, config, tiers)
                return _render(
                    summary,
                    state.with_(
                        current_key=SUMMARY_KEY,
                        last_was_attention=True,
                        known_keys=tuple(by_key),
                    ),
                    now=now,
                    config=config,
                    tiers=tiers,
                    attention_count=attention_count,
                    reason="summary card",
                    expiry=expiry,
                )
            chosen = by_key[next_key]
            new_state = new_state.with_(attention_key=next_key, last_was_attention=True)
            reason = reason or "next attention item"
        elif content:
            keys = [i.key for i in content]
            next_key, _ = _next_key(keys, state.content_key)
            chosen = by_key[next_key]
            new_state = new_state.with_(content_key=next_key, last_was_attention=False)
            reason = reason or "next content item"
        else:
            chosen = ordered[0]
            reason = reason or "only item"

    new_state = new_state.with_(known_keys=tuple(by_key))
    return _render(
        chosen,
        new_state,
        now=now,
        config=config,
        tiers=tiers,
        attention_count=attention_count,
        reason=reason,
        expiry=expiry,
    )


def _render(
    item: Item,
    state: CursorState,
    *,
    now: datetime,
    config: SchedulerConfig,
    tiers: TierSet,
    attention_count: int,
    reason: str,
    hold: bool = False,
    expiry: datetime | None = None,
) -> Decision:
    text = item.text
    tier: TierPolicy = tiers.get(item.tier)
    dwell = item.dwell or tier.dwell or config.dwell
    unchanged = text == state.last_rendered
    # Holding keeps the original deadline rather than pushing it out.
    deadline = (state.shown_at or now) + dwell if hold else now + dwell

    # An item whose text is a function of the clock needs waking sooner than
    # its dwell, but only until the dwell runs out - whichever comes first.
    wake, wake_trigger = deadline, Trigger.DWELL
    if item.refresh is not None and now + item.refresh < deadline:
        wake, wake_trigger = now + item.refresh, Trigger.REFRESH
    # Something aging out is a queue change, not a dwell expiring: if it is
    # not the item on the board, the board holds; if it is, the cursor no
    # longer resolves and the rotation advances.
    if expiry is not None and now < expiry < wake:
        wake, wake_trigger = expiry, Trigger.ITEMS_CHANGED

    return Decision(
        state=state.with_(
            current_key=item.key,
            shown_at=state.shown_at if hold else now,
            last_rendered=text,
        ),
        item=item,
        text=text,
        # Re-posting text the board already shows costs a physical flip and
        # fifteen seconds of rate limit for no information.
        write=not unchanged,
        next_wake=wake,
        attention_count=attention_count,
        reason=reason,
        wake_trigger=wake_trigger,
    )


def _summary_item(count: int, config: SchedulerConfig, tiers: TierSet) -> Item:
    top = max(
        (t for t in tiers if t.attention),
        key=lambda t: t.rank,
        default=tiers.lowest,
    )
    # str.replace rather than str.format: the template may carry colour
    # chips like {63}, which format() would read as a positional index.
    text = config.summary_template.replace("{n}", str(count))
    return Item(
        id=SUMMARY_ID,
        source=SUMMARY_SOURCE,
        text=text,
        tier=top.name,
    )


def _next_quiet_boundary(now: datetime, config: SchedulerConfig) -> datetime:
    """When to look again while quiet hours are holding the board."""
    if config.quiet_end is None:
        return now + timedelta(hours=1)
    candidate = now.replace(
        hour=config.quiet_end.hour,
        minute=config.quiet_end.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
