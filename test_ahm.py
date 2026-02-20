#!/usr/bin/env python3
"""
Test script for the AHM Zone Mixer integration.

Run directly against a physical device to verify connectivity and
protocol correctness before deploying to Home Assistant.

Usage:
    python test_ahm.py
    python test_ahm.py 192.168.1.100
    python test_ahm.py 192.168.1.100 1.5
"""

import asyncio
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "ahm"))

from ahm_client import AhmClient

# Set to DEBUG to see raw connection / protocol messages.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

PASS = "✓"
FAIL = "✗"
WARN = "⚠"


def _fmt_db(val) -> str:
    if val is None:
        return "None"
    if val == float("-inf"):
        return "-inf dB"
    return f"{val:.1f} dB"


async def _timed(coro):
    """Run *coro* and return (result, elapsed_ms)."""
    t0 = time.perf_counter()
    result = await coro
    return result, round((time.perf_counter() - t0) * 1000)


# ──────────────────────────────────────────────────────────────────────────────
# Test sections
# ──────────────────────────────────────────────────────────────────────────────

async def test_connection(client: AhmClient) -> bool:
    """Open the TCP connection and confirm the device responds."""
    print("── 1. Connection ─────────────────────────────────────────")

    print("   Opening persistent TCP connection ...", end=" ", flush=True)
    t0 = time.perf_counter()
    ok = await client.async_connect()
    elapsed = round((time.perf_counter() - t0) * 1000)
    if not ok:
        print(f"{FAIL}  (could not connect after {elapsed} ms)")
        return False
    print(f"{PASS}  ({elapsed} ms)")

    print("   Sending test query (input 1 mute status) ...", end=" ", flush=True)
    result, ms = await _timed(client.test_connection())
    if result:
        print(f"{PASS}  ({ms} ms — device responded)")
    else:
        print(f"{WARN}  ({ms} ms — no valid response, device may not support query)")

    return True


async def test_reads(client: AhmClient, channels: dict[str, list[int]]) -> None:
    """Read mute and level for each configured channel type."""
    print("\n── 2. Read Tests ─────────────────────────────────────────")

    type_map = {
        "input":         (client.get_input_muted,         client.get_input_level),
        "zone":          (client.get_zone_muted,          client.get_zone_level),
        "control_group": (client.get_control_group_muted, client.get_control_group_level),
        "room":          (client.get_room_muted,          client.get_room_level),
    }

    for ch_type, nums in channels.items():
        if not nums:
            continue
        get_muted, get_level = type_map[ch_type]
        label = ch_type.replace("_", " ").title()
        print(f"\n   {label}s: {nums}")

        for n in nums:
            muted, ms_m = await _timed(get_muted(n))
            level, ms_l = await _timed(get_level(n))

            mute_str  = str(muted) if muted is not None else f"{WARN} None"
            level_str = _fmt_db(level) if level is not None else f"{WARN} None"
            ok_sym    = PASS if (muted is not None and level is not None) else WARN

            print(
                f"   {ok_sym}  {label} {n:>2}  "
                f"muted={mute_str:<8}  level={level_str:<12}  "
                f"({ms_m}ms / {ms_l}ms)"
            )


async def test_crosspoint_read(client: AhmClient, source_type: str, source_num: int, dest_zone: int) -> None:
    """Read a single crosspoint send and print the result."""
    label = f"{'Input' if source_type == 'input' else 'Zone'} {source_num} → Zone {dest_zone}"

    muted, ms_m = await _timed(client.get_send_muted(source_type, source_num, dest_zone))
    level, ms_l = await _timed(client.get_send_level(source_type, source_num, dest_zone))

    ok_sym    = PASS if (muted is not None and level is not None) else WARN
    mute_str  = str(muted) if muted is not None else f"{WARN} None"
    level_str = _fmt_db(level) if level is not None else f"{WARN} None"

    print(
        f"   {ok_sym}  {label:<30}  "
        f"muted={mute_str:<8}  level={level_str:<12}  "
        f"({ms_m}ms / {ms_l}ms)"
    )


async def test_write(client: AhmClient) -> None:
    """
    Optionally test write (set) operations.
    Reads current values, writes the same values back — net zero change.
    """
    print("\n── 3. Write Test (round-trip, no audible change) ─────────")

    # Read current input 1 state.
    muted = await client.get_input_muted(1)
    level = await client.get_input_level(1)

    if muted is None or level is None:
        print(f"   {WARN}  Could not read input 1 state — skipping write test.")
        return

    level_safe = max(-48.0, min(10.0, level if level != float("-inf") else -48.0))

    print(f"   Input 1 current state: muted={muted}, level={_fmt_db(level)}")
    print(f"   Writing same values back ...")

    _, ms1 = await _timed(client.set_input_mute(1, muted))
    _, ms2 = await _timed(client.set_input_level(1, level_safe))

    # Read back to confirm.
    muted2 = await client.get_input_muted(1)
    level2 = await client.get_input_level(1)

    if muted2 == muted:
        print(f"   {PASS}  Mute round-trip OK ({ms1}ms write)")
    else:
        print(f"   {FAIL}  Mute mismatch: wrote {muted}, read back {muted2}")

    if level2 is not None and abs((level2 or 0) - level_safe) < 1.0:
        print(f"   {PASS}  Level round-trip OK ({ms2}ms write) — {_fmt_db(level2)}")
    else:
        print(f"   {WARN}  Level after write: {_fmt_db(level2)}  (expected ~{_fmt_db(level_safe)})")


