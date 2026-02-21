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
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
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
        """Background task: drain incoming AHM messages and apply them to HA state.

        The AHM sends MIDI push notifications whenever hardware state changes
        (e.g. someone turns a knob or presses a mute button).  GET query responses
        for channel entities (Note On / NRPN CC) are byte-for-byte identical to
        those unsolicited messages, so this loop handles both naturally.

        Wakes every 0.5 s, drains everything in the rx queue, applies any mute or
        level changes to local data, and notifies HA listeners immediately —
        without waiting for the 60-second poll.
        """
        while True:
            try:
                await asyncio.sleep(0.5)
                messages = self.client.drain_queue()
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
            "sw_version": None,
        }

    @property
    def config(self) -> dict[str, Any]:
        """Return effective config: entry.options takes precedence over entry.data.

        Connection parameters (host, version) always come from entry.data since
        they are not editable via the options flow.
        """
        return {**self.entry.data, **self.entry.options}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch / refresh data from the AHM device.

        **First call** (``self.data is None``):
          Sends GET requests for every configured channel entity, waits 500 ms
          for the AHM to respond (responses are MIDI Note On / NRPN CC messages,
          identical in format to unsolicited push messages), drains the queue,
          applies state to build the initial data dictionary, then queries each
          crosspoint individually via SysEx.

        **Subsequent calls** (regular 60-second poll):
          Re-requests all channel states and crosspoints so the integration
          always has authoritative state from the device, catching any updates
          missed by the push listener.
        """
        try:
            if self.data is None:
                return await self._initial_load()

            # Periodic poll: refresh channel states (inputs/zones/CGs).
            updated = {**self.data}
            await self._request_all_channel_states()
            await asyncio.sleep(0.5)
            messages = self.client.drain_queue()
            if messages:
                self._apply_unsolicited_updates(messages, updated)

            # Also refresh crosspoints.
            await self._collect_crosspoint_data(updated)
            return updated

        except Exception as err:
            raise UpdateFailed(f"Error communicating with AHM device: {err}") from err

    async def _initial_load(self) -> dict[str, Any]:
        """Build the first data dict by sending GETs and waiting for responses."""
        cfg = self.config

        # Initialise empty state containers for every configured entity so that
        # entities exist even if no GET response arrives within the window.
        data: dict[str, Any] = {
            "inputs": {int(n): {"muted": None, "level": None} for n in cfg.get(CONF_INPUTS, [])},
            "zones": {int(n): {"muted": None, "level": None} for n in cfg.get(CONF_ZONES, [])},
            "control_groups": {int(n): {"muted": None, "level": None} for n in cfg.get(CONF_CONTROL_GROUPS, [])},
            "crosspoints": {},
        }

        # Fire off GET requests for all channel entities (fire-and-forget).
        await self._request_all_channel_states()

        # Give the AHM time to send back responses.  The reader places them in
        # the queue as normal MIDI messages; we drain and apply them below.
        await asyncio.sleep(0.5)

        messages = self.client.drain_queue()
        if messages:
            self._apply_unsolicited_updates(messages, data)

        # Crosspoints respond with SysEx, not MIDI, so they need explicit polling.
        await self._collect_crosspoint_data(data)

        return data

    async def _request_all_channel_states(self) -> None:
        """Fire GET requests for all configured channel entities (inputs/zones/CGs).

        Each request sends two SysEx GET packets (mute + level) per entity.
        The AHM responds with identical MIDI to its unsolicited push messages;
        the push listener (or the initial-load drain) processes the responses.
        """
        cfg = self.config
        for num in cfg.get(CONF_INPUTS, []):
            await self.client.request_input_state(int(num))
        for num in cfg.get(CONF_ZONES, []):
            await self.client.request_zone_state(int(num))
        for num in cfg.get(CONF_CONTROL_GROUPS, []):
            await self.client.request_control_group_state(int(num))

    async def _collect_crosspoint_data(self, data: dict[str, Any]) -> None:
        """Collect crosspoint (send) data, merging fresh query results into existing state.

        Existing values (from push updates or previous successful queries) are
        preserved when a query times out, so a missed poll never blanks a
        crosspoint that the push listener already has correct.
        """
        cp_data: dict[str, Any] = data.setdefault("crosspoints", {})

        cfg = self.config
        input_to_zone_sends = cfg.get(CONF_INPUT_TO_ZONE_SENDS, {})
        for dest_zone_str, input_list in input_to_zone_sends.items():
            dest_zone = int(dest_zone_str)
            for input_str in input_list:
                input_num = int(input_str)
                crosspoint_id = f"input_{input_num}_to_zone_{dest_zone}"
                # Ensure the entry exists so the push listener can update it even
                # if every GET query times out.
                cp_data.setdefault(crosspoint_id, {
                    "muted": None, "level": None,
                    "source_type": "input", "source_num": input_num, "dest_zone": dest_zone,
                })
                await self._merge_crosspoint_data(cp_data, crosspoint_id, "input", input_num, dest_zone)

        zone_to_zone_sends = cfg.get(CONF_ZONE_TO_ZONE_SENDS, {})
        for dest_zone_str, zone_list in zone_to_zone_sends.items():
            dest_zone = int(dest_zone_str)
            for source_zone_str in zone_list:
                source_zone = int(source_zone_str)
                crosspoint_id = f"zone_{source_zone}_to_zone_{dest_zone}"
                cp_data.setdefault(crosspoint_id, {
                    "muted": None, "level": None,
                    "source_type": "zone", "source_num": source_zone, "dest_zone": dest_zone,
                })
                await self._merge_crosspoint_data(cp_data, crosspoint_id, "zone", source_zone, dest_zone)

    async def _merge_crosspoint_data(
        self, cp_data: dict[str, Any], crosspoint_id: str, source_type: str, source_num: int, dest_zone: int
    ) -> None:
        """Query a crosspoint and update only the fields the device replied to."""
        try:
            muted = await self.client.get_send_muted(source_type, source_num, dest_zone)
            if muted is not None:
                cp_data[crosspoint_id]["muted"] = muted

            level = await self.client.get_send_level(source_type, source_num, dest_zone)
            if level is not None:
                cp_data[crosspoint_id]["level"] = level
        except Exception as err:
            _LOGGER.debug(
                "Failed to query crosspoint %s: %s", crosspoint_id, err
            )

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
        }

        updated = False

        # NRPN parsing is stateful across three consecutive CC messages.
        # Track the partial state: {midi_channel_n: (nrpn_msb, nrpn_lsb)}
        nrpn_state: dict[int, tuple[int | None, int | None]] = {}

        for msg in messages:
            if not msg:
                continue

            # ---- SysEx: crosspoint (send level/mute) push -------------------
            # The AHM sends unsolicited SysEx when a crosspoint changes, either
            # from a hardware adjustment or as a confirmation after a SET command.
            # Format (15 bytes total):
            #   F0 00 00 1A 50 12 VV VV  ← 8-byte SysEx header
            #   SND_N CMD SND_CH 01 DEST_CH VALUE F7
            # This is the same byte layout as the SET command.
            # SND_N:   00=input source, 01=zone source
            # CMD:     02=level, 03=mute
            # SND_CH:  source channel, 0-indexed
            # DEST_CH: destination zone, 0-indexed
            # VALUE:   raw MIDI level (0-127) or mute (>63=muted)
            if msg[0] == 0xF0 and len(msg) == 15:
                snd_n   = msg[8]
                cmd     = msg[9]
                snd_ch  = msg[10]  # source channel (same layout as SET command)
                # msg[11] = dest_n, always 01 (destination is always a zone)
                dest_ch = msg[12]  # destination zone
                value   = msg[13]

                if snd_n == 0x00:
                    src_prefix = "input"
                elif snd_n == 0x01:
                    src_prefix = "zone"
                else:
                    continue

                crosspoint_id = f"{src_prefix}_{snd_ch + 1}_to_zone_{dest_ch + 1}"
                cp_data = data.get("crosspoints", {})
                if crosspoint_id in cp_data:
                    if cmd == 0x02:  # level
                        cp_data[crosspoint_id]["level"] = value
                        _LOGGER.debug(
                            "Unsolicited crosspoint level: %s → %d",
                            crosspoint_id, value,
                        )
                        updated = True
                    elif cmd == 0x03:  # mute
                        muted = value > 63
                        cp_data[crosspoint_id]["muted"] = muted
                        _LOGGER.debug(
                            "Unsolicited crosspoint mute: %s → %s",
                            crosspoint_id, "ON" if muted else "OFF",
                        )
                        updated = True
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
