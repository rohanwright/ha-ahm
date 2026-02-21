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

    Architecture
    ------------
    Write path  — ``send_command`` / ``send_sysex_command``
        Acquires a write lock for ordering, writes bytes, releases immediately.
        Never waits for a response.  All SET commands and GET triggers use this.

    Read path   — ``_reader_loop`` → ``_rx_queue`` → push listener
        A background task continuously parses incoming bytes into complete MIDI
        messages and places them on ``_rx_queue``.  The coordinator's push
        listener drains that queue every 0.5 s and applies state updates.
        Because the write path never blocks on a response, there is no
        competition between the push listener and GET responses.

    Crosspoint GETs (SysEx → SysEx response)
        The only case that needs request/response.  ``query_sysex`` sets a
        ``_sysex_waiter`` Future before writing; the reader resolves it as soon
        as a SysEx message arrives.  A separate ``_sysex_lock`` prevents two
        crosspoint queries from overlapping.
    """

    # SysEx protocol version bytes (hardcoded — this is the protocol version, not firmware).
    _SYSEX_VERSION = "0100"

    def __init__(self, host: str, port: int = 51325) -> None:
        """Initialize the AHM client."""
        self.host = host
        self.port = port

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # Write lock — ensures bytes from concurrent coroutines are not interleaved.
        self._write_lock: asyncio.Lock = asyncio.Lock()
        # SysEx query lock — only one crosspoint GET in flight at a time.
        self._sysex_lock: asyncio.Lock = asyncio.Lock()
        # Resolved by the reader loop when a SysEx response arrives.
        self._sysex_waiter: asyncio.Future | None = None
        # Background reader task.
        self._reader_task: asyncio.Task | None = None
        # Parsed inbound MIDI messages (Note On, CC) waiting for the push listener.
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()

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
                self.host, self.port, self._SYSEX_VERSION,
            )
            # Fresh queue — discard any stale messages from a previous connection.
            self._rx_queue = asyncio.Queue()
            self._sysex_waiter = None
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
        """Background task: parse incoming bytes into complete MIDI messages.

        SysEx messages are routed to ``_sysex_waiter`` if a crosspoint GET is
        in flight; all other messages (Note On mutes, NRPN CC levels) go to
        ``_rx_queue`` for the push listener to process.
        """
        buf = bytearray()
        last_status = 0  # MIDI running status: last channel-voice status byte seen
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

                while buf:
                    msg, consumed, last_status = self._parse_next_midi(buf, last_status)
                    if msg is None:
                        break
                    buf = buf[consumed:]
                    _LOGGER.debug("RX: %s", bytes(msg).hex(" ").upper())

                    if msg[0] == 0xF0:
                        # SysEx — resolve crosspoint GET waiter if one is pending,
                        # otherwise queue it for the push listener to parse
                        # (the device sends unsolicited SysEx when crosspoints change).
                        waiter = self._sysex_waiter
                        if waiter is not None and not waiter.done():
                            waiter.set_result(bytes(msg))
                        else:
                            await self._rx_queue.put(bytes(msg))
                    else:
                        # MIDI channel message — goes to push listener queue.
                        await self._rx_queue.put(bytes(msg))

        except asyncio.CancelledError:
            pass
        _LOGGER.debug("Reader loop exited")

    @staticmethod
    def _parse_next_midi(
        buf: bytearray, last_status: int = 0
    ) -> tuple[bytearray | None, int, int]:
        """Extract the next complete MIDI message from *buf*, honouring running status.

        MIDI running status allows senders to omit the status byte for consecutive
        messages on the same channel/type.  The AHM uses this in NRPN sequences
        and mute-response pairs.

        Args:
            buf:         Incoming byte buffer (at least 1 byte).
            last_status: The most recent channel-voice status byte (0 if none yet).

        Returns:
            ``(message, bytes_consumed, new_last_status)``
            or ``(None, 0, last_status)`` if the buffer is incomplete.
        """
        if not buf:
            return None, 0, last_status

        first = buf[0]

        # ---- SysEx (F0 ... F7): resets running status ----
        if first == 0xF0:
            end = buf.find(0xF7)
            if end == -1:
                return None, 0, last_status  # Incomplete — wait for more bytes.
            return bytearray(buf[:end + 1]), end + 1, 0

        # ---- Real-time (F8–FF): single byte, does NOT affect running status ----
        if first >= 0xF8:
            return bytearray([first]), 1, last_status

        # ---- System common (F1–F7 excl. F0/F7): reset running status ----
        if first >= 0xF0:
            return bytearray([first]), 1, 0

        # ---- Normal channel-voice status byte (80–7F) ----
        if first >= 0x80:
            msg_type = first & 0xF0
            if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # 3-byte
                if len(buf) < 3:
                    return None, 0, last_status  # Wait for data bytes.
                return bytearray(buf[:3]), 3, first
            if msg_type in (0xC0, 0xD0):  # 2-byte
                if len(buf) < 2:
                    return None, 0, last_status
                return bytearray(buf[:2]), 2, first
            # Unknown status — advance past it.
            _LOGGER.debug("Unknown status byte: %02X", first)
            return bytearray([first]), 1, 0

        # ---- Data byte (00–7F): running status ----
        # buf[0] is a data byte, not a status byte.  Re-use last_status to
        # reconstruct the full message without consuming a status byte.
        if last_status == 0:
            # No previous status — nothing we can do, skip.
            _LOGGER.debug("Orphan data byte (no running status): %02X", first)
            return bytearray([first]), 1, last_status

        msg_type = last_status & 0xF0
        if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # 3-byte: needs 2 data bytes
            if len(buf) < 2:
                return None, 0, last_status
            return bytearray([last_status, buf[0], buf[1]]), 2, last_status
        if msg_type in (0xC0, 0xD0):  # 2-byte: needs 1 data byte
            return bytearray([last_status, buf[0]]), 1, last_status

        # Shouldn't be reachable.
        return bytearray([first]), 1, last_status

    def drain_queue(self) -> list[bytes]:
        """Return all MIDI messages currently in the queue (non-blocking).

        Called by the coordinator's push listener each cycle to collect Note On
        (mute) and NRPN CC (level) messages — both unsolicited pushes from the
        hardware and responses to channel GET queries.
        """
        messages: list[bytes] = []
        while not self._rx_queue.empty():
            try:
                messages.append(self._rx_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if messages:
            _LOGGER.debug("Drain: %d message(s)", len(messages))
        return messages

    # ------------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------------

    async def send_command(self, data: bytes) -> bool:
        """Send raw bytes to the AHM.  Fire-and-forget — no response expected."""
        async with self._write_lock:
            for attempt in range(2):
                if not await self._ensure_connected():
                    return False
                try:
                    _LOGGER.debug("TX: %s", data.hex(" ").upper())
                    self._writer.write(data)
                    await self._writer.drain()
                    return True
                except (ConnectionResetError, BrokenPipeError, OSError) as err:
                    _LOGGER.warning("TX error (attempt %d/2): %s", attempt + 1, err)
                    await self.async_disconnect()
            return False

    async def send_sysex_command(self, message: str) -> bool:
        """Build and send a SysEx command.  Fire-and-forget."""
        packet = bytearray.fromhex(
            f"F000001A5012{self._SYSEX_VERSION}{message}"
        )
        return await self.send_command(bytes(packet))

    async def query_sysex(self, message: str, timeout: float = _READ_TIMEOUT) -> Optional[bytes]:
        """Send a SysEx GET and wait for the device's SysEx response.

        Used exclusively for crosspoint GET queries whose responses are SysEx
        blobs rather than MIDI channel messages.  ``_sysex_lock`` ensures only
        one query is in flight at a time so waiter futures are never confused.
        """
        async with self._sysex_lock:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[bytes] = loop.create_future()
            self._sysex_waiter = fut
            try:
                if not await self.send_sysex_command(message):
                    return None
                return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            except asyncio.TimeoutError:
                _LOGGER.debug("query_sysex timeout for: %s", message)
                return None
            finally:
                self._sysex_waiter = None

    async def recall_preset(self, number: int) -> bool:
        """Recall a preset."""
        try:
            number = min(500, max(1, number))
            if 1 <= number <= 128:
                bank, preset = "00", number - 1
            elif number <= 256:
                bank, preset = "01", number - 129
            elif number <= 384:
                bank, preset = "02", number - 257
            else:
                bank, preset = "03", number - 385
            return await self.send_command(bytearray.fromhex(f"B000{bank}C0{preset:02x}"))
        except Exception as err:
            _LOGGER.error("Failed to recall preset %d: %s", number, err)
            return False

    async def play_audio(self, track_id: int, channel: int = 0) -> bool:
        """Play audio track."""
        try:
            return await self.send_sysex_command(
                f"0006{channel:02x}{track_id:02x}F7"
            )
        except Exception as err:
            _LOGGER.error("Failed to play audio track %d: %s", track_id, err)
            return False

    async def test_connection(self) -> bool:
        """Test connection by ensuring the TCP socket is open."""
        return await self._ensure_connected()

    # ------------------------------------------------------------------
    # Channel state requests (fire-and-forget GET; responses via push listener)
    # ------------------------------------------------------------------
    # The AHM responds to mute GETs with a Note On (9N CH VL) and to level
    # GETs with an NRPN CC sequence (BN 63 CH  BN 62 17  BN 06 LV).  Both
    # formats are identical to the unsolicited push messages the device sends
    # when hardware controls are moved, so the coordinator's push listener
    # handles them without any special casing.

    async def request_input_state(self, number: int) -> None:
        """Request current mute and level for an input channel."""
        ch = f"{min(max(0, number - 1), 63):02x}"
        await self.send_sysex_command(f"000109{ch}F7")   # mute GET
        await self.send_sysex_command(f"00010B17{ch}F7") # level GET

    async def request_zone_state(self, number: int) -> None:
        """Request current mute and level for a zone."""
        ch = f"{min(max(0, number - 1), 63):02x}"
        await self.send_sysex_command(f"010109{ch}F7")
        await self.send_sysex_command(f"01010B17{ch}F7")

    async def request_control_group_state(self, number: int) -> None:
        """Request current mute and level for a control group."""
        ch = f"{min(max(0, number - 1), 31):02x}"
        await self.send_sysex_command(f"020109{ch}F7")
        await self.send_sysex_command(f"02010B17{ch}F7")

    # ------------------------------------------------------------------
    # Channel SET commands
    # ------------------------------------------------------------------

    async def set_input_mute(self, number: int, muted: bool) -> bool:
        """Set input mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            vel = "7F" if muted else "3F"
            return await self.send_command(bytearray.fromhex(f"90{ch}{vel}90{ch}00"))
        except Exception as err:
            _LOGGER.error("Failed to set input %d mute: %s", number, err)
            return False

    async def set_input_level(self, number: int, level: int) -> bool:
        """Set input level as raw MIDI value (0-127)."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            lv = f"{max(0, min(127, int(level))):02x}"
            return await self.send_command(bytearray.fromhex(f"B063{ch}B06217B006{lv}"))
        except Exception as err:
            _LOGGER.error("Failed to set input %d level: %s", number, err)
            return False

    async def set_zone_mute(self, number: int, muted: bool) -> bool:
        """Set zone mute status."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            vel = "7F" if muted else "3F"
            return await self.send_command(bytearray.fromhex(f"91{ch}{vel}91{ch}00"))
        except Exception as err:
            _LOGGER.error("Failed to set zone %d mute: %s", number, err)
            return False

    async def set_zone_level(self, number: int, level: int) -> bool:
        """Set zone level as raw MIDI value (0-127)."""
        try:
            ch = f"{min(max(0, number - 1), 63):02x}"
            lv = f"{max(0, min(127, int(level))):02x}"
            return await self.send_command(bytearray.fromhex(f"B163{ch}B16217B106{lv}"))
        except Exception as err:
            _LOGGER.error("Failed to set zone %d level: %s", number, err)
            return False

    async def set_control_group_mute(self, number: int, muted: bool) -> bool:
        """Set control group mute status."""
        try:
            ch = f"{min(max(0, number - 1), 31):02x}"
            vel = "7F" if muted else "3F"
            return await self.send_command(bytearray.fromhex(f"92{ch}{vel}92{ch}00"))
        except Exception as err:
            _LOGGER.error("Failed to set control group %d mute: %s", number, err)
            return False

    async def set_control_group_level(self, number: int, level: int) -> bool:
        """Set control group level as raw MIDI value (0-127)."""
        try:
            ch = f"{min(max(0, number - 1), 31):02x}"
            lv = f"{max(0, min(127, int(level))):02x}"
            return await self.send_command(bytearray.fromhex(f"B263{ch}B26217B206{lv}"))
        except Exception as err:
            _LOGGER.error("Failed to set control group %d level: %s", number, err)
            return False

    # ------------------------------------------------------------------
    # Crosspoint (send) controls
    # ------------------------------------------------------------------
    # GET queries return SysEx responses — handled via query_sysex / Future.
    # SET commands are fire-and-forget SysEx writes.

    def _crosspoint_addrs(self, source_type: str, source_num: int, dest_zone: int) -> tuple[str, str, str] | None:
        """Return (snd_n, snd_ch, dest_ch) hex strings or None for unknown type."""
        if source_type == "input":
            snd_n = "00"
        elif source_type == "zone":
            snd_n = "01"
        else:
            return None
        snd_ch = f"{min(max(0, source_num - 1), 63):02x}"
        dest_ch = f"{min(max(0, dest_zone - 1), 63):02x}"
        return snd_n, snd_ch, dest_ch

    async def get_send_level(self, source_type: str, source_num: int, dest_zone: int) -> Optional[int]:
        """Get send level as raw MIDI value (0-127)."""
        try:
            addrs = self._crosspoint_addrs(source_type, source_num, dest_zone)
            if addrs is None:
                return None
            snd_n, snd_ch, dest_ch = addrs
            result = await self.query_sysex(f"{snd_n}010F02{snd_ch}01{dest_ch}F7")
            if result and len(result) >= 3:
                return result[-2]
            return None
        except Exception as err:
            _LOGGER.error("Failed to get send level %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return None

    async def set_send_level(self, source_type: str, source_num: int, dest_zone: int, level: int) -> bool:
        """Set send level as raw MIDI value (0-127)."""
        try:
            addrs = self._crosspoint_addrs(source_type, source_num, dest_zone)
            if addrs is None:
                return False
            snd_n, snd_ch, dest_ch = addrs
            lv = f"{max(0, min(127, int(level))):02x}"
            # Format: snd_n(source type), 02(cmd), snd_ch(source ch), 01(zone dest), dest_ch, lv
            return await self.send_sysex_command(f"{snd_n}02{snd_ch}01{dest_ch}{lv}F7")
        except Exception as err:
            _LOGGER.error("Failed to set send level %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return False

    async def get_send_muted(self, source_type: str, source_num: int, dest_zone: int) -> Optional[bool]:
        """Get send mute status."""
        try:
            addrs = self._crosspoint_addrs(source_type, source_num, dest_zone)
            if addrs is None:
                return None
            snd_n, snd_ch, dest_ch = addrs
            result = await self.query_sysex(f"{snd_n}010F03{snd_ch}01{dest_ch}F7")
            if result and len(result) >= 3:
                return result[-2] > 63
            return None
        except Exception as err:
            _LOGGER.error("Failed to get send mute %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return None

    async def set_send_mute(self, source_type: str, source_num: int, dest_zone: int, muted: bool) -> bool:
        """Set send mute status."""
        try:
            addrs = self._crosspoint_addrs(source_type, source_num, dest_zone)
            if addrs is None:
                return False
            snd_n, snd_ch, dest_ch = addrs
            val = "7F" if muted else "3F"
            # Format: snd_n(source type), 03(cmd), snd_ch(source ch), 01(zone dest), dest_ch, val
            return await self.send_sysex_command(f"{snd_n}03{snd_ch}01{dest_ch}{val}F7")
        except Exception as err:
            _LOGGER.error("Failed to set send mute %s %d->zone %d: %s", source_type, source_num, dest_zone, err)
            return False
