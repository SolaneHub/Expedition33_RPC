"""End-to-End simulation testing the entire pipeline from game telemetry detection down to Discord IPC."""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path
from typing import Any

import pytest
from tests.harness import (
    DiscordPipeSimulator,
    GameSessionSimulator,
    HeadlessTrayHarness,
    MockDiscordServer,
)

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.integrations.discord_rpc import (
    OP_CLOSE,
    OP_FRAME,
    OP_HANDSHAKE,
    DiscordFrameCodec,
    DiscordIPCClient,
    DiscordRPCManager,
)
from expedition33_rpc.ui.presentation import build_presence_payload
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

pytestmark = pytest.mark.integration


@pytest.fixture
def simulated_discord():
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="123456789", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)
    assert rpc_manager.connect() is True
    pipe.outgoing_bytes.clear()
    return pipe, ipc_client, rpc_manager


@pytest.fixture
def session():
    with GameSessionSimulator() as sim:
        yield sim


# ---------------------------------------------------------------------------
# E2E Simulation Scenarios
# ---------------------------------------------------------------------------


def test_full_lifecycle_simulation(session: GameSessionSimulator, simulated_discord) -> None:
    """Verifies full lifecycle: Menu -> Combat -> Victory -> Anti-Spoiler -> Process Exit."""
    pipe, _client, rpc_manager = simulated_discord

    # 1. Game Launch into Main Menu
    session.start_game().enter_zone("Level_MainMenu")
    state1 = session.get_game_state()
    assert state1.is_running is True
    assert state1.zone_name == "Main Menu"
    assert state1.in_combat is False

    rpc_manager.update(build_presence_payload(state1, anti_spoiler=False))
    frame1 = pipe.pop_last_frame_payload()
    assert frame1 is not None
    activity1 = frame1["args"]["activity"]
    assert activity1["details"] == "In Main Menu"
    assert activity1["state"] == "Title Screen"
    assert activity1["assets"]["large_image"] == "logo"

    # 2. Transition into Combat (Old Lumière vs Duollistes)
    session.enter_zone("Level_Main_OldLumiere", checkpoint="Entrance").trigger_combat("Duollistes")
    state2 = session.get_game_state()
    assert state2.is_running is True
    assert state2.in_combat is True
    assert state2.enemy_name == "Duollistes"
    assert state2.zone_name == "Old Lumière"

    rpc_manager.update(build_presence_payload(state2, anti_spoiler=False))
    frame2 = pipe.pop_last_frame_payload()
    assert frame2 is not None
    activity2 = frame2["args"]["activity"]
    assert activity2["details"] == "Fighting: Duollistes"
    assert "Old Lumière" in activity2["state"]
    assert activity2["assets"]["large_image"] == "logo"

    # 3. Victory & Exploration with Checkpoint
    session.leave_combat(checkpoint="Manor Gardens")
    state3 = session.get_game_state()
    assert state3.in_combat is False
    assert state3.checkpoint_name == "Manor Gardens"

    rpc_manager.update(build_presence_payload(state3, anti_spoiler=False))
    frame3 = pipe.pop_last_frame_payload()
    assert frame3 is not None
    activity3 = frame3["args"]["activity"]
    assert activity3["details"] == "Exploring"
    assert "Old Lumière (Manor Gardens)" in activity3["state"]

    # 4. Anti-Spoiler Protection Enabled
    rpc_manager.invalidate()  # Force update
    rpc_manager.update(build_presence_payload(state3, anti_spoiler=True))
    frame4 = pipe.pop_last_frame_payload()
    assert frame4 is not None
    activity4 = frame4["args"]["activity"]
    assert activity4["details"] == "Exploring"
    assert activity4["state"] == "Hidden Location"

    # 5. Game Process Terminated
    session.stop_game()
    state5 = session.get_game_state()
    assert state5.is_running is False

    rpc_manager.update(None)
    frame5 = pipe.pop_last_frame_payload()
    assert frame5 is not None
    assert frame5["args"]["activity"] is None


