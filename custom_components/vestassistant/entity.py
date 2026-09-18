"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VestassistantCoordinator


class VestassistantEntity(CoordinatorEntity[VestassistantCoordinator]):
    """Every entity belongs to the one board this entry configures."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VestassistantCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}-{key}"
        self._attr_translation_key = key
        geometry = coordinator.geometry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Vestaboard",
            model=geometry.name if geometry else None,
            sw_version=coordinator.transport.firmware_version,
        )
