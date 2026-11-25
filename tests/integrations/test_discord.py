"""Verifies binary framing, handshake, activity payloads, and loopback transport for Discord IPC."""

from __future__ import annotations

import json
import logging
import os
import struct
import sys
import threading
import time
import uuid
from typing import Any

import pytest
from tests.harness import DiscordPipeSimulator, DualClockHarness, MockDiscordServer

import expedition33_rpc.core.platform as platform
from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.presence import PresencePayload
from expedition33_rpc.detection.detector import GameDetector
from expedition33_rpc.integrations.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    OP_HANDSHAKE,
    OP_PING,
    OP_PONG,
    DiscordFrameCodec,
    DiscordIPCClient,
    DiscordRPCManager,
)

# ---------------------------------------------------------------------------
# Unit Tests (Mock Pipe Simulator)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handshake_wire_protocol() -> None:
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client = DiscordIPCClient(client_id="123456789", transport=mock_pipe)
    assert client.connect() is True
    assert client.is_connected is True

    written = bytes(mock_pipe.written_data)
    out_op, out_len = struct.unpack("<II", written[:8])
    assert out_op == OP_HANDSHAKE
    out_body = json.loads(written[8 : 8 + out_len].decode("utf-8"))
    assert out_body["v"] == 1
    assert out_body["client_id"] == "123456789"


@pytest.mark.unit
def test_set_activity_wire_protocol() -> None:
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    mock_pipe.queue_response({"cmd": "SET_ACTIVITY", "data": {}})

    client = DiscordIPCClient(client_id="123456789", transport=mock_pipe)
    assert client.connect() is True
    assert client.is_connected is True

    success = client.set_activity(
        pid=9999,
        state="Exploring Old Lumiere",
        details="In Combat with Duollistes",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Expedition 33",
    )
    assert success is True

    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 2
    out_op, out_body = frames[1]
    assert out_op == OP_FRAME
    assert out_body["cmd"] == "SET_ACTIVITY"
    args = out_body["args"]
    assert args["pid"] == 9999
    assert args["activity"]["state"] == "Exploring Old Lumiere"
    assert args["activity"]["details"] == "In Combat with Duollistes"
    assert args["activity"]["timestamps"]["start"] == 1700000000


@pytest.mark.unit
def test_discord_rpc_manager_end_to_end_with_native_client() -> None:
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)

    client = DiscordIPCClient(client_id="test_client", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)
    assert manager.connect() is True
    assert manager.is_connected is True

    payload = PresencePayload(
        details="Flying Manor",
        state="Exploring",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Clair Obscur: Expedition 33",
    )

    manager.update_presence(payload, pid=5432)
    assert manager.last_update_state is not None
    assert "Flying Manor" in manager.last_update_state

    written_len_1 = len(mock_pipe.written_data)
    manager.update_presence(payload, pid=5432)
    assert len(mock_pipe.written_data) == written_len_1

    # Invalidate forces re-transmission
    manager.invalidate()
    manager.update_presence(payload, pid=5432)
    assert len(mock_pipe.written_data) > written_len_1

    # force=True forces re-transmission directly
    written_len_2 = len(mock_pipe.written_data)
    manager.update_presence(payload, pid=5432, force=True)
    assert len(mock_pipe.written_data) > written_len_2


# ---------------------------------------------------------------------------
# Integration Tests (Real Loopback IPC Transport)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_discord_ipc_loopback_handshake_and_set_activity() -> None:
    with MockDiscordServer() as server:
        client = DiscordIPCClient(client_id="test_client_123", custom_pipe_path=server.pipe_path)
        assert client.connect() is True
        assert client.is_connected is True

        frames = server.get_frames()
        assert len(frames) >= 1
        assert frames[0][0] == OP_HANDSHAKE
        assert frames[0][1]["client_id"] == "test_client_123"

        ok = client.set_activity(
            pid=4321,
            state="Exploring Old Lumiere",
            details="In Combat with Duollistes",
            start_timestamp=1700000000,
        )
        assert ok is True

        frames = server.get_frames()
        assert len(frames) == 2
        assert frames[1][0] == OP_FRAME
        assert frames[1][1]["cmd"] == "SET_ACTIVITY"
        assert frames[1][1]["args"]["pid"] == 4321
        assert frames[1][1]["args"]["activity"]["state"] == "Exploring Old Lumiere"
        assert frames[1][1]["args"]["activity"]["details"] == "In Combat with Duollistes"

        ok_clear = client.clear_activity(pid=4321)
        assert ok_clear is True

        frames = server.get_frames()
        assert len(frames) == 3
        assert frames[2][1]["cmd"] == "SET_ACTIVITY"
        assert frames[2][1]["args"]["activity"] is None

        client.close()
        assert client.is_connected is False


@pytest.mark.integration
def test_discord_ipc_loopback_reconnect_and_server_recovery() -> None:
    with MockDiscordServer() as server:
        client1 = DiscordIPCClient(client_id="client_1", custom_pipe_path=server.pipe_path)
        assert client1.connect() is True
        assert client1.set_activity(pid=111, state="Zone A", details="Exploring") is True
        client1.close()

        client2 = DiscordIPCClient(client_id="client_2", custom_pipe_path=server.pipe_path)
        assert client2.connect() is True
        assert client2.set_activity(pid=222, state="Zone B", details="Combat") is True
        client2.close()

        assert server.connection_count >= 2
        frames = server.get_frames()
        client_ids = [f[1].get("client_id") for f in frames if f[0] == OP_HANDSHAKE]
        assert "client_1" in client_ids
        assert "client_2" in client_ids


@pytest.mark.integration
def test_discord_rpc_manager_loopback_lifecycle_and_backoff() -> None:
    with MockDiscordServer() as server:
        client = DiscordIPCClient(client_id="manager_test", custom_pipe_path=server.pipe_path)
        manager = DiscordRPCManager(client=client)

        payload = PresencePayload(
            details="Flying Manor",
            state="Exploring",
            start_timestamp=1700000000,
            large_image="logo",
            large_text="Clair Obscur: Expedition 33",
        )

        manager.update_presence(payload, pid=5432)
        assert manager.is_connected is True
        assert manager.last_update_state is not None

        # Redundant update does not write extra frames
        frames_count = len(server.get_frames())
        manager.update_presence(payload, pid=5432)
        assert len(server.get_frames()) == frames_count

        # Disconnect
        manager.disconnect()
        assert manager.is_connected is False

        # Immediate connect after disconnect connects cleanly without auto-throttling
        assert manager.connect() is True
        assert manager.is_connected is True

        # Reconnect also reconnects cleanly without auto-throttling
        manager.reconnect()
        assert manager.is_connected is True
        manager.disconnect()

        # Verify backoff applies on actual connection failures
        unique_name = uuid.uuid4().hex[:12]
        bogus_path = (
            rf"\\.\pipe\nonexistent-discord-ipc-{unique_name}"
            if sys.platform == "win32"
            else f"/tmp/nonexistent-discord-ipc-{unique_name}"
        )
        fail_client = DiscordIPCClient(client_id="fail_manager", custom_pipe_path=bogus_path)
        mgr_fail = DiscordRPCManager(client=fail_client)
        assert mgr_fail.connect() is False
        assert mgr_fail.retry_failures == 1

        # Second immediate connect is throttled by backoff
        assert mgr_fail.connect() is False


