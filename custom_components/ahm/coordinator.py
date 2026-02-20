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
        self._push_task: asyncio.Task | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def start_push_listener(self) -> None:
        """Start the background task that applies real-time AHM push updates.

        Must be called after the first successful data refresh so ``self.data``
        is populated and ready to be updated.
        """
        if self._push_task is None or self._push_task.done():
            self._push_task = asyncio.ensure_future(self._push_listener_loop())

    async def _push_listener_loop(self) -> None:
        """Background task: drain unsolicited AHM messages and apply them immediately.

        The AHM sends MIDI push notifications whenever hardware state changes
        (e.g. someone turns a knob or presses a mute button). This loop wakes
        every 0.5 s, drains whatever has accumulated in the client's unsolicited
        buffer, applies the updates to local data, and notifies HA listeners —
        all without waiting for the 60-second poll.
        """
        while True:
            try:
                await asyncio.sleep(0.5)
                messages = self.client.drain_unsolicited()
                if messages and self.data:
                    updated_data = {**self.data}
                    if self._apply_unsolicited_updates(messages, updated_data):
                        self.async_set_updated_data(updated_data)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Push listener error: %s", err)

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
        """Fetch data from AHM device (slow poll — real-time updates handled by push listener)."""
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

    def _optimistic_update(
        self, data_key: str, entity_num: int | str, field: str, value: Any
    ) -> None:
        """Immediately reflect a confirmed write in the coordinator's local data.

        This avoids a full poll after every set command.  The AHM will also
        send an unsolicited update confirming the change, which will be a
        harmless no-op because the value already matches.
        """
        if not self.data:
            return
        section = self.data.get(data_key)
        if not section or entity_num not in section:
            return
        updated_data = {**self.data}
        updated_data[data_key] = {**section}
        updated_data[data_key][entity_num] = {**section[entity_num], field: value}
        self.async_set_updated_data(updated_data)

    async def async_set_input_mute(self, input_num: int, muted: bool) -> bool:
        """Set input mute status."""
        result = await self.client.set_input_mute(input_num, muted)
        if result:
            self._optimistic_update("inputs", input_num, "muted", muted)
        return result

    async def async_set_input_level(self, input_num: int, level: int) -> bool:
        """Set input level (raw MIDI 0-127)."""
        result = await self.client.set_input_level(input_num, level)
        if result:
            self._optimistic_update("inputs", input_num, "level", level)
        return result

    async def async_set_zone_mute(self, zone_num: int, muted: bool) -> bool:
        """Set zone mute status."""
        result = await self.client.set_zone_mute(zone_num, muted)
        if result:
            self._optimistic_update("zones", zone_num, "muted", muted)
        return result

    async def async_set_zone_level(self, zone_num: int, level: int) -> bool:
        """Set zone level (raw MIDI 0-127)."""
        result = await self.client.set_zone_level(zone_num, level)
        if result:
            self._optimistic_update("zones", zone_num, "level", level)
        return result

    async def async_set_control_group_mute(self, cg_num: int, muted: bool) -> bool:
        """Set control group mute status."""
        result = await self.client.set_control_group_mute(cg_num, muted)
        if result:
            self._optimistic_update("control_groups", cg_num, "muted", muted)
        return result

    async def async_set_control_group_level(self, cg_num: int, level: int) -> bool:
        """Set control group level (raw MIDI 0-127)."""
        result = await self.client.set_control_group_level(cg_num, level)
        if result:
            self._optimistic_update("control_groups", cg_num, "level", level)
        return result

    async def async_set_room_mute(self, room_num: int, muted: bool) -> bool:
        """Set room mute status."""
        result = await self.client.set_room_mute(room_num, muted)
        if result:
            self._optimistic_update("rooms", room_num, "muted", muted)
        return result

    async def async_set_room_level(self, room_num: int, level: int) -> bool:
        """Set room level (raw MIDI 0-127)."""
        result = await self.client.set_room_level(room_num, level)
        if result:
            self._optimistic_update("rooms", room_num, "level", level)
        return result

    async def async_recall_preset(self, preset_num: int) -> bool:
        """Recall a preset."""
        return await self.client.recall_preset(preset_num)

    async def async_play_audio(self, track_id: int, channel: int = 0) -> bool:
        """Play audio track."""
        return await self.client.play_audio(track_id, channel)

    async def async_shutdown(self) -> None:
        """Close the persistent connection and stop background tasks."""
        if self._push_task is not None:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
            self._push_task = None
        await self.client.async_disconnect()

    def _apply_unsolicited_updates(self, messages: list[bytes], data: dict[str, Any]) -> bool:
        """Parse unsolicited MIDI messages pushed by the AHM and apply to *data*.

        The AHM sends MIDI channel messages when hardware controls are changed:
          - Note On  (9N CH VL): mute state change for channel type N, channel CH
          - CC NRPN  (BN 63 CH, BN 62 17, BN 06 LV): level change

        Returns True if any state value was updated.
        """
        # Maps MIDI channel N → (data_key, label for logging)
        _CH_MAP = {
            0: "inputs",
            1: "zones",
            2: "control_groups",
            3: "rooms",
        }

        updated = False

        # NRPN parsing is stateful across three consecutive CC messages.
        # Track the partial state: {midi_channel_n: (nrpn_msb, nrpn_lsb)}
        nrpn_state: dict[int, tuple[int | None, int | None]] = {}

        for msg in messages:
            if not msg:
                continue

            status = msg[0]
            msg_type = status & 0xF0
            n = status & 0x0F  # MIDI channel (device type)

            # ---- Note On: mute state ----------------------------------------
            # Format (3 bytes): 9N CH VL
            # VL > 63 = muted on, 1–63 = muted off, 0 = Note Off (ignore)
            if msg_type == 0x90 and len(msg) == 3:
                velocity = msg[2]
                if velocity == 0:
                    continue  # Note Off — not meaningful here.
                ch_num = msg[1] + 1  # 0-indexed wire value → 1-indexed channel
                muted = velocity > 63
                data_key = _CH_MAP.get(n)
                if data_key and data_key in data and ch_num in data[data_key]:
                    data[data_key][ch_num]["muted"] = muted
                    _LOGGER.debug(
                        "Unsolicited mute: %s %d → %s",
                        data_key, ch_num, "ON" if muted else "OFF",
                    )
                    updated = True
                continue

            # ---- Control Change: NRPN level ---------------------------------
            # Three-message sequence per level change:
            #   BN 63 CH   (NRPN MSB = channel index)
            #   BN 62 17   (NRPN LSB = 0x17 → parameter "channel level")
            #   BN 06 LV   (Data Entry MSB = level MIDI value)
            if msg_type == 0xB0 and len(msg) == 3:
                cc = msg[1]
                val = msg[2]

                if cc == 0x63:   # NRPN MSB: channel index
                    nrpn_state[n] = (val, None)
                elif cc == 0x62:  # NRPN LSB: parameter ID
                    if n in nrpn_state and nrpn_state[n][0] is not None:
                        nrpn_state[n] = (nrpn_state[n][0], val)
                elif cc == 0x06:  # Data Entry MSB: value
                    state = nrpn_state.get(n)
                    if state and state[0] is not None and state[1] == 0x17:
                        # Complete level NRPN for channel type N, channel state[0]
                        ch_num = state[0] + 1  # 0-indexed → 1-indexed
                        data_key = _CH_MAP.get(n)
                        if data_key and data_key in data and ch_num in data[data_key]:
                            data[data_key][ch_num]["level"] = val
                            _LOGGER.debug(
                                "Unsolicited level: %s %d → %d",
                                data_key, ch_num, val,
                            )
                            updated = True
                    nrpn_state.pop(n, None)  # Reset state after value byte.
                continue

        return updated

    async def async_set_send_mute(self, source_num: int, dest_zone: int, muted: bool, is_zone_to_zone: bool = False) -> bool:
        """Set send mute status."""
        source_type = "zone" if is_zone_to_zone else "input"
        result = await self.client.set_send_mute(source_type, source_num, dest_zone, muted)
        if result:
            src_prefix = "zone" if is_zone_to_zone else "input"
            crosspoint_id = f"{src_prefix}_{source_num}_to_zone_{dest_zone}"
            self._optimistic_update("crosspoints", crosspoint_id, "muted", muted)
        return result

    async def async_set_send_level(self, source_num: int, dest_zone: int, level: int, is_zone_to_zone: bool = False) -> bool:
        """Set send level (raw MIDI 0-127)."""
        source_type = "zone" if is_zone_to_zone else "input"
        result = await self.client.set_send_level(source_type, source_num, dest_zone, level)
        if result:
            src_prefix = "zone" if is_zone_to_zone else "input"
            crosspoint_id = f"{src_prefix}_{source_num}_to_zone_{dest_zone}"
            self._optimistic_update("crosspoints", crosspoint_id, "level", level)
        return result
