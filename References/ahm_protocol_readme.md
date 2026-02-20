# AHM TCP/IP Protocol V1.5

A comprehensive guide for controlling AHM processors over TCP/IP using MIDI format messages.

## Table of Contents

- [Overview](#overview)
- [Getting Started](#getting-started)
- [Connection Setup](#connection-setup)
- [Protocol Basics](#protocol-basics)
- [Control Functions](#control-functions)
- [Reference Tables](#reference-tables)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

The AHM TCP/IP Protocol V1.5 enables external control of AHM processors using Firmware V1.5. This protocol uses MIDI format messages transmitted over TCP/IP to control various audio processing functions including:

- Input levels, mutes, preamps, and trim
- Zone levels and mutes
- Control group levels and mutes
- Channel names and colors
- Preset recalls
- Send levels and mutes
- Audio file playback
- Source selection
- Room controls

## Getting Started

### Prerequisites

- AHM processor with Firmware V1.5
- Network connection to the AHM processor
- MIDI message handling capability in your application

### Quick Start

1. Connect to the AHM processor on TCP port 51325 (unencrypted) or 51327 (encrypted)
2. If using encryption, authenticate with your user profile and password
3. Send MIDI format messages using the protocol specifications below

## Connection Setup

### Network Configuration

| Connection Type | Port  | Description |
|-----------------|-------|-------------|
| Unencrypted     | 51325 | Standard TCP connection |
| TLS/SSL         | 51327 | Encrypted connection with authentication |

### Authentication (TLS/SSL only)

For encrypted connections, send this message immediately after connecting:

```
UserProfile, UserPassword
```

- **UserProfile**: 00 to 1F (see [User Profile Table](#user-profile-table))
- **Success**: Returns "AuthOK"
- **Failure**: Connection is dropped

## Protocol Basics

### Channel Selection

Channels are selected using MIDI channel number (N) and note number (CH):

| Device Type | MIDI Channel (N) | Note Range (CH) | Count |
|-------------|------------------|-----------------|-------|
| Inputs      | 0                | 00 to 3F        | 1-64  |
| Zones       | 1                | 00 to 3F        | 1-64  |
| Control Groups | 2             | 00 to 1F        | 1-32  |
| Rooms       | 3                | 00 to 0F        | 1-16  |

### SysEx Header Format

All SysEx messages use this standard header:

```
F0, 00, 00, 1A, 50, 12, MV, mV
```

- **MV**: 01 (Major version)
- **mV**: 00 (Minor version)

## Control Functions

### Channel Mute

#### Mute Channel On
```
9N, CH, 7F, 9N, CH, 00
```
*NOTE ON with velocity > 40 followed by NOTE OFF*

#### Mute Channel Off
```
9N, CH, 3F, 9N, CH, 00
```
*NOTE ON with velocity < 40 followed by NOTE OFF*

#### Get Mute Status
```
SysEx Header, 0N, 01, 09, CH, F7
```

### Channel Level

Uses NRPN with parameter ID 17. Level range: -Inf to +10dB (00 to 7F)

#### Set Level
```
BN, 63, CH, BN, 62, 17, BN, 06, LV
```

#### Get Level
```
SysEx Header, 0N, 01, 0B, 17, CH, F7
```

#### Level Increment/Decrement
```
BN, 63, CH, BN, 62, 20
BN, 06, 7F  # Increment
BN, 06, 3F  # Decrement
```

### Input Controls

#### Input Trim (Parameter ID 18)
Range: -24 to +24dB (00 to 7F)
```
BN, 63, CH, BN, 62, 18, BN, 06, LV
```

#### Input Preamp Gain (Parameter ID 19)
Range: 5dB to +60dB (00 to 7F)
```
BN, 63, CH, BN, 62, 19, BN, 06, GN
```

#### Input Preamp Pad (Parameter ID 1A)
- 00-3F = Pad off
- 40-7F = Pad on
```
BN, 63, CH, BN, 62, 1A, BN, 06, VL
```

#### Input Phantom Power (Parameter ID 1B)
- 00-3F = Phantom off
- 40-7F = Phantom on
```
BN, 63, CH, BN, 62, 1B, BN, 06, VL
```

### Send Controls

#### Set Send Level
```
SysEx Header, 0N, 02, CH, SndN, SndCH, LV, F7
```

#### Send Mute Control
```
SysEx Header, 0N, 03, CH, SndN, SndCH, 7F, F7  # Mute On
SysEx Header, 0N, 03, CH, SndN, SndCH, 3F, F7  # Mute Off
```

#### Get Send Status
```
SysEx Header, 0N, 01, 0F, 02, CH, SndN, SndCH, F7  # Get Level
SysEx Header, 0N, 01, 0F, 03, CH, SndN, SndCH, F7  # Get Mute
```

### Preset Recall

500 presets across 4 banks using Bank and Program Change messages:

#### Presets 1-128
```
B0, 00, 00, C0, SS  # SS = 00-7F
```

#### Presets 129-256
```
B0, 00, 01, C0, SS  # SS = 00-7F
```

#### Presets 257-384
```
B0, 00, 02, C0, SS  # SS = 00-7F
```

#### Presets 385-500
```
B0, 00, 03, C0, SS  # SS = 00-73
```

### Audio Playback

```
SysEx Header, 00, 06, PlaybackChannel, TrackID, F7
```

- **PlaybackChannel**: 00=Mono 1, 01=Mono 2, 02=Stereo
- **TrackID**: 00 to 7F

### Source Selector

#### Set Source
```
SysEx Header, 00, 08, CH, SourceNumber, F7
```
*SourceNumber: 00 to 13*

#### Get Source Info
```
SysEx Header, 0N, 01, 0F, 08, CH, F7
```

### Room Controls

#### Room Source Selector
```
SysEx Header, 00, 0D, CH, SourceNumber, F7
```

#### Room Combiners
```
SysEx Header, 00, 0E, RoomNumber1, RoomNumber2, VL, F7
```
- 00-3F = Rooms Combined
- 40-7F = Rooms Divided

### Channel Information

#### Get Channel Name
```
SysEx Header, 0N, 09, CH, F7
```

#### Get Channel Color
```
SysEx Header, 0N, 0B, CH, F7
```

## Reference Tables

### Input Channel Mapping Table (Channels 1-32)
| Input # | CH Hex | Input # | CH Hex | Input # | CH Hex | Input # | CH Hex |
|---------|--------|---------|--------|---------|--------|---------|--------|
| 1       | 00     | 9       | 08     | 17      | 10     | 25      | 18     |
| 2       | 01     | 10      | 09     | 18      | 11     | 26      | 19     |
| 3       | 02     | 11      | 0A     | 19      | 12     | 27      | 1A     |
| 4       | 03     | 12      | 0B     | 20      | 13     | 28      | 1B     |
| 5       | 04     | 13      | 0C     | 21      | 14     | 29      | 1C     |
| 6       | 05     | 14      | 0D     | 22      | 15     | 30      | 1D     |
| 7       | 06     | 15      | 0E     | 23      | 16     | 31      | 1E     |
| 8       | 07     | 16      | 0F     | 24      | 17     | 32      | 1F     |

### Input Channel Mapping Table (Channels 33-64)
| Input # | CH Hex | Input # | CH Hex | Input # | CH Hex | Input # | CH Hex |
|---------|--------|---------|--------|---------|--------|---------|--------|
| 33      | 20     | 41      | 28     | 49      | 30     | 57      | 38     |
| 34      | 21     | 42      | 29     | 50      | 31     | 58      | 39     |
| 35      | 22     | 43      | 2A     | 51      | 32     | 59      | 3A     |
| 36      | 23     | 44      | 2B     | 52      | 33     | 60      | 3B     |
| 37      | 24     | 45      | 2C     | 53      | 34     | 61      | 3C     |
| 38      | 25     | 46      | 2D     | 54      | 35     | 62      | 3D     |
| 39      | 26     | 47      | 2E     | 55      | 36     | 63      | 3E     |
| 40      | 27     | 48      | 2F     | 56      | 37     | 64      | 3F     |

### Control Group Mapping Table
| Control Group # | CH Hex | Control Group # | CH Hex | Control Group # | CH Hex | Control Group # | CH Hex |
|-----------------|--------|-----------------|--------|-----------------|--------|-----------------|--------|
| 1               | 00     | 9               | 08     | 17              | 10     | 25              | 18     |
| 2               | 01     | 10              | 09     | 18              | 11     | 26              | 19     |
| 3               | 02     | 11              | 0A     | 19              | 12     | 27              | 1A     |
| 4               | 03     | 12              | 0B     | 20              | 13     | 28              | 1B     |
| 5               | 04     | 13              | 0C     | 21              | 14     | 29              | 1C     |
| 6               | 05     | 14              | 0D     | 22              | 15     | 30              | 1D     |
| 7               | 06     | 15              | 0E     | 23              | 16     | 31              | 1E     |
| 8               | 07     | 16              | 0F     | 24              | 17     | 32              | 1F     |

### Zone Channel Mapping Table (Zones 1-32)
| Zone # | CH Hex | Zone # | CH Hex | Zone # | CH Hex | Zone # | CH Hex |
|--------|--------|--------|--------|--------|--------|--------|--------|
| 1      | 00     | 9      | 08     | 17     | 10     | 25     | 18     |
| 2      | 01     | 10     | 09     | 18     | 11     | 26     | 19     |
| 3      | 02     | 11     | 0A     | 19     | 12     | 27     | 1A     |
| 4      | 03     | 12     | 0B     | 20     | 13     | 28     | 1B     |
| 5      | 04     | 13     | 0C     | 21     | 14     | 29     | 1C     |
| 6      | 05     | 14     | 0D     | 22     | 15     | 30     | 1D     |
| 7      | 06     | 15     | 0E     | 23     | 16     | 31     | 1E     |
| 8      | 07     | 16     | 0F     | 24     | 17     | 32     | 1F     |

### Zone Channel Mapping Table (Zones 33-64)
| Zone # | CH Hex | Zone # | CH Hex | Zone # | CH Hex | Zone # | CH Hex |
|--------|--------|--------|--------|--------|--------|--------|--------|
| 33     | 20     | 41     | 28     | 49     | 30     | 57     | 38     |
| 34     | 21     | 42     | 29     | 50     | 31     | 58     | 39     |
| 35     | 22     | 43     | 2A     | 51     | 32     | 59     | 3A     |
| 36     | 23     | 44     | 2B     | 52     | 33     | 60     | 3B     |
| 37     | 24     | 45     | 2C     | 53     | 34     | 61     | 3C     |
| 38     | 25     | 46     | 2D     | 54     | 35     | 62     | 3D     |
| 39     | 26     | 47     | 2E     | 55     | 36     | 63     | 3E     |
| 40     | 27     | 48     | 2F     | 56     | 37     | 64     | 3F     |

### User Profile Table
| User Profile # | Hex | User Profile # | Hex | User Profile # | Hex | User Profile # | Hex |
|----------------|-----|----------------|-----|----------------|-----|----------------|-----|
| 1              | 00  | 9              | 08  | 17             | 10  | 25             | 18  |
| 2              | 01  | 10             | 09  | 18             | 11  | 26             | 19  |
| 3              | 02  | 11             | 0A  | 19             | 12  | 27             | 1A  |
| 4              | 03  | 12             | 0B  | 20             | 13  | 28             | 1B  |
| 5              | 04  | 13             | 0C  | 21             | 14  | 29             | 1C  |
| 6              | 05  | 14             | 0D  | 22             | 15  | 30             | 1D  |
| 7              | 06  | 15             | 0E  | 23             | 16  | 31             | 1E  |
| 8              | 07  | 16             | 0F  | 24             | 17  | 32             | 1F  |

### Preset Bank and Hex Value Reference
| Preset Range | Bank | Hex Range | Calculation |
|--------------|------|-----------|-------------|
| 1-128        | 00   | 00-7F     | Hex = Preset - 1 |
| 129-256      | 01   | 00-7F     | Hex = Preset - 129 |
| 257-384      | 02   | 00-7F     | Hex = Preset - 257 |
| 385-500      | 03   | 00-73     | Hex = Preset - 385 |

### Preset Conversion Examples
| Preset # | Bank | Hex | MIDI Command |
|----------|------|-----|--------------|
| 1        | 00   | 00  | B0, 00, 00, C0, 00 |
| 64       | 00   | 3F  | B0, 00, 00, C0, 3F |
| 128      | 00   | 7F  | B0, 00, 00, C0, 7F |
| 129      | 01   | 00  | B0, 00, 01, C0, 00 |
| 150      | 01   | 15  | B0, 00, 01, C0, 15 |
| 256      | 01   | 7F  | B0, 00, 01, C0, 7F |
| 257      | 02   | 00  | B0, 00, 02, C0, 00 |
| 300      | 02   | 2B  | B0, 00, 02, C0, 2B |
| 384      | 02   | 7F  | B0, 00, 02, C0, 7F |
| 385      | 03   | 00  | B0, 00, 03, C0, 00 |
| 450      | 03   | 41  | B0, 00, 03, C0, 41 |
| 500      | 03   | 73  | B0, 00, 03, C0, 73 |

### Source Name Character Table
| Source # | Name | Char Hex |
|----------|------|----------|
| A        | a    | 61       |
| B        | b    | 62       |
| C        | c    | 63       |
| D        | d    | 64       |
| E        | e    | 65       |
| F        | f    | 66       |
| G        | g    | 67       |
| H        | h    | 68       |
| I        | i    | 69       |
| J        | j    | 6A       |
| K        | k    | 6B       |
| L        | l    | 6C       |
| M        | m    | 6D       |
| N        | n    | 6E       |
| O        | o    | 6F       |
| P        | p    | 70       |
| Q        | q    | 71       |
| R        | r    | 72       |
| S        | s    | 73       |
| T        | t    | 74       |
| U        | u    | 75       |
| V        | v    | 76       |
| W        | w    | 77       |
| X        | x    | 78       |
| Y        | y    | 79       |
| Z        | z    | 7A       |

### Color Code Table
| Color   | Hex |
|---------|-----|
| Off     | 00  |
| Red     | 01  |
| Green   | 02  |
| Yellow  | 03  |
| Blue    | 04  |
| Magenta | 05  |
| Cyan    | 06  |
| White   | 07  |

### Channel Level Conversion Table (dB to Hex)
| dB   | Hex | Dec |
|------|-----|-----|
| +10  | 7F  | 127 |
| +5   | 74  | 116 |
| 0    | 69  | 105 |
| -5   | 5E  | 94  |
| -10  | 53  | 83  |
| -15  | 48  | 72  |
| -20  | 3D  | 61  |
| -25  | 32  | 50  |
| -30  | 27  | 39  |
| -35  | 1C  | 28  |
| -40  | 11  | 17  |
| -45  | 06  | 6   |
| -48  | 01  | 1   |
| -inf | 00  | 0   |

## Examples

### Example 1: Mute Input Channel 5
```
# MIDI Channel N=0 (Input), CH=04 (Channel 5)
# Mute On: NOTE ON with velocity > 40, then NOTE OFF
90, 04, 7F, 90, 04, 00
```

### Example 2: Set Zone 10 Level to -10dB
```
# MIDI Channel N=1 (Zone), CH=09 (Zone 10), Level=53 (-10dB)
# NRPN Parameter ID 17 (Channel Level)
B1, 63, 09, B1, 62, 17, B1, 06, 53
```

### Example 3: Recall Preset 150
```
# Preset 150 is in range 129-256, so Bank = 01, Hex = 150-129 = 21 = 15 hex
B0, 00, 01, C0, 15
```

### Example 4: Get Input 1 Phantom Power Status
```
# SysEx Header + 00 (Input MIDI channel) + 01 + 0B + 1B (Phantom parameter) + 00 (Channel 1) + F7
F0, 00, 00, 1A, 50, 12, 01, 00, 00, 01, 0B, 1B, 00, F7
```

## Troubleshooting

### Common Issues

**Connection Refused**
- Verify the correct port (51325 or 51327)
- Check network connectivity
- Ensure AHM processor is powered on and network-enabled

**Authentication Failed (TLS/SSL)**
- Verify user profile is in range 00-1F
- Check username and password
- Ensure proper message format: `UserProfile, UserPassword`

**No Response to Commands**
- Verify MIDI message format and hexadecimal values
- Check channel mappings using reference tables
- Ensure SysEx header is correct for SysEx messages

**Incorrect Channel Control**
- Double-check channel number conversion using reference tables
- Verify MIDI channel (N) corresponds to correct device type
- Ensure note number (CH) is within valid range

### Message Format Notes

- All values in protocol are hexadecimal
- MIDI channel N and note number CH must be correctly calculated
- SysEx messages require proper header and termination (F7)
- NRPN messages require specific parameter IDs

---

**Document Version**: V1.5 Issue 1  
**Protocol Version**: V1.5  
**Firmware Compatibility**: V1.5

For additional support, consult your AHM processor documentation or contact Allen & Heath technical support.