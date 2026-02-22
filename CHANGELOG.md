# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-02-22

### Changed
- Adopted Home Assistant modern entity naming (`_attr_has_entity_name = True`) across number, switch, media_player, and button entities
- Standardized fallback entity names to channel/function only (device name no longer embedded in fallback name strings)
- Preserved stable, device-prefixed suggested object IDs for new entities so IDs follow the `Device_Type_Number_Function` pattern (slugified by Home Assistant to lowercase)
- Standardized crosspoint friendly naming to **Destination → Source → Function** for both level and mute entities

### Notes
- Existing entity IDs already stored in Home Assistant's entity registry are unchanged; only newly created entities use the updated suggested object ID pattern

## [1.0.0] - 2026-02-21

### Added
- **Channel Name Sync**: New "Fetch Channel Names" button entity requests display names from the AHM for all configured channels. Entities are renamed immediately (e.g. `Spotify Level`, `Foyer Mute`, `Foyer Spotify Level`)
- **Name persistence**: Fetched channel names are saved to HA storage and automatically restored on integration reload or Home Assistant restart — no need to re-fetch after reboot
- **Dynamic entity names**: All channel entities (inputs, zones, control groups, crosspoints) now reflect AHM display names. Crosspoint entities follow the pattern `<Zone> <Input> Level/Mute` (destination first)
- **Channel names in config/options flows**: Connection setup now fetches names from the AHM so selection screens show `"Input 1 - Spotify"` rather than plain `"Input 1"`. Options flow loads persisted names from storage on open
- **Multi-device entity naming**: Entity names and unique IDs are prefixed with the device's configured friendly name, ensuring clarity when multiple AHM units are present (e.g. `AHM 1 Input 1 Level` vs `AHM 2 Input 1 Level`)
- **Model selection**: Setup flow now asks for device model (AHM-16, AHM-32, or AHM-64). Channel count limits are enforced per model during entity selection

### Changed
- **Real-time push listener**: Replaced 5-second polling with a persistent TCP push listener that reacts to state changes (mute, level, crosspoint) within 0.5 seconds. A 60-second safety poll continues to run in the background
- **`play_audio` track_id is now 1-indexed**: `track_id` in the `ahm.play_audio` service now matches the AHM UI (1–128). The integration converts to 0-indexed internally before transmission. **Breaking change** — update any automations using `track_id: 0` to `track_id: 1`, etc.
- Crosspoints now have both a level (Number) and mute (Switch) entity per send

### Fixed
- NUL byte padding in AHM name responses is now stripped correctly; unnamed channels no longer appear with NUL characters in their entity names

## [0.0.1] - 2025-06-23

### Added
- Initial release of AHM Zone Mixer integration
- Support for Allen & Heath AHM Zone Mixer devices with Firmware V1.5
- Number entities for level control (raw MIDI 0–127) for inputs, zones, and control groups
- Switch entities for dedicated mute controls
- Crosspoint (send) controls — level and mute per input-to-zone and zone-to-zone send
- Configuration flow with entity and crosspoint selection
- `ahm.recall_preset` service (presets 1–500)
- `ahm.play_audio` service with channel selection (Mono 1, Mono 2, Stereo)
- HACS compatibility
- Debug logging (TX/RX MIDI hex output)

### Requirements
- Home Assistant 2025.6.0 or later
- Allen & Heath AHM Zone Mixer with Firmware V1.5
- TCP port 51325 accessible from the HA host
