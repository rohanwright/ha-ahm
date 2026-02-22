"""Button platform for AHM integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
    """Set up AHM button entities."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([AhmFetchNamesButton(coordinator)])


class AhmFetchNamesButton(CoordinatorEntity, ButtonEntity):
    """Button that fetches display names from the AHM device.

    When pressed, sends a GET name request for every configured input, zone,
    and control group.  The AHM responds asynchronously; the push listener
    processes the responses and renames the corresponding entities to match
    the names programmed on the device (e.g. "Spotify Level", "Main Hall Mute").
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tag-multiple"
    _attr_has_entity_name = True

    def __init__(self, coordinator: AhmCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fetch_names"
        self._attr_suggested_object_id = f"{coordinator.device_name}_fetch_channel_names"
        self._attr_name = "Fetch Channel Names"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    async def async_press(self) -> None:
        """Send GET name requests to the AHM for all configured channels."""
        await self.coordinator.async_fetch_all_names()
