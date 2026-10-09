"""End-to-End simulation testing the entire pipeline from game telemetry detection down to Discord IPC."""

from __future__ import annotations

import pytest
from tests.harness import (
    DiscordPipeSimulator,
    GameSessionSimulator,
    SaveFixtureBuilder,
)

from expedition33_rpc.integrations.discord_rpc import (
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
    session.start_game().enter_zone("Level_Bootstrap")
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

    # 2. Transition into Combat (Old Lumiere vs Duollistes)
    session.enter_zone("Level_Main_OldLumiere", checkpoint="Entrance").trigger_combat("Duollistes")
    state2 = session.get_game_state()
    assert state2.is_running is True
    assert state2.in_combat is True
    assert state2.enemy_name == "Duollistes"
    assert state2.zone_name == "Old Lumiere"

    rpc_manager.update(state2, anti_spoiler=False)
    frame2 = pipe.pop_last_frame_payload()
    assert frame2 is not None
    activity2 = frame2["args"]["activity"]
    assert activity2["details"] == "Fighting: Duollistes"
    assert "Old Lumiere" in activity2["state"]
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
    assert "Old Lumiere (Manor Gardens)" in activity3["state"]

    # 4. Anti-Spoiler Protection Enabled
    rpc_manager.last_update_state = None  # Force update
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
    assert st2.zone_name == "Old Lumiere"
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
    session.enter_zone("Level_Bootstrap")
    st4 = session.get_game_state()
    assert "Main Menu" in st4.zone_name
    assert st4.in_combat is False
    assert st4.enemy_name == ""
    assert st4.checkpoint_name == ""
    rpc_manager.update(st4, anti_spoiler=False)
    frame4 = pipe.pop_last_frame_payload()
    assert frame4 is not None
    assert frame4["args"]["activity"]["state"] == "Title Screen"


def test_timeline_death_reload_save_fallback(session: GameSessionSimulator) -> None:
    """Simulates player death and save reload via SaveFile fallback without process restart."""
    session.start_game()
    if session.bridge_path.exists():
        session.bridge_path.unlink()

    # 1. Initial save state before death
    SaveFixtureBuilder.container().with_last_map("Level_Main_OldLumiere").write_saves_container(
        session.save_dir
    )
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_Main_OldLumiere",
        spawn_point_tag="Level.SpawnPoint.Camp",
    ).write_expedition_slot(session.save_dir, slot=0, mtime=1000.0)

    st1 = session.get_game_state()
    assert st1.is_running is True
    assert st1.zone_name == "Old Lumiere"
    assert st1.checkpoint_name == "Campfire"

    # 2. Player dies and reloads an earlier/different save point (slot 1 with newer timestamp)
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_Main_OldLumiere",
        spawn_point_tag="Level.SpawnPoint.ManorGardens",
    ).write_expedition_slot(session.save_dir, slot=1, mtime=2000.0)

    st2 = session.get_game_state()
    assert st2.is_running is True
    assert st2.zone_name == "Old Lumiere"
    assert st2.checkpoint_name == "Manor Gardens"


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
    rpc_manager.last_update_state = None
    rpc_manager.update(st, anti_spoiler=False)

    # 3. Simulate Discord reconnecting with a fresh pipe
    new_pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    new_client = DiscordIPCClient(client_id="123456789", transport=new_pipe)
    rpc_manager.rpc = new_client
    rpc_manager.last_retry_time = 0.0
    assert rpc_manager.connect() is True
    new_pipe.outgoing_bytes.clear()

    rpc_manager.last_update_state = None
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
    assert state.zone_name == "Old Lumiere"
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
    assert post_state.checkpoint_name == "Francois' Cave"

    # 5. Stop game
    session.stop_game()
    stopped_state = session.get_game_state()
    assert stopped_state.is_running is False