def test_timeline_menu_to_combat_and_return_to_menu(
    session: GameSessionSimulator, simulated_discord
) -> None:
    """Validates state transitions: Main Menu -> Exploration -> Combat -> Main Menu."""
    pipe, _client, rpc_manager = simulated_discord

    # 1. Main Menu
    session.start_game().enter_zone("Level_MainMenu")
    st1 = session.get_game_state()
    assert st1.is_running is True
    assert "Main Menu" in st1.zone_name
    rpc_manager.update(build_presence_payload(st1, anti_spoiler=False))
    frame1 = pipe.pop_last_frame_payload()
    assert frame1 is not None
    assert frame1["args"]["activity"]["state"] == "Title Screen"

    # 2. Transition to Exploration
    session.enter_zone("Level_Main_OldLumiere")
    st2 = session.get_game_state()
    assert st2.zone_name == "Old Lumière"
    assert st2.in_combat is False
    rpc_manager.update(build_presence_payload(st2, anti_spoiler=False))
    frame2 = pipe.pop_last_frame_payload()
    assert frame2 is not None
    assert frame2["args"]["activity"]["details"] == "Exploring"

    # 3. Enter Combat
    session.trigger_combat("Duollistes")
    st3 = session.get_game_state()
    assert st3.in_combat is True
    assert st3.enemy_name == "Duollistes"
    rpc_manager.update(build_presence_payload(st3, anti_spoiler=False))
    frame3 = pipe.pop_last_frame_payload()
    assert frame3 is not None
    assert frame3["args"]["activity"]["details"] == "Fighting: Duollistes"

    # 4. Exit to Main Menu
    session.enter_zone("Level_MainMenu")
    st4 = session.get_game_state()
    assert "Main Menu" in st4.zone_name
    assert st4.in_combat is False
    assert st4.enemy_name == ""
    assert st4.checkpoint_name == ""
    rpc_manager.update(build_presence_payload(st4, anti_spoiler=False))
    frame4 = pipe.pop_last_frame_payload()
    assert frame4 is not None
    assert frame4["args"]["activity"]["state"] == "Title Screen"


def test_timeline_death_reload_telemetry(session: GameSessionSimulator) -> None:
    """Simulates player death in combat and checkpoint reload via Bridge telemetry without process restart."""
    session.start_game()

    # 1. Initial state: exploring Old Lumière at Campfire checkpoint
    session.enter_zone("Level_Main_OldLumiere", checkpoint="Campfire")
    st1 = session.get_game_state()
    assert st1.is_running is True
    assert st1.zone_name == "Old Lumière"
    assert st1.checkpoint_name == "Campfire"

    # 2. Player enters combat and dies
    session.trigger_combat("Duollistes")
    st_combat = session.get_game_state()
    assert st_combat.in_combat is True
    assert st_combat.enemy_name == "Duollistes"

    # 3. Player reloads at Manor Gardens checkpoint
    session.leave_combat(checkpoint="Manor Gardens")
    st2 = session.get_game_state()
    assert st2.is_running is True
    assert st2.zone_name == "Old Lumière"
    assert st2.checkpoint_name == "Manor Gardens"
    assert st2.in_combat is False


