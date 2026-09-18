"""The numeric settings, as entities rather than buried in a config form."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLOCK_REFRESH,
    CONF_DWELL,
    CONF_SUMMARY_THRESHOLD,
    DEFAULT_CLOCK_REFRESH,
    DEFAULT_DWELL_MINUTES,
    DEFAULT_SUMMARY_THRESHOLD,
)
from .coordinator import VestassistantConfigEntry
from .entity import VestassistantEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VestassistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DwellNumber(coordinator),
            SummaryThresholdNumber(coordinator),
            ClockIntervalNumber(coordinator),
        ]
    )


class _OptionNumber(VestassistantEntity, NumberEntity):
    """A number backed by the entry's options, so it survives a restart."""

    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    _option: str
    _default: float

    @property
    def native_value(self) -> float:
        options = self.coordinator.config_entry.options
        return float(options.get(self._option, self._default))

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.async_set_option(self._option, int(value))


class DwellNumber(_OptionNumber):
    """How long each message stays up."""

    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _option = CONF_DWELL
    _default = DEFAULT_DWELL_MINUTES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dwell")


class SummaryThresholdNumber(_OptionNumber):
    """Pending items needed before a count card leads each pass. Zero is off."""

    _attr_native_min_value = 0
    _attr_native_max_value = 20
    _option = CONF_SUMMARY_THRESHOLD
    _default = DEFAULT_SUMMARY_THRESHOLD

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "summary_threshold")


class ClockIntervalNumber(_OptionNumber):
    """How often the clock card is rebuilt while it is up.

    Every rewrite is a physical flip, so this is deliberately yours to set
    rather than as fast as possible.
    """

    _attr_native_min_value = 1
    _attr_native_max_value = 60
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _option = CONF_CLOCK_REFRESH
    _default = DEFAULT_CLOCK_REFRESH

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clock_interval")
