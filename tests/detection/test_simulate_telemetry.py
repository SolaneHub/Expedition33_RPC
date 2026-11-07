"""Unit tests for tools/simulate_telemetry.py developer CLI tool."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tools.simulate_telemetry import SCENARIOS, main, play_scenario, write_telemetry

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.detection.detector import BridgeStateProvider, GameDetector


@pytest.mark.unit
def test_write_telemetry_atomic_and_schema(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_Main_OldLumiere",
        in_combat=True,
        enemy_name="Duollistes",
        floor=12,
        checkpoint="Gate",
    )

    assert target_file.is_file()
    read_data = json.loads(target_file.read_text(encoding="utf-8"))

    assert read_data["zone"] == "Level_Main_OldLumiere"
    assert read_data["in_combat"] is True
    assert read_data["enemy_name"] == "Duollistes"
    assert read_data["floor"] == 12
    assert read_data["checkpoint"] == "Gate"
    assert "timestamp" in read_data
    assert read_data["timestamp"] == payload["timestamp"]


@pytest.mark.unit
def test_write_telemetry_non_combat_clears_enemy(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_Sirene_Main_V2",
        in_combat=False,
        enemy_name="Duollistes",
    )

    assert target_file.is_file()
    assert payload["in_combat"] is False
    assert payload["enemy_name"] == ""
    assert payload["enemies"] == []


@pytest.mark.unit
def test_write_telemetry_with_explicit_enemies(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    enemies = ["Alpha Francois", "Duollistes"]
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_EndlessTower",
        in_combat=True,
        enemy_name="Alpha Francois, Duollistes",
        floor=5,
        enemies=enemies,
    )

    assert target_file.is_file()
    read_data = json.loads(target_file.read_text(encoding="utf-8"))
    assert read_data["enemies"] == enemies
    assert read_data["enemies"] == payload["enemies"]
    assert read_data["floor"] == 5
    assert read_data["in_combat"] is True


@pytest.mark.unit
def test_simulate_telemetry_cli_main_write(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Custom_Abyss",
        "--combat",
        "--enemy",
        "AbyssWatcher",
        "--enemies",
        "AbyssWatcher",
        "Phantom",
        "--floor",
        "99",
        "--checkpoint",
        "Sanctum",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Custom_Abyss"
    assert data["in_combat"] is True
    assert data["enemy_name"] == "AbyssWatcher"
    assert data["enemies"] == ["AbyssWatcher", "Phantom"]
    assert data["floor"] == 99
    assert data["checkpoint"] == "Sanctum"


@pytest.mark.unit
def test_simulate_telemetry_cli_main_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target_file = tmp_path / "expedition33_status.json"
    target_file.write_text("{}", encoding="utf-8")
    assert target_file.exists()

    cli_args = ["simulate_telemetry.py", "--clean", "--path", str(target_file)]
    with patch("sys.argv", cli_args):
        main()

    assert not target_file.exists()
    out = capsys.readouterr().out
    assert "Removed telemetry file" in out

    # Test clean on non-existent file
    with patch("sys.argv", cli_args):
        main()
    out_missing = capsys.readouterr().out
    assert "does not exist" in out_missing


@pytest.mark.unit
def test_simulate_telemetry_cli_non_combat(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Sirene_Hub",
        "--enemy",
        "IgnoreMe",
        "--checkpoint",
        "Camp",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Sirene_Hub"
    assert data["in_combat"] is False
    assert data["enemy_name"] == ""
    assert data["enemies"] == []
    assert data["checkpoint"] == "Camp"


@pytest.mark.unit
def test_simulate_telemetry_cli_loop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Loop_Test",
        "--loop",
        "--interval",
        "0.1",
        "--path",
        str(target_file),
    ]

    with (
        patch("sys.argv", cli_args),
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Loop_Test"
    out = capsys.readouterr().out
    assert "Refreshing telemetry every 0.1s" in out
    assert "Simulation stopped." in out


@pytest.mark.unit
def test_simulate_telemetry_scenario_definitions() -> None:
    """Verifies that predefined scenarios match specification requirements."""
    assert "boss_fight" in SCENARIOS
    assert "tower_climb" in SCENARIOS

    boss_steps = SCENARIOS["boss_fight"]
    assert len(boss_steps) == 3
    # Step 1: 5s exploration in Level_Main_OldLumiere
    assert boss_steps[0].duration == 5.0
    assert boss_steps[0].zone == "Level_Main_OldLumiere"
    assert boss_steps[0].in_combat is False
    # Step 2: 10s combat encounter with Duollistes
    assert boss_steps[1].duration == 10.0
    assert boss_steps[1].zone == "Level_Main_OldLumiere"
    assert boss_steps[1].in_combat is True
    assert boss_steps[1].enemy_name == "Duollistes"
    # Step 3: victory and exploration at Manor Gardens
    assert boss_steps[2].zone == "Level_Main_OldLumiere"
    assert boss_steps[2].in_combat is False
    assert boss_steps[2].checkpoint == "Manor Gardens"

    tower_steps = SCENARIOS["tower_climb"]
    assert len(tower_steps) == 3
    # Transition through 3 consecutive trials of the Endless Tower
    assert tower_steps[0].tower_trial in ((1, 1), [1, 1], "Stage 1, Trial 1")
    assert tower_steps[1].tower_trial in ((1, 2), [1, 2], "Stage 1, Trial 2")
    assert tower_steps[2].tower_trial in ((1, 3), [1, 3], "Stage 1, Trial 3")


@pytest.mark.unit
def test_simulate_telemetry_cli_scenario_boss_fight(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifies CLI execution of the 'boss_fight' storyboard scenario."""
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--scenario",
        "boss_fight",
        "--speed",
        "100.0",
        "--interval",
        "0.05",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args), patch("time.sleep", return_value=None):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Main_OldLumiere"
    assert data["in_combat"] is False
    assert data["checkpoint"] == "Manor Gardens"

    out = capsys.readouterr().out
    assert "Starting scenario 'boss_fight'" in out
    assert "Exploration in Level_Main_OldLumiere" in out
    assert "Boss encounter with Duollistes" in out
    assert "Manor Gardens" in out
    assert "Scenario 'boss_fight' completed." in out