def test_timeline_discord_ipc_disconnect_and_reconnect_during_gameplay(
    session: GameSessionSimulator, simulated_discord
) -> None:
    """Verifies resilience when Discord IPC disconnects mid-game and later reconnects."""
    pipe, ipc_client, rpc_manager = simulated_discord

    session.start_game().enter_zone("Level_Main_OldLumiere").trigger_combat("Duollistes")
    st = session.get_game_state()

    # 1. First update succeeds
    rpc_manager.update(build_presence_payload(st, anti_spoiler=False))
    assert pipe.pop_last_frame_payload() is not None

    # 2. Simulate Discord pipe broken / disconnect
    ipc_client.close()
    pipe.close()

    # Graceful handling - should not crash
    rpc_manager.invalidate()
    rpc_manager.update(build_presence_payload(st, anti_spoiler=False))

    # 3. Simulate Discord reconnecting with a fresh pipe
    new_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    new_client = DiscordIPCClient(client_id="123456789", transport=new_pipe)
    rpc_manager = DiscordRPCManager(client=new_client)
    assert rpc_manager.connect() is True

    new_pipe.outgoing_bytes.clear()

    rpc_manager.invalidate()
    rpc_manager.update(build_presence_payload(st, anti_spoiler=False))

    frame = new_pipe.pop_last_frame_payload()
    assert frame is not None
    assert frame["args"]["activity"]["details"] == "Fighting: Duollistes"


def test_fluent_game_session_simulation_chaining(session: GameSessionSimulator) -> None:
    """Verifies fluent chaining with GameSessionSimulator through complex state transitions."""
    # 1. Start game and explore
    session.start_game().enter_zone("Level_Main_OldLumiere", checkpoint="Entrance")
    state = session.get_game_state()
    assert state.is_running is True
    assert state.in_combat is False
    assert state.zone_name == "Old Lumière"
    assert state.checkpoint_name == "Entrance"

    # 2. Trigger combat with Boss
    session.trigger_combat("Duollistes")
    state = session.get_game_state()
    assert state.in_combat is True
    assert state.enemy_name == "Duollistes"

    # 3. Enter Endless Tower trial combat
    session.enter_zone("Level_CleasTower").trigger_combat(
        "Alpha Gold Chevaliere (+2)",
        enemies=["Alpha Gold Chevaliere", "Alpha Steel Chevaliere", "Alpha Ceramic Chevaliere"],
    )
    tower_state = session.get_game_state()
    assert tower_state.in_combat is True
    assert tower_state.tower_stage_trial == (10, 2)

    # 4. Leave combat and update checkpoint
    session.leave_combat().set_checkpoint("Level.SpawnPoint.EsquieNest.Francois")
    post_state = session.get_game_state()
    assert post_state.in_combat is False
    assert post_state.checkpoint_name == "François' Cave"

    # 5. Stop game
    session.stop_game()
    stopped_state = session.get_game_state()
    assert stopped_state.is_running is False


