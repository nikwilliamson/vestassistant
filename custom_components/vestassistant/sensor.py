"""Sensors: what is on the board, and how much needs you."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestassistantConfigEntry
from .entity import VestassistantEntity


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

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "current_item")

    @property
    def native_value(self) -> str | None:
        text = self.coordinator.current_text
        if text is None:
            return None
        # State is capped at 255 characters; a board cannot hold that much,
        # but a misconfigured source could.
        return text[:255]

    @property
    def extra_state_attributes(self) -> dict:
        decision = self.coordinator.decision
        if decision is None:
            return {}
        item = decision.item
        return {
            "source": item.meta.get("source_name") if item else None,
            "source_id": item.source if item else None,
            "item_id": item.id if item else None,
            "tier": item.tier if item else None,
            "card": decision.card_index + 1 if item else None,
            "cards": len(item.cards) if item else None,
            "since": self.coordinator.cursor.shown_at,
            "next_at": decision.next_wake,
            "reason": decision.reason,
            "queue": [
                {"id": i.id, "source": i.source, "tier": i.tier, "text": i.cards[0]}
                for i in self.coordinator.collect(
                    self.coordinator.cursor.shown_at or dt_now()
                )
            ],
        }


def dt_now():
    from homeassistant.util import dt as dt_util

    return dt_util.now()


class AttentionCountSensor(VestassistantEntity, SensorEntity):
    """How many items currently need attention - drives the summary card."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "attention_count")

    @property
    def native_value(self) -> int:
        return self.coordinator.attention_count