@pytest.mark.integration
def test_discord_ipc_client_connect_failure_graceful() -> None:
    unique_name = uuid.uuid4().hex[:12]
    bogus_path = (
        rf"\\.\pipe\nonexistent-discord-ipc-{unique_name}"
        if sys.platform == "win32"
        else f"/tmp/nonexistent-discord-ipc-{unique_name}"
    )
    client = DiscordIPCClient(client_id="fail_client", custom_pipe_path=bogus_path)
    assert client.connect(attempts=1) is False
    assert client.is_connected is False


class ChunkedStreamMock:
    """Mock binary stream that simulates fragmented TCP / IPC packets by returning at most chunk_size bytes."""

    def __init__(self, data: bytes, chunk_size: int = 2):
        self._data = bytearray(data)
        self._chunk_size = chunk_size

    def read(self, n: int = -1) -> bytes:
        if not self._data:
            return b""
        limit = min(n if n > 0 else len(self._data), self._chunk_size, len(self._data))
        chunk = bytes(self._data[:limit])
        del self._data[:limit]
        return chunk

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        pass


@pytest.mark.unit
def test_discord_ipc_client_chunked_stream_handling() -> None:
    """Verifies that _recv and _read_exact properly assemble frames split across multiple read chunks."""
    payload = {"cmd": "DISPATCH", "evt": "READY", "data": {"user": {"username": "Gamer"}}}
    payload_bytes = json.dumps(payload).encode("utf-8")
    header = struct.pack("<II", OP_FRAME, len(payload_bytes))
    full_frame = header + payload_bytes

    # Delivery in 2-byte fragments
    stream = ChunkedStreamMock(full_frame, chunk_size=2)
    client = DiscordIPCClient(client_id="test_chunked", transport=stream)
    assert client.connect() is True
    assert client.is_connected is True


@pytest.mark.unit
def test_discord_rpc_manager_injected_client_retention() -> None:
    """Verifies that an injected custom client is retained across manager disconnect and reconnect."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    custom_client = DiscordIPCClient(client_id="retained_custom", transport=mock_pipe)

    manager = DiscordRPCManager(client=custom_client)
    assert manager.connect() is True
    assert manager.is_connected is True

    # Disconnect
    manager.disconnect()
    assert manager.is_connected is False
    assert manager.client is custom_client

    # Bypass backoff and reconnect
    manager.last_retry_time = 0.0
    # Injected client is re-used by manager.connect()
    assert manager.connect() is True
    assert manager.is_connected is True


@pytest.mark.integration
def test_discord_ipc_client_and_orchestrator_freeze_chaos() -> None:
    """Verifies that when Discord IPC server freezes, client and orchestrator disconnect cleanly without hang."""
    # 1. Test DiscordIPCClient timeout on initial handshake freeze
    with MockDiscordServer(simulate_freeze=True) as server:
        start = time.perf_counter()
        client = DiscordIPCClient(
            client_id="chaos_test",
            custom_pipe_path=server.pipe_path,
            timeout=0.02,
        )
        res = client.connect(attempts=1)
        duration = time.perf_counter() - start

        assert res is False
        assert client.is_connected is False
        assert duration < 2.0  # Must not hang or block indefinitely

    # 2. Test mid-session freeze: connected session freezes during runtime set_activity
    with MockDiscordServer(simulate_freeze=False) as server:
        active_client = DiscordIPCClient(
            client_id="chaos_test_midsession",
            custom_pipe_path=server.pipe_path,
            timeout=0.02,
        )
        manager = DiscordRPCManager(client=active_client)
        orchestrator = AppOrchestrator(
            rpc_manager=manager,
            detector=GameDetector(bridge_provider=None),
            auto_install_bridge=False,
            sync_startup=False,
        )

        assert orchestrator.rpc_manager.connect() is True
        assert orchestrator.rpc_manager.is_connected is True

        payload1 = PresencePayload(details="SafeZone", state="Exploring")
        orchestrator.rpc_manager.update_presence(payload1)
        assert orchestrator.rpc_manager.is_connected is True
        safe_fingerprint = orchestrator.rpc_manager.last_update_state
        assert safe_fingerprint is not None

        # Now simulate Discord IPC daemon deadlock / frozen named pipe
        server.simulate_freeze = True

        payload2 = PresencePayload(details="DeadlockZone", state="Exploring")
        t0 = time.perf_counter()
        orchestrator.rpc_manager.update_presence(payload2)
        freeze_duration = time.perf_counter() - t0

        assert freeze_duration < 1.0  # Finished within timeout budget
        assert orchestrator.rpc_manager.is_connected is False
        assert orchestrator.rpc_manager.is_connected is False
        # Must not falsely register the failed state2 as successfully updated
        assert orchestrator.rpc_manager.last_update_state == safe_fingerprint
        assert "DeadlockZone" not in (orchestrator.rpc_manager.last_update_state or "")


@pytest.mark.unit
def test_discord_rpc_manager_is_stopping_prevents_connect() -> None:
    """Verifies that connect() aborts immediately when is_stopping predicate reports shutdown."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="stopping_test", transport=mock_pipe)

    stopping = False
    manager = DiscordRPCManager(client=client, is_stopping=lambda: stopping)

    assert manager.connect() is True
    assert manager.is_connected is True

    # When stopping, connect returns False and does not re-establish connection
    manager.disconnect()
    stopping = True
    assert manager.connect() is False
    assert manager.is_connected is False


