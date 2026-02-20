"""Allen & Heath AHM Zone Mixer integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import AhmCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AHM from a config entry."""
    coordinator = AhmCoordinator(hass, entry)
    
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to connect to AHM device: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start the real-time push listener now that data is populated.
    coordinator.start_push_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await _async_register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: AhmCoordinator = hass.data[DOMAIN][entry.entry_id]

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

        # Remove services when the last entry is unloaded.
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "recall_preset")
            hass.services.async_remove(DOMAIN, "play_audio")

    return unload_ok


async def _async_register_services(hass: HomeAssistant, coordinator: AhmCoordinator) -> None:
    """Register AHM services — only once, regardless of how many entries are loaded.

    Services look up the target coordinator at call time via an optional
    ``entry_id`` field. When omitted (single-device setups) the first available
    coordinator is used.
    """
    import voluptuous as vol

    # Guard: don't overwrite registrations already made by a previous entry.
    if hass.services.has_service(DOMAIN, "recall_preset"):
        return

    def _get_coordinator(call) -> AhmCoordinator | None:
        """Resolve the target coordinator from an optional entry_id."""
        entry_id = call.data.get("entry_id")
        if entry_id:
            return hass.data[DOMAIN].get(entry_id)
        coordinators = list(hass.data[DOMAIN].values())
        return coordinators[0] if coordinators else None

    async def recall_preset(call) -> None:
        """Recall a preset on the target AHM device."""
        target = _get_coordinator(call)
        if target is None:
            _LOGGER.error("ahm.recall_preset: no AHM coordinator found for call %s", call.data)
            return
        await target.async_recall_preset(call.data["preset_number"])

    async def play_audio(call) -> None:
        """Trigger audio playback on the target AHM device."""
        target = _get_coordinator(call)
        if target is None:
            _LOGGER.error("ahm.play_audio: no AHM coordinator found for call %s", call.data)
            return
        await target.async_play_audio(call.data["track_id"], call.data.get("channel", 0))

    hass.services.async_register(
        DOMAIN,
        "recall_preset",
        recall_preset,
        schema=vol.Schema({
            vol.Required("preset_number"): vol.All(int, vol.Range(min=1, max=500)),
            vol.Optional("entry_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        "play_audio",
        play_audio,
        schema=vol.Schema({
            vol.Required("track_id"): vol.All(int, vol.Range(min=0, max=127)),
            vol.Optional("channel", default=0): vol.All(vol.Coerce(int), vol.In([0, 1, 2])),
            vol.Optional("entry_id"): str,
        }),
    )
