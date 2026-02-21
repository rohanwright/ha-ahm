"""Config flow for AHM integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store

from .ahm_client import AhmClient
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_MODEL,
    CONF_HOST,
    CONF_NAME,
    CONF_MODEL,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_INPUT_TO_ZONE_SENDS,
    CONF_ZONE_TO_ZONE_SENDS,
    MODEL_LIMITS,
)

_LOGGER = logging.getLogger(__name__)

# Maps device-type byte → entity_type key (mirrors AhmCoordinator._CH_MAP).
_CH_NAME_MAP: dict[int, str] = {0: "inputs", 1: "zones", 2: "control_groups"}


def _channel_label(names: dict, entity_type: str, number: int, prefix: str) -> str:
    """Return 'Prefix N - Name' if a fetched name exists, otherwise 'Prefix N'."""
    name = names.get(entity_type, {}).get(number)
    return f"{prefix} {number} - {name}" if name else f"{prefix} {number}"


async def _fetch_channel_names(
    client: AhmClient, limits: dict
) -> dict[str, dict[int, str]]:
    """Send name GET requests to the AHM and return responses that arrive within 1 s.

    Fires a SysEx GET (cmd 0x09) for every input, zone, and control group
    within the model limits then waits 1 second for the device to reply.
    Name responses (cmd 0x0A) are parsed from the rx queue.

    Returns ``{entity_type: {1_indexed_ch_num: name_str}}``.
    """
    for n in range(limits["inputs"]):
        await client.request_channel_name(0, n + 1)
    for n in range(limits["zones"]):
        await client.request_channel_name(1, n + 1)
    for n in range(limits["control_groups"]):
        await client.request_channel_name(2, n + 1)

    await asyncio.sleep(1.0)

    names: dict[str, dict[int, str]] = {}
    for msg in client.drain_queue():
        if msg[0] == 0xF0 and len(msg) >= 12 and msg[9] == 0x0A:
            data_key = _CH_NAME_MAP.get(msg[8])
            ch_num = msg[10] + 1  # wire is 0-indexed; store as 1-indexed
            try:
                # AHM pads short names to 8 chars with NUL bytes — strip them
                # before decoding, then strip any trailing/leading whitespace.
                name = bytes(msg[11:-1]).rstrip(b"\x00").decode("ascii").strip()
            except (UnicodeDecodeError, ValueError):
                name = ""
            if data_key and name:
                names.setdefault(data_key, {})[ch_num] = name
    return names


class AhmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AHM."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.data: dict[str, Any] = {}
        # Zone iteration state — kept on self so it never ends up in entry.data.
        self._selected_zones: list[int] = []
        self._current_zone_index: int = 0
        # Channel names fetched from the AHM during the connection step.
        # Used to label multi-select options as "Input 1 - Spotify" etc.
        self._channel_names: dict[str, dict[int, str]] = {}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "AhmOptionsFlow":
        """Return the options flow handler."""
        return AhmOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                client = AhmClient(
                    host=user_input[CONF_HOST],
                )
                connected = await client.async_connect()
                if connected:
                    # Fetch channel names while we still have the connection open.
                    # Names are used to label the entity-selection multi-selects.
                    self._channel_names = await _fetch_channel_names(
                        client, MODEL_LIMITS[user_input[CONF_MODEL]]
                    )
                    await client.async_disconnect()

                if connected:
                    self.data.update(user_input)
                    return await self.async_step_entities()
                else:
                    errors["base"] = "cannot_connect"

            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        data_schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Required(CONF_MODEL, default=DEFAULT_MODEL): vol.In(list(MODEL_LIMITS.keys())),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle entity selection step."""
        if user_input is not None:
            self.data.update(user_input)

            selected_zones = self.data.get(CONF_ZONES, [])
            if selected_zones:
                # Initialise zone iteration state on self (not self.data).
                self._selected_zones = [int(z) for z in selected_zones]
                self._current_zone_index = 0
                self.data[CONF_INPUT_TO_ZONE_SENDS] = {}
                self.data[CONF_ZONE_TO_ZONE_SENDS] = {}
                return await self.async_step_zone_crosspoints()
            else:
                self.data["channel_names"] = {
                    et: {str(k): v for k, v in ch.items()}
                    for et, ch in self._channel_names.items()
                }
                return self.async_create_entry(
                    title=self.data[CONF_NAME],
                    data=self.data,
                )

        # Build entity selection schema using the chosen model's limits.
        limits = MODEL_LIMITS[self.data[CONF_MODEL]]
        n = self._channel_names
        data_schema = vol.Schema({
            vol.Optional(CONF_INPUTS, default=["1"]): cv.multi_select({
                str(i): _channel_label(n, "inputs", i, "Input")
                for i in range(1, limits["inputs"] + 1)
            }),
            vol.Optional(CONF_ZONES, default=["1"]): cv.multi_select({
                str(i): _channel_label(n, "zones", i, "Zone")
                for i in range(1, limits["zones"] + 1)
            }),
            vol.Optional(CONF_CONTROL_GROUPS, default=[]): cv.multi_select({
                str(i): _channel_label(n, "control_groups", i, "Control Group")
                for i in range(1, limits["control_groups"] + 1)
            }),
        })

        return self.async_show_form(
            step_id="entities",
            data_schema=data_schema,
            description_placeholders={
                "name": self.data[CONF_NAME],
            },
        )

    async def async_step_zone_crosspoints(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle per-zone crosspoint send configuration.

        Iterates through every selected zone in sequence, presenting a
        multi-select for input-to-zone and zone-to-zone sends. Leaving both
        empty is valid — it simply means no crosspoints are created for that
        zone. Temporary iteration state is stored on *self*, not self.data, so
        it never leaks into the config entry.
        """
        if self._current_zone_index >= len(self._selected_zones):
            # All zones visited — persist and finish.
            self.data["channel_names"] = {
                et: {str(k): v for k, v in ch.items()}
                for et, ch in self._channel_names.items()
            }
            return self.async_create_entry(
                title=self.data[CONF_NAME],
                data=self.data,
            )

        current_zone = self._selected_zones[self._current_zone_index]

        if user_input is not None:
            input_sends = user_input.get("input_sends", [])
            zone_sends = user_input.get("zone_sends", [])

            if input_sends:
                self.data[CONF_INPUT_TO_ZONE_SENDS][str(current_zone)] = [
                    str(i) for i in input_sends
                ]
            if zone_sends:
                self.data[CONF_ZONE_TO_ZONE_SENDS][str(current_zone)] = [
                    str(z) for z in zone_sends
                ]

            self._current_zone_index += 1
            return await self.async_step_zone_crosspoints()

        # Build schema for this zone.
        selected_inputs = self.data.get(CONF_INPUTS, [])
        available_zones = [z for z in self._selected_zones if z != current_zone]

        n = self._channel_names
        schema_dict: dict = {}
        if selected_inputs:
            schema_dict[vol.Optional("input_sends", default=[])] = cv.multi_select(
                {str(i): _channel_label(n, "inputs", int(i), "Input") for i in selected_inputs}
            )
        if available_zones:
            schema_dict[vol.Optional("zone_sends", default=[])] = cv.multi_select(
                {str(z): _channel_label(n, "zones", z, "Zone") for z in available_zones}
            )

        if not schema_dict:
            # Nothing to configure for this zone — skip it silently.
            self._current_zone_index += 1
            return await self.async_step_zone_crosspoints()

        progress = f"({self._current_zone_index + 1}/{len(self._selected_zones)})"

        return self.async_show_form(
            step_id="zone_crosspoints",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zone_label": _channel_label(n, "zones", current_zone, "Zone"),
                "zone_number": str(current_zone),
                "progress": progress,
                "input_count": str(len(selected_inputs)),
                "zone_count": str(len(available_zones)),
            },
        )


class AhmOptionsFlow(config_entries.OptionsFlow):
    """Handle options for AHM integration.

    Allows changing entity selections and crosspoint routing after initial
    setup. HA automatically reloads the config entry when options are saved.
    The connection parameters (host, firmware version) are not editable here
    — those require re-adding the integration.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise the options flow."""
        self._entry = config_entry
        self._options: dict[str, Any] = {}
        self._selected_zones: list[int] = []
        self._current_zone_index: int = 0
        # Channel names loaded from storage for friendly multi-select labels.
        self._channel_names: dict[str, dict[int, str]] = {}

    @property
    def _current_config(self) -> dict[str, Any]:
        """Return the current effective config: options override entry data."""
        return {**self._entry.data, **self._entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Entity selection step — pre-populated with current values."""
        cfg = self._current_config

        if user_input is not None:
            self._options.update(user_input)
            selected_zones = self._options.get(CONF_ZONES, [])
            if selected_zones:
                self._selected_zones = [int(z) for z in selected_zones]
                self._current_zone_index = 0
                self._options[CONF_INPUT_TO_ZONE_SENDS] = {}
                self._options[CONF_ZONE_TO_ZONE_SENDS] = {}
                return await self.async_step_zone_crosspoints()
            return self.async_create_entry(data=self._options)

        # Restrict choices to the model's limits (model is always in entry.data).
        limits = MODEL_LIMITS.get(cfg.get(CONF_MODEL, DEFAULT_MODEL), MODEL_LIMITS[DEFAULT_MODEL])

        # Load previously fetched channel names from storage for friendly labels.
        stored = await Store(
            self.hass, 1, f"ahm_channel_names_{self._entry.entry_id}"
        ).async_load() or {}
        self._channel_names = {
            entity_type: {int(k): v for k, v in ch_names.items()}
            for entity_type, ch_names in stored.items()
        }

        n = self._channel_names
        data_schema = vol.Schema({
            vol.Optional(CONF_INPUTS, default=cfg.get(CONF_INPUTS, ["1"])): cv.multi_select(
                {str(i): _channel_label(n, "inputs", i, "Input") for i in range(1, limits["inputs"] + 1)}
            ),
            vol.Optional(CONF_ZONES, default=cfg.get(CONF_ZONES, ["1"])): cv.multi_select(
                {str(i): _channel_label(n, "zones", i, "Zone") for i in range(1, limits["zones"] + 1)}
            ),
            vol.Optional(CONF_CONTROL_GROUPS, default=cfg.get(CONF_CONTROL_GROUPS, [])): cv.multi_select(
                {str(i): _channel_label(n, "control_groups", i, "Control Group") for i in range(1, limits["control_groups"] + 1)}
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )

    async def async_step_zone_crosspoints(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Per-zone crosspoint configuration — pre-populated with current sends."""
        if self._current_zone_index >= len(self._selected_zones):
            return self.async_create_entry(data=self._options)

        current_zone = self._selected_zones[self._current_zone_index]

        if user_input is not None:
            input_sends = user_input.get("input_sends", [])
            zone_sends = user_input.get("zone_sends", [])
            if input_sends:
                self._options[CONF_INPUT_TO_ZONE_SENDS][str(current_zone)] = [
                    str(i) for i in input_sends
                ]
            if zone_sends:
                self._options[CONF_ZONE_TO_ZONE_SENDS][str(current_zone)] = [
                    str(z) for z in zone_sends
                ]
            self._current_zone_index += 1
            return await self.async_step_zone_crosspoints()

        cfg = self._current_config
        selected_inputs = self._options.get(CONF_INPUTS, cfg.get(CONF_INPUTS, []))
        available_zones = [z for z in self._selected_zones if z != current_zone]

        # Pre-populate from current config so existing sends are shown ticked.
        existing_iz = cfg.get(CONF_INPUT_TO_ZONE_SENDS, {}).get(str(current_zone), [])
        existing_zz = cfg.get(CONF_ZONE_TO_ZONE_SENDS, {}).get(str(current_zone), [])

        n = self._channel_names
        schema_dict: dict = {}
        if selected_inputs:
            schema_dict[vol.Optional("input_sends", default=existing_iz)] = cv.multi_select(
                {str(i): _channel_label(n, "inputs", int(i), "Input") for i in selected_inputs}
            )
        if available_zones:
            schema_dict[vol.Optional("zone_sends", default=existing_zz)] = cv.multi_select(
                {str(z): _channel_label(n, "zones", z, "Zone") for z in available_zones}
            )

        if not schema_dict:
            self._current_zone_index += 1
            return await self.async_step_zone_crosspoints()

        progress = f"({self._current_zone_index + 1}/{len(self._selected_zones)})"

        return self.async_show_form(
            step_id="zone_crosspoints",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zone_label": _channel_label(n, "zones", current_zone, "Zone"),
                "zone_number": str(current_zone),
                "progress": progress,
                "input_count": str(len(selected_inputs)),
                "zone_count": str(len(available_zones)),
            },
        )