@pytest.mark.unit
def test_discord_rpc_manager_is_stopping_prevents_update_reconnect() -> None:
    """Verifies that update_presence() aborts without calling connect() when application is stopping."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="stopping_update_test", transport=mock_pipe)

    stopping = True
    manager = DiscordRPCManager(client=client, is_stopping=lambda: stopping)

    payload = PresencePayload(details="Old Lumiere", state="Exploring")
    # Must return False and not attempt connection when application is stopping
    res = manager.update_presence(payload)
    assert res is False
    assert manager.is_connected is False
    assert len(mock_pipe.written_data) == 0


@pytest.mark.unit
def test_orchestrator_stop_sets_stopping_and_prevents_discord_reconnect() -> None:
    """Verifies that stopping AppOrchestrator prevents Discord RPC from attempting reconnect."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="orch_stopping_test", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)

    orchestrator = AppOrchestrator(
        rpc_manager=manager,
        detector=GameDetector(bridge_provider=None),
        auto_install_bridge=False,
        sync_startup=False,
    )

    orchestrator.start()
    assert orchestrator.running is True
    orchestrator.stop()

    assert orchestrator.running is False
    assert orchestrator.worker_thread is None

    # After stop, step_update returns None and does not invoke Discord connect
    mock_pipe.outgoing_bytes.clear()
    state = orchestrator.step_update()
    assert state is None
    assert manager.is_connected is False
    assert len(mock_pipe.written_data) == 0


@pytest.mark.unit
def test_update_presence_detects_large_image_or_text_change() -> None:
    """Verifies that update_presence detects changes in large_image/large_text and sends IPC write."""
    assert not hasattr(PresencePayload, "small_image")
    assert not hasattr(PresencePayload, "small_text")

    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="presence_fp_test", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)

    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    payload1 = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Clair Obscur: Expedition 33",
    )
    res1 = manager.update_presence(payload1)
    assert res1 is True
    frames1 = mock_pipe.drain_all_frames()
    assert len(frames1) == 1
    assert frames1[0][1]["args"]["activity"]["assets"]["large_image"] == "logo"
    assert (
        frames1[0][1]["args"]["activity"]["assets"]["large_text"] == "Clair Obscur: Expedition 33"
    )

    # Same details & state, but change large_image and large_text
    payload2 = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="lumiere",
        large_text="Old Lumiere",
    )
    res2 = manager.update_presence(payload2)
    assert res2 is True
    frames2 = mock_pipe.drain_all_frames()
    assert len(frames2) == 1
    assets2 = frames2[0][1]["args"]["activity"]["assets"]
    assert assets2["large_image"] == "lumiere"
    assert assets2["large_text"] == "Old Lumiere"


@pytest.mark.unit
def test_discord_rpc_manager_exponential_backoff_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that DiscordRPCManager implements exponential backoff on repeated failures and resets on success."""
    simulated_now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: simulated_now)

    class FailingClient(DiscordIPCClient):
        def connect(self, attempts: int | None = None) -> bool:
            del attempts
            return False

    client = FailingClient(client_id="backoff_test")
    manager = DiscordRPCManager(client=client)
    assert manager.retry_failures == 0

    # 1. First attempt: proceeds immediately because last_retry_time == 0.0
    assert manager.connect() is False
    assert manager.last_retry_time == 100.0
    assert manager.retry_failures == 1

    # 2. Second attempt immediately afterwards: throttled by 5.0s (failures=1 => 5 * 2^0 = 5.0s, no jitter)
    simulated_now = 102.0
    assert manager.connect() is False
    assert manager.retry_failures == 1  # Throttled, did not execute connect()

    # Advance clock to 105.0s (5.0s elapsed)
    simulated_now = 105.0
    assert manager.connect() is False
    assert manager.retry_failures == 2
    assert manager.last_retry_time == 105.0

    # 3. Third attempt: interval is 5 * 2^1 = 10.0s (+ jitter [0, 0.5])
    simulated_now = 110.0
    assert manager.connect() is False  # Throttled because < 10.0s elapsed
    assert manager.retry_failures == 2

    simulated_now = 116.0  # > 10.5s elapsed
    assert manager.connect() is False
    assert manager.retry_failures == 3
    assert manager.last_retry_time == 116.0

    # 4. Success resets failures and last_retry_time
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    success_client = DiscordIPCClient(client_id="success", transport=mock_pipe)
    manager.client = success_client
    simulated_now = 150.0
    assert manager.connect() is True
    assert manager.retry_failures == 0
    assert manager.last_retry_time == 0.0

    # 5. Unexpected connection drop allows immediate reconnection attempt at next tick before backoff
    success_client.close()
    simulated_now = 151.0  # Only 1.0s elapsed after last connection, but retry_failures is 0
    # Simulate a failing reconnection on this immediate attempt
    manager.client = client
    assert manager.connect() is False
    assert manager.retry_failures == 1
    assert manager.last_retry_time == 151.0

    # Next attempt 1s later is throttled because retry_failures == 1
    simulated_now = 152.0
    assert manager.connect() is False
    assert manager.retry_failures == 1

    # 6. Disconnect resets failures and last_retry_time
    manager.retry_failures = 5
    manager.disconnect()
    assert manager.retry_failures == 0
    assert manager.last_retry_time == 0.0


@pytest.mark.unit
def test_rpc_manager_truncates_multibyte_utf8_fields_to_128_bytes() -> None:
    """Verifies that update_presence truncates multibyte UTF-8 fields exceeding 128 bytes safely."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="truncate_test", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)
    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    payload = PresencePayload(
        details="É" * 100,  # 200 bytes UTF-8, 100 characters
        state="🎮" * 50,  # 200 bytes UTF-8, 50 characters
        start_timestamp=1700000000,
    )
    assert manager.update_presence(payload, pid=1234) is True
    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 1
    act = frames[0][1]["args"]["activity"]
    assert len(act["details"].encode("utf-8")) <= 128
    assert len(act["state"].encode("utf-8")) <= 128


