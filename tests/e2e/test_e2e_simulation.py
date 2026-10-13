"""End-to-End simulation testing the entire pipeline from game telemetry detection down to Discord IPC."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from tests.harness import (
    DiscordPipeSimulator,
    GameSessionSimulator,
    MockDiscordServer,
)

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.integrations.discord_rpc import (
    OP_FRAME,
    OP_HANDSHAKE,
    DiscordIPCClient,
    DiscordRPCManager,
)

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

    rpc_manager.update(state1, anti_spoiler=False)
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

    rpc_manager.update(state2, anti_spoiler=False)
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

    rpc_manager.update(state3, anti_spoiler=False)
    frame3 = pipe.pop_last_frame_payload()
    assert frame3 is not None
    activity3 = frame3["args"]["activity"]
    assert activity3["details"] == "Exploring"
    assert "Old Lumière (Manor Gardens)" in activity3["state"]

    # 4. Anti-Spoiler Protection Enabled
    rpc_manager.invalidate()  # Force update
    rpc_manager.update(state3, anti_spoiler=True)
    frame4 = pipe.pop_last_frame_payload()
    assert frame4 is not None
    activity4 = frame4["args"]["activity"]
    assert activity4["details"] == "Exploring"
    assert activity4["state"] == "Hidden Location"

    # 5. Game Process Terminated
    session.stop_game()
    state5 = session.get_game_state()
    assert state5.is_running is False

    rpc_manager.update(state5, anti_spoiler=False)
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
    rpc_manager.update(st1, anti_spoiler=False)
    frame1 = pipe.pop_last_frame_payload()
    assert frame1 is not None
    assert frame1["args"]["activity"]["state"] == "Title Screen"

    # 2. Transition to Exploration
    session.enter_zone("Level_Main_OldLumiere")
    st2 = session.get_game_state()
    assert st2.zone_name == "Old Lumière"
    assert st2.in_combat is False
    rpc_manager.update(st2, anti_spoiler=False)
    frame2 = pipe.pop_last_frame_payload()
    assert frame2 is not None
    assert frame2["args"]["activity"]["details"] == "Exploring"

    # 3. Enter Combat
    session.trigger_combat("Duollistes")
    st3 = session.get_game_state()
    assert st3.in_combat is True
    assert st3.enemy_name == "Duollistes"
    rpc_manager.update(st3, anti_spoiler=False)
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
    rpc_manager.update(st4, anti_spoiler=False)
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
    rpc_manager.update(st, anti_spoiler=False)
    assert pipe.pop_last_frame_payload() is not None

    # 2. Simulate Discord pipe broken / disconnect
    ipc_client.close()
    pipe.close()

    # Graceful handling - should not crash
    rpc_manager.invalidate()
    rpc_manager.update(st, anti_spoiler=False)

    # 3. Simulate Discord reconnecting with a fresh pipe
    new_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    new_client = DiscordIPCClient(client_id="123456789", transport=new_pipe)
    rpc_manager = DiscordRPCManager(client=new_client)
    assert rpc_manager.connect() is True

    new_pipe.outgoing_bytes.clear()

    rpc_manager.invalidate()
    rpc_manager.update(st, anti_spoiler=False)

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

        # 1. Initially game not running -> step_update produces no active activity
        state_idle = orchestrator.step_update()
        assert state_idle is not None
        assert state_idle.is_running is False

        # 2. Game launched into zone "Level_Main_OldLumiere" with checkpoint "Entrance"
        session.start_game(pid=7777).enter_zone("Level_Main_OldLumiere", checkpoint="Entrance")
        state_explore = orchestrator.step_update()
        assert state_explore is not None
        assert state_explore.is_running is True
        assert state_explore.zone_name == "Old Lumière"
        assert state_explore.checkpoint_name == "Entrance"

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

        # 4. Toggle Anti-Spoiler via orchestrator
        is_anti_spoiler = orchestrator.toggle_anti_spoiler()
        assert is_anti_spoiler is True
        orchestrator.step_update()
        frames_anti_spoiler = server.get_frames()
        anti_spoiler_activity = frames_anti_spoiler[-1][1]["args"]["activity"]
        assert anti_spoiler_activity["state"] == "Hidden Location"
        assert anti_spoiler_activity["details"] == "In Combat"

        # 5. Terminate game process
        session.stop_game()
        state_stopped = orchestrator.step_update()
        assert state_stopped is not None
        assert state_stopped.is_running is False

        frames_stopped = server.get_frames()
        stopped_activity = frames_stopped[-1][1]["args"]["activity"]
        assert stopped_activity is None  # Clear activity on game exit

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
