# Allen & Heath AHM Zone Mixer Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/rohanwright/ha-ahm.svg)](https://github.com/rohanwright/ha-ahm/releases/)
[![License](https://img.shields.io/github/license/user/ha-ahm.svg)](LICENSE)

A Home Assistant custom integration for controlling Allen & Heath AHM Zone Mixer devices over TCP/IP using the AHM TCP/IP Protocol V1.5.

## Features

- **Media Player Entities**: Volume and mute control for inputs, zones, control groups, and rooms
- **Number Entities**: Fine-grained dB level control (-48dB to +10dB)
- **Switch Entities**: Dedicated mute/unmute controls with appropriate icons
- **Crosspoint (Send) Controls**: Full control over input-to-zone and zone-to-zone sends
- **Services**: Preset recall and audio playback triggers
- **Configurable Entity Creation**: Choose exactly which inputs/outputs to control and which crosspoints to create
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

1. **Device Connection**: Enter your AHM device's IP address and firmware version
2. **Entity Selection**: Choose which inputs, zones, control groups, and rooms you want to control
3. **Crosspoint Configuration**: For each selected zone, a dedicated screen lets you choose which inputs and other zones should have send (crosspoint) controls routed to it
   - Leaving a zone's selections empty is valid — no crosspoint entities are created for that zone
   - Both a level number entity and a mute switch entity are created for every selected send
   - Crosspoint routing can be changed at any time via **Settings → Devices & Services → AHM Zone Mixer → Configure**

### Supported Entities

- **Inputs**: Up to 64 input channels
- **Zones**: Up to 64 zone outputs  
- **Control Groups**: Up to 32 control groups
- **Rooms**: Up to 16 rooms
- **Crosspoints**: Input-to-zone and zone-to-zone sends (routing controls)

### Entity Types Created

For each selected input, zone, control group, and room, the integration creates:

- **Media Player**: Primary volume and mute control (appears in media player cards)
- **Number**: Precise dB level adjustment (-48 to +10 dB in 0.5dB steps)
- **Switch**: Dedicated mute toggle with volume icons

For each configured crosspoint (send), the integration creates:

- **Number**: Send level control (-48 to +10 dB in 0.5dB steps) 
- **Switch**: Send mute toggle

### Crosspoint Entity Examples

When you configure crosspoint controls, entities are created with descriptive names:

- `number.input_1_to_zone_3_send_level` - Controls the send level from Input 1 to Zone 3
- `switch.input_1_to_zone_3_send_mute` - Mutes/unmutes the send from Input 1 to Zone 3
- `number.zone_2_to_zone_4_send_level` - Controls the send level from Zone 2 to Zone 4
- `switch.zone_2_to_zone_4_send_mute` - Mutes/unmutes the send from Zone 2 to Zone 4

## Services

### `ahm.recall_preset`

Recall a preset on the AHM device.

**Parameters:**
- `preset_number` (required): Preset number (1-500)
- `entry_id` (optional): Config entry ID of the target device. Only needed when more than one AHM device is configured.

**Example:**
```yaml
service: ahm.recall_preset
data:
  preset_number: 1
```

**Multi-device example:**
```yaml
service: ahm.recall_preset
data:
  preset_number: 1
  entry_id: "abc123def456..."  # Settings → Devices → AHM → URL
```

### `ahm.play_audio`

Trigger audio playback on the AHM device.

**Parameters:**
- `track_id` (required): Audio track ID (0-127)
- `channel` (optional): Playback channel (0=Mono 1, 1=Mono 2, 2=Stereo, default=0)
- `entry_id` (optional): Config entry ID of the target device. Only needed when more than one AHM device is configured.

**Example:**
```yaml
service: ahm.play_audio
data:
  track_id: 5
  channel: 2  # Stereo
```

## Usage Examples

### Volume Control
```yaml
# Set input 1 to -10dB using number entity
service: number.set_value
target:
  entity_id: number.ahm_input_1_level
data:
  value: -10

# Set zone 3 volume to 50% using media player
service: media_player.volume_set
target:
  entity_id: media_player.ahm_zone_3
data:
  volume_level: 0.5
```

### Mute Control
```yaml
# Mute input 2 using switch
service: switch.turn_on
target:
  entity_id: switch.ahm_input_2_mute

# Mute zone 1 using media player
service: media_player.volume_mute
target:
  entity_id: media_player.ahm_zone_1
data:
  is_volume_muted: true
```

### Automation Example
```yaml
automation:
  - alias: "Mute all inputs when doorbell rings"
    trigger:
      - platform: state
        entity_id: binary_sensor.doorbell
        to: 'on'
    action:
      - service: switch.turn_on
        target:
          entity_id: 
            - switch.ahm_input_1_mute
            - switch.ahm_input_2_mute
            - switch.ahm_input_3_mute
      - service: ahm.play_audio
        data:
          track_id: 1  # Doorbell chime
          channel: 2   # Stereo
      - delay: '00:00:05'
      - service: switch.turn_off
        target:
          entity_id: 
            - switch.ahm_input_1_mute
            - switch.ahm_input_2_mute  
            - switch.ahm_input_3_mute
```

## Device Requirements

- Allen & Heath AHM Zone Mixer with Firmware V1.5
- Network connectivity to the AHM device
- TCP port 51325 accessible (unencrypted) or 51327 (TLS/SSL encrypted)

## Troubleshooting

### Connection Issues
- Verify the AHM device IP address and network connectivity
- Ensure the correct firmware version is specified (found on device front panel)
- Check that TCP port 51325 is not blocked by firewalls

### Entity Updates
- The integration polls the device every 5 seconds for status updates
- Manual refresh can be triggered through the integration page
- Some changes may take a moment to reflect in the UI

### Performance
- Select only the channels you need to reduce polling time
- The integration uses a single persistent TCP connection for all communication
- If the connection drops (e.g. device reboot), it reconnects automatically on the next poll cycle

## Protocol Information

This integration implements the AHM TCP/IP Protocol V1.5 using MIDI format messages over TCP/IP. For detailed protocol information, refer to the AHM documentation.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- [Issues](https://github.com/rohanwright/ha-ahm/issues)
- [Discussions](https://github.com/rohanwright/ha-ahm/discussions)
- [Allen & Heath Support](https://www.allen-heath.com/support/)

## Acknowledgments

- Allen & Heath for the AHM protocol documentation
- Home Assistant community for integration development guidelines
- HACS for making custom component distribution easy