@pytest.mark.unit
def test_discord_ipc_client_handles_op_ping_with_automatic_op_pong() -> None:
    """Verifies that DiscordIPCClient automatically replies with OP_PONG containing the same payload and reads the next frame."""
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client = DiscordIPCClient(client_id="ping_test_client", transport=mock_pipe)
    assert client.connect() is True
    assert client.is_connected is True
    mock_pipe.drain_all_frames()

    # Queue an OP_PING frame followed by an OP_FRAME response
    ping_payload = {"nonce": "test_ping_nonce_12345"}
    mock_pipe.queue_response(ping_payload, op=OP_PING)
    mock_pipe.queue_response({"cmd": "SET_ACTIVITY", "data": {}}, op=OP_FRAME)

    # Calling set_activity sends OP_FRAME, then _recv reads OP_PING, responds with OP_PONG, and reads OP_FRAME
    success = client.set_activity(pid=4321, details="Testing Ping Response")
    assert success is True

    # Check the frames written to the pipe by the client
    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 2
    # Frame 1: Outbound SET_ACTIVITY
    assert frames[0][0] == OP_FRAME
    assert frames[0][1]["cmd"] == "SET_ACTIVITY"
    # Frame 2: Outbound OP_PONG echoing ping_payload
    assert frames[1][0] == OP_PONG
    assert frames[1][1] == ping_payload

    # Direct _recv() handling of OP_PING
    ping_payload_2 = {"nonce": "ping_2", "timestamp": 123456}
    mock_pipe.queue_response(ping_payload_2, op=OP_PING)
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "TEST"}, op=OP_FRAME)
    op, resp = client.read_frame()
    assert op == OP_FRAME
    assert resp == {"cmd": "DISPATCH", "evt": "TEST"}
    frames_after = mock_pipe.drain_all_frames()
    assert len(frames_after) == 1
    assert frames_after[0][0] == OP_PONG
    assert frames_after[0][1] == ping_payload_2


@pytest.mark.unit
def test_discord_ipc_client_handles_op_close_clean_closure_and_error() -> None:
    """Verifies that OP_CLOSE closes pipe, sets is_connected=False, and raises ConnectionError."""
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})

    client = DiscordIPCClient(client_id="close_test_client", transport=mock_pipe)
    assert client.connect() is True
    assert client.is_connected is True
    mock_pipe.drain_all_frames()

    # 1. Direct read_frame() handling of OP_CLOSE
    close_payload = {"code": 4000, "message": "Connection closed by Discord"}
    mock_pipe.queue_response(close_payload, op=OP_CLOSE)

    with pytest.raises(ConnectionError, match="Discord closed IPC connection"):
        client.read_frame()

    assert client.is_connected is False
    assert mock_pipe.is_closed is True

    # 2. set_activity() handling when OP_CLOSE is received
    mock_pipe2 = DiscordPipeSimulator()
    mock_pipe2.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client2 = DiscordIPCClient(client_id="close_test_client_2", transport=mock_pipe2)
    assert client2.connect() is True
    mock_pipe2.drain_all_frames()

    mock_pipe2.queue_response({"code": 4001, "message": "Closed"}, op=OP_CLOSE)
    res = client2.set_activity(pid=1234, details="Close test")
    assert res is False
    assert client2.is_connected is False
    assert mock_pipe2.is_closed is True


@pytest.mark.unit
def test_discord_rpc_manager_disconnect_uses_last_target_pid() -> None:
    """Verifies that DiscordRPCManager tracks _last_target_pid and passes it to clear_activity on disconnect()."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="pid_test_client", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)

    assert manager.last_target_pid is None
    assert manager.connect() is True

    payload = PresencePayload(
        details="Flying Manor",
        state="Exploring",
        start_timestamp=1700000000,
    )

    # 1. When update_presence is called with a specific game PID
    effective_game_pid = 77123
    manager.update_presence(payload, pid=effective_game_pid)
    assert manager.last_target_pid == effective_game_pid

    # Drain outgoing SET_ACTIVITY frames
    mock_pipe.drain_all_frames()

    # 2. Disconnect should clear activity using _last_target_pid instead of os.getpid()
    manager.disconnect()
    assert manager.is_connected is False

    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 1
    op, body = frames[0]
    assert op == OP_FRAME
    assert body["cmd"] == "SET_ACTIVITY"
    assert body["args"]["pid"] == effective_game_pid
    assert body["args"]["activity"] is None

    # 3. Fallback when disconnect() is called without prior presence update
    mock_pipe_fallback = DiscordPipeSimulator(auto_respond_set_activity=True)
    client_fallback = DiscordIPCClient(client_id="fallback_client", transport=mock_pipe_fallback)
    manager_fallback = DiscordRPCManager(client=client_fallback)
    assert manager_fallback.connect() is True
    mock_pipe_fallback.drain_all_frames()

    # Disconnect with _last_target_pid is None -> uses os.getpid()
    manager_fallback.disconnect()
    fallback_frames = mock_pipe_fallback.drain_all_frames()
    assert len(fallback_frames) == 1
    assert fallback_frames[0][1]["args"]["pid"] == os.getpid()


@pytest.mark.unit
def test_update_presence_fingerprint_dirty_checking_with_normalized_large_text() -> None:
    """Verifies that update_presence computes fingerprint using normalized large_text fallback value."""
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="dirty_check_client", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)

    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    # 1. Update with large_text=None (which normalizes to "Clair Obscur: Expedition 33")
    payload_none = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        large_text=None,
    )
    assert manager.update_presence(payload_none, pid=9999) is True

    frames1 = mock_pipe.drain_all_frames()
    assert len(frames1) == 1
    assert (
        frames1[0][1]["args"]["activity"]["assets"]["large_text"] == "Clair Obscur: Expedition 33"
    )

    # Fingerprint must contain the normalized fallback "Clair Obscur: Expedition 33", not "None"
    assert manager.last_update_state is not None
    fp_parts = manager.last_update_state.split("|")
    assert fp_parts[4] == "Clair Obscur: Expedition 33"

    # 2. Subsequent update with explicit default large_text="Clair Obscur: Expedition 33"
    # Should match fingerprint and NOT write a redundant frame to the pipe
    payload_explicit = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Clair Obscur: Expedition 33",
    )
    assert manager.update_presence(payload_explicit, pid=9999) is True
    frames2 = mock_pipe.drain_all_frames()
    assert len(frames2) == 0  # Dirty-checking suppressed redundant frame!

    # 3. Subsequent update with empty string large_text=""
    # (which also normalizes to "Clair Obscur: Expedition 33")
    payload_empty = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="",
    )
    assert manager.update_presence(payload_empty, pid=9999) is True
    frames3 = mock_pipe.drain_all_frames()
    assert len(frames3) == 0  # Dirty-checking suppressed redundant frame!

    # 4. Modifying large_text to a genuinely different string should send an update
    payload_custom = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        large_text="Custom Mission Title",
    )
    assert manager.update_presence(payload_custom, pid=9999) is True
    frames4 = mock_pipe.drain_all_frames()
    assert len(frames4) == 1
    assert frames4[0][1]["args"]["activity"]["assets"]["large_text"] == "Custom Mission Title"


@pytest.mark.integration
def test_discord_rpc_manager_reconnect_rapid_calls_without_throttling() -> None:
    """Verifies that reconnect() and connect() rapidly after disconnect() do not hit auto-throttling."""
    with MockDiscordServer() as server:
        client = DiscordIPCClient(client_id="reconnect_test", custom_pipe_path=server.pipe_path)
        manager = DiscordRPCManager(client=client)

        assert manager.connect() is True
        assert manager.is_connected is True

        # Rapid reconnect within milliseconds succeeds without hitting 5s auto-throttling
        manager.reconnect()
        assert manager.is_connected is True

        # Disconnect and immediately connect again succeeds without hitting 5s auto-throttling
        manager.disconnect()
        assert manager.is_connected is False
        assert manager.last_retry_time == 0.0

        assert manager.connect() is True
        assert manager.is_connected is True
        manager.disconnect()


@pytest.mark.unit
def test_discord_ipc_client_evt_error_rejected_on_set_and_clear_activity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifies that evt == 'ERROR' responses cause set_activity and clear_activity to log and return False."""
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    mock_pipe.queue_response(
        {"cmd": "SET_ACTIVITY", "evt": "ERROR", "data": {"code": 4000, "message": "Invalid"}},
    )
    mock_pipe.queue_response(
        {"cmd": "SET_ACTIVITY", "evt": "ERROR", "data": {"code": 4001, "message": "Denied"}},
    )

    client = DiscordIPCClient(client_id="evt_error_client", transport=mock_pipe)
    assert client.connect() is True

    with caplog.at_level(logging.ERROR):
        assert client.set_activity(pid=1234, details="Old Lumiere", state="Exploring") is False
        assert client.clear_activity(pid=1234) is False

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) >= 2


