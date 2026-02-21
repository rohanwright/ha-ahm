"""Config flow for AHM integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .ahm_client import AhmClient
from .const import (
    DOMAIN,
    DEFAULT_NAME,
    CONF_HOST,
    CONF_NAME,
    CONF_INPUTS,
    CONF_ZONES,
    CONF_CONTROL_GROUPS,
    CONF_INPUT_TO_ZONE_SENDS,
    CONF_ZONE_TO_ZONE_SENDS,
    MAX_INPUTS,
    MAX_ZONES,
    MAX_CONTROL_GROUPS,
)

_LOGGER = logging.getLogger(__name__)


class AhmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AHM."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.data: dict[str, Any] = {}
        # Zone iteration state — kept on self so it never ends up in entry.data.
        self._selected_zones: list[int] = []
        self._current_zone_index: int = 0

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
                    result = await client.test_connection()
                    await client.async_disconnect()
                else:
                    result = False

                if result:
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
                return self.async_create_entry(
                    title=self.data[CONF_NAME],
                    data=self.data,
                )

        # Build entity selection schema
        data_schema = vol.Schema({
            vol.Optional(CONF_INPUTS, default=["1"]): cv.multi_select({
                str(i): f"Input {i}" for i in range(1, MAX_INPUTS + 1)
            }),
            vol.Optional(CONF_ZONES, default=["1"]): cv.multi_select({
                str(i): f"Zone {i}" for i in range(1, MAX_ZONES + 1)
            }),
            vol.Optional(CONF_CONTROL_GROUPS, default=[]): cv.multi_select({
                str(i): f"Control Group {i}" for i in range(1, MAX_CONTROL_GROUPS + 1)
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

        schema_dict: dict = {}
        if selected_inputs:
            schema_dict[vol.Optional("input_sends", default=[])] = cv.multi_select(
                {str(i): f"Input {i}" for i in selected_inputs}
            )
        if available_zones:
            schema_dict[vol.Optional("zone_sends", default=[])] = cv.multi_select(
                {str(z): f"Zone {z}" for z in available_zones}
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

        data_schema = vol.Schema({
            vol.Optional(CONF_INPUTS, default=cfg.get(CONF_INPUTS, ["1"])): cv.multi_select(
                {str(i): f"Input {i}" for i in range(1, MAX_INPUTS + 1)}
            ),
            vol.Optional(CONF_ZONES, default=cfg.get(CONF_ZONES, ["1"])): cv.multi_select(
                {str(i): f"Zone {i}" for i in range(1, MAX_ZONES + 1)}
            ),
            vol.Optional(CONF_CONTROL_GROUPS, default=cfg.get(CONF_CONTROL_GROUPS, [])): cv.multi_select(
                {str(i): f"Control Group {i}" for i in range(1, MAX_CONTROL_GROUPS + 1)}
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

        schema_dict: dict = {}
        if selected_inputs:
            schema_dict[vol.Optional("input_sends", default=existing_iz)] = cv.multi_select(
                {str(i): f"Input {i}" for i in selected_inputs}
            )
        if available_zones:
            schema_dict[vol.Optional("zone_sends", default=existing_zz)] = cv.multi_select(
                {str(z): f"Zone {z}" for z in available_zones}
            )

        if not schema_dict:
            self._current_zone_index += 1
            return await self.async_step_zone_crosspoints()

        progress = f"({self._current_zone_index + 1}/{len(self._selected_zones)})"

        return self.async_show_form(
            step_id="zone_crosspoints",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "zone_number": str(current_zone),
                "progress": progress,
                "input_count": str(len(selected_inputs)),
                "zone_count": str(len(available_zones)),
            },
        )