def test_unified_orchestrator_e2e_simulation(tmp_path: Path) -> None:
    """Verifies end-to-end integration pipeline: GameSessionSimulator -> AppOrchestrator -> MockDiscordServer.

    Connects simulated game telemetry to the real AppOrchestrator loopback-wired
    to an in-process MockDiscordServer via native named pipe/socket wire protocol.
    """
    settings_file = tmp_path / "e2e_settings.json"
    settings = SettingsService(custom_path=settings_file)

    with MockDiscordServer() as server, GameSessionSimulator() as session:
        ipc_client = DiscordIPCClient(client_id="987654321", custom_pipe_path=server.pipe_path)
        rpc_manager = DiscordRPCManager(client=ipc_client)
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc_manager,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        tray_app = ExpeditionTrayApp(orchestrator=orchestrator)
        tray_harness = HeadlessTrayHarness(menu=tray_app.create_menu())

        # 1. Initially game not running -> step_update produces no active activity
        state_idle = orchestrator.step_update()
        assert state_idle is not None
        assert state_idle.is_running is False
        idle_labels = tray_harness.get_labels()
        assert "Game: Not running" in idle_labels
        assert "Location: --" in idle_labels
        assert "Status: --" in idle_labels

        # 2. Game launched into zone "Level_Main_OldLumiere" with checkpoint "Entrance"
        session.start_game(pid=7777).enter_zone("Level_Main_OldLumiere", checkpoint="Entrance")
        state_explore = orchestrator.step_update()
        assert state_explore is not None
        assert state_explore.is_running is True
        assert state_explore.zone_name == "Old Lumière"
        assert state_explore.checkpoint_name == "Entrance"

        explore_labels = tray_harness.get_labels()
        assert "Game: Running (PID: 7777)" in explore_labels
        assert "Location: Old Lumière (Entrance)" in explore_labels
        assert "Status: Exploring" in explore_labels

        # Verify wire-level frame transmitted through MockDiscordServer
        frames = server.get_frames()
        assert len(frames) >= 2  # Handshake + SET_ACTIVITY
        handshake_op, handshake_body = frames[0]
        assert handshake_op == OP_HANDSHAKE
        assert handshake_body.get("client_id") == "987654321"

        activity_frame = frames[-1]
        assert activity_frame[0] == OP_FRAME
        assert activity_frame[1]["cmd"] == "SET_ACTIVITY"
        args = activity_frame[1]["args"]
        assert args["pid"] == 7777
        assert "Old Lumière" in args["activity"]["state"]
        assert args["activity"]["details"] == "Exploring"

        # 3. Enter combat with boss encounter
        session.trigger_combat("Duollistes")
        state_combat = orchestrator.step_update()
        assert state_combat is not None
        assert state_combat.in_combat is True
        assert state_combat.enemy_name == "Duollistes"

        frames_combat = server.get_frames()
        assert len(frames_combat) > len(frames)
        latest_activity = frames_combat[-1][1]["args"]["activity"]
        assert latest_activity["details"] == "Fighting: Duollistes"

        combat_labels = tray_harness.get_labels()
        assert "Location: Old Lumière (Entrance)" in combat_labels
        assert "Combat: Fighting Duollistes" in combat_labels

        # 4. Toggle Anti-Spoiler via orchestrator
        is_anti_spoiler = orchestrator.toggle_anti_spoiler()
        assert is_anti_spoiler is True
        orchestrator.step_update()
        frames_anti_spoiler = server.get_frames()
        anti_spoiler_activity = frames_anti_spoiler[-1][1]["args"]["activity"]
        assert anti_spoiler_activity["state"] == "Hidden Location"
        assert anti_spoiler_activity["details"] == "In Combat"

        anti_spoiler_labels = tray_harness.get_labels()
        assert "Location: [Hidden - Anti-Spoiler]" in anti_spoiler_labels
        assert "Status: In Combat" in anti_spoiler_labels
        assert "Anti-Spoiler Mode  [Enabled]" in anti_spoiler_labels

        # 5. Terminate game process
        session.stop_game()
        state_stopped = orchestrator.step_update()
        assert state_stopped is not None
        assert state_stopped.is_running is False

        frames_stopped = server.get_frames()
        stopped_activity = frames_stopped[-1][1]["args"]["activity"]
        assert stopped_activity is None  # Clear activity on game exit

        stopped_labels = tray_harness.get_labels()
        assert "Game: Not running" in stopped_labels
        assert "Location: --" in stopped_labels
        assert "Status: --" in stopped_labels

        # Clean shutdown of orchestrator
        orchestrator.stop()
        assert rpc_manager.is_connected is False


