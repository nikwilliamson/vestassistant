"""Rotation on/off, and the built-in cards."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CLOCK, CONF_FORECAST, CONF_FORECAST_ENTITY
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

    Backed by the entry's options rather than by runtime state, so there is
    one source of truth and the setting reads the same in Settings as it does
    on the switch. Writing an option reloads the entry, which is what rebuilds
    the source list - the board itself is undisturbed, because the rotation
    cursor is persisted.
    """

    _option: str

    async def _async_write(self, value: bool) -> None:
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, self._option: value}
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.config_entry.options.get(self._option))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)


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
