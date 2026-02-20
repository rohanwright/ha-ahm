"""Data update coordinator for AHM integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ahm_client import AhmClient
from .const import (
    DOMAIN,
    UPDATE_INTERVAL,
    CONF_HOST,
    CONF_NAME,
    CONF_VERSION,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_ROOMS,
    CONF_INPUT_TO_ZONE_SENDS,
    CONF_ZONE_TO_ZONE_SENDS,
)

_LOGGER = logging.getLogger(__name__)


class AhmCoordinator(DataUpdateCoordinator):
    """AHM data update coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.client = AhmClient(
            host=entry.data[CONF_HOST],
            version=entry.data.get(CONF_VERSION, "1.5")
        )
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": self.entry.data[CONF_NAME],
            "manufacturer": "Allen & Heath",
            "model": "AHM Zone Mixer",
            "sw_version": self.entry.data.get(CONF_VERSION, "1.5"),
        }

    @property
    def config(self) -> dict[str, Any]:
        """Return effective config: entry.options takes precedence over entry.data.

        Connection parameters (host, version) always come from entry.data since
        they are not editable via the options flow.
        """
        return {**self.entry.data, **self.entry.options}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from AHM device."""
        try:
            data = {}
            cfg = self.config

            # Get input data
            if CONF_INPUTS in cfg:
                data["inputs"] = {}
                for input_num in cfg[CONF_INPUTS]:
                    input_num = int(input_num)
                    input_data = await self._get_input_data(input_num)
                    if input_data:
                        data["inputs"][input_num] = input_data

            # Get zone data
            if CONF_ZONES in cfg:
                data["zones"] = {}
                for zone_num in cfg[CONF_ZONES]:
                    zone_num = int(zone_num)
                    zone_data = await self._get_zone_data(zone_num)
                    if zone_data:
                        data["zones"][zone_num] = zone_data

            # Get control group data
            if CONF_CONTROL_GROUPS in cfg:
                data["control_groups"] = {}
                for cg_num in cfg[CONF_CONTROL_GROUPS]:
                    cg_num = int(cg_num)
                    cg_data = await self._get_control_group_data(cg_num)
                    if cg_data:
                        data["control_groups"][cg_num] = cg_data

            # Get room data
            if CONF_ROOMS in cfg:
                data["rooms"] = {}
                for room_num in cfg[CONF_ROOMS]:
                    room_num = int(room_num)
                    room_data = await self._get_room_data(room_num)
                    if room_data:
                        data["rooms"][room_num] = room_data

            # Get crosspoint data
            await self._collect_crosspoint_data(data)

            return data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with AHM device: {err}") from err

    async def _get_input_data(self, input_num: int) -> dict[str, Any] | None:
        """Get data for a specific input."""
        try:
            tasks = [
                self.client.get_input_muted(input_num),
                self.client.get_input_level(input_num),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get input %d data: %s", input_num, err)
            return None

    async def _get_zone_data(self, zone_num: int) -> dict[str, Any] | None:
        """Get data for a specific zone."""
        try:
            tasks = [
                self.client.get_zone_muted(zone_num),
                self.client.get_zone_level(zone_num),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get zone %d data: %s", zone_num, err)
            return None

    async def _get_control_group_data(self, cg_num: int) -> dict[str, Any] | None:
        """Get data for a specific control group."""
        try:
            tasks = [
                self.client.get_control_group_muted(cg_num),
                self.client.get_control_group_level(cg_num),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get control group %d data: %s", cg_num, err)
            return None

    async def _get_room_data(self, room_num: int) -> dict[str, Any] | None:
        """Get data for a specific room."""
        try:
            tasks = [
                self.client.get_room_muted(room_num),
                self.client.get_room_level(room_num),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get room %d data: %s", room_num, err)
            return None

    async def _collect_crosspoint_data(self, data: dict[str, Any]) -> None:
        """Collect crosspoint (send) data."""
        data["crosspoints"] = {}

        cfg = self.config
        input_to_zone_sends = cfg.get(CONF_INPUT_TO_ZONE_SENDS, {})
        for dest_zone_str, input_list in input_to_zone_sends.items():
            dest_zone = int(dest_zone_str)
            for input_str in input_list:
                input_num = int(input_str)
                crosspoint_id = f"input_{input_num}_to_zone_{dest_zone}"
                crosspoint_data = await self._get_input_to_zone_send_data(input_num, dest_zone)
                if crosspoint_data:
                    data["crosspoints"][crosspoint_id] = crosspoint_data

        # Collect zone-to-zone sends
        zone_to_zone_sends = cfg.get(CONF_ZONE_TO_ZONE_SENDS, {})
        for dest_zone_str, zone_list in zone_to_zone_sends.items():
            dest_zone = int(dest_zone_str)
            for source_zone_str in zone_list:
                source_zone = int(source_zone_str)
                crosspoint_id = f"zone_{source_zone}_to_zone_{dest_zone}"
                crosspoint_data = await self._get_zone_to_zone_send_data(source_zone, dest_zone)
                if crosspoint_data:
                    data["crosspoints"][crosspoint_id] = crosspoint_data

    async def _get_input_to_zone_send_data(self, input_num: int, zone_num: int) -> dict[str, Any] | None:
        """Get data for an input-to-zone send."""
        try:
            tasks = [
                self.client.get_send_muted("input", input_num, zone_num),
                self.client.get_send_level("input", input_num, zone_num),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
                "source_type": "input",
                "source_num": input_num,
                "dest_zone": zone_num,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get input %d to zone %d send data: %s", input_num, zone_num, err)
            return None

    async def _get_zone_to_zone_send_data(self, source_zone: int, dest_zone: int) -> dict[str, Any] | None:
        """Get data for a zone-to-zone send."""
        try:
            tasks = [
                self.client.get_send_muted("zone", source_zone, dest_zone),
                self.client.get_send_level("zone", source_zone, dest_zone),
            ]
            
            muted, level = await asyncio.gather(*tasks, return_exceptions=True)
            
            return {
                "muted": muted if not isinstance(muted, Exception) else None,
                "level": level if not isinstance(level, Exception) else None,
                "source_type": "zone",
                "source_num": source_zone,
                "dest_zone": dest_zone,
            }
        except Exception as err:
            _LOGGER.debug("Failed to get zone %d to zone %d send data: %s", source_zone, dest_zone, err)
            return None

    async def async_set_input_mute(self, input_num: int, muted: bool) -> bool:
        """Set input mute status."""
        result = await self.client.set_input_mute(input_num, muted)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_input_level(self, input_num: int, level: float) -> bool:
        """Set input level."""
        result = await self.client.set_input_level(input_num, level)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_zone_mute(self, zone_num: int, muted: bool) -> bool:
        """Set zone mute status."""
        result = await self.client.set_zone_mute(zone_num, muted)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_zone_level(self, zone_num: int, level: float) -> bool:
        """Set zone level."""
        result = await self.client.set_zone_level(zone_num, level)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_control_group_mute(self, cg_num: int, muted: bool) -> bool:
        """Set control group mute status."""
        result = await self.client.set_control_group_mute(cg_num, muted)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_control_group_level(self, cg_num: int, level: float) -> bool:
        """Set control group level."""
        result = await self.client.set_control_group_level(cg_num, level)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_room_mute(self, room_num: int, muted: bool) -> bool:
        """Set room mute status."""
        result = await self.client.set_room_mute(room_num, muted)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_room_level(self, room_num: int, level: float) -> bool:
        """Set room level."""
        result = await self.client.set_room_level(room_num, level)
        if result:
            await self.async_request_refresh()
        return result

    async def async_recall_preset(self, preset_num: int) -> bool:
        """Recall a preset."""
        return await self.client.recall_preset(preset_num)

    async def async_play_audio(self, track_id: int, channel: int = 0) -> bool:
        """Play audio track."""
        return await self.client.play_audio(track_id, channel)

    async def async_shutdown(self) -> None:
        """Close the persistent connection to the AHM device."""
        await self.client.async_disconnect()

    # Crosspoint control methods
    async def async_set_send_mute(self, source_num: int, dest_zone: int, muted: bool, is_zone_to_zone: bool = False) -> bool:
        """Set send mute status."""
        source_type = "zone" if is_zone_to_zone else "input"
        result = await self.client.set_send_mute(source_type, source_num, dest_zone, muted)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_send_level(self, source_num: int, dest_zone: int, level: float, is_zone_to_zone: bool = False) -> bool:
        """Set send level."""
        source_type = "zone" if is_zone_to_zone else "input"
        result = await self.client.set_send_level(source_type, source_num, dest_zone, level)
        if result:
            await self.async_request_refresh()
        return result
