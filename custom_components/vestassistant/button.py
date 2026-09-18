"""Advance the rotation by hand."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestassistantConfigEntry
from .entity import VestassistantEntity

#: Every read and write goes through the one coordinator, which
#: serialises them and enforces the board's own spacing, so there is
#: nothing here for Home Assistant to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([NextButton(entry.runtime_data)])


class NextButton(VestassistantEntity, ButtonEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "next")

    async def async_press(self) -> None:
        await self.coordinator.async_next()