@pytest.mark.integration
def test_discord_rpc_manager_evt_error_preserves_last_update_state_and_retries() -> None:
    """Verifies that evt == 'ERROR' does not update last_update_state and allows clean retry after reconnect."""
    call_count = 0

    def handler(opcode: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        nonlocal call_count
        if opcode == OP_HANDSHAKE:
            return (OP_FRAME, {"cmd": "DISPATCH", "evt": "READY", "data": {}})
        if opcode == OP_FRAME and payload.get("cmd") == "SET_ACTIVITY":
            call_count += 1
            if call_count == 1:
                return (
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "evt": "ERROR",
                        "data": {"code": 4000, "message": "Rate limited"},
                        "nonce": payload.get("nonce"),
                    },
                )
            if call_count == 3:
                return (
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "evt": "ERROR",
                        "data": {"code": 4002, "message": "Clear failed"},
                        "nonce": payload.get("nonce"),
                    },
                )
            return (
                OP_FRAME,
                {
                    "cmd": "SET_ACTIVITY",
                    "data": payload.get("args", {}).get("activity"),
                    "evt": None,
                    "nonce": payload.get("nonce"),
                },
            )
        return None

    with MockDiscordServer(handler=handler) as server:
        client = DiscordIPCClient(client_id="evt_err_mgr", custom_pipe_path=server.pipe_path)
        manager = DiscordRPCManager(client=client)
        try:
            payload = PresencePayload(
                details="Stone Wave Cliffs", state="Exploring", start_timestamp=1700000100
            )

            # 1. First SET_ACTIVITY returns evt=ERROR -> returns False, marks disconnected, leaves last_update_state None
            assert manager.update_presence(payload, pid=4321) is False
            assert manager.is_connected is False
            assert manager.last_update_state is None

            # 2. Retry with the exact same payload -> must reconnect and actually re-send (not skipped by dirty-check)
            assert manager.update_presence(payload, pid=4321) is True
            assert manager.is_connected is True
            assert manager.last_update_state is not None
            saved_fingerprint = manager.last_update_state

            # 3. clear_activity returning evt=ERROR -> returns False, leaves last_update_state intact (not "idle")
            assert manager.update_presence(None, pid=4321) is False
            assert manager.is_connected is False
            assert manager.last_update_state == saved_fingerprint
        finally:
            manager.disconnect()
            client.close()


@pytest.mark.unit
def test_discord_rpc_manager_start_timestamp_none_dirty_checks_single_frame() -> None:
    """Verifies repeated PresencePayload(start_timestamp=None) sends exactly 1 frame across advancing epoch clock."""
    clock = DualClockHarness(initial_monotonic=1000.0, initial_epoch=1_700_000_000.0)
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(
        client_id="none_ts_client",
        transport=mock_pipe,
        monotonic_provider=clock.monotonic_clock,
    )
    manager = DiscordRPCManager(
        client=client,
        monotonic_provider=clock.monotonic_clock,
        epoch_provider=clock.epoch_clock,
    )

    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    payload = PresencePayload(details="Old Lumière", state="Exploring", start_timestamp=None)
    for step in range(10):
        assert manager.update_presence(payload, pid=4321) is True
        clock.advance(2.0 if step % 2 == 0 else 10.0)
        if step == 5:
            clock.simulate_ntp_jump(-300.0)

    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 1
    activity = frames[0][1]["args"]["activity"]
    assert activity["details"] == "Old Lumière"
    assert activity["state"] == "Exploring"
    assert "timestamps" not in activity

    # Switching to explicit start_timestamp sends a new frame with timestamps
    payload_with_ts = PresencePayload(
        details="Old Lumière", state="Exploring", start_timestamp=1700000500
    )
    assert manager.update_presence(payload_with_ts, pid=4321) is True
    ts_frames = mock_pipe.drain_all_frames()
    assert len(ts_frames) == 1
    assert ts_frames[0][1]["args"]["activity"]["timestamps"] == {"start": 1700000500}


