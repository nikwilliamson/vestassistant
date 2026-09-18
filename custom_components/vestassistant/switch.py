"""Rotation on/off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestassistantConfigEntry
from .entity import VestassistantEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([RotationSwitch(entry.runtime_data)])


class RotationSwitch(VestassistantEntity, SwitchEntity):
    """Turning this off leaves the board exactly as it is."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "rotation")

    @property
    def is_on(self) -> bool:
        return self.coordinator.rotation_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_rotation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_rotation(False)
