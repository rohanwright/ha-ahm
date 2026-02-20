"""AHM Client for communicating with Allen & Heath AHM devices."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# How long to wait for a query response before giving up.
# Set commands don't always produce a response, so a short timeout is used and
# a TimeoutError is treated as "sent OK, no reply expected".
_READ_TIMEOUT = 0.2
# How long to wait when opening the TCP connection.
_CONNECT_TIMEOUT = 5.0


class AhmClient:
    """Client for communicating with AHM devices over a persistent TCP connection.

    The AHM uses a single TCP socket for all MIDI-over-TCP traffic. Opening a
    fresh connection per message (as a naïve implementation would do) is both
    slow and unreliable on the device's embedded TCP stack. This client keeps
    one connection alive for the lifetime of the integration and serialises every
    send/receive pair through an asyncio.Lock so that messages are never
    interleaved.
    """

    def __init__(self, host: str, version: str = "1.5", port: int = 51325) -> None:
        """Initialize the AHM client."""
        self.host = host
        self.version = version
        self.port = port

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # All I/O is serialised so responses are never mixed up.
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def version_bytestring(self) -> str:
        """Get firmware version as a 4-char hex string for SysEx messages (e.g. "1.5" → "0105")."""
        major, minor = self.version.split(".")
        return str(int(major)).zfill(2) + str(int(minor)).zfill(2)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def async_connect(self) -> bool:
        """Open the persistent TCP connection to the AHM device."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=_CONNECT_TIMEOUT,
            )
            _LOGGER.debug("Connected to AHM at %s:%s", self.host, self.port)
            return True
        except Exception as err:
            _LOGGER.error("Failed to connect to AHM at %s:%s: %s", self.host, self.port, err)
            self._reader = self._writer = None
            return False

    async def async_disconnect(self) -> None:
        """Close the persistent TCP connection."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            finally:
                self._reader = self._writer = None
        _LOGGER.debug("Disconnected from AHM")

    async def _ensure_connected(self) -> bool:
        """Return True if connected, attempting a reconnect if not."""
        if self._writer is not None and not self._writer.is_closing():
            return True
        _LOGGER.debug("AHM connection lost — reconnecting")
        return await self.async_connect()

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    async def send_bytes(self, message: bytes, get_result: bool = True) -> Optional[bytes]:
        """Send *message* over the persistent connection and optionally read the reply.

        All calls are serialised through ``_lock`` so concurrent coroutines
        cannot interleave their messages and responses.

        Returns:
            - The response bytes when ``get_result=True`` and the device replied.
            - ``b""`` when ``get_result=False`` (fire-and-forget, sent OK).
            - ``None`` on any unrecoverable error.
        """
        async with self._lock:
            for attempt in range(2):
                if not await self._ensure_connected():
                    return None
                try:
                    self._writer.write(message)
                    await self._writer.drain()

                    # Always attempt a read. The AHM firmware requires a recv even
                    # for commands that produce no response (see reference client).
                    # A TimeoutError simply means "no response" which is expected
                    # for most set/control commands.
                    try:
                        data = await asyncio.wait_for(
                            self._reader.read(1024), timeout=_READ_TIMEOUT
                        )
                        return data if get_result else b""
                    except asyncio.TimeoutError:
                        # No response within the window — normal for set commands.
                        return None if get_result else b""

                except (ConnectionResetError, BrokenPipeError, OSError) as err:
                    _LOGGER.warning(
                        "AHM connection error (attempt %d/2): %s", attempt + 1, err
                    )
                    await self.async_disconnect()
                    # Loop to retry once after reconnect.

            return None

    async def send_sysex(self, message: str | list[str]) -> Optional[bytes]:
        """Send SysEx message to AHM device."""
        if isinstance(message, list):
            message = "".join(message)
        
        sysex_message = bytearray.fromhex(
            f"F000001A5012{self.version_bytestring}{message}"
        )
        return await self.send_bytes(sysex_message)

    async def recall_preset(self, number: int) -> bool:
        """Recall a preset."""
        try:
            number = min(500, max(1, number))
            
            if 1 <= number <= 128:
                bank = "00"
                preset = number - 1
            elif number <= 256:
                bank = "01"
                preset = number - 129
            elif number <= 384:
                bank = "02"
                preset = number - 257
            else:
                bank = "03"
                preset = number - 385
            
            ss = f"{preset:02x}"
            message = bytearray.fromhex(f"B000{bank}C0{ss}")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to recall preset %d: %s", number, err)
            return False

    async def play_audio(self, track_id: int, channel: int = 0) -> bool:
        """Play audio track."""
        try:
            track_hex = f"{track_id:02x}"
            channel_hex = f"{channel:02x}"
            message = f"0006{channel_hex}{track_hex}F7"
            
            result = await self.send_sysex(message)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to play audio track %d: %s", track_id, err)
            return False

    # Input controls
    async def get_input_muted(self, number: int) -> Optional[bool]:
        """Get input mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            message = f"000109{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) > 2:
                return result[2] > 63
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get input %d mute status: %s", number, err)
            return None

    async def set_input_mute(self, number: int, muted: bool) -> bool:
        """Set input mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            velocity = "7F" if muted else "3F"
            message = bytearray.fromhex(f"90{ch}{velocity}90{ch}00")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set input %d mute: %s", number, err)
            return False

    async def get_input_level(self, number: int) -> Optional[float]:
        """Get input level in dB."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            message = f"00010B17{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) >= 7:
                midi_val = result[6]
                return self._midi_to_db(midi_val)
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get input %d level: %s", number, err)
            return None

    async def set_input_level(self, number: int, level: float) -> bool:
        """Set input level in dB."""
        try:
            level = min(10.0, max(-48.0, level))
            level_midi = self._db_to_midi(level)
            level_hex = f"{level_midi:02x}"
            ch = f"{min(max(0, number - 1), 63):02x}"
            
            message = bytearray.fromhex(f"B063{ch}B06217B006{level_hex}")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set input %d level: %s", number, err)
            return False

    # Zone controls
    async def get_zone_muted(self, number: int) -> Optional[bool]:
        """Get zone mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            message = f"010109{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) > 2:
                return result[2] > 63
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get zone %d mute status: %s", number, err)
            return None

    async def set_zone_mute(self, number: int, muted: bool) -> bool:
        """Set zone mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            velocity = "7F" if muted else "3F"
            message = bytearray.fromhex(f"91{ch}{velocity}91{ch}00")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set zone %d mute: %s", number, err)
            return False

    async def get_zone_level(self, number: int) -> Optional[float]:
        """Get zone level in dB."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            message = f"01010B17{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) >= 7:
                midi_val = result[6]
                return self._midi_to_db(midi_val)
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get zone %d level: %s", number, err)
            return None

    async def set_zone_level(self, number: int, level: float) -> bool:
        """Set zone level in dB."""
        try:
            level = min(10.0, max(-48.0, level))
            level_midi = self._db_to_midi(level)
            level_hex = f"{level_midi:02x}"
            ch = f"{min(max(0, number - 1), 63):02x}"
            
            message = bytearray.fromhex(f"B163{ch}B16217B106{level_hex}")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set zone %d level: %s", number, err)
            return False

    # Control group controls
    async def get_control_group_muted(self, number: int) -> Optional[bool]:
        """Get control group mute status."""
        try:
            ch = f"{min(max(0, number - 1), 31):02x}"
            message = f"020109{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) > 2:
                return result[2] > 63
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get control group %d mute status: %s", number, err)
            return None

    async def set_control_group_mute(self, number: int, muted: bool) -> bool:
        """Set control group mute status."""
        try:
            ch = f"{min(max(0, number - 1), 31):02x}"
            velocity = "7F" if muted else "3F"
            message = bytearray.fromhex(f"92{ch}{velocity}92{ch}00")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set control group %d mute: %s", number, err)
            return False

    async def get_control_group_level(self, number: int) -> Optional[float]:
        """Get control group level in dB."""
        try:
            ch = f"{min(max(0, number - 1), 31):02x}"
            message = f"02010B17{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) >= 7:
                midi_val = result[6]
                return self._midi_to_db(midi_val)
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get control group %d level: %s", number, err)
            return None

    async def set_control_group_level(self, number: int, level: float) -> bool:
        """Set control group level in dB."""
        try:
            level = min(10.0, max(-48.0, level))
            level_midi = self._db_to_midi(level)
            level_hex = f"{level_midi:02x}"
            ch = f"{min(max(0, number - 1), 31):02x}"
            
            message = bytearray.fromhex(f"B263{ch}B26217B206{level_hex}")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set control group %d level: %s", number, err)
            return False

    # Room controls
    async def get_room_muted(self, number: int) -> Optional[bool]:
        """Get room mute status."""
        try:
            ch = f"{min(max(0, number - 1), 15):02x}"
            message = f"030109{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) > 2:
                return result[2] > 63
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get room %d mute status: %s", number, err)
            return None

    async def set_room_mute(self, number: int, muted: bool) -> bool:
        """Set room mute status."""
        try:
            ch = f"{min(max(0, number - 1), 15):02x}"
            velocity = "7F" if muted else "3F"
            message = bytearray.fromhex(f"93{ch}{velocity}93{ch}00")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set room %d mute: %s", number, err)
            return False

    async def get_room_level(self, number: int) -> Optional[float]:
        """Get room level in dB."""
        try:
            ch = f"{min(max(0, number - 1), 15):02x}"
            message = f"03010B17{ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) >= 7:
                midi_val = result[6]
                return self._midi_to_db(midi_val)
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get room %d level: %s", number, err)
            return None

    async def set_room_level(self, number: int, level: float) -> bool:
        """Set room level in dB."""
        try:
            level = min(10.0, max(-48.0, level))
            level_midi = self._db_to_midi(level)
            level_hex = f"{level_midi:02x}"
            ch = f"{min(max(0, number - 1), 15):02x}"
            
            message = bytearray.fromhex(f"B363{ch}B36217B306{level_hex}")
            
            result = await self.send_bytes(message, get_result=False)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set room %d level: %s", number, err)
            return False

    async def test_connection(self) -> bool:
        """Test connection to AHM device."""
        try:
            # Try to get input 1 mute status as a connection test
            result = await self.get_input_muted(1)
            return result is not None
        except Exception:
            return False

    # Send controls (crosspoints)
    async def get_send_level(self, source_type: str, source_num: int, dest_zone: int) -> Optional[float]:
        """Get send level from source to destination zone."""
        try:
            # Map source type to MIDI channel and source number
            if source_type == "input":
                snd_n = "00"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            elif source_type == "zone":
                snd_n = "01"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            else:
                return None
            
            # Destination zone
            dest_ch = f"{min(max(0, dest_zone - 1), 63):02x}"
            
            # Send request: SysEx Header + 01 + 01 + 0F + 02 + dest_ch + snd_n + snd_ch + F7
            message = f"01010F02{dest_ch}{snd_n}{snd_ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) >= 7:
                midi_val = result[6]
                return self._midi_to_db(midi_val)
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get send level %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return None

    async def set_send_level(self, source_type: str, source_num: int, dest_zone: int, level: float) -> bool:
        """Set send level from source to destination zone."""
        try:
            level = min(10.0, max(-48.0, level))
            level_midi = self._db_to_midi(level)
            level_hex = f"{level_midi:02x}"
            
            # Map source type to MIDI channel and source number
            if source_type == "input":
                snd_n = "00"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            elif source_type == "zone":
                snd_n = "01"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            else:
                return False
            
            # Destination zone
            dest_ch = f"{min(max(0, dest_zone - 1), 63):02x}"
            
            # Set send level: SysEx Header + 01 + 02 + dest_ch + snd_n + snd_ch + level + F7
            message = f"0102{dest_ch}{snd_n}{snd_ch}{level_hex}F7"
            result = await self.send_sysex(message)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set send level %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return False

    async def get_send_muted(self, source_type: str, source_num: int, dest_zone: int) -> Optional[bool]:
        """Get send mute status from source to destination zone."""
        try:
            # Map source type to MIDI channel and source number
            if source_type == "input":
                snd_n = "00"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            elif source_type == "zone":
                snd_n = "01"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            else:
                return None
            
            # Destination zone
            dest_ch = f"{min(max(0, dest_zone - 1), 63):02x}"
            
            # Send request: SysEx Header + 01 + 01 + 0F + 03 + dest_ch + snd_n + snd_ch + F7
            message = f"01010F03{dest_ch}{snd_n}{snd_ch}F7"
            result = await self.send_sysex(message)
            
            if result and len(result) > 2:
                return result[2] > 63
            return None
            
        except Exception as err:
            _LOGGER.error("Failed to get send mute %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return None

    async def set_send_mute(self, source_type: str, source_num: int, dest_zone: int, muted: bool) -> bool:
        """Set send mute status from source to destination zone."""
        try:
            # Map source type to MIDI channel and source number
            if source_type == "input":
                snd_n = "00"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            elif source_type == "zone":
                snd_n = "01"
                snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
            else:
                return False
            
            # Destination zone
            dest_ch = f"{min(max(0, dest_zone - 1), 63):02x}"
            
            # Set send mute: SysEx Header + 01 + 03 + dest_ch + snd_n + snd_ch + mute_val + F7
            mute_val = "7F" if muted else "3F"
            message = f"0103{dest_ch}{snd_n}{snd_ch}{mute_val}F7"
            result = await self.send_sysex(message)
            return result is not None
            
        except Exception as err:
            _LOGGER.error("Failed to set send mute %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return False

    @staticmethod
    def _db_to_midi(level: float) -> int:
        """Convert dB level to MIDI value."""
        return max(0, min(127, int(((level + 48) / 58.0) * 127)))

    @staticmethod
    def _midi_to_db(val: int) -> float:
        """Convert MIDI value to dB level."""
        if val == 0:
            return float("-inf")
        return ((val / 127.0) * 58) - 48
