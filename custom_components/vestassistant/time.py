"""Quiet hours, as two times you can set from a dashboard or an automation."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_QUIET_END, CONF_QUIET_START
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
        [
            QuietHoursTime(coordinator, "quiet_start", CONF_QUIET_START),
            QuietHoursTime(coordinator, "quiet_end", CONF_QUIET_END),
        ]
    )


class QuietHoursTime(VestassistantEntity, TimeEntity):
    """One end of the quiet window.

    Set both to the same time to turn quiet hours off - that is what the
    scheduler already treats as no window at all, so there is no separate
    switch to get out of step with these two.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: VestassistantCoordinator, key: str, option: str
    ) -> None:
        super().__init__(coordinator, key)
        self._option = option

    @property
    def native_value(self) -> time | None:
        stored = self.coordinator.config_entry.options.get(self._option)
        return dt_util.parse_time(stored) if stored else None

    async def async_set_value(self, value: time) -> None:
        self.coordinator.async_set_option(self._option, value.isoformat())
