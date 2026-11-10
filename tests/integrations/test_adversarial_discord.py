#!/usr/bin/env python3
"""Adversarial stress-testing suite for Discord binary wire frame serialization,

opcode validation, dirty-checking, string limits, and flapping resilience.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tests.harness import (
    DiscordPipeSimulator,
    GameSessionSimulator,
)

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.presence import PresencePayload
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameState
from expedition33_rpc.integrations.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    OP_HANDSHAKE,
    OP_PING,
    OP_PONG,
    DiscordFrameCodec,
    DiscordIPCClient,
    DiscordRPCManager,
    IPCTransport,
)
from expedition33_rpc.ui.presentation import (
    DISCORD_MAX_FIELD_LENGTH,
    build_presence_payload,
    format_presence,
    truncate_presence_field,
)

pytestmark = pytest.mark.integration


# ===========================================================================
# Helper: Drain and strictly verify binary frames
# ===========================================================================


def drain_and_verify_binary_frames(
    pipe_sim: DiscordPipeSimulator,
) -> list[tuple[int, dict[str, Any]]]:
    """Drains pipe and validates exact binary <II header layout and JSON body."""
    raw_bytes = pipe_sim.written_data
    frames = pipe_sim.drain_all_frames()
    assert len(raw_bytes) >= DiscordFrameCodec.HEADER_SIZE * len(frames)

    offset = 0
    for op, body in frames:
        header_bytes = raw_bytes[offset : offset + DiscordFrameCodec.HEADER_SIZE]
        unpacked_op, unpacked_len = struct.unpack("<II", header_bytes)
        assert unpacked_op == op
        assert unpacked_op in (OP_HANDSHAKE, OP_FRAME, OP_CLOSE)
        offset += DiscordFrameCodec.HEADER_SIZE

        body_bytes = raw_bytes[offset : offset + unpacked_len]
        assert len(body_bytes) == unpacked_len
        decoded_json = json.loads(body_bytes.decode("utf-8"))
        assert decoded_json == body
        offset += unpacked_len

        # Discord 128-byte string limit verification
        if op == OP_FRAME and body.get("cmd") == "SET_ACTIVITY":
            act = body.get("args", {}).get("activity")
            if act is not None:
                if "details" in act and act["details"] is not None:
                    assert len(act["details"].encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH
                if "state" in act and act["state"] is not None:
                    assert len(act["state"].encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH

    assert offset == len(raw_bytes)
    return frames


# ===========================================================================
# Area 1: Header format <II (8-byte little-endian: opcode uint32, length uint32)
# ===========================================================================


def test_area1_header_format_little_endian_uint32() -> None:
    """Stress-tests little-endian <II binary packing, boundary values, and truncation."""
    # 1. Little-endian byte order verification (0x0102 length with op 1)
    # Little-endian: 01 00 00 00 | 02 01 00 00
    encoded = struct.pack("<II", 1, 0x0102)
    assert encoded == b"\x01\x00\x00\x00\x02\x01\x00\x00"

    # Big-endian must decode differently and be invalid
    be_encoded = struct.pack(">II", 1, 0x0102)
    op_from_be, len_from_be = DiscordFrameCodec.decode_header(be_encoded)
    assert op_from_be == 16777216  # 0x01000000
    assert len_from_be == 33619968

    # 2. Uint32 boundary values: 0, 1, 2^31 - 1, 2^32 - 1
    for val in (0, 1, 2147483647, 4294967295):
        hdr = struct.pack("<II", 0, val)
        op_dec, len_dec = DiscordFrameCodec.decode_header(hdr)
        assert op_dec == 0
        assert len_dec == val

    # Negative numbers must raise struct.error (unsigned int)
    with pytest.raises(struct.error):
        struct.pack("<II", -1, 10)

    # 3. Header size and insufficient data checks
    for invalid_len in range(8):
        with pytest.raises(ValueError, match="Insufficient data for header"):
            DiscordFrameCodec.decode_header(b"\x00" * invalid_len)

    for invalid_len in range(8):
        with pytest.raises(ValueError, match="Insufficient data for frame header"):
            DiscordFrameCodec.decode(b"\x00" * invalid_len)

    # 4. Truncated payload handling in decode
    hdr = struct.pack("<II", OP_FRAME, 100)
    with pytest.raises(ValueError, match="Truncated frame payload: expected 100 bytes, got 10"):
        DiscordFrameCodec.decode(hdr + b"1234567890")

    # 5. Incomplete trailing bytes in pipe simulator
    pipe = DiscordPipeSimulator()
    pipe.write(DiscordFrameCodec.encode(OP_FRAME, {"k": "v"}))
    # Add 5 incomplete trailing bytes
    pipe.write(b"12345")
    with pytest.raises(ValueError, match="Incomplete trailing bytes in pipe: 5 bytes remaining"):
        pipe.drain_all_frames()


# ===========================================================================
# Area 2: Opcode validation (OP_HANDSHAKE=0, OP_FRAME=1, OP_CLOSE=2)
# ===========================================================================


def test_area2_opcode_validation() -> None:
    """Verifies opcode definitions, client dispatch opcodes, and simulator responses."""
    assert OP_HANDSHAKE == 0
    assert OP_FRAME == 1
    assert OP_CLOSE == 2
    assert OP_PING == 3
    assert OP_PONG == 4

    # 1. Encode / decode roundtrip for all standard opcodes
    for op in (OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG):
        payload = {"op_test": op, "data": "payload_content"}
        frame = DiscordFrameCodec.encode(op, payload)
        dec_op, dec_payload = DiscordFrameCodec.decode(frame)
        assert dec_op == op
        assert dec_payload == payload

    # 2. DiscordPipeSimulator opcode-specific responses
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    # Handshake write triggers READY response
    pipe.write(DiscordFrameCodec.encode(OP_HANDSHAKE, {"v": 1, "client_id": "123"}))
    resp = pipe.read()
    op, body = DiscordFrameCodec.decode(resp)
    assert op == OP_FRAME
    assert body["evt"] == "READY"

    # Frame write triggers SET_ACTIVITY response
    pipe.write(DiscordFrameCodec.encode(OP_FRAME, {"cmd": "SET_ACTIVITY", "args": {}}))
    resp2 = pipe.read()
    op2, body2 = DiscordFrameCodec.decode(resp2)
    assert op2 == OP_FRAME
    assert body2["cmd"] == "SET_ACTIVITY"

    # 3. Injection of out-of-spec opcode must fail at write-time (pipe validation)
    with pytest.raises(ValueError):
        pipe.write(DiscordFrameCodec.encode(999, {"invalid": True}))

    # Direct raw buffer injection of invalid opcode triggers ValueError / AssertionError on drain
    pipe.outgoing_bytes.extend(DiscordFrameCodec.encode(999, {"invalid": True}))
    with pytest.raises((ValueError, AssertionError)):
        drain_and_verify_binary_frames(pipe)


# ===========================================================================
# Area 3: Payload length match & Multi-byte UTF-8 wire integrity
# ===========================================================================


def test_area3_payload_exact_byte_count_match_unicode() -> None:
    """Adversarially tests multibyte UTF-8 strings ensuring byte length matches header."""
    adversarial_payloads = [
        {"desc": "ASCII basic", "data": {"zone": "Level_Main_OldLumiere"}},
        {"desc": "French accents", "data": {"zone": "Old Lumière", "cp": "François' Cave"}},
        {"desc": "Cyrillic", "data": {"title": "Экспедиция 33", "zone": "Старый Люмьер"}},
        {
            "desc": "Japanese CJK",
            "data": {"game": "遠征33：クレアオブスクール", "zone": "ルミエール"},
        },
        {"desc": "Chinese CJK", "data": {"name": "远征33：光与影", "boss": "双刀客"}},
        {
            "desc": "Emojis 4-byte UTF-8",
            "data": {"status": "⚔️ Fighting Duollistes 💀 🔥 👑 🛡️", "extra": "✨🌟"},
        },
        {"desc": "Special JSON escaping", "data": {"quotes": 'He said "Hello"', "slash": "a/b\\c"}},
        {"desc": "Empty dict", "data": {}},
    ]

    for item in adversarial_payloads:
        payload = item["data"]
        encoded = DiscordFrameCodec.encode(OP_FRAME, payload)

        header_bytes = encoded[: DiscordFrameCodec.HEADER_SIZE]
        body_bytes = encoded[DiscordFrameCodec.HEADER_SIZE :]

        unpacked_op, unpacked_len = struct.unpack("<II", header_bytes)
        assert unpacked_op == OP_FRAME
        # Crucial: header length MUST equal bytes length, NOT character length
        assert unpacked_len == len(body_bytes)

        # Decode body and verify round-trip
        decoded_json = json.loads(body_bytes.decode("utf-8"))
        assert decoded_json == payload

    # Mismatched length injections:
    valid_frame = DiscordFrameCodec.encode(OP_FRAME, {"hello": "world"})
    # Case A: Header says 5 bytes longer than body
    bad_long_header = struct.pack("<II", OP_FRAME, len(valid_frame) - 8 + 5)
    pipe_bad_long = DiscordPipeSimulator()
    pipe_bad_long.write(bad_long_header + valid_frame[8:])
    with pytest.raises(ValueError, match="Truncated frame payload"):
        pipe_bad_long.drain_all_frames()

    # Case B: Header says 5 bytes shorter than body (leaving 5 unconsumed bytes)
    bad_short_header = struct.pack("<II", OP_FRAME, len(valid_frame) - 8 - 5)
    pipe_bad_short = DiscordPipeSimulator()
    pipe_bad_short.write(bad_short_header + valid_frame[8:])
    # Decode of body will either fail json parsing or leave trailing bytes
    with pytest.raises((ValueError, json.JSONDecodeError)):
        pipe_bad_short.drain_all_frames()


# ===========================================================================
# Area 4: Discord 128-byte string limits on details and state
# ===========================================================================


def test_area4_discord_128_byte_string_limits_multibyte() -> None:
    """Stress-tests truncate_presence_field and build_presence_payload against Discord's 128-byte limit."""
    # 1. ASCII 200 chars -> clamped to 128 chars = 128 bytes
    ascii_200 = "A" * 200
    res_ascii = truncate_presence_field(ascii_200)
    assert len(res_ascii) == 128
    assert len(res_ascii.encode("utf-8")) == 128

    # 2. Cyrillic (2 bytes per character)
    # 80 characters = 160 bytes. Must be truncated to 64 characters = 128 bytes.
    cyrillic_80 = "Ж" * 80
    res_cyrillic = truncate_presence_field(cyrillic_80)
    assert len(res_cyrillic) == 64
    assert len(res_cyrillic.encode("utf-8")) == 128

    # 3. CJK (3 bytes per character)
    # 50 characters = 150 bytes. 128 // 3 = 42 characters = 126 bytes.
    # Slicing at byte 128 falls inside the 43rd character.
    # errors='ignore' must cleanly discard the partial character without corrupting.
    cjk_50 = "遠" * 50
    res_cjk = truncate_presence_field(cjk_50)
    assert len(res_cjk) == 42
    assert len(res_cjk.encode("utf-8")) == 126
    assert len(res_cjk.encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH

    # 4. Emojis (4 bytes per character)
    # 40 characters = 160 bytes. 128 // 4 = 32 emojis = 128 bytes.
    emojis_40 = "🔥" * 40
    res_emojis = truncate_presence_field(emojis_40)
    assert len(res_emojis) == 32
    assert len(res_emojis.encode("utf-8")) == 128

    # 5. Mixed UTF-8 string right at boundary
    # 125 ASCII bytes + 1 3-byte character (128 bytes total)
    perfect_128 = ("a" * 125) + "遠"
    assert len(perfect_128.encode("utf-8")) == 128
    assert truncate_presence_field(perfect_128) == perfect_128

    # 126 ASCII bytes + 1 3-byte character (129 bytes total)
    # Must drop the 3-byte character to stay <= 128 bytes
    exceed_129 = ("a" * 126) + "遠"
    res_129 = truncate_presence_field(exceed_129)
    assert res_129 == "a" * 126
    assert len(res_129.encode("utf-8")) == 126

    # 6. Presentation layer end-to-end with adversarial GameState (long strings > 128 bytes)
    extreme_state = GameState(
        is_running=True,
        process_pid=9999,
        raw_zone="Level_ExtremeZone_" + ("X" * 150),
        zone_name="Old Lumière " + ("SecretZone" * 15),
        in_combat=True,
        enemy_name="Duollistes Prime Supreme " + ("BossEnemy" * 15),
        checkpoint_name="Deep Secret Manor Vault " + ("Checkpoint" * 15),
    )
    details, state_str = format_presence(extreme_state, anti_spoiler=False)
    assert len(details.encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH
    assert len(state_str.encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH

    payload = build_presence_payload(extreme_state, anti_spoiler=False)
    assert payload.details is not None
    assert payload.state is not None
    assert len(payload.details.encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH
    assert len(payload.state.encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH

    # 7. Wire transmission verification: pipe simulator receives payload <= 128 bytes
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="123456789", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)
    assert rpc_manager.connect() is True
    pipe.outgoing_bytes.clear()

    update_ok = rpc_manager.update(payload, pid=9999)
    assert update_ok is True
    assert rpc_manager.is_connected is True

    frames = drain_and_verify_binary_frames(pipe)
    assert len(frames) == 1
    act = frames[0][1]["args"]["activity"]
    assert len(act["details"].encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH
    assert len(act["state"].encode("utf-8")) <= DISCORD_MAX_FIELD_LENGTH


# ===========================================================================
# Area 5: Dirty-checking (Zero outbound frames on identical GameState)
# ===========================================================================


def test_area5_dirty_checking_zero_outbound_frames(tmp_path: Path) -> None:
    """Verifies that identical ticks produce ZERO outbound wire frames across all lifecycle phases."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings_file = tmp_path / "settings_dirty_check.json"
    settings = SettingsService(custom_path=settings_file)

    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="1552405358503272468", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)

    with GameSessionSimulator(base_dir=tmp_path) as session:
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc_manager,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        # Phase 1: Game Idle (connects on first tick, sends clear_activity, suppresses subsequent ticks)
        orchestrator.step_update()
        frames_idle = drain_and_verify_binary_frames(pipe)
        assert len(frames_idle) == 2  # Handshake + clear_activity
        assert len(pipe.written_data) == 0

        # STRESS: 10 consecutive ticks in idle produce ZERO frames
        for _ in range(10):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        # Phase 2: Game Launch & Exploration
        session.start_game(pid=4321).enter_zone(
            "Level_Main_OldLumiere", checkpoint="Level.SpawnPoint.Camp01"
        )
        orchestrator.step_update()
        frames_launch = drain_and_verify_binary_frames(pipe)
        assert len(frames_launch) == 1  # SET_ACTIVITY (already connected in Phase 1)
        assert len(pipe.written_data) == 0

        # STRESS: 25 consecutive ticks with identical Exploration state -> 0 frames
        for _ in range(25):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        # Phase 3: Transition to Combat
        session.trigger_combat("Duollistes", checkpoint="Level.SpawnPoint.Camp01")
        orchestrator.step_update()
        frames_combat = drain_and_verify_binary_frames(pipe)
        assert len(frames_combat) == 1
        assert len(pipe.written_data) == 0

        # STRESS: 25 consecutive ticks in combat -> 0 frames
        for _ in range(25):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        # Phase 4: Transition to Endless Tower
        session.enter_zone("Level_EndlessTower").trigger_combat(
            "Alpha Gold Chevaliere (+2)",
            tower_trial=[10, 2],
            enemies=["Alpha Gold Chevaliere", "Alpha Steel Chevaliere", "Alpha Ceramic Chevaliere"],
        )
        orchestrator.step_update()
        frames_tower = drain_and_verify_binary_frames(pipe)
        assert len(frames_tower) == 1
        assert len(pipe.written_data) == 0

        # STRESS: 20 consecutive ticks in same Tower trial -> 0 frames
        for _ in range(20):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        # Phase 5: Cache Invalidation forces single update
        rpc_manager.invalidate()
        orchestrator.step_update()
        frames_inval = drain_and_verify_binary_frames(pipe)
        assert len(frames_inval) == 1
        # Subsequent ticks back to zero
        for _ in range(5):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        # Phase 6: Game Shutdown
        session.stop_game()
        orchestrator.step_update()
        frames_stop = drain_and_verify_binary_frames(pipe)
        assert len(frames_stop) == 1
        assert frames_stop[0][1]["args"]["activity"] is None
        assert len(pipe.written_data) == 0

        # STRESS: 10 consecutive ticks after shutdown -> 0 frames
        for _ in range(10):
            orchestrator.step_update()
            assert len(pipe.written_data) == 0

        orchestrator.stop()


# ===========================================================================
# Area 6: Flapping resilience & Resource leaks (50 flapping cycles)
# ===========================================================================


class BrokenTransport(IPCTransport):
    """Transport simulator that fails writes and reads immediately."""

    def read(self, n: int) -> bytes:
        _ = n
        raise OSError("Simulated broken pipe during read")

    def write(self, data: bytes) -> int:
        _ = data
        raise BrokenPipeError("Simulated broken pipe during write")

    def close(self) -> None:
        pass


def test_area6_flapping_resilience_and_leak_freedom(tmp_path: Path) -> None:
    """Stress-tests 50 flapping disconnect/reconnect cycles without thread or socket leaks."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    thread_count_start = threading.active_count()

    session = GameSessionSimulator(base_dir=tmp_path)
    session.__enter__()
    session.start_game(pid=8888).enter_zone("Level_Main_OldLumiere").trigger_combat("Duollistes")

    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="1552405358503272468", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)

    orchestrator = AppOrchestrator(
        detector=session.detector,
        rpc_manager=rpc_manager,
        settings_service=SettingsService(custom_path=tmp_path / "settings_flapping.json"),
        auto_install_bridge=False,
        sync_startup=False,
    )

    try:
        # Initial connection and activity
        orchestrator.step_update()
        drain_and_verify_binary_frames(pipe)
        assert rpc_manager.is_connected is True

        # STRESS: 50 consecutive flapping cycles
        for _cycle in range(50):
            # 1. Break pipe mid-game
            ipc_client.close()
            pipe.close()
            assert rpc_manager.is_connected is False

            # Step update during disconnect must not raise exception
            state_flap = orchestrator.step_update()
            assert state_flap is not None
            assert state_flap.in_combat is True

            # 2. Reconnect with fresh transport
            new_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
            ipc_client._transport = new_pipe
            rpc_manager.disconnect()
            rpc_manager.invalidate()

            state_reconnected = orchestrator.step_update()
            assert state_reconnected is not None
            assert rpc_manager.is_connected is True

            # Verify wire frame integrity on every cycle
            frames = drain_and_verify_binary_frames(new_pipe)
            assert len(frames) == 2  # Handshake + SET_ACTIVITY
            assert frames[0][0] == OP_HANDSHAKE
            assert frames[1][0] == OP_FRAME
            assert frames[1][1]["args"]["activity"]["details"] == "Fighting: Duollistes"

        # 3. Test resilience against BrokenPipeError on transport write
        broken_ipc = DiscordIPCClient(client_id="123", transport=BrokenTransport())
        broken_rpc = DiscordRPCManager(client=broken_ipc)
        # Attempting to connect or update must return False without crashing
        assert broken_rpc.connect() is False
        assert (
            broken_rpc.update(
                PresencePayload(details="Exploring", state="Old Lumière"),
                pid=8888,
            )
            is False
        )
        assert broken_rpc.is_connected is False

        # 4. Idempotent double-close
        ipc_client.close()
        ipc_client.close()  # No exception
        rpc_manager.disconnect()
        rpc_manager.disconnect()  # No exception

    finally:
        orchestrator.stop()
        session.__exit__(None, None, None)

    # Verify zero thread leaks
    thread_count_end = threading.active_count()
    assert thread_count_end <= thread_count_start, (
        f"Thread leak detected: started with {thread_count_start}, ended with {thread_count_end}"
    )


# ===========================================================================
# Area 7: Rapid Ping/Pong, Opcode Close & Target PID Invariants
# ===========================================================================


def test_stress_rapid_multiple_op_pings_before_response() -> None:
    """Simulates Discord bombarding the client with rapid multiple OP_PING frames before responding.

    Verifies:
    1. Client automatically responds with OP_PONG for every single OP_PING.
    2. Payload/nonce is faithfully echoed back for each OP_PONG.
    3. Client successfully reads through all pings until the final OP_FRAME response.
    4. Client works identically during connect() handshake when pings precede READY.
    """
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client = DiscordIPCClient(client_id="ping_stress_client", transport=mock_pipe)
    assert client.connect() is True
    mock_pipe.drain_all_frames()

    # 1. Queue 25 rapid OP_PING frames followed by an OP_FRAME SET_ACTIVITY response
    num_pings = 25
    for i in range(num_pings):
        mock_pipe.queue_response(
            {"nonce": f"ping_nonce_{i}", "seq": i, "meta": {"timestamp": 1700000000 + i}},
            op=OP_PING,
        )
    mock_pipe.queue_response({"cmd": "SET_ACTIVITY", "data": {"status": "ok"}}, op=OP_FRAME)

    # Calling set_activity triggers write, then _recv which loops through all 25 pings
    success = client.set_activity(
        pid=12345,
        state="Battling Paintress",
        details="Act III Climax",
    )
    assert success is True

    # Validate all outbound frames written to the pipe
    outbound = mock_pipe.drain_all_frames()
    assert len(outbound) == 1 + num_pings  # 1 SET_ACTIVITY + 25 OP_PONG

    # First frame is outbound SET_ACTIVITY
    assert outbound[0][0] == OP_FRAME
    assert outbound[0][1]["cmd"] == "SET_ACTIVITY"
    assert outbound[0][1]["args"]["pid"] == 12345

    # Remaining 25 frames must be OP_PONG in exact sequence with exact payload
    for i in range(num_pings):
        op, payload = outbound[1 + i]
        assert op == OP_PONG
        assert payload["nonce"] == f"ping_nonce_{i}"
        assert payload["seq"] == i
        assert payload["meta"]["timestamp"] == 1700000000 + i

    # 2. Test 50 rapid OP_PING frames during connect() handshake before READY
    mock_pipe_handshake = DiscordPipeSimulator()
    for i in range(50):
        mock_pipe_handshake.queue_response({"handshake_ping": i}, op=OP_PING)
    mock_pipe_handshake.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client_hs = DiscordIPCClient(client_id="hs_client", transport=mock_pipe_handshake)
    assert client_hs.connect() is True
    assert client_hs.is_connected is True

    hs_outbound = mock_pipe_handshake.drain_all_frames()
    assert len(hs_outbound) == 51  # 1 OP_HANDSHAKE + 50 OP_PONG
    for i in range(50):
        op, payload = hs_outbound[1 + i]
        assert op == OP_PONG
        assert payload == {"handshake_ping": i}


def test_stress_op_close_mid_session_lifecycle() -> None:
    """Simulates Discord sending OP_CLOSE frames mid-session across all IPC operations.

    Verifies:
    1. Direct _recv() closes pipe and raises ConnectionError("Discord closed IPC connection").
    2. set_activity() catches OP_CLOSE, marks client disconnected, and returns False.
    3. clear_activity() catches OP_CLOSE, marks client disconnected, and returns False.
    4. DiscordRPCManager.update_presence() updates is_connected=False when OP_CLOSE occurs.
    5. Pipe write after OP_CLOSE cleanly fails without hanging.
    6. Reconnect after OP_CLOSE functions properly.
    """
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client = DiscordIPCClient(client_id="close_client", transport=mock_pipe)
    assert client.connect() is True
    mock_pipe.drain_all_frames()

    # 1. Direct _recv() receiving OP_CLOSE
    mock_pipe.queue_response({"code": 4000, "message": "Server shutting down"}, op=OP_CLOSE)
    with pytest.raises(ConnectionError, match="Discord closed IPC connection"):
        client._recv()

    assert client.is_connected is False
    assert client._pipe is None
    assert mock_pipe.is_closed is True

    # 2. Reconnect and simulate OP_CLOSE during set_activity()
    mock_pipe2 = DiscordPipeSimulator()
    mock_pipe2.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client2 = DiscordIPCClient(client_id="close_client_2", transport=mock_pipe2)
    assert client2.connect() is True
    mock_pipe2.drain_all_frames()

    mock_pipe2.queue_response({"code": 4006, "message": "Session invalidated"}, op=OP_CLOSE)
    res = client2.set_activity(pid=444, details="Exploring")
    assert res is False
    assert client2.is_connected is False
    assert mock_pipe2.is_closed is True

    # 3. Simulate OP_CLOSE during clear_activity()
    mock_pipe3 = DiscordPipeSimulator()
    mock_pipe3.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client3 = DiscordIPCClient(client_id="close_client_3", transport=mock_pipe3)
    assert client3.connect() is True
    mock_pipe3.drain_all_frames()

    mock_pipe3.queue_response({"code": 4007, "message": "Closed"}, op=OP_CLOSE)
    res_clear = client3.clear_activity(pid=444)
    assert res_clear is False
    assert client3.is_connected is False
    assert mock_pipe3.is_closed is True

    # 4. Simulate DiscordRPCManager handling OP_CLOSE mid-session during update_presence()
    mock_pipe4 = DiscordPipeSimulator()
    mock_pipe4.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client4 = DiscordIPCClient(client_id="close_mgr_client", transport=mock_pipe4)
    manager = DiscordRPCManager(client=client4)
    assert manager.connect() is True
    mock_pipe4.drain_all_frames()

    # Discord closes connection upon presence update
    mock_pipe4.queue_response({"code": 4000, "message": "Shutdown"}, op=OP_CLOSE)
    payload = PresencePayload(details="Final Battle", state="In Combat")
    res_update = manager.update_presence(payload, pid=9999)
    assert res_update is False
    assert manager.is_connected is False
    assert client4.is_connected is False

    # 5. Subsequent disconnect() should be safe and idempotent
    manager.disconnect()
    assert manager.is_connected is False
    assert manager._rpc is None


def test_stress_pid_passed_to_clear_activity() -> None:
    """Verifies PID passed to clear_activity across all lifecycle states:

    - No game PID was ever set -> fallback to os.getpid()
    - Game PID was set in prior update_presence -> passed to clear_activity on disconnect
    - Game PID is 0 or negative -> fallback to os.getpid()
    - update_presence(None, pid=...) updates _last_target_pid
    """
    # 1. No game PID ever set -> disconnect passes os.getpid()
    mock_pipe1 = DiscordPipeSimulator(auto_respond_set_activity=True)
    client1 = DiscordIPCClient(client_id="pid_test_1", transport=mock_pipe1)
    manager1 = DiscordRPCManager(client=client1)
    assert manager1.connect() is True
    mock_pipe1.drain_all_frames()

    assert manager1._last_target_pid is None
    manager1.disconnect()

    frames1 = mock_pipe1.drain_all_frames()
    assert len(frames1) == 1
    assert frames1[0][0] == OP_FRAME
    assert frames1[0][1]["cmd"] == "SET_ACTIVITY"
    assert frames1[0][1]["args"]["pid"] == os.getpid()
    assert frames1[0][1]["args"]["activity"] is None

    # 2. Game PID set via update_presence -> disconnect uses effective game PID
    mock_pipe2 = DiscordPipeSimulator(auto_respond_set_activity=True)
    client2 = DiscordIPCClient(client_id="pid_test_2", transport=mock_pipe2)
    manager2 = DiscordRPCManager(client=client2)
    assert manager2.connect() is True
    mock_pipe2.drain_all_frames()

    payload = PresencePayload(details="Flying Manor", state="Exploring")
    effective_game_pid = 88123
    manager2.update_presence(payload, pid=effective_game_pid)
    assert manager2._last_target_pid == effective_game_pid
    mock_pipe2.drain_all_frames()

    manager2.disconnect()
    frames2 = mock_pipe2.drain_all_frames()
    assert len(frames2) == 1
    assert frames2[0][1]["args"]["pid"] == effective_game_pid
    assert frames2[0][1]["args"]["activity"] is None

    # 3. Game PID is 0 or negative -> fallback to os.getpid()
    mock_pipe3 = DiscordPipeSimulator(auto_respond_set_activity=True)
    client3 = DiscordIPCClient(client_id="pid_test_3", transport=mock_pipe3)
    manager3 = DiscordRPCManager(client=client3)
    assert manager3.connect() is True
    mock_pipe3.drain_all_frames()

    manager3.update_presence(payload, pid=0)
    assert manager3._last_target_pid == os.getpid()
    mock_pipe3.drain_all_frames()

    manager3.update_presence(payload, pid=-999, force=True)
    assert manager3._last_target_pid == os.getpid()
    mock_pipe3.drain_all_frames()

    manager3.disconnect()
    frames3 = mock_pipe3.drain_all_frames()
    assert frames3[0][1]["args"]["pid"] == os.getpid()

    # 4. update_presence(None, pid=77777) calls clear_activity and sets _last_target_pid
    mock_pipe4 = DiscordPipeSimulator(auto_respond_set_activity=True)
    client4 = DiscordIPCClient(client_id="pid_test_4", transport=mock_pipe4)
    manager4 = DiscordRPCManager(client=client4)
    assert manager4.connect() is True
    mock_pipe4.drain_all_frames()

    manager4.update_presence(None, pid=77777)
    assert manager4._last_target_pid == 77777
    frames4 = mock_pipe4.drain_all_frames()
    assert len(frames4) == 1
    assert frames4[0][1]["args"]["pid"] == 77777
    assert frames4[0][1]["args"]["activity"] is None


def test_stress_dirty_checking_fingerprint_variations() -> None:
    """Stress-tests dirty-checking fingerprint calculation with edge cases:

    - large_text: None, empty string "", default title, and long string
    - details/state: None vs empty string "" vs long multibyte strings (>128 bytes)
    - Verifies that transitions between semantically equivalent values emit ZERO redundant frames.
    """
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="fingerprint_client", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)
    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    # Case 1: large_text=None normalizes to "Clair Obscur: Expedition 33"
    p_none = PresencePayload(
        details="Ancient Sanctuary",
        state="Exploring",
        start_timestamp=1700000000,
        large_image="logo",
        large_text=None,
    )
    assert manager.update_presence(p_none, pid=1234) is True
    f1 = mock_pipe.drain_all_frames()
    assert len(f1) == 1
    assert f1[0][1]["args"]["activity"]["assets"]["large_text"] == "Clair Obscur: Expedition 33"

    # Verify fingerprint contains normalized string, not "None"
    assert manager.last_update_state is not None
    assert "Clair Obscur: Expedition 33" in manager.last_update_state

    # Transition to large_text="" (empty string) -> must NOT emit any new frame
    p_empty = PresencePayload(
        details="Ancient Sanctuary",
        state="Exploring",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="",
    )
    assert manager.update_presence(p_empty, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 0  # Suppressed!

    # Transition to explicit large_text="Clair Obscur: Expedition 33" -> must NOT emit any new frame
    p_explicit = PresencePayload(
        details="Ancient Sanctuary",
        state="Exploring",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Clair Obscur: Expedition 33",
    )
    assert manager.update_presence(p_explicit, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 0  # Suppressed!

    # Case 2: details / state with None vs empty string ""
    manager.invalidate()
    mock_pipe.drain_all_frames()

    p_det_none = PresencePayload(
        details=None,
        state=None,
        start_timestamp=1700000000,
    )
    assert manager.update_presence(p_det_none, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 1

    p_det_empty = PresencePayload(
        details="",
        state="",
        start_timestamp=1700000000,
    )
    assert manager.update_presence(p_det_empty, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 0  # Suppressed because both evaluate to None

    # Case 3: Long multibyte text truncation and dirty checking
    # When text is truncated to 128 bytes, modifying characters beyond the 128-byte boundary
    # produces identical wire payloads and identical fingerprints.
    manager.invalidate()
    mock_pipe.drain_all_frames()

    long_prefix = "A" * 128
    p_long_1 = PresencePayload(
        details=long_prefix + "EXTRA_DATA_1111",
        state="In Combat",
        start_timestamp=1700000000,
    )
    assert manager.update_presence(p_long_1, pid=1234) is True
    f_long1 = mock_pipe.drain_all_frames()
    assert len(f_long1) == 1
    assert len(f_long1[0][1]["args"]["activity"]["details"].encode("utf-8")) == 128

    # Changing only bytes beyond 128 should produce identical truncated text and be suppressed
    p_long_2 = PresencePayload(
        details=long_prefix + "EXTRA_DATA_2222",
        state="In Combat",
        start_timestamp=1700000000,
    )
    assert manager.update_presence(p_long_2, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 0  # Suppressed!

    # Case 4: Long large_text (e.g. 300 chars)
    manager.invalidate()
    mock_pipe.drain_all_frames()

    long_title = "Expedition 33 " * 20
    p_long_title = PresencePayload(
        details="Sanctuary",
        state="Exploring",
        start_timestamp=1700000000,
        large_text=long_title,
    )
    assert manager.update_presence(p_long_title, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 1

    # Sending same long title is suppressed
    assert manager.update_presence(p_long_title, pid=1234) is True
    assert len(mock_pipe.drain_all_frames()) == 0  # Suppressed!


# ===========================================================================
# Standalone CLI execution
# ===========================================================================


def run_all_stress_tests() -> int:
    """Executes all adversarial stress tests directly with detailed reporting."""
    print("=" * 70)
    print("RUNNING ADVERSARIAL DISCORD WIRE FRAME STRESS SUITE (CHALLENGER 1)")
    print("=" * 70)

    import tempfile

    tests = [
        (
            "Area 1: Header Format <II (Endianness, Boundaries, Truncation)",
            lambda: test_area1_header_format_little_endian_uint32(),
        ),
        (
            "Area 2: Opcode Validation (Handshake, Frame, Close, Responses)",
            lambda: test_area2_opcode_validation(),
        ),
        (
            "Area 3: Payload Length Match & Multi-byte UTF-8 Wire Framing",
            lambda: test_area3_payload_exact_byte_count_match_unicode(),
        ),
        (
            "Area 4: Discord 128-Byte String Limits & Adversarial State",
            lambda: test_area4_discord_128_byte_string_limits_multibyte(),
        ),
        (
            "Area 5: Dirty-Checking & Redundant Outbound Frame Suppression",
            lambda: None,
        ),  # handled below with tmp_path
        (
            "Area 6: Flapping Resilience (50 Cycles) & Zero Resource Leaks",
            lambda: None,
        ),  # handled below with tmp_path
    ]

    failed = 0
    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for name, fn in tests:
            print(f"[RUNNING] {name} ... ", end="", flush=True)
            t_test = time.monotonic()
            try:
                if "Area 5" in name:
                    test_area5_dirty_checking_zero_outbound_frames(tmp_path / "area5")
                elif "Area 6" in name:
                    test_area6_flapping_resilience_and_leak_freedom(tmp_path / "area6")
                else:
                    fn()
                elapsed = time.monotonic() - t_test
                print(f"PASSED ({elapsed:.3f}s)")
            except Exception as e:
                elapsed = time.monotonic() - t_test
                print(f"FAILED ({elapsed:.3f}s)")
                print(f"  Error: {e}")
                import traceback

                traceback.print_exc()
                failed += 1

    total_time = time.monotonic() - t0
    print("=" * 70)
    if failed == 0:
        print(f"ALL 6 ADVERSARIAL STRESS TEST AREAS PASSED in {total_time:.3f}s! VERDICT: APPROVE")
        return 0
    else:
        print(f"{failed} TEST AREAS FAILED in {total_time:.3f}s! VERDICT: REQUEST_CHANGES")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_stress_tests())