def test_bridge_heartbeat_timeout_clears_zombie_combat_presence(tmp_path: Path) -> None:
    """Verifies that stale telemetry (>5s old) expires and does not transmit zombie combat state to Discord."""
    settings_file = tmp_path / "e2e_settings.json"
    settings = SettingsService(custom_path=settings_file)

    with MockDiscordServer() as server, GameSessionSimulator() as session:
        ipc_client = DiscordIPCClient(client_id="987654321", custom_pipe_path=server.pipe_path)
        rpc_manager = DiscordRPCManager(client=ipc_client)
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc_manager,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        # 1. Start game and enter combat with Duollistes
        session.start_game(pid=5555).enter_zone("Level_Main_OldLumiere").trigger_combat(
            "Duollistes"
        )
        st_active = orchestrator.step_update()
        assert st_active is not None
        assert st_active.in_combat is True
        assert st_active.enemy_name == "Duollistes"

        # Check emitted Discord frame
        frames = server.get_frames()
        assert len(frames) >= 2
        active_activity = frames[-1][1]["args"]["activity"]
        assert active_activity["details"] == "Fighting: Duollistes"

        # 2. Overwrite telemetry file with timestamp >5s in the past (simulating game crash/freeze)
        stale_payload = {
            "timestamp": time.time() - 10.0,
            "zone": "Level_Main_OldLumiere",
            "in_combat": True,
            "enemy_name": "Duollistes",
            "checkpoint": "",
        }
        session.bridge_path.write_text(json.dumps(stale_payload), encoding="utf-8")

        # 3. Next orchestrator tick must detect stale telemetry and NOT keep fighting Duollistes
        st_stale = orchestrator.step_update()
        assert st_stale is not None
        assert st_stale.in_combat is False
        assert st_stale.enemy_name == ""

        # Verify wire-level activity sent to Discord is no longer "Fighting: Duollistes"
        frames_after = server.get_frames()
        assert len(frames_after) > len(frames)
        latest_activity = frames_after[-1][1]["args"]["activity"]
        assert latest_activity["details"] != "Fighting: Duollistes"
        assert latest_activity["details"] == "Exploring"

        orchestrator.stop()


def test_async_concurrent_orchestrator_e2e_simulation(tmp_path: Path) -> None:
    """Verifies real concurrent lifecycle where orchestrator runs asynchronously on a background worker thread."""
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="123456789", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)
    assert rpc_manager.connect() is True
    pipe.outgoing_bytes.clear()

    settings = SettingsService(custom_path=tmp_path / "settings_async_e2e.json")
    received_frames: list[dict[str, Any]] = []

    with GameSessionSimulator(base_dir=tmp_path) as session:
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc_manager,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
            polling_interval=0.05,
        )

        def poll_frames_until(predicate: Any, timeout: float = 3.0) -> dict[str, Any]:
            deadline = time.time() + timeout
            while time.time() < deadline:
                while True:
                    payload = pipe.pop_last_frame_payload()
                    if payload is None:
                        break
                    received_frames.append(payload)
                    if predicate(payload):
                        return payload
                time.sleep(0.02)
            raise TimeoutError(f"Condition not met within {timeout}s. Received: {received_frames}")

        orchestrator.start()
        assert orchestrator.running is True
        assert orchestrator.worker_thread is not None
        assert orchestrator.worker_thread.is_alive()

        try:
            # 1. Start game and explore
            session.start_game(pid=9999).enter_zone("Level_Main_OldLumiere", checkpoint="Entrance")
            frame_explore = poll_frames_until(
                lambda f: (
                    f.get("cmd") == "SET_ACTIVITY"
                    and f.get("args", {}).get("pid") == 9999
                    and "Old Lumière" in f.get("args", {}).get("activity", {}).get("state", "")
                    and f.get("args", {}).get("activity", {}).get("details") == "Exploring"
                )
            )
            assert frame_explore is not None

            # 2. Trigger combat concurrently
            session.trigger_combat("Duollistes")
            frame_combat = poll_frames_until(
                lambda f: (
                    f.get("cmd") == "SET_ACTIVITY"
                    and f.get("args", {}).get("activity", {}).get("details")
                    == "Fighting: Duollistes"
                )
            )
            assert frame_combat is not None

            # 3. Leave combat concurrently
            session.leave_combat(checkpoint="Manor Gardens")
            frame_peace = poll_frames_until(
                lambda f: (
                    f.get("cmd") == "SET_ACTIVITY"
                    and f.get("args", {}).get("activity", {}).get("details") == "Exploring"
                    and "Manor Gardens" in f.get("args", {}).get("activity", {}).get("state", "")
                )
            )
            assert frame_peace is not None

            # 4. Stop game concurrently
            session.stop_game()
            frame_stop = poll_frames_until(
                lambda f: (
                    f.get("cmd") == "SET_ACTIVITY" and f.get("args", {}).get("activity") is None
                )
            )
            assert frame_stop is not None
        finally:
            orchestrator.stop()
            assert orchestrator.running is False
            if orchestrator.worker_thread is not None:
                assert not orchestrator.worker_thread.is_alive()
            assert not rpc_manager.is_connected


