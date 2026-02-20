"""Media player platform for AHM integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_ROOMS,
    MIN_DB,
    MAX_DB,
)
from .coordinator import AhmCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AHM media player entities."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    # Merge options over data so the options flow changes take effect.
    cfg = {**config_entry.data, **config_entry.options}
    entities = []

    # Add input entities
    if CONF_INPUTS in cfg:
        for input_num in cfg[CONF_INPUTS]:
            entities.append(
                AhmInputMediaPlayer(coordinator, int(input_num))
            )

    # Add zone entities
    if CONF_ZONES in cfg:
        for zone_num in cfg[CONF_ZONES]:
            entities.append(
                AhmZoneMediaPlayer(coordinator, int(zone_num))
            )

    # Add control group entities
    if CONF_CONTROL_GROUPS in cfg:
        for cg_num in cfg[CONF_CONTROL_GROUPS]:
            entities.append(
                AhmControlGroupMediaPlayer(coordinator, int(cg_num))
            )

    # Add room entities
    if CONF_ROOMS in cfg:
        for room_num in cfg[CONF_ROOMS]:
            entities.append(
                AhmRoomMediaPlayer(coordinator, int(room_num))
            )

    async_add_entities(entities)


class AhmBaseMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Base class for AHM media player entities."""

    def __init__(self, coordinator: AhmCoordinator, number: int, entity_type: str) -> None:
        """Initialize the media player."""
        super().__init__(coordinator)
        self._number = number
        self._entity_type = entity_type
        self._attr_supported_features = (
            MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return self.coordinator.device_info

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the media player."""
        if self._get_data() and self._get_data().get("muted"):
            return MediaPlayerState.OFF
        return MediaPlayerState.ON

    @property
    def is_volume_muted(self) -> bool | None:
        """Return boolean if volume is currently muted."""
        data = self._get_data()
        return data.get("muted") if data else None

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        data = self._get_data()
        if data and data.get("level") is not None:
            level_db = data["level"]
            if level_db == float("-inf"):
                return 0.0
            # Convert from dB range to 0-1
            return max(0.0, min(1.0, (level_db - MIN_DB) / (MAX_DB - MIN_DB)))
        return None

    def _get_data(self) -> dict[str, Any] | None:
        """Get entity data from coordinator."""
        raise NotImplementedError

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set mute status."""
        raise NotImplementedError

    async def _async_set_level(self, level: float) -> bool:
        """Set level in dB."""
        raise NotImplementedError

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        await self._async_set_mute(mute)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        # Convert from 0-1 to dB range
        level_db = MIN_DB + (volume * (MAX_DB - MIN_DB))
        await self._async_set_level(level_db)


class AhmInputMediaPlayer(AhmBaseMediaPlayer):
    """AHM input media player entity."""

    def __init__(self, coordinator: AhmCoordinator, input_num: int) -> None:
        """Initialize the input media player."""
        super().__init__(coordinator, input_num, "input")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_input_{input_num}"
        self._attr_name = f"AHM Input {input_num}"

    def _get_data(self) -> dict[str, Any] | None:
        """Get input data from coordinator."""
        if self.coordinator.data and "inputs" in self.coordinator.data:
            return self.coordinator.data["inputs"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set input mute status."""
        return await self.coordinator.async_set_input_mute(self._number, muted)

    async def _async_set_level(self, level: float) -> bool:
        """Set input level in dB."""
        return await self.coordinator.async_set_input_level(self._number, level)


class AhmZoneMediaPlayer(AhmBaseMediaPlayer):
    """AHM zone media player entity."""

    def __init__(self, coordinator: AhmCoordinator, zone_num: int) -> None:
        """Initialize the zone media player."""
        super().__init__(coordinator, zone_num, "zone")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_zone_{zone_num}"
        self._attr_name = f"AHM Zone {zone_num}"

    def _get_data(self) -> dict[str, Any] | None:
        """Get zone data from coordinator."""
        if self.coordinator.data and "zones" in self.coordinator.data:
            return self.coordinator.data["zones"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set zone mute status."""
        return await self.coordinator.async_set_zone_mute(self._number, muted)

    async def _async_set_level(self, level: float) -> bool:
        """Set zone level in dB."""
        return await self.coordinator.async_set_zone_level(self._number, level)


class AhmControlGroupMediaPlayer(AhmBaseMediaPlayer):
    """AHM control group media player entity."""

    def __init__(self, coordinator: AhmCoordinator, cg_num: int) -> None:
        """Initialize the control group media player."""
        super().__init__(coordinator, cg_num, "control_group")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_control_group_{cg_num}"
        self._attr_name = f"AHM Control Group {cg_num}"

    def _get_data(self) -> dict[str, Any] | None:
        """Get control group data from coordinator."""
        if self.coordinator.data and "control_groups" in self.coordinator.data:
            return self.coordinator.data["control_groups"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set control group mute status."""
        return await self.coordinator.async_set_control_group_mute(self._number, muted)

    async def _async_set_level(self, level: float) -> bool:
        """Set control group level in dB."""
        return await self.coordinator.async_set_control_group_level(self._number, level)


class AhmRoomMediaPlayer(AhmBaseMediaPlayer):
    """AHM room media player entity."""

    def __init__(self, coordinator: AhmCoordinator, room_num: int) -> None:
        """Initialize the room media player."""
        super().__init__(coordinator, room_num, "room")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_room_{room_num}"
        self._attr_name = f"AHM Room {room_num}"

    def _get_data(self) -> dict[str, Any] | None:
        """Get room data from coordinator."""
        if self.coordinator.data and "rooms" in self.coordinator.data:
            return self.coordinator.data["rooms"].get(self._number)
        return None

    async def _async_set_mute(self, muted: bool) -> bool:
        """Set room mute status."""
        return await self.coordinator.async_set_room_mute(self._number, muted)

    async def _async_set_level(self, level: float) -> bool:
        """Set room level in dB."""
        return await self.coordinator.async_set_room_level(self._number, level)