@pytest.mark.unit
def test_discord_rpc_manager_deterministic_backoff_with_jitter_provider_and_dual_clock() -> None:
    """Verifies exact exponential backoff and cap deterministically via DualClockHarness and jitter_provider."""
    clock = DualClockHarness(initial_monotonic=1000.0, initial_epoch=1_700_000_000.0)
    jitter_calls: list[tuple[float, float]] = []

    def fixed_jitter(low: float, high: float) -> float:
        jitter_calls.append((low, high))
        return 0.25

    class FailingClient(DiscordIPCClient):
        def connect(self, attempts: int | None = None) -> bool:
            del attempts
            return False

    manager = DiscordRPCManager(
        client=FailingClient(client_id="det_backoff", monotonic_provider=clock.monotonic_clock),
        monotonic_provider=clock.monotonic_clock,
        epoch_provider=clock.epoch_clock,
        jitter_provider=fixed_jitter,
    )

    # Failure 1 at t=1000.0 (no backoff yet)
    assert manager.connect() is False
    assert manager.retry_failures == 1
    assert manager.last_retry_time == 1000.0

    # NTP backward jump must NOT alter monotonic backoff
    clock.simulate_ntp_jump(-10_000.0)

    # Failure 2 requires 5.0s (no jitter when retry_failures == 1)
    clock.advance(4.99)
    assert manager.connect() is False
    assert manager.retry_failures == 1

    clock.advance(0.01)  # t = 1005.0
    assert manager.connect() is False
    assert manager.retry_failures == 2
    assert manager.last_retry_time == 1005.0

    # Failure 3 requires 10.0 + 0.25 = 10.25s
    clock.advance(10.24)
    assert manager.connect() is False
    assert manager.retry_failures == 2

    clock.advance(0.01)  # t = 1015.25
    assert manager.connect() is False
    assert manager.retry_failures == 3
    assert manager.last_retry_time == 1015.25

    # Failure 4 requires 20.0 + 0.25 = 20.25s
    clock.advance(20.24)
    assert manager.connect() is False
    assert manager.retry_failures == 3

    clock.advance(0.01)  # t = 1035.50
    assert manager.connect() is False
    assert manager.retry_failures == 4
    assert manager.last_retry_time == 1035.50

    # Failure 5 capped at 30.0 + 0.25 = 30.25s
    clock.advance(30.24)
    assert manager.connect() is False
    assert manager.retry_failures == 4

    clock.advance(0.01)  # t = 1065.75
    assert manager.connect() is False
    assert manager.retry_failures == 5
    assert all(bounds == (0.0, 0.5) for bounds in jitter_calls)

    # Success resets failure count and last_retry_time
    clock.advance(40.0)
    ok_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    manager.client = DiscordIPCClient(
        client_id="det_ok", transport=ok_pipe, monotonic_provider=clock.monotonic_clock
    )
    assert manager.connect() is True
    assert manager.retry_failures == 0
    assert manager.last_retry_time == 0.0


@pytest.mark.unit
def test_discord_rpc_manager_forwards_monotonic_provider_to_default_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies DiscordRPCManager forwards monotonic_provider to every default DiscordIPCClient it creates."""
    clock = DualClockHarness()
    mono = clock.monotonic_clock
    manager = DiscordRPCManager(monotonic_provider=mono)
    assert manager.client.monotonic_provider is mono

    manager.client = None
    assert manager.client.monotonic_provider is mono

    def fail_open(_path: str, timeout: float = 5.0) -> Any:
        del timeout
        raise FileNotFoundError("no pipe")

    monkeypatch.setattr(platform, "open_discord_pipe", fail_open)
    assert manager.connect() is False
    assert manager.client.monotonic_provider is mono

    manager.disconnect()
    assert manager.client.monotonic_provider is mono


@pytest.mark.unit
def test_discord_ipc_client_connect_routes_through_platform_open_discord_pipe_posix_and_win32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies DiscordIPCClient.connect() routes through platform.open_discord_pipe() on POSIX and Win32 paths."""
    opened_calls: list[tuple[str, float]] = []

    class FakeSocket:
        def __init__(self, stream: DiscordPipeSimulator) -> None:
            self.stream = stream
            self.makefile_args: list[tuple[str, int]] = []
            self.closed = False

        def makefile(self, mode: str, buffering: int = -1) -> DiscordPipeSimulator:
            self.makefile_args.append((mode, buffering))
            return self.stream

        def close(self) -> None:
            self.closed = True

    # 1. POSIX socket path (object exposing .makefile)
    posix_stream = DiscordPipeSimulator(auto_respond_set_activity=True)
    fake_sock = FakeSocket(posix_stream)

    def fake_open_posix(path: str, timeout: float = 5.0) -> FakeSocket:
        opened_calls.append((path, timeout))
        return fake_sock

    monkeypatch.setattr(platform, "open_discord_pipe", fake_open_posix)
    client_posix = DiscordIPCClient(
        client_id="posix_route", custom_pipe_path="/tmp/fake-discord-ipc-0", timeout=1.5
    )
    assert client_posix.connect(attempts=1) is True
    assert client_posix.is_connected is True
    assert opened_calls == [("/tmp/fake-discord-ipc-0", 1.5)]
    assert fake_sock.makefile_args == [("rwb", 0)]

    client_posix.close()
    assert posix_stream.is_closed is True
    assert fake_sock.closed is True

    # 2. Win32 file-like path (object WITHOUT .makefile)
    opened_calls.clear()
    win32_stream = DiscordPipeSimulator(auto_respond_set_activity=True)

    def fake_open_win32(path: str, timeout: float = 5.0) -> DiscordPipeSimulator:
        opened_calls.append((path, timeout))
        return win32_stream

    monkeypatch.setattr(platform, "open_discord_pipe", fake_open_win32)
    client_win32 = DiscordIPCClient(
        client_id="win32_route", custom_pipe_path=r"\\.\pipe\fake-discord-ipc-0", timeout=2.5
    )
    assert client_win32.connect(attempts=1) is True
    assert client_win32.is_connected is True
    assert opened_calls == [(r"\\.\pipe\fake-discord-ipc-0", 2.5)]

    client_win32.close()
    assert win32_stream.is_closed is True


