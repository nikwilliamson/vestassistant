"""The framework-free half of Vestassistant.

Nothing in this package imports Home Assistant. That is a hard rule, not a
preference: it is what lets the scheduling logic - the part with all the
behaviour that is easy to get subtly wrong - be tested directly, in
milliseconds, without a HA harness.

Anything that needs hass, entities or I/O belongs one level up.
"""

from .layout import FLAGSHIP, NOTE, FitResult, Geometry, blank, decode, fit
from .models import (
    TIER_CONTENT,
    TIER_CRITICAL,
    TIER_TASK,
    CursorState,
    Decision,
    Item,
    QuietHours,
    SchedulerConfig,
    TierPolicy,
    TierSet,
    Trigger,
)
from .scheduler import decide, in_quiet_hours

__all__ = [
    "FLAGSHIP",
    "NOTE",
    "TIER_CONTENT",
    "TIER_CRITICAL",
    "TIER_TASK",
    "CursorState",
    "Decision",
    "FitResult",
    "Geometry",
    "Item",
    "QuietHours",
    "SchedulerConfig",
    "TierPolicy",
    "TierSet",
    "Trigger",
    "blank",
    "decide",
    "decode",
    "fit",
    "in_quiet_hours",
]
