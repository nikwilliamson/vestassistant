"""Core data model for Vestassistant.

This module is deliberately free of any Home Assistant imports so that the
scheduling logic built on top of it can be unit tested without a HA harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
import enum

from .layout import Band

__all__ = [
    "DEFAULT_TIERS",
    "TIER_CONTENT",
    "TIER_CRITICAL",
    "TIER_TASK",
    "Band",
    "CursorState",
    "Decision",
    "Item",
    "QuietHours",
    "SchedulerConfig",
    "TierPolicy",
    "TierSet",
    "Trigger",
    "resolve_band",
]

TIER_CRITICAL = "critical"
TIER_TASK = "task"
TIER_CONTENT = "content"


class QuietHours(enum.StrEnum):
    """What a tier does when the board is inside its quiet window."""

    IGNORE = "ignore"
    """Post anyway. Hazards use this."""

    DEFER = "defer"
    """Hold until quiet hours end, then resume."""

    DROP = "drop"
    """Skip entirely; do not come back for it."""


class Trigger(enum.StrEnum):
    """Why the scheduler is being asked to make a decision."""

    START = "start"
    DWELL = "dwell"
    REFRESH = "refresh"
    """A self-refreshing item rewriting itself in place, mid-dwell."""

    ITEMS_CHANGED = "items_changed"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class TierPolicy:
    """Behaviour attached to a tier.

    The set of tiers is fixed at three; everything about how they *behave* is
    configuration. See ``DEFAULT_TIERS`` for the shipped defaults.
    """

    name: str
    rank: int
    exclusive: bool
    """When items in this tier are active, suppress every lower-ranked tier.

    A hazard takes the whole board. A chore shares it.
    """

    attention: bool
    """Counts toward the attention total and the summary card."""

    preempts: bool
    """An arriving item in this tier interrupts rather than waiting its turn."""

    quiet_hours: QuietHours = QuietHours.DEFER
    dwell: timedelta | None = None
    """Overrides the global dwell for items in this tier."""

    band: int = 0
    """Columns of coloured band down the left edge. Zero draws none.

    Severity decides the width and the item decides the hue, so a green
    critical card still gets the wider band - it just is not red.
    """

    colour: int | None = None
    """The default hue for this tier's frame, overridable per item."""


DEFAULT_TIERS: tuple[TierPolicy, ...] = (
    TierPolicy(
        name=TIER_CRITICAL,
        rank=30,
        exclusive=True,
        attention=True,
        preempts=True,
        quiet_hours=QuietHours.IGNORE,
        band=2,
        colour=63,
    ),
    TierPolicy(
        name=TIER_TASK,
        rank=20,
        exclusive=False,
        attention=True,
        preempts=True,
        quiet_hours=QuietHours.DEFER,
        band=1,
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
)


class TierSet:
    """Lookup for the configured tiers."""

    def __init__(self, tiers: tuple[TierPolicy, ...] = DEFAULT_TIERS) -> None:
        if not tiers:
            raise ValueError("at least one tier is required")
        self._by_name = {t.name: t for t in tiers}
        if len(self._by_name) != len(tiers):
            raise ValueError("tier names must be unique")
        self._ordered = tuple(sorted(tiers, key=lambda t: t.rank, reverse=True))

    def __iter__(self):
        return iter(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    @property
    def lowest(self) -> TierPolicy:
        return self._ordered[-1]

    def get(self, name: str) -> TierPolicy:
        """Return the named tier, falling back to the lowest-ranked one.

        Falling back rather than raising is deliberate: a source referencing a
        tier that has been renamed in config should degrade to showing up at
        the bottom of the board, not take the scheduler down.
        """
        return self._by_name.get(name, self.lowest)

    def rank(self, name: str) -> int:
        return self.get(name).rank


@dataclass(frozen=True, slots=True)
class Item:
    """One thing the board can show.

    One item is one boardful. A message that does not fit is shortened, and
    failing that truncated - it is never continued onto a second board, so
    what you write is what somebody standing in the room reads in one go.
    """

    id: str
    source: str
    text: str
    tier: str = TIER_CONTENT
    expires: datetime | None = None
    dwell: timedelta | None = None
    refresh: timedelta | None = None
    """How often this item's text should be rebuilt while it is on the board.

    For an item whose text is a function of the clock. The scheduler brings
    the next wake forward to match, and holds the original dwell deadline -
    refreshing rewrites the card, it does not win more board time.
    """

    colour: int | None = None
    """Overrides the tier's default hue for this item's frame.

    One of 63-68. Whether there is a frame at all is the tier's decision.
    """

    meta: dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("item id is required")
        if not self.text:
            raise ValueError(f"item {self.id!r} has no text")

    @property
    def key(self) -> str:
        """Identity used for cursor tracking and de-duplication."""
        return f"{self.source}:{self.id}"

    def is_expired(self, now: datetime) -> bool:
        return self.expires is not None and self.expires <= now


@dataclass(frozen=True, slots=True)
class CursorState:
    """Everything the scheduler needs to resume exactly where it left off.

    Persisted verbatim, so a restart picks up mid-rotation rather than
    starting over. Cursors are stored as item *keys* rather than indices -
    an index into a list that has since changed membership points at the
    wrong thing, which shows up as the board appearing to skip.
    """

    current_key: str | None = None
    shown_at: datetime | None = None
    last_rendered: str | None = None
    attention_key: str | None = None
    content_key: str | None = None
    last_was_attention: bool = False
    known_keys: tuple[str, ...] = ()
    """Keys seen on the previous pass, so arrivals can be told from survivors."""

    def with_(self, **changes) -> CursorState:
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class Decision:
    """The scheduler's answer: what to show, when to come back, what to save."""

    state: CursorState
    item: Item | None = None
    text: str | None = None
    write: bool = False
    """False means the board already shows this - skip the write, keep the flap
    still, and just re-arm the timer."""

    blank: bool = False
    next_wake: datetime | None = None
    attention_count: int = 0
    reason: str = ""
    wake_trigger: Trigger = Trigger.DWELL
    """Why the scheduler wants to be woken at ``next_wake``."""


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    dwell: timedelta = timedelta(minutes=20)
    summary_threshold: int = 3
    summary_template: str = "YOU HAVE {n} THINGS THAT NEED YOU."
    """``{n}`` is replaced with the count. Any other braces - colour chips
    like ``{63}`` - pass through to the board untouched."""

    quiet_start: time | None = None
    quiet_end: time | None = None
    tiers: TierSet = field(default_factory=TierSet)
    blend: str = "alternate"
    """Which blend strategy mixes attention and content. See scheduler.BLENDS."""

    foreign_write_grace: timedelta = timedelta(minutes=30)
    """How long to leave the board alone after a human writes to it directly.

    Read by the coordinator, which holds the board the same way a pin does;
    the scheduler itself never sees a foreign write.
    """


def resolve_band(tier_name: str, colour: int | None, tiers: TierSet) -> Band | None:
    """The band for an item of ``tier_name``, or None when its tier draws none.

    Severity sets the width, the item sets the hue. Takes the two values
    rather than an Item so that authoring paths - the config flow, the
    validate action - can ask before there is any text to build an Item from.
    """
    tier = tiers.get(tier_name)
    if tier.band <= 0:
        return None
    hue = colour if colour is not None else tier.colour
    if hue is None:
        return None
    return Band(colour=hue, width=tier.band)