# ---------------------------------------------------------------------------
# Requirement R3: Enhanced Dry-Run Lifecycle & Binary Wire Framing Integration
# ---------------------------------------------------------------------------


def _verify_binary_frames(
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

        # Schema constraint checks (Discord 128-byte string length limit)
        if op == OP_FRAME and body.get("cmd") == "SET_ACTIVITY":
            act = body.get("args", {}).get("activity")
            if act is not None:
                if "details" in act and act["details"] is not None:
                    assert len(act["details"].encode("utf-8")) <= 128
                if "state" in act and act["state"] is not None:
                    assert len(act["state"].encode("utf-8")) <= 128

    assert offset == len(raw_bytes)
    return frames


def test_dry_run_full_lifecycle_with_binary_wire_frame_verification(
    tmp_path: Path,
) -> None:
    """Verifies complete dry-run lifecycle: Launch -> Exploration -> Combat -> Tower

    -> Discord Flapping -> Shutdown, strictly verifying binary <II wire frames.
    """
    settings_file = tmp_path / "dry_run_settings.json"
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

        # -------------------------------------------------------------------
        # 1. Idle State (Game not launched)
        # -------------------------------------------------------------------
        state_idle = session.get_game_state()
        assert state_idle.is_running is False
        assert len(pipe.written_data) == 0

        # -------------------------------------------------------------------
        # 2. Game Launch & Process Detection
        # -------------------------------------------------------------------
        session.start_game(pid=8765)
        state_launch = orchestrator.step_update()
        assert state_launch is not None
        assert state_launch.is_running is True
        assert state_launch.process_pid == 8765

        frames_launch = _verify_binary_frames(pipe)
        assert len(frames_launch) == 2  # Handshake + initial presence
        assert frames_launch[0][0] == OP_HANDSHAKE
        assert frames_launch[0][1]["client_id"] == "1552405358503272468"
        assert frames_launch[1][0] == OP_FRAME
        assert frames_launch[1][1]["cmd"] == "SET_ACTIVITY"
        assert frames_launch[1][1]["args"]["pid"] == 8765

        # -------------------------------------------------------------------
        # 3. Transition: Exploration with Checkpoint
        # -------------------------------------------------------------------
        session.enter_zone("Level_Main_OldLumiere", checkpoint="Level.SpawnPoint.Camp01")
        state_explore = orchestrator.step_update()
        assert state_explore is not None
        assert state_explore.zone_name == "Old Lumière"
        assert state_explore.in_combat is False

        frames_explore = _verify_binary_frames(pipe)
        assert len(frames_explore) == 1
        explore_act = frames_explore[0][1]["args"]["activity"]
        assert explore_act["details"] == "Exploring"
        assert "Old Lumière" in explore_act["state"]

        # Dirty-checking: repeated tick without changes sends NO new frames
        orchestrator.step_update()
        assert len(pipe.written_data) == 0

        # -------------------------------------------------------------------
        # 4. Transition: Combat with Boss
        # -------------------------------------------------------------------
        session.trigger_combat("Duollistes", checkpoint="Level.SpawnPoint.Camp01")
        state_combat = orchestrator.step_update()
        assert state_combat is not None
        assert state_combat.in_combat is True
        assert state_combat.enemy_name == "Duollistes"

        frames_combat = _verify_binary_frames(pipe)
        assert len(frames_combat) == 1
        combat_act = frames_combat[0][1]["args"]["activity"]
        assert combat_act["details"] == "Fighting: Duollistes"
        assert "Old Lumière" in combat_act["state"]

        # -------------------------------------------------------------------
        # 5. Transition: Infinite Tower with Trial / Phase
        # -------------------------------------------------------------------
        session.enter_zone("Level_EndlessTower").trigger_combat(
            "Alpha Gold Chevaliere (+2)",
            tower_trial=[10, 2],
            enemies=["Alpha Gold Chevaliere", "Alpha Steel Chevaliere", "Alpha Ceramic Chevaliere"],
        )
        state_tower = orchestrator.step_update()
        assert state_tower is not None
        assert state_tower.in_combat is True
        assert state_tower.tower_stage_trial in ((10, 2), [10, 2])
        assert state_tower.zone_name == "Endless Tower"

        frames_tower = _verify_binary_frames(pipe)
        assert len(frames_tower) == 1
        tower_act = frames_tower[0][1]["args"]["activity"]
        assert "Alpha Gold Chevaliere" in tower_act["details"]
        assert "Endless Tower" in tower_act["state"]
        assert "Stage 10, Trial 2" in tower_act["state"]

        # -------------------------------------------------------------------
        # 6. Discord Flapping: Disconnect & Reconnect
        # -------------------------------------------------------------------
        # Simulate pipe breakage mid-combat
        ipc_client.close()
        pipe.close()
        assert rpc_manager.is_connected is False

        # Step update during disconnect does not crash and preserves state
        state_flap = orchestrator.step_update()
        assert state_flap is not None
        assert state_flap.in_combat is True

        # Reconnect with fresh pipe simulator
        new_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
        ipc_client._transport = new_pipe
        rpc_manager.last_retry_time = 0.0  # Bypass backoff
        rpc_manager.invalidate()

        state_reconnected = orchestrator.step_update()
        assert state_reconnected is not None
        assert rpc_manager.is_connected is True

        frames_reconnected = _verify_binary_frames(new_pipe)
        assert len(frames_reconnected) == 2  # Handshake + SET_ACTIVITY
        assert frames_reconnected[0][0] == OP_HANDSHAKE
        assert frames_reconnected[1][0] == OP_FRAME
        reconnected_act = frames_reconnected[1][1]["args"]["activity"]
        assert "Endless Tower" in reconnected_act["state"]

        # -------------------------------------------------------------------
        # 7. Game Shutdown
        # -------------------------------------------------------------------
        session.stop_game()
        state_stop = orchestrator.step_update()
        assert state_stop is not None
        assert state_stop.is_running is False

        frames_stop = _verify_binary_frames(new_pipe)
        assert len(frames_stop) == 1
        assert frames_stop[0][0] == OP_FRAME
        assert frames_stop[0][1]["args"]["activity"] is None

        orchestrator.stop()


def test_dry_run_infinite_tower_progression_binary_framing(tmp_path: Path) -> None:
    """Verifies multi-trial progression in Infinite Tower and wire encoding integrity."""
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="1552405358503272468", transport=pipe)
    rpc_manager = DiscordRPCManager(client=ipc_client)

    with GameSessionSimulator(base_dir=tmp_path) as session:
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc_manager,
            settings_service=SettingsService(custom_path=tmp_path / "settings_tower.json"),
            auto_install_bridge=False,
            sync_startup=False,
        )

        session.start_game(pid=7000).enter_zone("Level_EndlessTower")
        orchestrator.step_update()
        _verify_binary_frames(pipe)

        trials = [
            ([1, 1], "Trial 1 Mob", "Stage 1, Trial 1"),
            ([1, 2], "Trial 2 Pack", "Stage 1, Trial 2"),
            ([1, 3], "Trial 3 Elite", "Stage 1, Trial 3"),
        ]

        for trial_coord, enemy, expected_label in trials:
            session.trigger_combat(enemy, tower_trial=trial_coord)
            orchestrator.step_update()

            frames = _verify_binary_frames(pipe)
            assert len(frames) == 1
            op, payload = frames[0]
            assert op == OP_FRAME
            act = payload["args"]["activity"]
            assert expected_label in act["state"]
            assert enemy in act["details"]

        orchestrator.stop()
