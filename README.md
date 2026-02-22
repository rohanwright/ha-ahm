# Allen & Heath AHM Zone Mixer Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/rohanwright/ha-ahm.svg)](https://github.com/rohanwright/ha-ahm/releases/)
[![License](https://img.shields.io/github/license/user/ha-ahm.svg)](LICENSE)

A Home Assistant custom integration for controlling Allen & Heath AHM Zone Mixer devices over TCP/IP using the AHM TCP/IP Protocol V1.5.

## Features

- **Real-time push updates**: State changes (knob turns, mute presses) are reflected in HA within 0.5 seconds
- **Number Entities**: Raw MIDI level control (0–127) for inputs, zones, control groups, and crosspoint sends
- **Switch Entities**: Dedicated mute/unmute controls with volume icons
- **Crosspoint (Send) Controls**: Level and mute for input-to-zone and zone-to-zone sends
- **Diagnostic Sensors**: Last recalled preset and current connection status for troubleshooting
- **Channel Name Sync**: Fetch display names programmed on the AHM device — entities rename automatically and names persist across restarts
- **Multi-device Support**: Each device is identified by its configured name, so entities are unambiguous when multiple AHM units are present
- **Model Selection**: AHM-16, AHM-32, and AHM-64 — entity selection is constrained to the actual channel count
- **Services**: Preset recall (1–500) and audio playback (tracks 1–128)
- **Configurable Entity Creation**: Choose exactly which inputs, zones, control groups, and crosspoints to expose
- **HACS Compatible**: Easy installation and updates through HACS

## Installation

### Via HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Install the "AHM Zone Mixer" integration
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration
5. Search for "AHM Zone Mixer" and follow the configuration steps

### Manual Installation

1. Download the latest release
2. Extract the contents to `custom_components/ahm/` in your Home Assistant configuration directory
3. Restart Home Assistant
4. Add the integration through the UI

## Configuration

### Initial Setup

1. **Connection**: Enter the AHM device's IP address, a friendly name for the device (e.g. `AHM 1`), and choose the model (AHM-16, AHM-32, or AHM-64).

   > During this step the integration connects to the device and fetches all channel display names — these appear immediately in the next steps so you see `"Input 1 - Spotify"` instead of just `"Input 1"`.

2. **Entity Selection**: Choose which inputs, zones, and control groups to create entities for. The maximum values shown match your chosen model.

3. **Crosspoint Configuration**: For each selected zone, a dedicated screen lets you choose which inputs and zones should have send (crosspoint) controls routed to it. Both a level number and a mute switch are created for every selected send. Leaving a zone's selections empty is valid.

Routing can be changed at any time under **Settings → Devices & Services → AHM Zone Mixer → Configure**.

### Supported Channels

| Model | Inputs | Zones | Control Groups |
|---|---|---|---|
| AHM-16 | up to 16 | up to 16 | up to 32 |
| AHM-32 | up to 32 | up to 32 | up to 32 |
| AHM-64 | up to 64 | up to 64 | up to 32 |

### Entity Types Created

For each selected input, zone, or control group:

- **Number**: Level control (raw MIDI 0–127)
- **Switch**: Mute toggle

For each configured crosspoint (send):

- **Number**: Send level control (raw MIDI 0–127)
- **Switch**: Send mute toggle

Always created diagnostic entities:

- **Sensor**: Last Recalled Preset (shows `Preset N` from the last preset recall message received from the AHM)
- **Sensor**: Connection Status (`Connected` / `Disconnected`)

### Reconfiguring After Setup

Open **Settings → Devices & Services**, find your AHM device, and click **Configure**. The options flow pre-populates all current selections. If channel names have previously been fetched they will already appear in the selection lists.

### Channel Names

Press the **Fetch Channel Names** button (found under the device's configuration category) to request display names from the AHM for all configured channels. Entities are renamed immediately:

| Without names | With names fetched |
|---|---|
| `AHM 1 Input 1 Level` | `Spotify Level` |
| `AHM 1 Zone 1 Mute` | `Foyer Mute` |
| `AHM 1 Input 1 to Zone 1 Send Level` | `Foyer Spotify Level` |

Names survive integration reloads and Home Assistant restarts — you only need to press the button again when names are changed on the device.

### Entity Naming and IDs

This integration uses Home Assistant's modern entity naming model:

- Entities are created with `_attr_has_entity_name = True`
- Entity display names come from the AHM when available (for example `Spotify Level`)
- Fallback names are simple channel/function names (for example `Input 1 Level`, `Zone 3 Mute`)
- Crosspoint friendly names always use **Destination → Source → Function** ordering (for example `Foyer Spotify Level`)

Entity IDs are intentionally kept stable using suggested object IDs. They use the device name prefix plus type/number/function pattern, then Home Assistant slugifies to lowercase:

- Source pattern: `AHM_Input_1_Level`
- Actual entity ID: `number.ahm_input_1_level`

> Note: Existing entity IDs already stored in Home Assistant's entity registry are not automatically renamed by integration updates.

### Crosspoint Entity Examples

When you configure crosspoint controls, entities are created with descriptive names. Examples with a device named `AHM 1` and Input 1 = "Spotify", Zone 3 = "Foyer":

- `number.foyer_spotify_level` — send level from Input 1 (Spotify) to Zone 3 (Foyer)
- `switch.foyer_spotify_mute` — mutes/unmutes that send
- `number.ahm_1_input_1_to_zone_3_send_level` — same entity before names are fetched
- `switch.ahm_1_input_1_to_zone_3_send_mute` — same entity before names are fetched

### Diagnostic Sensor Examples

- `sensor.ahm_1_last_recalled_preset` — `Preset 1`, `Preset 42`, etc. (latest received from the device)
- `sensor.ahm_1_connection_status` — `Connected` or `Disconnected`

## Services

### `ahm.recall_preset`

Recall a preset on the AHM device.

**Parameters:**

| Field | Required | Description |
|---|---|---|
| `preset_number` | Yes | Preset number (1–500) |
| `entry_id` | No | Config entry ID of the target device. Only needed when more than one AHM device is configured. |

**Example:**
```yaml
service: ahm.recall_preset
data:
  preset_number: 42
```

**Multi-device example:**
```yaml
service: ahm.recall_preset
data:
  preset_number: 42
  entry_id: "abc123def456"   # found in Settings → Devices → AHM → URL
```

### `ahm.play_audio`

Trigger audio file playback on the AHM device.

**Parameters:**

| Field | Required | Default | Description |
|---|---|---|---|
| `track_id` | Yes | — | Audio track number (1–128, matching the AHM UI) |
| `channel` | No | `0` | Playback channel: `0` = Mono 1, `1` = Mono 2, `2` = Stereo |
| `entry_id` | No | — | Config entry ID. Only needed with multiple AHM devices. |

**Example:**
```yaml
service: ahm.play_audio
data:
  track_id: 1     # Track 1 as shown in the AHM UI
  channel: 2      # Stereo
```

## Usage Examples

### Level Control

```yaml
# Set input level (raw MIDI 0-127; MIDI 84 ≈ 0 dB)
service: number.set_value
target:
  entity_id: number.spotify_level   # or number.ahm_1_input_1_level before names are fetched
data:
  value: 84
```

### Mute Control

```yaml
# Mute a zone
service: switch.turn_on
target:
  entity_id: switch.foyer_mute

# Unmute a crosspoint send
service: switch.turn_off
target:
  entity_id: switch.foyer_spotify_mute
```

### Automation Example

```yaml
automation:
  - alias: "Doorbell — pause music and play chime"
    trigger:
      - platform: state
        entity_id: binary_sensor.doorbell
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.foyer_spotify_mute   # mute Spotify send to Foyer
      - service: ahm.play_audio
        data:
          track_id: 1    # doorbell chime — track number as shown in AHM UI
          channel: 0     # Mono 1
      - delay: "00:00:05"
      - service: switch.turn_off
        target:
          entity_id: switch.foyer_spotify_mute   # restore
```

## Real-time Updates

The integration uses a persistent TCP connection to the AHM and runs a background push listener that wakes every 0.5 seconds to process any incoming MIDI messages (mute presses, knob turns, crosspoint changes). HA state updates immediately on detection — no waiting for a poll cycle.

A 60-second safety poll runs in the background to catch any missed packets and keep state authoritative.

If the TCP connection drops (e.g. AHM reboot), it is re-established automatically on the next poll cycle.

## Device Requirements

- Allen & Heath AHM Zone Mixer with Firmware V1.5
- Network connectivity to the AHM device
- TCP port 51325 accessible (unencrypted). Port 51327 (TLS/SSL) is not currently supported.

## Troubleshooting

### Connection Issues
- Verify the AHM device IP address and that it is reachable from the HA host
- Check that TCP port 51325 is not blocked by firewalls
- Check the AHM's network settings page to confirm TCP/IP control is enabled

### Entities Show "Unknown" After Startup
- The integration fires GET requests on startup and waits 1 second for responses. If the AHM is slow to respond on a fresh connection, the next 60-second poll will fill in any missing values.

### Channel Names Not Appearing
- Press **Fetch Channel Names** from the device page
- If names still show as numbered defaults, check that the channels have names programmed on the AHM (unnamed channels transmit empty or NUL-padded responses, which are discarded)

### Debug Logging

```yaml
logger:
  logs:
    custom_components.ahm: debug
```

Restart Home Assistant after adding this. Debug output shows `TX:` / `RX:` lines with full MIDI hex for every packet — useful for diagnosing protocol issues.

## Protocol

This integration implements the Allen & Heath AHM TCP/IP Protocol V1.5 using MIDI format messages. All communication uses a single persistent TCP connection on port 51325.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Support

- [Issues](https://github.com/rohanwright/ha-ahm/issues)
- [Discussions](https://github.com/rohanwright/ha-ahm/discussions)
- [Allen & Heath Support](https://www.allen-heath.com/support/)

## Acknowledgments

- Allen & Heath for the AHM TCP/IP protocol documentation
- Home Assistant community for integration development guidelines
- HACS for making custom component distribution easy
