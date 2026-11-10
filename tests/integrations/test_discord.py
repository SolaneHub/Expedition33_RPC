"""Verifies binary framing, handshake, activity payloads, and loopback transport for Discord IPC."""

from __future__ import annotations

import json
import os
import struct
import sys
import time
import uuid

import pytest
from tests.harness import DiscordPipeSimulator, MockDiscordServer

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.presence import PresencePayload
from expedition33_rpc.detection.detector import GameDetector
from expedition33_rpc.integrations.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    OP_HANDSHAKE,
    OP_PING,
    OP_PONG,
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

    manager.update(payload, pid=5432)
    assert manager.last_update_state is not None
    assert "Flying Manor" in manager.last_update_state

    written_len_1 = len(mock_pipe.written_data)
    manager.update(payload, pid=5432)
    assert len(mock_pipe.written_data) == written_len_1

    # Invalidate forces re-transmission
    manager.invalidate()
    manager.update(payload, pid=5432)
    assert len(mock_pipe.written_data) > written_len_1

    # force=True forces re-transmission directly
    written_len_2 = len(mock_pipe.written_data)
    manager.update(payload, pid=5432, force=True)
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

        manager.update(payload, pid=5432)
        assert manager.is_connected is True
        assert manager.last_update_state is not None

        # Redundant update does not write extra frames
        frames_count = len(server.get_frames())
        manager.update(payload, pid=5432)
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
        assert mgr_fail._retry_failures == 1

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
    assert manager.rpc is None

    # Bypass backoff and reconnect
    manager.last_retry_time = 0.0
    # Injected client is re-used by manager.connect()
    assert manager.connect() is True
    assert manager.is_connected is True
    assert manager.rpc is custom_client


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
        assert orchestrator.is_rpc_connected() is True

        payload1 = PresencePayload(details="SafeZone", state="Exploring")
        orchestrator.rpc_manager.update(payload1)
        assert orchestrator.is_rpc_connected() is True
        safe_fingerprint = orchestrator.rpc_manager.last_update_state
        assert safe_fingerprint is not None

        # Now simulate Discord IPC daemon deadlock / frozen named pipe
        server.simulate_freeze = True

        payload2 = PresencePayload(details="DeadlockZone", state="Exploring")
        t0 = time.perf_counter()
        orchestrator.rpc_manager.update(payload2)
        freeze_duration = time.perf_counter() - t0

        assert freeze_duration < 1.0  # Finished within timeout budget
        assert orchestrator.is_rpc_connected() is False
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
def test_update_presence_detects_small_image_or_text_change() -> None:
    """Verifies that update_presence detects changes in small_image/small_text and sends IPC write."""
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
        small_image="combat",
        small_text="In Combat",
    )
    res1 = manager.update_presence(payload1)
    assert res1 is True
    frames1 = mock_pipe.drain_all_frames()
    assert len(frames1) == 1
    assert frames1[0][1]["args"]["activity"]["assets"]["small_image"] == "combat"
    assert frames1[0][1]["args"]["activity"]["assets"]["small_text"] == "In Combat"

    # Same details & state, but change small_image and small_text
    payload2 = PresencePayload(
        details="Exploring Old Lumiere",
        state="In Combat",
        start_timestamp=1700000000,
        large_image="logo",
        small_image="",
        small_text="",
    )
    res2 = manager.update_presence(payload2)
    assert res2 is True
    frames2 = mock_pipe.drain_all_frames()
    assert len(frames2) == 1
    assets2 = frames2[0][1]["args"]["activity"]["assets"]
    assert assets2.get("small_image") is None or assets2.get("small_image") == ""
    assert assets2.get("small_text") is None or assets2.get("small_text") == ""


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
    assert manager._retry_failures == 0

    # 1. First attempt: proceeds immediately because last_retry_time == 0.0
    assert manager.connect() is False
    assert manager.last_retry_time == 100.0
    assert manager._retry_failures == 1

    # 2. Second attempt immediately afterwards: throttled by 5.0s (failures=1 => 5 * 2^0 = 5.0s, no jitter)
    simulated_now = 102.0
    assert manager.connect() is False
    assert manager._retry_failures == 1  # Throttled, did not execute connect()

    # Advance clock to 105.0s (5.0s elapsed)
    simulated_now = 105.0
    assert manager.connect() is False
    assert manager._retry_failures == 2
    assert manager.last_retry_time == 105.0

    # 3. Third attempt: interval is 5 * 2^1 = 10.0s (+ jitter [0, 0.5])
    simulated_now = 110.0
    assert manager.connect() is False  # Throttled because < 10.0s elapsed
    assert manager._retry_failures == 2

    simulated_now = 116.0  # > 10.5s elapsed
    assert manager.connect() is False
    assert manager._retry_failures == 3
    assert manager.last_retry_time == 116.0

    # 4. Success resets failures
    mock_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    success_client = DiscordIPCClient(client_id="success", transport=mock_pipe)
    manager._client = success_client
    manager._rpc = success_client
    simulated_now = 150.0
    assert manager.connect() is True
    assert manager._retry_failures == 0

    # 5. Disconnect resets failures
    manager._retry_failures = 5
    manager.disconnect()
    assert manager._retry_failures == 0


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
    op, resp = client._recv()
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

    # 1. Direct _recv() handling of OP_CLOSE
    close_payload = {"code": 4000, "message": "Connection closed by Discord"}
    mock_pipe.queue_response(close_payload, op=OP_CLOSE)

    with pytest.raises(ConnectionError, match="Discord closed IPC connection"):
        client._recv()

    assert client.is_connected is False
    assert client._pipe is None
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

    assert manager._last_target_pid is None
    assert manager.connect() is True

    payload = PresencePayload(
        details="Flying Manor",
        state="Exploring",
        start_timestamp=1700000000,
    )

    # 1. When update_presence is called with a specific game PID
    effective_game_pid = 77123
    manager.update_presence(payload, pid=effective_game_pid)
    assert manager._last_target_pid == effective_game_pid

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
