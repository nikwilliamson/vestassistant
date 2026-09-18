"""Rotation on/off, and the built-in cards."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CLOCK, CONF_FORECAST, CONF_FORECAST_ENTITY
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
    coordinator = entry.runtime_data
    async_add_entities(
        [
            RotationSwitch(coordinator),
            ClockSwitch(coordinator),
            ForecastSwitch(coordinator),
        ]
    )


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


class _OptionSwitch(VestassistantEntity, SwitchEntity):
    """A built-in card, switchable from a dashboard or an automation.

    Backed by the entry's options, like every other setting that has an
    entity, so the value reads the same wherever you look at it.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _option: str

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.config_entry.options.get(self._option))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.async_set_option(self._option, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_set_option(self._option, False)


class ClockSwitch(_OptionSwitch):
    """The built-in clock card."""

    _option = CONF_CLOCK

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "clock")


class ForecastSwitch(_OptionSwitch):
    """The built-in forecast card.

    Unavailable until a weather entity is chosen in the options: switching it
    on without one used to contribute nothing at all, with no error and no
    card, which looked exactly like a bug.
    """

    _option = CONF_FORECAST

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "forecast")

    @property
    def available(self) -> bool:
        options = self.coordinator.config_entry.options
        return super().available and bool(options.get(CONF_FORECAST_ENTITY))
