"""Switch platform for AHM integration - for mute controls."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_INPUT_TO_ZONE_SENDS,
    CONF_ZONE_TO_ZONE_SENDS,
)
from .coordinator import AhmCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AHM switch entities."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    # Merge options over data so the options flow changes take effect.
    cfg = {**config_entry.data, **config_entry.options}
    entities = []

    # Add input mute entities
    if CONF_INPUTS in cfg:
        for input_num in cfg[CONF_INPUTS]:
            entities.append(
                AhmInputMuteSwitch(coordinator, int(input_num))
            )

    # Add zone mute entities
    if CONF_ZONES in cfg:
        for zone_num in cfg[CONF_ZONES]:
            entities.append(
                AhmZoneMuteSwitch(coordinator, int(zone_num))
            )

    # Add control group mute entities
    if CONF_CONTROL_GROUPS in cfg:
        for cg_num in cfg[CONF_CONTROL_GROUPS]:
            entities.append(
                AhmControlGroupMuteSwitch(coordinator, int(cg_num))
            )

    # Add input-to-zone crosspoint mute switches
    for dest_zone_str, input_list in cfg.get(CONF_INPUT_TO_ZONE_SENDS, {}).items():
        dest_zone = int(dest_zone_str)
        for input_str in input_list:
            input_num = int(input_str)
            crosspoint_id = f"input_{input_num}_to_zone_{dest_zone}"
            entities.append(
                AhmCrosspointMuteSwitch(coordinator, crosspoint_id, input_num, dest_zone, is_zone_to_zone=False)
            )

    # Add zone-to-zone crosspoint mute switches
    for dest_zone_str, zone_list in cfg.get(CONF_ZONE_TO_ZONE_SENDS, {}).items():
        dest_zone = int(dest_zone_str)
        for source_zone_str in zone_list:
            source_zone = int(source_zone_str)
            crosspoint_id = f"zone_{source_zone}_to_zone_{dest_zone}"
            entities.append(
                AhmCrosspointMuteSwitch(coordinator, crosspoint_id, source_zone, dest_zone, is_zone_to_zone=True)
            )

    async_add_entities(entities)


class AhmBaseMuteSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for AHM mute switch entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AhmCoordinator, number: int, entity_type: str) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._number = number
        self._entity_type = entity_type
        self._attr_suggested_object_id = f"{coordinator.device_name}_{entity_type}_{number}_mute"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def name(self) -> str:
        """Return the entity name, using the AHM channel name if one has been fetched."""
        data = self._get_data()
        if data and data.get("name"):
            return f"{data['name']} Mute"
        return self._default_name

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on (muted)."""
        data = self._get_data()
        return data.get("muted") if data else None

    @property
    def icon(self) -> str:
        """Return the icon for the switch."""
        return "mdi:volume-off" if self.is_on else "mdi:volume-high"

    def _get_data(self) -> dict[str, Any] | None:
        """Get entity data from coordinator."""
        raise NotImplementedError

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set mute status."""
        raise NotImplementedError

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch (mute)."""
        await self._async_set_mute(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch (unmute)."""
        await self._async_set_mute(False)


class AhmInputMuteSwitch(AhmBaseMuteSwitch):
    """AHM input mute switch entity."""

    def __init__(self, coordinator: AhmCoordinator, input_num: int) -> None:
        """Initialize the input mute switch."""
        super().__init__(coordinator, input_num, "input")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_input_mute_{input_num}"
        self._default_name = f"Input {input_num} Mute"

    def _get_data(self) -> dict[str, Any] | None:
        """Get input data from coordinator."""
        if self.coordinator.data and "inputs" in self.coordinator.data:
            return self.coordinator.data["inputs"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set input mute status."""
        return await self.coordinator.async_set_input_mute(self._number, muted)


class AhmZoneMuteSwitch(AhmBaseMuteSwitch):
    """AHM zone mute switch entity."""

    def __init__(self, coordinator: AhmCoordinator, zone_num: int) -> None:
        """Initialize the zone mute switch."""
        super().__init__(coordinator, zone_num, "zone")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_zone_mute_{zone_num}"
        self._default_name = f"Zone {zone_num} Mute"

    def _get_data(self) -> dict[str, Any] | None:
        """Get zone data from coordinator."""
        if self.coordinator.data and "zones" in self.coordinator.data:
            return self.coordinator.data["zones"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set zone mute status."""
        return await self.coordinator.async_set_zone_mute(self._number, muted)


class AhmControlGroupMuteSwitch(AhmBaseMuteSwitch):
    """AHM control group mute switch entity."""

    def __init__(self, coordinator: AhmCoordinator, cg_num: int) -> None:
        """Initialize the control group mute switch."""
        super().__init__(coordinator, cg_num, "control_group")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_control_group_mute_{cg_num}"
        self._default_name = f"Control Group {cg_num} Mute"

    def _get_data(self) -> dict[str, Any] | None:
        """Get control group data from coordinator."""
        if self.coordinator.data and "control_groups" in self.coordinator.data:
            return self.coordinator.data["control_groups"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set control group mute status."""
        return await self.coordinator.async_set_control_group_mute(self._number, muted)


class AhmCrosspointMuteSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of an AHM crosspoint (send) mute switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AhmCoordinator,
        crosspoint_id: str,
        source_num: int,
        dest_zone: int,
        is_zone_to_zone: bool,
    ) -> None:
        """Initialize the crosspoint mute switch."""
        super().__init__(coordinator)
        self._crosspoint_id = crosspoint_id
        self._source_num = source_num
        self._dest_zone = dest_zone
        self._is_zone_to_zone = is_zone_to_zone

        source_type = "Zone" if is_zone_to_zone else "Input"
        self._default_name = f"Zone {dest_zone} {source_type} {source_num} Send Mute"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{crosspoint_id}_mute"
        self._attr_suggested_object_id = f"{coordinator.device_name}_{crosspoint_id}_send_mute"

    def _channel_name(self, entity_type: str, number: int) -> str | None:
        """Return the fetched AHM display name for a channel, or None if not yet available."""
        if not self.coordinator.data:
            return None
        ch = self.coordinator.data.get(entity_type, {}).get(number)
        return ch.get("name") if ch else None

    @property
    def name(self) -> str:
        """Return the entity name.

        Uses fetched AHM channel names when available:
          "<dest zone name> <source name> Mute"
        Falls back to the default numbered name when names have not been fetched.
        """
        source_type = "zones" if self._is_zone_to_zone else "inputs"
        zone_name = self._channel_name("zones", self._dest_zone)
        source_name = self._channel_name(source_type, self._source_num)
        if zone_name and source_name:
            return f"{zone_name} {source_name} Mute"
        if zone_name and not source_name:
            src_label = "Zone" if self._is_zone_to_zone else "Input"
            return f"{zone_name} {src_label} {self._source_num} Mute"
        if source_name and not zone_name:
            return f"Zone {self._dest_zone} {source_name} Mute"
        return self._default_name

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return True if the crosspoint send is muted."""
        if not self.coordinator.data:
            return None
        crosspoint_data = self.coordinator.data.get("crosspoints", {}).get(self._crosspoint_id)
        if crosspoint_data is None:
            return None
        return crosspoint_data.get("muted")

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:volume-off" if self.is_on else "mdi:volume-high"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mute the crosspoint send."""
        await self.coordinator.async_set_send_mute(
            self._source_num, self._dest_zone, True, self._is_zone_to_zone
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unmute the crosspoint send."""
        await self.coordinator.async_set_send_mute(
            self._source_num, self._dest_zone, False, self._is_zone_to_zone
        )
