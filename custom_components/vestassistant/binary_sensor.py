"""Quiet hours indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import VestassistantConfigEntry
from .core.scheduler import in_quiet_hours
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
    async_add_entities([QuietHoursSensor(entry.runtime_data)])


class QuietHoursSensor(VestassistantEntity, BinarySensorEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "quiet_hours")

    @property
    def is_on(self) -> bool:
        config = self.coordinator.scheduler_config
        return in_quiet_hours(dt_util.now(), config.quiet_start, config.quiet_end)
