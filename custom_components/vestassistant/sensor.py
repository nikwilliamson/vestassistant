"""Sensors: what is on the board, and how much needs you."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import VestassistantConfigEntry, VestassistantCoordinator
from .entity import VestassistantEntity

PARALLEL_UPDATES = 0  # every write is serialised by the coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [CurrentItemSensor(coordinator), AttentionCountSensor(coordinator)]
    )


class CurrentItemSensor(VestassistantEntity, SensorEntity):
    """The message currently on the board."""

    # The queue is every message text on every state change; the recorder
    # does not need a copy of it each time the board flips.
    _unrecorded_attributes = frozenset({"queue", "board"})

    def __init__(self, coordinator: VestassistantCoordinator) -> None:
        super().__init__(coordinator, "current_item")

    @property
    def native_value(self) -> str | None:
        # Somebody else's message is up: name what is on the wall, not the
        # last card of ours it covered.
        if self.coordinator.foreign_since is not None:
            return " ".join(self.coordinator.board_text.split())[:255] or None
        displayed = self.coordinator.displayed_decision
        if displayed is None or displayed.text is None:
            return None
        # A pattern's text is a boardful of chips; the item names itself.
        if displayed.item is not None and (label := displayed.item.meta.get("label")):
            return label
        # State is capped at 255 characters; a board cannot hold that much,
        # but a misconfigured source could.
        return displayed.text[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The displayed decision, not the raw scheduler decision, for card
        # identity: a card the board could not render (WriteOutcome.SKIPPED)
        # must not be named here either, or the state and its attributes
        # would disagree. next_at/reason are different - they describe the
        # live scheduler, not the wall, so a skipped or failed render must
        # not leave them stuck reporting a wake time already in the past and
        # a stale reason.
        coordinator = self.coordinator
        foreign = coordinator.foreign_since is not None
        displayed = None if foreign else coordinator.displayed_decision
        live = coordinator.decision
        item = displayed.item if displayed else None
        queue = [
            {"id": i.id, "source": i.source, "tier": i.tier, "text": i.text}
            for i in coordinator.queue
        ]
        # While a hold is running the scheduler does not tick, so its last
        # decision would report a wake time long gone; the hold's end is the
        # real next change.
        held = coordinator.paused_until
        if held is not None and held > dt_util.now():
            next_at = held
            reason = "someone else posted; yielding" if foreign else "pinned"
        else:
            next_at = live.next_wake if live else None
            reason = live.reason if live else ""
        if foreign:
            source, since = "elsewhere", coordinator.foreign_since
        else:
            source = item.meta.get("source_name") if item else None
            since = coordinator.cursor.shown_at
        return {
            "source": source,
            "source_id": item.source if item else None,
            "item_id": item.id if item else None,
            "tier": item.tier if item else None,
            "since": since,
            "next_at": next_at,
            "reason": reason,
            "board": coordinator.board_rows,
            "queue": queue,
        }


class AttentionCountSensor(VestassistantEntity, SensorEntity):
    """How many items currently need attention - drives the summary card."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VestassistantCoordinator) -> None:
        super().__init__(coordinator, "attention_count")

    @property
    def native_value(self) -> int:
        return self.coordinator.attention_count
