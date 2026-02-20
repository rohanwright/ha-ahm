# AHM Integration Crosspoint Implementation Summary

## What Was Implemented

This implementation adds comprehensive crosspoint (send) control capabilities to the Allen & Heath AHM Zone Mixer Home Assistant integration. Crosspoints allow routing audio from any input or zone to any zone with independent level and mute control.

## Key Features Added

### 1. Multi-Step Configuration Flow
- Extended the configuration process to include crosspoint selection
- Zone-centric approach: for each selected zone, users can choose which inputs and other zones should have send controls to that zone
- Progressive configuration that only shows relevant options
- Smart defaults and validation

### 2. Backend Support (ahm_client.py)
Added methods for crosspoint communication:
- `get_send_level(source_num, dest_zone, is_zone_to_zone=False)` - Get send level
- `set_send_level(source_num, dest_zone, level, is_zone_to_zone=False)` - Set send level  
- `get_send_muted(source_num, dest_zone, is_zone_to_zone=False)` - Get send mute status
- `set_send_mute(source_num, dest_zone, muted, is_zone_to_zone=False)` - Set send mute status

These methods handle both input-to-zone and zone-to-zone sends using the AHM protocol commands:
- Input-to-Zone: `GET/SET INPUT <input> SEND <zone> LEVEL/MUTE`
- Zone-to-Zone: `GET/SET ZONE <source_zone> SEND <dest_zone> LEVEL/MUTE`

### 3. Data Coordination (coordinator.py)
- Extended the coordinator to collect crosspoint data during updates
- Added methods to fetch input-to-zone and zone-to-zone send data
- Integrated crosspoint control methods that trigger data refreshes
- Efficient async data collection using gather() for parallel requests

### 4. Crosspoint Entities (crosspoint.py)
Created a new platform file with specialized entities:

**AhmCrosspointMuteSwitch**: 
- Switch entities for muting/unmuting sends
- Names like "Input 1 to Zone 3 Send Mute"
- Proper device association and unique IDs

**AhmCrosspointLevelNumber**:
- Number entities for send level control
- Range: -48dB to +10dB in 0.5dB steps
- Names like "Input 1 to Zone 3 Send Level"
- Box mode for direct value entry

### 5. Platform Integration (__init__.py)
- Added crosspoint platform loading when crosspoints are configured
- Proper setup and teardown of crosspoint entities
- Maintains separation between main entities and crosspoint entities

### 6. Constants and Configuration (const.py)
Added constants for:
- Crosspoint configuration keys
- Entity type identifiers  
- Crosspoint type classifications

## Configuration Data Structure

The configuration stores crosspoint selections as:

```python
{
    "input_to_zone_sends": {
        "3": ["1", "2"],  # Zone 3 receives sends from Inputs 1 and 2
        "4": ["1"]        # Zone 4 receives send from Input 1
    },
    "zone_to_zone_sends": {
        "3": ["1", "2"],  # Zone 3 receives sends from Zones 1 and 2  
        "4": ["1"]        # Zone 4 receives send from Zone 1
    }
}
```

## Entity Naming Convention

Entities are created with descriptive names:
- `switch.input_1_to_zone_3_send_mute`
- `number.input_1_to_zone_3_send_level`
- `switch.zone_2_to_zone_4_send_mute`
- `number.zone_2_to_zone_4_send_level`

Unique IDs include the crosspoint identifier to ensure no conflicts.

## Translation Support

Added translation keys for:
- Crosspoint configuration step descriptions
- Configuration progress indicators
- Help text for crosspoint selection

## Use Cases Enabled

1. **PA Announcements**: Route microphone inputs to specific zones
2. **Background Music Distribution**: Send zone audio to multiple destination zones
3. **Conference Room Routing**: Complex routing between meeting spaces
4. **Overflow Area Management**: Dynamically route audio to overflow spaces
5. **Sound Reinforcement**: Layer multiple sources into zones with precise level control

## Example Automation

```yaml
# Route microphone to meeting rooms for announcements
- alias: "PA Announcement Routing"
  trigger:
    - platform: state
      entity_id: input_boolean.pa_active
      to: 'on'
  action:
    - service: switch.turn_off
      target:
        entity_id:
          - switch.input_1_to_zone_2_send_mute
          - switch.input_1_to_zone_3_send_mute
    - service: number.set_value
      target:
        entity_id:
          - number.input_1_to_zone_2_send_level
          - number.input_1_to_zone_3_send_level
      data:
        value: -10
```

## Technical Implementation Notes

### Async Design
All crosspoint operations are async and use the existing coordinator pattern for consistent state management and UI updates.

### Error Handling
Robust error handling with graceful degradation - if crosspoint data can't be fetched, entities show unavailable state rather than failing entirely.

### Protocol Compliance
All commands follow the AHM TCP/IP Protocol V1.5 specification exactly, ensuring compatibility with AHM firmware.

### Performance
Crosspoint data collection is parallelized and integrated into the main update cycle to minimize network overhead.

## Files Modified/Created

### New Files:
- `custom_components/ahm/crosspoint.py` - Crosspoint entity platform

### Modified Files:
- `custom_components/ahm/config_flow.py` - Extended for crosspoint configuration
- `custom_components/ahm/coordinator.py` - Added crosspoint data handling
- `custom_components/ahm/ahm_client.py` - Added crosspoint protocol methods
- `custom_components/ahm/const.py` - Added crosspoint constants
- `custom_components/ahm/__init__.py` - Added crosspoint platform support
- `custom_components/ahm/strings.json` - Added crosspoint translations
- `custom_components/ahm/translations/en.json` - Added crosspoint translations
- `README.md` - Documented crosspoint features
- `examples/configuration.yaml` - Added crosspoint usage examples

## Testing Recommendations

1. **Configuration Flow**: Test the multi-step crosspoint configuration with various zone selections
2. **Entity Creation**: Verify correct entity creation and naming for different crosspoint combinations
3. **Protocol Commands**: Test send level and mute commands against actual AHM hardware
4. **Data Updates**: Verify crosspoint states update correctly in the UI
5. **Error Handling**: Test behavior when crosspoint commands fail or timeout

## Future Enhancements

1. **Options Flow**: Allow editing crosspoint entities after initial setup
2. **Bulk Operations**: Services for controlling multiple crosspoints at once
3. **Preset Integration**: Include crosspoint states in preset recalls
4. **Visual Routing**: Custom cards showing routing matrix
5. **Templates**: Helper templates for common routing scenarios

This implementation provides complete crosspoint control capabilities while maintaining the integration's existing patterns and user experience.
