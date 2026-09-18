"""Dwell time."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import VestassistantConfigEntry
from .entity import VestassistantEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DwellNumber(entry.runtime_data)])


class DwellNumber(VestassistantEntity, NumberEntity):
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dwell")

    @property
    def native_value(self) -> float:
        return self.coordinator.scheduler_config.dwell.total_seconds() / 60

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_dwell(value)
