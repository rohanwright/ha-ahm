"""Number platform for AHM integration - for fine-grained level control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_ROOMS,
    CONF_INPUT_TO_ZONE_SENDS,
    CONF_ZONE_TO_ZONE_SENDS,
    MIN_DB,
    MAX_DB,
)
from .coordinator import AhmCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AHM number entities."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    # Merge options over data so the options flow changes take effect.
    cfg = {**config_entry.data, **config_entry.options}
    entities = []

    # Add input level entities
    if CONF_INPUTS in cfg:
        for input_num in cfg[CONF_INPUTS]:
            entities.append(
                AhmInputLevelNumber(coordinator, int(input_num))
            )

    # Add zone level entities
    if CONF_ZONES in cfg:
        for zone_num in cfg[CONF_ZONES]:
            entities.append(
                AhmZoneLevelNumber(coordinator, int(zone_num))
            )

    # Add control group level entities
    if CONF_CONTROL_GROUPS in cfg:
        for cg_num in cfg[CONF_CONTROL_GROUPS]:
            entities.append(
                AhmControlGroupLevelNumber(coordinator, int(cg_num))
            )

    # Add room level entities
    if CONF_ROOMS in cfg:
        for room_num in cfg[CONF_ROOMS]:
            entities.append(
                AhmRoomLevelNumber(coordinator, int(room_num))
            )

    # Add input-to-zone crosspoint level numbers
    for dest_zone_str, input_list in cfg.get(CONF_INPUT_TO_ZONE_SENDS, {}).items():
        dest_zone = int(dest_zone_str)
        for input_str in input_list:
            input_num = int(input_str)
            crosspoint_id = f"input_{input_num}_to_zone_{dest_zone}"
            entities.append(
                AhmCrosspointLevelNumber(coordinator, crosspoint_id, input_num, dest_zone, is_zone_to_zone=False)
            )

    # Add zone-to-zone crosspoint level numbers
    for dest_zone_str, zone_list in cfg.get(CONF_ZONE_TO_ZONE_SENDS, {}).items():
        dest_zone = int(dest_zone_str)
        for source_zone_str in zone_list:
            source_zone = int(source_zone_str)
            crosspoint_id = f"zone_{source_zone}_to_zone_{dest_zone}"
            entities.append(
                AhmCrosspointLevelNumber(coordinator, crosspoint_id, source_zone, dest_zone, is_zone_to_zone=True)
            )

    async_add_entities(entities)


class AhmBaseLevelNumber(CoordinatorEntity, NumberEntity):
    """Base class for AHM level number entities."""

    def __init__(self, coordinator: AhmCoordinator, number: int, entity_type: str) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._number = number
        self._entity_type = entity_type
        self._attr_native_min_value = MIN_DB
        self._attr_native_max_value = MAX_DB
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = "dB"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        data = self._get_data()
        if data and data.get("level") is not None:
            level = data["level"]
            return level if level != float("-inf") else MIN_DB
        return None

    def _get_data(self) -> dict[str, Any] | None:
        """Get entity data from coordinator."""
        raise NotImplementedError

    async def _async_set_level(self, level: float) -> bool:
        """Set level in dB."""
        raise NotImplementedError

    async def async_set_native_value(self, value: float) -> None:
        """Set the level."""
        await self._async_set_level(value)


class AhmInputLevelNumber(AhmBaseLevelNumber):
    """AHM input level number entity."""

    def __init__(self, coordinator: AhmCoordinator, input_num: int) -> None:
        """Initialize the input level number."""
        super().__init__(coordinator, input_num, "input")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_input_level_{input_num}"
        self._attr_name = f"AHM Input {input_num} Level"
        self._attr_entity_category = EntityCategory.CONFIG

    def _get_data(self) -> dict[str, Any] | None:
        """Get input data from coordinator."""
        if self.coordinator.data and "inputs" in self.coordinator.data:
            return self.coordinator.data["inputs"].get(self._number)
        return None

    async def _async_set_level(self, level: float) -> bool:
        """Set input level in dB."""
        return await self.coordinator.async_set_input_level(self._number, level)


class AhmZoneLevelNumber(AhmBaseLevelNumber):
    """AHM zone level number entity."""

    def __init__(self, coordinator: AhmCoordinator, zone_num: int) -> None:
        """Initialize the zone level number."""
        super().__init__(coordinator, zone_num, "zone")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_zone_level_{zone_num}"
        self._attr_name = f"AHM Zone {zone_num} Level"
        self._attr_entity_category = EntityCategory.CONFIG

    def _get_data(self) -> dict[str, Any] | None:
        """Get zone data from coordinator."""
        if self.coordinator.data and "zones" in self.coordinator.data:
            return self.coordinator.data["zones"].get(self._number)
        return None

    async def _async_set_level(self, level: float) -> bool:
        """Set zone level in dB."""
        return await self.coordinator.async_set_zone_level(self._number, level)


class AhmControlGroupLevelNumber(AhmBaseLevelNumber):
    """AHM control group level number entity."""

    def __init__(self, coordinator: AhmCoordinator, cg_num: int) -> None:
        """Initialize the control group level number."""
        super().__init__(coordinator, cg_num, "control_group")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_control_group_level_{cg_num}"
        self._attr_name = f"AHM Control Group {cg_num} Level"
        self._attr_entity_category = EntityCategory.CONFIG

    def _get_data(self) -> dict[str, Any] | None:
        """Get control group data from coordinator."""
        if self.coordinator.data and "control_groups" in self.coordinator.data:
            return self.coordinator.data["control_groups"].get(self._number)
        return None

    async def _async_set_level(self, level: float) -> bool:
        """Set control group level in dB."""
        return await self.coordinator.async_set_control_group_level(self._number, level)


class AhmRoomLevelNumber(AhmBaseLevelNumber):
    """AHM room level number entity."""

    def __init__(self, coordinator: AhmCoordinator, room_num: int) -> None:
        """Initialize the room level number."""
        super().__init__(coordinator, room_num, "room")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_room_level_{room_num}"
        self._attr_name = f"AHM Room {room_num} Level"
        self._attr_entity_category = EntityCategory.CONFIG

    def _get_data(self) -> dict[str, Any] | None:
        """Get room data from coordinator."""
        if self.coordinator.data and "rooms" in self.coordinator.data:
            return self.coordinator.data["rooms"].get(self._number)
        return None

    async def _async_set_level(self, level: float) -> bool:
        """Set room level in dB."""
        return await self.coordinator.async_set_room_level(self._number, level)


class AhmCrosspointLevelNumber(CoordinatorEntity, NumberEntity):
    """Representation of an AHM crosspoint (send) level number entity."""

    def __init__(
        self,
        coordinator: AhmCoordinator,
        crosspoint_id: str,
        source_num: int,
        dest_zone: int,
        is_zone_to_zone: bool,
    ) -> None:
        """Initialize the crosspoint level number."""
        super().__init__(coordinator)
        self._crosspoint_id = crosspoint_id
        self._source_num = source_num
        self._dest_zone = dest_zone
        self._is_zone_to_zone = is_zone_to_zone

        source_type = "Zone" if is_zone_to_zone else "Input"
        self._attr_name = f"{source_type} {source_num} to Zone {dest_zone} Send Level"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{crosspoint_id}_level"
        self._attr_native_min_value = MIN_DB
        self._attr_native_max_value = MAX_DB
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = "dB"
        self._attr_mode = "box"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the current send level."""
        if not self.coordinator.data:
            return None
        crosspoint_data = self.coordinator.data.get("crosspoints", {}).get(self._crosspoint_id)
        if crosspoint_data is None:
            return None
        level = crosspoint_data.get("level")
        return level if level != float("-inf") else MIN_DB

    async def async_set_native_value(self, value: float) -> None:
        """Set the send level."""
        await self.coordinator.async_set_send_level(
            self._source_num, self._dest_zone, value, self._is_zone_to_zone
        )