@pytest.mark.unit
def test_discord_ipc_client_deterministic_timeout_via_monotonic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies DiscordIPCClient._read_exact passes monotonic_provider and times out deterministically."""
    clock = DualClockHarness(initial_monotonic=500.0)
    peek_providers: list[Any] = []

    def fake_peek(_pipe: Any, timeout: float = 0.0, monotonic_provider: Any = None) -> bool:
        del timeout
        peek_providers.append(monotonic_provider)
        return True

    monkeypatch.setattr(platform, "peek_named_pipe_ready", fake_peek)

    ready_frame = DiscordFrameCodec.encode(
        OP_FRAME, {"cmd": "DISPATCH", "evt": "READY", "data": {}}
    )
    # After handshake succeeds, next frame is delivered 1 byte at a time and each read advances clock by 0.4s
    slow_frame = DiscordFrameCodec.encode(OP_FRAME, {"cmd": "SET_ACTIVITY", "data": {}})

    class SlowChunkTransport:
        def __init__(self) -> None:
            self._buf = bytearray(ready_frame + slow_frame)
            self._advance_clock = False

        def write(self, data: bytes) -> int:
            return len(data)

        def read(self, n: int = -1) -> bytes:
            if not self._advance_clock:
                take = min(n if n > 0 else len(ready_frame), len(self._buf))
                out = bytes(self._buf[:take])
                del self._buf[:take]
                if len(self._buf) <= len(slow_frame):
                    self._advance_clock = True
                return out
            clock.advance(0.4)
            out = bytes(self._buf[:1])
            del self._buf[:1]
            return out

        def close(self) -> None:
            pass

    mono = clock.monotonic_clock
    client = DiscordIPCClient(
        client_id="timeout_client",
        transport=SlowChunkTransport(),
        timeout=1.0,
        monotonic_provider=mono,
    )
    assert client.connect() is True
    assert all(p is mono for p in peek_providers)

    with pytest.raises(TimeoutError, match="timed out after 1.0s"):
        client.read_frame()


@pytest.mark.integration
def test_discord_ipc_client_evt_error_closes_real_handle_immediately_without_gc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies evt == 'ERROR' explicitly closes real OS handles before reconnect without relying on GC."""
    call_count = 0

    def handler(opcode: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
        nonlocal call_count
        if opcode == OP_HANDSHAKE:
            return (OP_FRAME, {"cmd": "DISPATCH", "evt": "READY", "data": {}})
        if opcode == OP_FRAME and payload.get("cmd") == "SET_ACTIVITY":
            call_count += 1
            if call_count in (1, 3):
                return (
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "evt": "ERROR",
                        "data": {"code": 4000, "message": "Rejected"},
                        "nonce": payload.get("nonce"),
                    },
                )
            return (
                OP_FRAME,
                {
                    "cmd": "SET_ACTIVITY",
                    "data": payload.get("args", {}).get("activity"),
                    "evt": None,
                    "nonce": payload.get("nonce"),
                },
            )
        return None

    real_open = platform.open_discord_pipe
    opened_proxies: list[Any] = []
    explicit_close_flags: list[bool] = []

    class NonGCCloseProxy:
        """Wraps a real socket/handle and records explicit close() without closing in __del__."""

        def __init__(self, inner: Any, idx: int) -> None:
            self._inner = inner
            self._idx = idx

        def read(self, n: int = -1) -> bytes:
            return bytes(self._inner.read(n))

        def write(self, data: bytes) -> int:
            return int(self._inner.write(data))

        def close(self) -> None:
            explicit_close_flags[self._idx] = True
            self._inner.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    def tracked_open(path: str, timeout: float = 5.0) -> Any:
        inner = real_open(path, timeout=timeout)
        idx = len(explicit_close_flags)
        explicit_close_flags.append(False)
        proxy = NonGCCloseProxy(inner, idx)
        opened_proxies.append(proxy)
        return proxy

    monkeypatch.setattr(platform, "open_discord_pipe", tracked_open)

    with MockDiscordServer(handler=handler) as server:
        client = DiscordIPCClient(client_id="evt_err_no_gc", custom_pipe_path=server.pipe_path)
        manager = DiscordRPCManager(client=client)
        payload = PresencePayload(details="Forgotten Battlefield", state="Exploring")
        try:
            # 1. SET_ACTIVITY returns evt=ERROR -> socket 0 must be explicitly closed immediately
            assert manager.update_presence(payload, pid=4321) is False
            assert manager.is_connected is False
            assert len(explicit_close_flags) == 1
            assert explicit_close_flags[0] is True

            # 2. Retry succeeds immediately without hanging on unclosed socket 0
            assert manager.update_presence(payload, pid=4321) is True
            assert manager.is_connected is True
            assert len(explicit_close_flags) == 2
            assert explicit_close_flags[1] is False

            # 3. clear_activity returns evt=ERROR -> socket 1 must be explicitly closed immediately
            assert manager.update_presence(None, pid=4321) is False
            assert manager.is_connected is False
            assert explicit_close_flags[1] is True
        finally:
            manager.disconnect()
            client.close()
            for proxy in opened_proxies:
                proxy.close()


@pytest.mark.unit
def test_discord_ipc_client_connect_precloses_stale_handle_and_manager_closes_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies connect() pre-closes stale handles in real-pipe branch and manager closes client on error."""

    class StaleHandle:
        def __init__(self) -> None:
            self.closed = False

        def read(self, n: int = 1024) -> bytes:
            del n
            return b""

        def write(self, data: bytes) -> int:
            return len(data)

        def close(self) -> None:
            self.closed = True

    stale_pipe = StaleHandle()
    stale_sock = StaleHandle()
    fresh_stream = DiscordPipeSimulator(auto_respond_set_activity=True)

    def fake_open_pipe(_path: str, timeout: float = 5.0) -> DiscordPipeSimulator:
        del timeout
        return fresh_stream

    monkeypatch.setattr(platform, "open_discord_pipe", fake_open_pipe)

    client = DiscordIPCClient(client_id="preclose_test", custom_pipe_path="/tmp/fake-ipc-0")
    client._pipe = stale_pipe
    client._sock = stale_sock
    client.is_connected = False

    assert client.connect(attempts=1) is True
    assert stale_pipe.closed is True
    assert stale_sock.closed is True
    client.close()
    assert fresh_stream.is_closed is True

    # Also verify DiscordRPCManager.connect() closes non-injected client if connect() raises unexpectedly
    closed_clients: list[bool] = []

    class ExplodingClient(DiscordIPCClient):
        def connect(self, attempts: int | None = None) -> bool:
            del attempts
            raise RuntimeError("Unexpected transport explosion")

        def close(self) -> None:
            closed_clients.append(True)
            super().close()

    monkeypatch.setattr(
        "expedition33_rpc.integrations.discord_rpc.DiscordIPCClient",
        ExplodingClient,
    )
    manager = DiscordRPCManager()
    assert manager.connect() is False
    # Closed at least twice: previous client before creating new_client, and new_client on exception
    assert len(closed_clients) >= 2


@pytest.mark.integration
def test_discord_rpc_manager_concurrent_connect_zero_fd_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies concurrent DiscordRPCManager.connect() calls serialize cleanly with zero leaked FDs."""
    real_open = platform.open_discord_pipe
    opened_handles: list[Any] = []
    handles_lock = threading.Lock()

    def slow_tracked_open(path: str, timeout: float = 5.0) -> Any:
        time.sleep(0.02)
        handle = real_open(path, timeout=timeout)
        with handles_lock:
            opened_handles.append(handle)
        return handle

    monkeypatch.setattr(platform, "open_discord_pipe", slow_tracked_open)

    with MockDiscordServer() as server:
        # Use custom_pipe_path on an injected client OR patch _candidate_pipe_paths on default clients.
        monkeypatch.setattr(
            DiscordIPCClient,
            "_candidate_pipe_paths",
            lambda _self: [server.pipe_path],
        )
        manager = DiscordRPCManager()
        num_threads = 4
        barrier = threading.Barrier(num_threads)
        results: list[bool] = []
        errors: list[Exception] = []
        res_lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait()
                ok = manager.connect()
                with res_lock:
                    results.append(ok)
            except Exception as exc:
                with res_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

            assert errors == []
            assert all(r is True for r in results)
            assert manager.is_connected is True
            assert len(opened_handles) == 1
        finally:
            manager.disconnect()

        for handle in opened_handles:
            if getattr(handle, "closed", False):
                continue
            if hasattr(handle, "fileno"):
                assert handle.fileno() == -1