@pytest.mark.unit
def test_simulate_telemetry_cli_scenario_tower_climb(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifies CLI execution of the 'tower_climb' storyboard scenario."""
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--scenario",
        "tower_climb",
        "--speed",
        "100.0",
        "--interval",
        "0.05",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args), patch("time.sleep", return_value=None):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_EndlessTower"
    assert data["in_combat"] is True
    assert data["tower_trial"] == [1, 3]

    out = capsys.readouterr().out
    assert "Starting scenario 'tower_climb'" in out
    assert "Stage 1, Trial 1" in out
    assert "Stage 1, Trial 2" in out
    assert "Stage 1, Trial 3" in out
    assert "Scenario 'tower_climb' completed." in out


@pytest.mark.unit
def test_simulate_telemetry_cli_scenario_loop_interrupt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verifies KeyboardInterrupt terminates scenario playback cleanly."""
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--scenario",
        "boss_fight",
        "--loop",
        "--path",
        str(target_file),
    ]

    with (
        patch("sys.argv", cli_args),
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        main()

    out = capsys.readouterr().out
    assert "Scenario playback stopped." in out


@pytest.mark.unit
def test_simulate_telemetry_play_scenario_invalid(tmp_path: Path) -> None:
    """Verifies play_scenario raises ValueError on unrecognized scenario name."""
    with pytest.raises(ValueError, match="Unknown scenario 'non_existent'"):
        play_scenario("non_existent", tmp_path / "telemetry.json")


@pytest.mark.unit
def test_bridge_provider_resilience_to_corrupt_and_truncated_ipc(tmp_path: Path) -> None:
    """Verifies that BridgeStateProvider silently and transparently absorbs corrupt,

    truncated, and 0-byte IPC JSON frames via its internal grace period without crashing
    or propagating unhandled exceptions to the orchestrator.
    """
    status_file = tmp_path / "expedition33_status.json"

    # 1. Establish initial valid telemetry state
    now = 1000.0
    current_time = now

    def mock_time() -> float:
        return current_time

    write_telemetry(
        file_path=status_file,
        zone="Level_Main_OldLumiere",
        in_combat=True,
        enemy_name="Duollistes",
        checkpoint="Entrance",
    )
    # Update timestamp in file to match mock time
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    payload["timestamp"] = now
    status_file.write_text(json.dumps(payload), encoding="utf-8")

    provider = BridgeStateProvider(
        paths=[str(status_file)], grace_period=2.5, time_provider=mock_time
    )
    assert str(status_file) in provider.paths

    initial_data = provider.read_game_data()
    assert initial_data is not None
    assert initial_data["raw_zone"] == "Level_Main_OldLumiere"
    assert initial_data["in_combat"] is True
    assert initial_data["enemy_name"] == "Duollistes"

    mock_proc = MagicMock()
    mock_proc.pid = 4333
    mock_proc.name.return_value = "Sandfall-Win64-Shipping.exe"
    mock_proc.exe.return_value = "C:/Game/Sandfall-Win64-Shipping.exe"
    mock_proc.create_time.return_value = now
    mock_proc.is_running.return_value = True

    mock_rpc = MagicMock()
    detector = GameDetector(
        bridge_provider=provider,
        process_scanner=lambda: [mock_proc],
        time_provider=mock_time,
    )
    orchestrator = AppOrchestrator(
        detector=detector,
        rpc_manager=mock_rpc,
        time_provider=mock_time,
        auto_install_bridge=False,
        sync_startup=False,
    )
    # Orchestrator poll succeeds initially
    state = orchestrator.step_update()
    assert state is not None
    assert state.raw_zone == "Level_Main_OldLumiere"
    assert state.in_combat is True

    # 2. Simulate truncated half-written JSON frame (simulating interrupted atomic write)
    current_time = now + 1.0  # 1.0s later, within 2.5s grace period
    status_file.write_text('{"timestamp": 1001.0, "zone": "Level_Main_', encoding="utf-8")

    # BridgeStateProvider silently suppresses JSONDecodeError and returns cached valid state
    corrupt_read = provider.read_game_data()
    assert corrupt_read is not None
    assert corrupt_read["raw_zone"] == "Level_Main_OldLumiere"
    assert corrupt_read["in_combat"] is True

    # Orchestrator does not crash or raise uncaught exception
    orch_state = orchestrator.step_update()
    assert orch_state is not None
    assert orch_state.raw_zone == "Level_Main_OldLumiere"
    assert orch_state.in_combat is True

    # 3. Simulate 0-byte file (file exists but size is 0 bytes)
    current_time = now + 2.0  # 2.0s later, still within 2.5s grace period
    status_file.write_bytes(b"")

    empty_read = provider.read_game_data()
    assert empty_read is not None
    assert empty_read["raw_zone"] == "Level_Main_OldLumiere"

    orch_state_empty = orchestrator.step_update()
    assert orch_state_empty is not None
    assert orch_state_empty.raw_zone == "Level_Main_OldLumiere"

    # 4. Grace period expires (time exceeds grace period with no valid frame)
    current_time = now + 5.0  # 5.0s later > 2.5s grace period
    expired_read = provider.read_game_data()
    assert expired_read is None

    orch_state_expired = orchestrator.step_update()
    assert orch_state_expired is not None
    # Presence gracefully drops or falls back to default exploring without throwing
    assert orch_state_expired.in_combat is False

    # 5. Recovery: New valid frame written after grace period expiry
    current_time = now + 6.0
    write_telemetry(
        file_path=status_file,
        zone="Level_Main_OldLumiere",
        in_combat=False,
        checkpoint="Manor Gardens",
    )
    recovered_payload = json.loads(status_file.read_text(encoding="utf-8"))
    recovered_payload["timestamp"] = current_time
    status_file.write_text(json.dumps(recovered_payload), encoding="utf-8")

    recovered_read = provider.read_game_data()
    assert recovered_read is not None
    assert recovered_read["checkpoint"] == "Manor Gardens"
    assert recovered_read["in_combat"] is False

    orch_state_recovered = orchestrator.step_update()
    assert orch_state_recovered is not None
    assert orch_state_recovered.checkpoint_name == "Manor Gardens"
    assert orch_state_recovered.in_combat is False


@pytest.mark.unit
def test_bridge_provider_concurrent_corrupt_ipc_stress(tmp_path: Path) -> None:
    """Verifies high-frequency concurrent writing of truncated and 0-byte frames

    does not throw uncaught exceptions to the orchestrator.
    """
    status_file = tmp_path / "expedition33_status.json"

    write_telemetry(
        file_path=status_file,
        zone="Level_Main_OldLumiere",
        in_combat=True,
        enemy_name="Duollistes",
    )

    provider = BridgeStateProvider(paths=[str(status_file)], grace_period=1.0)
    mock_rpc = MagicMock()
    detector = GameDetector(bridge_provider=provider)
    orchestrator = AppOrchestrator(
        detector=detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    stop_event = threading.Event()
    writer_errors: list[Exception] = []
    reader_errors: list[Exception] = []

    def writer_thread() -> None:
        try:
            iteration = 0
            while not stop_event.is_set() and iteration < 30:
                iteration += 1
                try:
                    match iteration % 3:
                        case 0:
                            # 0-byte file
                            with open(status_file, "wb"):
                                pass
                        case 1:
                            # Half-written truncated JSON
                            with open(status_file, "wb") as f:
                                f.write(b'{"timestamp": 12345.0, "zone": "Level_Main_')
                        case _:
                            # Valid JSON
                            payload = {
                                "timestamp": time.time(),
                                "zone": "Level_Main_OldLumiere",
                                "in_combat": True,
                                "enemy_name": "Duollistes",
                                "checkpoint": "Entrance",
                                "floor": None,
                            }
                            with open(status_file, "w", encoding="utf-8") as f:
                                json.dump(payload, f)
                except OSError:
                    pass
                time.sleep(0.0005)
        except Exception as e:
            writer_errors.append(e)

    t = threading.Thread(target=writer_thread, daemon=True)
    t.start()

    try:
        for _ in range(25):
            try:
                orchestrator.step_update()
            except Exception as e:
                reader_errors.append(e)
            time.sleep(0.001)
    finally:
        stop_event.set()
        t.join(timeout=2.0)

    assert not writer_errors, f"Writer thread failed unexpectedly: {writer_errors}"
    assert not reader_errors, f"Orchestrator encountered unhandled exceptions: {reader_errors}"
