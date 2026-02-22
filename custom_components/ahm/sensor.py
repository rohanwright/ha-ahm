"""Sensor platform for AHM integration diagnostics."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AhmCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AHM sensor entities."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        [
            AhmLastPresetSensor(coordinator),
            AhmConnectionStatusSensor(coordinator),
        ]
    )


class AhmLastPresetSensor(CoordinatorEntity, SensorEntity):
    """Shows the last preset recall received from the AHM."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:playlist-star"

    def __init__(self, coordinator: AhmCoordinator) -> None:
        """Initialize the last preset sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_recalled_preset"
        self._attr_suggested_object_id = f"{coordinator.device_name}_last_recalled_preset"
        self._attr_name = "Last Recalled Preset"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> str | None:
        """Return the last recalled preset label."""
        if not self.coordinator.data:
            return None
        preset_num = self.coordinator.data.get("last_recalled_preset")
        if preset_num is None:
            return None
        return f"Preset {preset_num}"


class AhmConnectionStatusSensor(CoordinatorEntity, SensorEntity):
    """Shows whether the AHM TCP connection is currently established."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator: AhmCoordinator) -> None:
        """Initialize the connection status sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_connection_status"
        self._attr_suggested_object_id = f"{coordinator.device_name}_connection_status"
        self._attr_name = "Connection Status"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> str:
        """Return connection state as text."""
        if not self.coordinator.data:
            return "Disconnected"
        return "Connected" if self.coordinator.data.get("connected") else "Disconnected"
