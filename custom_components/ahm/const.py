"""Constants for the AHM integration."""
from typing import Final

DOMAIN: Final = "ahm"

# Default values
DEFAULT_NAME = "AHM Zone Mixer"
DEFAULT_PORT = 51325
DEFAULT_MODEL = "AHM-16"

# Configuration
CONF_HOST = "host"
CONF_NAME = "name"
CONF_MODEL = "model"

# Device model limits: inputs, zones, control groups
MODEL_LIMITS: Final = {
    "AHM-16": {"inputs": 16, "zones": 16, "control_groups": 32},
    "AHM-32": {"inputs": 32, "zones": 32, "control_groups": 32},
    "AHM-64": {"inputs": 64, "zones": 64, "control_groups": 32},
}
CONF_INPUTS = "inputs"
CONF_ZONES = "zones"
CONF_CONTROL_GROUPS = "control_groups"
CONF_INPUT_TO_ZONE_SENDS = "input_to_zone_sends"
CONF_ZONE_TO_ZONE_SENDS = "zone_to_zone_sends"

# Update intervals
# Push updates from the AHM are the primary mechanism; polling is a slow
# fallback to catch any missed packets.
UPDATE_INTERVAL = 60  # seconds

# Device limits (absolute maximums across all models)
MAX_CONTROL_GROUPS = 32
MAX_PRESETS = 500

# Audio playback channels
PLAYBACK_CHANNELS = {
    0: "Mono 1",
    1: "Mono 2", 
    2: "Stereo"
}

# Entity types
ENTITY_TYPE_INPUT = "input"
ENTITY_TYPE_ZONE = "zone"
ENTITY_TYPE_CONTROL_GROUP = "control_group"
ENTITY_TYPE_CROSSPOINT = "crosspoint"
ENTITY_TYPE_INPUT_TO_ZONE_SEND = "input_to_zone_send"
ENTITY_TYPE_ZONE_TO_ZONE_SEND = "zone_to_zone_send"

# Crosspoint types
CROSSPOINT_TYPE_INPUT_TO_ZONE = "input_to_zone"
CROSSPOINT_TYPE_ZONE_TO_ZONE = "zone_to_zone"

# Raw MIDI level range (0-127 as used by the AHM protocol)
MIDI_LEVEL_MIN = 0
MIDI_LEVEL_MAX = 127
