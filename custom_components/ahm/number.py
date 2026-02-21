"""Number platform for AHM integration - for fine-grained level control."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
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
    MIDI_LEVEL_MIN,
    MIDI_LEVEL_MAX,
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
        self._attr_native_min_value = MIDI_LEVEL_MIN
        self._attr_native_max_value = MIDI_LEVEL_MAX
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> int | None:
        """Return the current value (raw MIDI 0-127)."""
        data = self._get_data()
        if data is not None:
            return data.get("level")
        return None

    def _get_data(self) -> dict[str, Any] | None:
        """Get entity data from coordinator."""
        raise NotImplementedError

    async def _async_set_level(self, level: int) -> bool:
        """Set level (raw MIDI 0-127)."""
        raise NotImplementedError

    async def async_set_native_value(self, value: float) -> None:
        """Set the level."""
        await self._async_set_level(int(value))


class AhmInputLevelNumber(AhmBaseLevelNumber):
    """AHM input level number entity."""

    def __init__(self, coordinator: AhmCoordinator, input_num: int) -> None:
        """Initialize the input level number."""
        super().__init__(coordinator, input_num, "input")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_input_level_{input_num}"
        self._attr_name = f"AHM Input {input_num} Level"

    def _get_data(self) -> dict[str, Any] | None:
        """Get input data from coordinator."""
        if self.coordinator.data and "inputs" in self.coordinator.data:
            return self.coordinator.data["inputs"].get(self._number)
        return None

    async def _async_set_level(self, level: int) -> bool:
        """Set input level (raw MIDI 0-127)."""
        return await self.coordinator.async_set_input_level(self._number, level)


class AhmZoneLevelNumber(AhmBaseLevelNumber):
    """AHM zone level number entity."""

    def __init__(self, coordinator: AhmCoordinator, zone_num: int) -> None:
        """Initialize the zone level number."""
        super().__init__(coordinator, zone_num, "zone")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_zone_level_{zone_num}"
        self._attr_name = f"AHM Zone {zone_num} Level"

    def _get_data(self) -> dict[str, Any] | None:
        """Get zone data from coordinator."""
        if self.coordinator.data and "zones" in self.coordinator.data:
            return self.coordinator.data["zones"].get(self._number)
        return None

    async def _async_set_level(self, level: int) -> bool:
        """Set zone level (raw MIDI 0-127)."""
        return await self.coordinator.async_set_zone_level(self._number, level)


class AhmControlGroupLevelNumber(AhmBaseLevelNumber):
    """AHM control group level number entity."""

    def __init__(self, coordinator: AhmCoordinator, cg_num: int) -> None:
        """Initialize the control group level number."""
        super().__init__(coordinator, cg_num, "control_group")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_control_group_level_{cg_num}"
        self._attr_name = f"AHM Control Group {cg_num} Level"

    def _get_data(self) -> dict[str, Any] | None:
        """Get control group data from coordinator."""
        if self.coordinator.data and "control_groups" in self.coordinator.data:
            return self.coordinator.data["control_groups"].get(self._number)
        return None

    async def _async_set_level(self, level: int) -> bool:
        """Set control group level (raw MIDI 0-127)."""
        return await self.coordinator.async_set_control_group_level(self._number, level)


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
        self._attr_native_min_value = MIDI_LEVEL_MIN
        self._attr_native_max_value = MIDI_LEVEL_MAX
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> int | None:
        """Return the current send level (raw MIDI 0-127)."""
        if not self.coordinator.data:
            return None
        crosspoint_data = self.coordinator.data.get("crosspoints", {}).get(self._crosspoint_id)
        if crosspoint_data is None:
            return None
        return crosspoint_data.get("level")

    async def async_set_native_value(self, value: float) -> None:
        """Set the send level."""
        await self.coordinator.async_set_send_level(
            self._source_num, self._dest_zone, int(value), self._is_zone_to_zone
        )
