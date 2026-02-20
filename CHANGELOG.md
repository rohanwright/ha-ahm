# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-06-23

### Added
- Initial release of AHM Zone Mixer integration
- Support for Allen & Heath AHM Zone Mixer devices with Firmware V1.5
- Media player entities for volume and mute control
- Number entities for precise dB level adjustment
- Switch entities for dedicated mute controls
- Configuration flow with entity selection
- Services for preset recall and audio playback
- Support for inputs, zones, control groups, and rooms
- HACS compatibility
- Comprehensive documentation and examples

### Features
- Control up to 64 inputs, 64 zones, 32 control groups, and 16 rooms
- Real-time status polling with 5-second update interval
- Volume range: -48dB to +10dB with 0.5dB precision
- Preset recall (1-500 presets across 4 banks)
- Audio track playback with channel selection
- Async communication with proper error handling
- Device info integration with Home Assistant

### Requirements
- Home Assistant 2025.6.0 or later
- Allen & Heath AHM Zone Mixer with Firmware V1.5
- Network connectivity to AHM device
