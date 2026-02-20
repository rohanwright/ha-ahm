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

    The AHM uses a single TCP socket for all MIDI-over-TCP traffic. All
    incoming bytes are consumed by a background reader task that parses complete
    MIDI messages and enqueues them.  GET queries drain any pre-buffered
    (unsolicited) messages before sending, then wait for the device's response
    in the queue.  Unsolicited messages — pushed by the device when someone
    changes something on the hardware — are collected and returned by
    ``drain_unsolicited()`` so the coordinator can apply them immediately.
    """

    def __init__(self, host: str, version: str = "1.5", port: int = 51325) -> None:
        """Initialize the AHM client."""
        self.host = host
        self.version = version
        self.port = port

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # All outbound I/O is serialised so requests are never interleaved.
        self._lock: asyncio.Lock = asyncio.Lock()
        # Background reader task — started on connect, cancelled on disconnect.
        self._reader_task: asyncio.Task | None = None
        # Parsed inbound MIDI messages waiting to be consumed.
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()
        # Messages drained from the queue before a GET send (i.e. unsolicited).
        self._unsolicited_buffer: list[bytes] = []

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
            _LOGGER.debug("Connecting to AHM at %s:%s", self.host, self.port)
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=_CONNECT_TIMEOUT,
            )
            _LOGGER.debug(
                "Connected to AHM at %s:%s (SysEx version bytes: %s)",
                self.host, self.port, self.version_bytestring,
            )
            # Fresh queue — discard any stale messages from a previous connection.
            self._rx_queue = asyncio.Queue()
            self._unsolicited_buffer.clear()
            self._reader_task = asyncio.ensure_future(self._reader_loop())
            return True
        except Exception as err:
            _LOGGER.error("Failed to connect to AHM at %s:%s: %s", self.host, self.port, err)
            self._reader = self._writer = None
            return False

    async def async_disconnect(self) -> None:
        """Close the persistent TCP connection."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
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
        _LOGGER.debug("AHM connection lost — attempting reconnect")
        return await self.async_connect()

    async def _reader_loop(self) -> None:
        """Background task: continuously read bytes from the socket and parse
        complete MIDI messages into ``_rx_queue``.

        Running independently of the send/receive lock means unsolicited messages
        pushed by the AHM (e.g. when someone changes a level on the hardware)
        are captured in the queue rather than being silently dropped or being
        mistaken for a GET query response.
        """
        buf = bytearray()
        try:
            while self._reader is not None:
                try:
                    chunk = await self._reader.read(1024)
                except asyncio.CancelledError:
                    raise
                except (ConnectionResetError, BrokenPipeError, OSError) as err:
                    _LOGGER.debug("Reader loop connection error: %s", err)
                    break

                if not chunk:
                    _LOGGER.debug("AHM closed the connection (EOF)")
                    break

                buf.extend(chunk)

                # Extract every complete MIDI message from the buffer.
                while buf:
                    msg, consumed = self._parse_next_midi(buf)
                    if msg is None:
                        break  # Need more bytes.
                    buf = buf[consumed:]
                    _LOGGER.debug("RX: %s", bytes(msg).hex(" ").upper())
                    await self._rx_queue.put(bytes(msg))

        except asyncio.CancelledError:
            pass
        _LOGGER.debug("Reader loop exited")

    @staticmethod
    def _parse_next_midi(buf: bytearray) -> tuple[bytearray | None, int]:
        """Extract the next complete MIDI message from *buf*.

        Returns ``(message, bytes_consumed)`` or ``(None, 0)`` if the buffer
        does not yet contain a complete message.
        """
        if not buf:
            return None, 0

        status = buf[0]

        # SysEx: F0 ... F7
        if status == 0xF0:
            end = buf.find(0xF7)
            if end == -1:
                return None, 0  # Incomplete — wait for more bytes.
            return bytearray(buf[:end + 1]), end + 1

        # Real-time messages (single byte: F8-FF, excluding F0).
        if status >= 0xF8:
            return bytearray([status]), 1

        # Channel voice messages.
        msg_type = status & 0xF0
        if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # 3-byte messages
            if len(buf) < 3:
                return None, 0
            return bytearray(buf[:3]), 3
        if msg_type in (0xC0, 0xD0):  # 2-byte messages
            if len(buf) < 2:
                return None, 0
            return bytearray(buf[:2]), 2

        # Unknown status byte — skip it so the parser doesn't stall.
        _LOGGER.debug("Skipping unknown MIDI byte: %02X", status)
        return bytearray([status]), 1

    def drain_unsolicited(self) -> list[bytes]:
        """Return all unsolicited messages received since the last call.

        These are MIDI messages that arrived from the AHM between GET queries
        (i.e. not a response to any request we made) — typically state-change
        notifications pushed by the device when hardware controls are moved.
        Clears the internal buffer.
        """
        # Include messages drained from the queue before GETs, plus any that
        # arrived after the last GET (still sitting in the queue right now).
        messages = list(self._unsolicited_buffer)
        self._unsolicited_buffer.clear()
        while not self._rx_queue.empty():
            try:
                messages.append(self._rx_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if messages:
            _LOGGER.debug("Returning %d unsolicited message(s) to coordinator", len(messages))
        return messages

    # ------------------------------------------------------------------
    # Low-level send/receive
    # ------------------------------------------------------------------

    async def send_bytes(self, message: bytes, get_result: bool = True) -> Optional[bytes]:
        """Send *message* and optionally read the reply from the queue.

        For GET queries (``get_result=True``):
          - Any messages already sitting in ``_rx_queue`` before we send must be
            unsolicited pushes — move them to ``_unsolicited_buffer`` first so
            the next item we dequeue is genuinely the response to our request.
          - Wait up to ``_READ_TIMEOUT`` seconds for a response.

        For fire-and-forget commands (``get_result=False``):
          - Send and return immediately; the device may echo back a notification
            which will be picked up by ``drain_unsolicited()``.
        """
        async with self._lock:
            for attempt in range(2):
                if not await self._ensure_connected():
                    return None
                try:
                    if get_result:
                        # Move any pre-existing queue items to the unsolicited buffer
                        # so they don't masquerade as the response to our query.
                        while not self._rx_queue.empty():
                            try:
                                item = self._rx_queue.get_nowait()
                                _LOGGER.debug(
                                    "Pre-send unsolicited: %s", item.hex(" ").upper()
                                )
                                self._unsolicited_buffer.append(item)
                            except asyncio.QueueEmpty:
                                break

                    _LOGGER.debug("TX: %s", message.hex(" ").upper())
                    self._writer.write(message)
                    await self._writer.drain()

                    if get_result:
                        # Collect ALL messages received within the timeout window
                        # and return them concatenated. This is critical for NRPN
                        # responses (level queries) which arrive as three separate
                        # 3-byte CC messages. Callers use byte-index addressing
                        # (e.g. result[6] for level), so they need the full blob.
                        data = await self._receive_all(_READ_TIMEOUT)
                        if data:
                            return data
                        _LOGGER.debug("RX: <no response within %.3fs>", _READ_TIMEOUT)
                        return None

                    return b""

                except (ConnectionResetError, BrokenPipeError, OSError) as err:
                    _LOGGER.warning(
                        "AHM connection error (attempt %d/2): %s", attempt + 1, err
                    )
                    await self.async_disconnect()
                    # Loop to retry once after reconnect.

            return None

    async def _receive_all(self, timeout: float) -> bytes:
        """Dequeue all messages from ``_rx_queue`` received within *timeout* seconds.

        Returns the messages concatenated as a single bytes object (or ``b""``
        if nothing arrived). Collecting all messages into one blob means callers
        can use simple byte-index addressing regardless of how many individual
        MIDI messages make up the response — e.g. a GET level reply is three
        CC messages (9 bytes total) and callers read the level from byte index 6.
        """
        buf = bytearray()
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                msg = await asyncio.wait_for(self._rx_queue.get(), timeout=remaining)
                _LOGGER.debug("RX msg: %s", msg.hex(" ").upper())
                buf.extend(msg)
            except asyncio.TimeoutError:
                break
        return bytes(buf)

    async def send_sysex(self, message: str | list[str], get_result: bool = True) -> Optional[bytes]:
        """Build and send a SysEx message to the AHM device.

        Set ``get_result=False`` for write-only commands that produce no response.
        """
        if isinstance(message, list):
            message = "".join(message)
        
        sysex_message = bytearray.fromhex(
            f"F000001A5012{self.version_bytestring}{message}"
        )
        return await self.send_bytes(sysex_message, get_result=get_result)

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
            
            result = await self.send_sysex(message, get_result=False)
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
            # NRPN: BN 63 CH  BN 62 17  BN 06 LV  (9 bytes, per spec)
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
            # NRPN: BN 63 CH  BN 62 17  BN 06 LV  (9 bytes, per spec)
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
            # NRPN: BN 63 CH  BN 62 17  BN 06 LV  (9 bytes, per spec)
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
            # NRPN: BN 63 CH  BN 62 17  BN 06 LV  (9 bytes, per spec)
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
            
            # Set send level: SysEx Header + 0N(zone) + 02 + dest_ch + snd_n + snd_ch + level + F7
            message = f"0102{dest_ch}{snd_n}{snd_ch}{level_hex}F7"
            result = await self.send_sysex(message, get_result=False)
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
            
            # Set send mute: SysEx Header + 0N(zone) + 03 + dest_ch + snd_n + snd_ch + mute_val + F7
            mute_val = "7F" if muted else "3F"
            message = f"0103{dest_ch}{snd_n}{snd_ch}{mute_val}F7"
            result = await self.send_sysex(message, get_result=False)
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