@pytest.mark.unit
def test_discord_rpc_manager_concurrent_update_presence_none_ts_and_disconnect_race() -> None:
    """Verifies concurrent update_presence(start_timestamp=None) and update_presence/disconnect races."""
    # Part A: 8 threads concurrently calling update_presence(start_timestamp=None) send exactly 1 frame
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="conc_none_ts", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)
    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    payload = PresencePayload(details="Old Lumière", state="Exploring", start_timestamp=None)
    num_threads = 8
    barrier = threading.Barrier(num_threads)
    errors: list[Exception] = []

    def update_worker() -> None:
        try:
            barrier.wait()
            assert manager.update_presence(payload, pid=4321) is True
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=update_worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    frames = mock_pipe.drain_all_frames()
    assert len(frames) == 1
    assert "timestamps" not in frames[0][1]["args"]["activity"]

    # Part B: Concurrent update_presence() paused mid-write vs disconnect() must not poison last_update_state
    write_entered = threading.Event()
    allow_resume = threading.Event()

    class SlowWritePipe(DiscordPipeSimulator):
        def __init__(self) -> None:
            super().__init__(auto_respond_set_activity=True)
            self.pause_next_set_activity = False

        def write(self, data: bytes) -> int:
            if self.pause_next_set_activity:
                self.pause_next_set_activity = False
                write_entered.set()
                allow_resume.wait(timeout=5.0)
            return super().write(data)

    slow_pipe = SlowWritePipe()
    slow_client = DiscordIPCClient(client_id="conc_disc_race", transport=slow_pipe)
    race_mgr = DiscordRPCManager(client=slow_client)
    assert race_mgr.connect() is True
    slow_pipe.drain_all_frames()

    slow_pipe.pause_next_set_activity = True
    race_payload = PresencePayload(details="Lumière", state="Exploring", start_timestamp=None)
    race_errors: list[Exception] = []

    def run_update() -> None:
        try:
            race_mgr.update_presence(race_payload, pid=999)
        except Exception as exc:
            race_errors.append(exc)

    def run_disconnect() -> None:
        try:
            race_mgr.disconnect()
        except Exception as exc:
            race_errors.append(exc)

    t_upd = threading.Thread(target=run_update)
    t_upd.start()
    assert write_entered.wait(timeout=2.0)

    t_disc = threading.Thread(target=run_disconnect)
    t_disc.start()
    allow_resume.set()

    t_upd.join(timeout=5.0)
    t_disc.join(timeout=5.0)

    assert race_errors == []
    assert race_mgr.is_connected is False
    assert race_mgr.last_update_state is None

    # Reconnect and send exact same payload -> MUST send 1 SET_ACTIVITY frame (never dropped as 0)
    slow_pipe.drain_all_frames()
    assert race_mgr.connect() is True
    slow_pipe.drain_all_frames()  # discard handshake
    assert race_mgr.update_presence(race_payload, pid=999) is True
    after_reconnect_frames = slow_pipe.drain_all_frames()
    assert len(after_reconnect_frames) == 1
    assert after_reconnect_frames[0][0] == OP_FRAME
    assert after_reconnect_frames[0][1]["cmd"] == "SET_ACTIVITY"


@pytest.mark.unit
def test_discord_frame_codec_rejects_oversized_frame_without_oom() -> None:
    """Verifies frames with length > MAX_FRAME_LENGTH are rejected before allocating payload memory."""

    class OversizedHeaderPipe(DiscordPipeSimulator):
        def __init__(self) -> None:
            super().__init__()
            self.inject_oversized = False

        def read(self, n: int = 1024) -> bytes:
            if self.inject_oversized and n == 8:
                self.inject_oversized = False
                return struct.pack("<II", OP_FRAME, DiscordFrameCodec.MAX_FRAME_LENGTH + 1)
            return super().read(n)

    mock_pipe = OversizedHeaderPipe()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client = DiscordIPCClient(client_id="123456789", transport=mock_pipe)
    assert client.connect() is True
    mock_pipe.drain_all_frames()

    mock_pipe.inject_oversized = True
    assert client.set_activity(1234, state="test") is False


@pytest.mark.unit
def test_discord_rpc_manager_handles_error_event_without_polluting_cache() -> None:
    """Verifies Discord evt=ERROR response causes update_presence to return False without caching."""
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client = DiscordIPCClient(client_id="123456789", transport=mock_pipe)
    manager = DiscordRPCManager(client=client)
    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    mock_pipe.queue_response(
        {"cmd": "SET_ACTIVITY", "evt": "ERROR", "data": {"code": 4000, "message": "Invalid"}}
    )
    payload = PresencePayload(details="Lumière", state="Exploring", start_timestamp=None)
    assert manager.update_presence(payload, pid=1234) is False
    assert manager.last_update_state is None


@pytest.mark.unit
def test_discord_rpc_manager_dirty_check_with_none_start_timestamp_across_advancing_epoch() -> None:
    """Verifies dirty-check suppresses duplicate frames when start_timestamp is None as epoch advances."""
    clock = DualClockHarness(initial_epoch=1000.0)
    mock_pipe = DiscordPipeSimulator()
    mock_pipe.queue_response({"cmd": "DISPATCH", "evt": "READY", "data": {}})
    client = DiscordIPCClient(client_id="123456789", transport=mock_pipe)
    manager = DiscordRPCManager(client=client, epoch_provider=lambda: clock.epoch)
    assert manager.connect() is True
    mock_pipe.drain_all_frames()

    payload = PresencePayload(details="Lumière", state="Exploring", start_timestamp=None)
    for _ in range(5):
        manager.update_presence(payload, pid=1234)
        clock.advance(10.0)

    frames = mock_pipe.drain_all_frames()
    set_activity_frames = [
        f for f in frames if f[0] == OP_FRAME and f[1].get("cmd") == "SET_ACTIVITY"
    ]
    assert len(set_activity_frames) == 1
