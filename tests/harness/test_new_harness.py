"""Unit tests validating the new test harness extensions:

- DualClockHarness
- DiscordFaultInjector
- BridgeContractInspector
"""

from __future__ import annotations

import struct

import pytest
from tests.harness.bridge_contract_verifier import BridgeContractInspector
from tests.harness.clock_harness import DualClockHarness
from tests.harness.discord_pipe import DiscordFaultInjector

from expedition33_rpc.integrations.discord_rpc import (
    OP_FRAME,
    OP_HANDSHAKE,
    DiscordFrameCodec,
    DiscordIPCClient,
)

# ---------------------------------------------------------------------------
# DualClockHarness Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dual_clock_harness_basic_and_advance() -> None:
    clock = DualClockHarness(initial_monotonic=100.0, initial_epoch=1_700_000_000.0)

    assert clock.monotonic == 100.0
    assert clock.epoch == 1_700_000_000.0
    assert clock.monotonic_clock() == 100.0
    assert clock.epoch_clock() == 1_700_000_000.0

    # Advance synchronized
    clock.advance(2.5)
    assert clock.monotonic == 102.5
    assert clock.epoch == 1_700_000_002.5

    # Negative advance rejected
    with pytest.raises(ValueError, match="Cannot advance monotonic clock by negative duration"):
        clock.advance(-1.0)


@pytest.mark.unit
def test_dual_clock_harness_simulate_ntp_jump() -> None:
    clock = DualClockHarness(initial_monotonic=50.0, initial_epoch=1_700_000_000.0)

    # Jump backward by 100 seconds (NTP step / OS sync)
    clock.simulate_ntp_jump(-100.0)
    assert clock.monotonic == 50.0  # Monotonic clock MUST remain unchanged
    assert clock.epoch == 1_700_000_000.0 - 100.0

    # Jump forward by 3600 seconds
    clock.simulate_ntp_jump(3600.0)
    assert clock.monotonic == 50.0
    assert clock.epoch == 1_700_000_000.0 + 3500.0

    # Advance still advances both from their respective current values
    clock.advance(10.0)
    assert clock.monotonic == 60.0
    assert clock.epoch == 1_700_000_000.0 + 3510.0


# ---------------------------------------------------------------------------
# DiscordFaultInjector Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discord_fault_injector_chunked_delivery_and_read_exact() -> None:
    """Verifies that DiscordFaultInjector in chunked byte-by-byte mode feeds DiscordIPCClient correctly."""
    injector = DiscordFaultInjector(chunk_size=1)
    handshake_resp = {"cmd": "DISPATCH", "evt": "READY", "data": {"user": {"username": "Tester"}}}
    injector.queue_response(handshake_resp, op=OP_FRAME)

    client = DiscordIPCClient(client_id="1234567890", transport=injector)
    assert client.connect() is True
    assert client.is_connected is True

    # Handshake request should be in written data
    written = injector.written_data
    op, length = struct.unpack("<II", written[:8])
    assert op == OP_HANDSHAKE
    assert length > 0


@pytest.mark.unit
def test_discord_fault_injector_write_and_read_latency() -> None:
    slept_durations: list[float] = []
    injector = DiscordFaultInjector(
        write_latency=0.01,
        read_latency=0.02,
        sleeper=slept_durations.append,
    )
    injector.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    frame = DiscordFrameCodec.encode(OP_FRAME, {"test": "data"})
    injector.write(frame)
    assert slept_durations == [0.01]

    data = injector.read(8)
    assert slept_durations == [0.01, 0.02]
    assert len(data) == 8


@pytest.mark.unit
def test_discord_fault_injector_failure_simulation() -> None:
    injector = DiscordFaultInjector(fail_write_with=BrokenPipeError)
    with pytest.raises(BrokenPipeError):
        injector.write(b"any_data")

    injector_read = DiscordFaultInjector(fail_read_with=ConnectionError("Pipe severed"))
    with pytest.raises(ConnectionError, match="Pipe severed"):
        injector_read.read(10)


# ---------------------------------------------------------------------------
# BridgeContractInspector Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bridge_contract_inspector_script_extraction_and_tokens() -> None:
    inspector = BridgeContractInspector()
    script = inspector.read_mod_script()
    assert len(script) > 500
    assert "Expedition33RPC" in script

    params = inspector.extract_write_status_parameters(script)
    assert "in_combat" in params
    assert "enemy_name" in params
    assert "zone" in params
    assert "checkpoint" in params
    assert "enemies" in params

    keys = inspector.extract_write_status_json_keys(script)
    assert "in_combat" in keys
    assert "enemy_name" in keys
    assert "enemies" in keys
    assert "zone" in keys
    assert "raw_zone" in keys
    assert "raw_level" in keys
    assert "world_path" in keys
    assert "checkpoint" in keys
    assert "tower_floor" in keys
    assert "tower_trial" in keys
    assert "timestamp" in keys


@pytest.mark.unit
def test_bridge_contract_inspector_verify_contract_with_provider() -> None:
    inspector = BridgeContractInspector()
    valid, errors = inspector.verify_contract_with_provider()
    assert valid is True, f"Contract verification failed with errors: {errors}"
    assert len(errors) == 0