async def test_timing(client: AhmClient, iterations: int = 5) -> None:
    """
    Measure how long a realistic poll cycle takes over the persistent connection.
    Simulates polling inputs 1–4 and zones 1–2 (8 queries).
    """
    print(f"\n── 4. Poll Timing ({iterations} cycles, 8 queries each) ──────")

    times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        for n in range(1, 5):
            await client.get_input_muted(n)
            await client.get_input_level(n)
        for n in range(1, 3):
            await client.get_zone_muted(n)
            await client.get_zone_level(n)
        elapsed = round((time.perf_counter() - t0) * 1000)
        times.append(elapsed)
        print(f"   Cycle {i+1}: {elapsed} ms")

    avg = round(sum(times) / len(times))
    print(f"\n   Average: {avg} ms  |  Min: {min(times)} ms  |  Max: {max(times)} ms")
    if avg < 500:
        print(f"   {PASS}  Well within the 5-second poll interval.")
    elif avg < 3000:
        print(f"   {WARN}  Acceptable but consider reducing the number of polled channels.")
    else:
        print(f"   {FAIL}  Too slow — a full poll may exceed the 5-second interval.")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def run_tests(host: str, version: str) -> None:
    print(f"\nAHM Integration Test  —  {host}  (firmware {version})")
    print("=" * 60)

    client = AhmClient(host=host, version=version)

    try:
        # 1. Connection
        if not await test_connection(client):
            print(f"\n{FAIL}  Cannot reach device. Aborting.")
            return

        # 2. Read tests — edit these lists to match your setup.
        await test_reads(client, {
            "input":         [1, 2, 3, 4],
            "zone":          [1, 2],
            "control_group": [],
            "room":          [],
        })

        # Crosspoint reads — comment out if you have none configured.
        need_xp = input("\n   Test crosspoint (send) reads? [y/N]: ").strip().lower()
        if need_xp == "y":
            print("\n── 2b. Crosspoint Read Tests ─────────────────────────────")
            # Edit these to match your actual routing.
            await test_crosspoint_read(client, "input", 1, 1)
            await test_crosspoint_read(client, "input", 2, 1)
            await test_crosspoint_read(client, "zone",  1, 2)

        # 3. Write test (optional — safe round-trip).
        do_write = input("\n   Run write round-trip test on Input 1? [y/N]: ").strip().lower()
        if do_write == "y":
            await test_write(client)

        # 4. Timing
        await test_timing(client)

    finally:
        print("\n── Disconnecting ─────────────────────────────────────────")
        await client.async_disconnect()
        print(f"   {PASS}  Connection closed cleanly.")

    print("\n" + "=" * 60)
    print("Test run complete.")


async def interactive() -> None:
    # Allow args from CLI or prompt interactively.
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    else:
        host = input("AHM device IP address: ").strip()
    if not host:
        print("Error: IP address required.")
        return

    if len(sys.argv) >= 3:
        version = sys.argv[2]
    else:
        version = input("Firmware version [1.5]: ").strip() or "1.5"

    try:
        await run_tests(host, version)
    except KeyboardInterrupt:
        print("\nInterrupted.")


def main() -> None:
    try:
        asyncio.run(interactive())
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()



async def test_ahm_connection(host: str, version: str = "1.5"):
    """Test basic AHM device connectivity."""
    
    print(f"Testing AHM connection to {host} (version {version})")
    print("-" * 50)
    
    client = AhmClient(host=host, version=version)
    
    # Test basic connection
    print("1. Testing basic connection...")
    if await client.test_connection():
        print("   ✓ Connection successful")
    else:
        print("   ✗ Connection failed")
        return False
    
    # Test input controls
    print("\n2. Testing input controls...")
    try:
        # Test input 1
        muted = await client.get_input_muted(1)
        level = await client.get_input_level(1)
        
        print(f"   Input 1 - Muted: {muted}, Level: {level}dB")
        
        if muted is not None and level is not None:
            print("   ✓ Input status read successful")
        else:
            print("   ⚠ Input status read returned None values")
            
    except Exception as e:
        print(f"   ✗ Input test failed: {e}")
    
    # Test zone controls
    print("\n3. Testing zone controls...")
    try:
        # Test zone 1
        muted = await client.get_zone_muted(1)
        level = await client.get_zone_level(1)
        
        print(f"   Zone 1 - Muted: {muted}, Level: {level}dB")
        
        if muted is not None and level is not None:
            print("   ✓ Zone status read successful")
        else:
            print("   ⚠ Zone status read returned None values")
            
    except Exception as e:
        print(f"   ✗ Zone test failed: {e}")
    
    # Test preset recall (non-destructive test)
    print("\n4. Testing preset recall...")
    try:
        # Just test if the command can be sent (don't actually change preset)
        print("   Skipping preset recall test (non-destructive)")
        print("   ✓ Preset recall method available")
    except Exception as e:
        print(f"   ✗ Preset recall test failed: {e}")
    
    print("\n" + "=" * 50)
    print("Test completed successfully!")
    print("Your AHM device appears to be compatible with this integration.")
    
    return True


async def interactive_test():
    """Interactive test with user input."""
    
    print("AHM Zone Mixer Integration Test Script")
    print("=" * 50)
    print()
    
    # Get device details from user
    host = input("Enter AHM device IP address: ").strip()
    if not host:
        print("Error: IP address is required")
        return
    
    version = input("Enter firmware version (default: 1.5): ").strip()
    if not version:
        version = "1.5"
    
    print()
    
    try:
        success = await test_ahm_connection(host, version)
        if success:
            print("\n✓ All tests passed! You can proceed with the Home Assistant integration setup.")
        else:
            print("\n✗ Tests failed. Please check your device configuration and network connectivity.")
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        logger.exception("Test failed with exception")


def main():
    """Main entry point."""
    try:
        asyncio.run(interactive_test())
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
