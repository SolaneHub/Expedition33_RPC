"""Tests for GameDetector process discovery, timer tracking, and telemetry providers."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import threading
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from expedition33_rpc.detection.detector import (
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

# ---------------------------------------------------------------------------
# Test Doubles
# ---------------------------------------------------------------------------


class FakeProcess:
    """Mock process implementing ProcessLike static protocol for deterministic unit tests."""

    def __init__(
        self,
        pid: int,
        name: str,
        is_running: bool = True,
        create_time: float = 100.0,
        exe_path: str | None = None,
    ):
        self._pid = pid
        self._name = name
        self._is_running = is_running
        self._create_time = create_time
        self._exe_path = exe_path

    @property
    def pid(self) -> int:
        return self._pid

    def name(self) -> str:
        return self._name

    def exe(self) -> str | None:
        return self._exe_path

    def is_running(self) -> bool:
        return self._is_running

    def create_time(self) -> float:
        return self._create_time


# ---------------------------------------------------------------------------
# ZoneTimerTracker State Machine Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_zone_timer_exploration_deterministic() -> None:
    tracker = ZoneTimerTracker()
    start_t1 = tracker.update("Zone A", in_combat=False, now=1000.0)
    assert start_t1 == 1000.0
    assert tracker.current_zone_id == "Zone A"

    start_t2 = tracker.update("Zone A", in_combat=False, now=1050.0)
    assert start_t2 == 1000.0


@pytest.mark.unit
def test_zone_timer_combat_pause_and_resume() -> None:
    tracker = ZoneTimerTracker()
    # 1. Start exploring Zone A at t = 1000.0
    tracker.update("Zone A", in_combat=False, now=1000.0)

    # 2. Enter combat at t = 1030.0
    combat_start = tracker.update("Zone A", in_combat=True, now=1030.0)
    assert combat_start == 1030.0

    # 3. Exit combat at t = 1060.0 (combat duration was 30s)
    resume_t = tracker.update("Zone A", in_combat=False, now=1060.0)
    # Shifted forward by 30s: 1000.0 + 30.0 = 1030.0
    assert resume_t == 1030.0


@pytest.mark.unit
def test_tower_chained_trial_combat() -> None:
    tracker = ZoneTimerTracker()
    c1 = tracker.update(
        "Tower", in_combat=True, is_tower=True, current_tower_trial=(1, 1), now=2000.0
    )
    assert c1 == 2000.0

    c2 = tracker.update(
        "Tower", in_combat=True, is_tower=True, current_tower_trial=(1, 2), now=2045.0
    )
    assert c2 == 2045.0


@pytest.mark.unit
def test_zone_transition_resets_timers() -> None:
    tracker = ZoneTimerTracker()
    tracker.update("Zone A", in_combat=False, now=1000.0)
    new_start = tracker.update("Zone B", in_combat=False, now=1100.0)
    assert new_start == 1100.0
    assert tracker.current_zone_id == "Zone B"


@pytest.mark.unit
def test_tracker_reset() -> None:
    tracker = ZoneTimerTracker()
    tracker.update("Zone A", in_combat=True, now=1000.0)
    tracker.reset()
    assert tracker.current_zone_id is None
    assert tracker.zone_start_time is None


# ---------------------------------------------------------------------------
# Process Discovery & Lifecycle Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_process_found_and_cached() -> None:
    target = FakeProcess(pid=1001, name="Sandfall-Win64-Shipping.exe")
    detector = GameDetector(process_scanner=lambda: [target])
    proc1 = detector.find_game_process()
    assert proc1 is not None
    assert proc1.pid == 1001

    # Second call returns cached process
    proc2 = detector.find_game_process()
    assert proc2 is not None
    assert proc2.pid == 1001


@pytest.mark.unit
def test_process_not_found() -> None:
    detector = GameDetector(process_scanner=lambda: [])
    assert detector.find_game_process() is None


@pytest.mark.unit
def test_cached_pid_invalidated_when_process_stops() -> None:
    proc = FakeProcess(pid=4001, name="Sandfall-Win64-Shipping.exe")
    procs = [proc]
    detector = GameDetector(process_scanner=lambda: list(procs))

    # 1. Finds and returns running process
    found = detector.find_game_process()
    assert found is not None
    assert found.pid == 4001

    # 2. Process exits
    proc._is_running = False
    procs.clear()

    # 3. Cache invalidated and returns None
    assert detector.find_game_process() is None


@pytest.mark.unit
def test_cached_pid_reused_by_unrelated_process_discovers_new_game() -> None:
    old_game = FakeProcess(pid=5555, name="Sandfall-Win64-Shipping.exe")
    procs = [old_game]
    detector = GameDetector(process_scanner=lambda: list(procs))
    p1 = detector.find_game_process()
    assert p1 is not None
    assert p1.pid == 5555

    # PID 5555 reused by chrome.exe, real game launched on PID 8888
    reused_proc = FakeProcess(pid=5555, name="chrome.exe", is_running=True)
    new_game = FakeProcess(pid=8888, name="Sandfall-Win64-Shipping.exe", is_running=True)
    procs.clear()
    procs.extend([reused_proc, new_game])

    p2 = detector.find_game_process()
    assert p2 is not None
    assert p2.pid == 8888


@pytest.mark.unit
def test_detector_custom_target_process_names_string_injection() -> None:
    proc = FakeProcess(pid=7777, name="MyCustomGame.exe")
    detector = GameDetector(
        process_scanner=lambda: [proc],
        target_process_names="mycustomgame.exe",
    )
    assert "mycustomgame.exe" in detector.target_process_names
    found = detector.find_game_process()
    assert found is not None
    assert found.pid == 7777


@pytest.mark.unit
def test_detector_custom_target_process_names_injection() -> None:
    proc_b = FakeProcess(pid=8888, name="GameVariantB.exe")
    detector = GameDetector(
        process_scanner=lambda: [proc_b],
        target_process_names=["gamevarianta.exe", "gamevariantb.exe"],
    )
    assert "gamevarianta.exe" in detector.target_process_names
    assert "gamevariantb.exe" in detector.target_process_names
    found = detector.find_game_process()
    assert found is not None
    assert found.pid == 8888


@pytest.mark.unit
def test_detector_discovers_wingdk_process() -> None:
    proc_gdk = FakeProcess(pid=9999, name="Sandfall-WinGDK-Shipping.exe")
    detector = GameDetector(process_scanner=lambda: [proc_gdk])
    found = detector.find_game_process()
    assert found is not None
    assert found.pid == 9999


# ---------------------------------------------------------------------------
# Telemetry Providers & Coordination Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bridge_provider_reads_valid_json(tmp_path: Path) -> None:
    now = time.time()
    payload = {
        "timestamp": now,
        "zone": "Level_Main_OldLumiere",
        "in_combat": True,
        "enemy_name": "Duollistes",
        "floor": 5,
        "checkpoint": "Entrance",
    }
    bridge_path = tmp_path / "expedition33_status.json"
    bridge_path.write_text(json.dumps(payload), encoding="utf-8")

    provider = BridgeStateProvider(paths=[str(bridge_path)])
    data = provider.read_game_data(min_valid_timestamp=now - 5.0, lang="en")
    assert data is not None
    assert data["raw_zone"] == "Level_Main_OldLumiere"
    assert data["in_combat"] is True
    assert data["enemy_name"] == "Duollistes"
    assert data["tower_floor"] == 5


@pytest.mark.integration
def test_bridge_provider_rejects_corrupted_or_partial_json(tmp_path: Path) -> None:
    bridge_path = tmp_path / "expedition33_status.json"
    provider = BridgeStateProvider(paths=[str(bridge_path)])

    for bad_content in (
        '{\x00"corrupted": invalid...',
        '{"timestamp": 123.0, "zone": "Leve',
        "",
        "[]",
    ):
        bridge_path.write_text(bad_content, encoding="utf-8")
        assert provider.read_bridge_status() is None


@pytest.mark.integration
@pytest.mark.parametrize("menu_token", ["MainMenu", "Level_MainMenu", "WBP_MM_MainMenu"])
def test_main_menu_detection(tmp_path: Path, menu_token: str) -> None:
    mock_proc = FakeProcess(pid=9999, name="Sandfall-Win64-Shipping.exe")
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text("[Internationalization]\nLanguage=en\n", encoding="utf-8")

    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": menu_token,
        "in_combat": False,
        "enemy_name": "",
        "tower_floor": None,
        "checkpoint": "",
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        game_user_settings_path=ini_path,
    )

    state = detector.get_game_state()
    assert state.is_running is True
    assert state.zone_name == "Main Menu"
    assert state.checkpoint_name == ""
    assert state.in_combat is False


@pytest.mark.integration
def test_bridge_provider_wall_clock_timeout_rejects_stale_data(tmp_path: Path) -> None:
    bridge_path = tmp_path / "expedition33_status.json"
    simulated_now = 1000.0
    payload = {
        "timestamp": simulated_now - 10.0,
        "zone": "Level_Main_OldLumiere",
        "in_combat": True,
        "enemy_name": "Duollistes",
    }
    bridge_path.write_text(json.dumps(payload), encoding="utf-8")
    provider = BridgeStateProvider(
        paths=[str(bridge_path)],
        grace_period=0.0,
        time_provider=lambda: simulated_now,
    )

    # Stale timestamp (>5s difference) is marked invalid
    assert provider.read_game_data(min_valid_timestamp=simulated_now - 20.0) is None


@pytest.mark.integration
def test_bridge_provider_rejects_non_numeric_timestamp(tmp_path: Path) -> None:
    bridge_path = tmp_path / "expedition33_status.json"
    provider = BridgeStateProvider(paths=[str(bridge_path)], grace_period=0.0)

    # Non-numeric timestamp is rejected as unparseable
    bridge_path.write_text(
        json.dumps(
            {"timestamp": "invalid_time", "zone": "Level_Main_OldLumiere", "in_combat": True}
        ),
        encoding="utf-8",
    )
    assert provider.read_game_data() is None


@pytest.mark.unit
def test_game_state_frozen_immutability() -> None:
    state = GameState.create(is_running=True, zone_name="Old Lumiere")
    with pytest.raises(FrozenInstanceError):
        state.zone_name = "New Lumiere"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        state.in_combat = True  # type: ignore


@pytest.mark.unit
def test_game_state_dataclass_replace_immutability() -> None:
    state_active = GameState.create(in_combat=True, enemy_name="Duollistes")
    assert state_active.in_combat is True
    assert state_active.enemy_name == "Duollistes"

    state_peace = dataclasses.replace(state_active, in_combat=False, enemy_name="")
    assert state_peace.in_combat is False
    assert state_peace.enemy_name == ""


@pytest.mark.integration
def test_bridge_provider_concurrent_writer_resilience(tmp_path: Path) -> None:
    bridge_path = tmp_path / "expedition33_status.json"
    provider = BridgeStateProvider(paths=[str(bridge_path)])

    stop = threading.Event()
    stats = {"success": 0, "failure": 0}

    def writer():
        i = 0
        while not stop.is_set():
            i += 1
            with contextlib.suppress(Exception):
                bridge_path.write_text(
                    json.dumps({"timestamp": time.time(), "zone": f"Zone_{i}", "in_combat": False}),
                    encoding="utf-8",
                )
            time.sleep(0.015)

    t = threading.Thread(target=writer, daemon=True)
    t.start()

    for _ in range(25):
        data = provider.read_bridge_status()
        if data is None:
            stats["failure"] += 1
        else:
            stats["success"] += 1
        time.sleep(0.001)

    stop.set()
    t.join(timeout=1.0)

    total = stats["success"] + stats["failure"]
    assert total > 0
    failure_rate = (stats["failure"] / total) * 100
    assert failure_rate < 5.0, f"Failure rate was {failure_rate:.1f}%"


@pytest.mark.integration
def test_detector_bridge_grace_period_prevents_telemetry_jitter(tmp_path: Path) -> None:
    mock_proc = FakeProcess(pid=4321, name="Sandfall-Win64-Shipping.exe")
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text("[Internationalization]\nLanguage=en\n", encoding="utf-8")

    current_clock = 1000.0
    bridge_provider = BridgeStateProvider(grace_period=2.5, time_provider=lambda: current_clock)
    bridge_provider.read_bridge_status = MagicMock(  # type: ignore
        side_effect=[
            {
                "timestamp": 1000.0,
                "zone": "Level_Main_OldLumiere",
                "in_combat": True,
                "enemy_name": "Duollistes",
                "tower_floor": None,
                "checkpoint": "",
            },
            None,  # transient glitch within grace period
            None,  # transient glitch past grace period
        ]
    )

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        game_user_settings_path=ini_path,
    )

    # Tick 1: Bridge succeeds
    st1 = detector.get_game_state()
    assert st1.zone_name == "Old Lumière"
    assert st1.in_combat is True

    # Tick 2: Bridge glitch (read_bridge_status returns None), bridge internal grace period returns cached state
    current_clock = 1001.0
    st2 = detector.get_game_state()
    assert st2.zone_name == "Old Lumière"
    assert st2.in_combat is True

    # Tick 3: Past grace period (5.0s > 2.5s), telemetry expires
    current_clock = 1005.0
    st3 = detector.get_game_state()
    assert st3.in_combat is False


@pytest.mark.unit
def test_bridge_retains_checkpoint_across_ticks_for_same_zone() -> None:
    """Verifies that when BridgeStateProvider has empty checkpoint for same zone, last known checkpoint is retained."""
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.name.return_value = "sandfall-win64-shipping.exe"
    mock_proc.is_running.return_value = True
    mock_proc.create_time.return_value = 1000.0

    bridge_provider = MagicMock(spec=BridgeStateProvider)

    # Bridge returns valid data with empty checkpoint
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Main_OldLumiere",
        "in_combat": False,
        "enemy_name": "",
        "checkpoint": "",
        "timestamp": time.time(),
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
    )

    # First tick: bridge is active, checkpoint supplied
    bridge_provider.read_game_data.return_value["checkpoint"] = "Entrance"
    st1 = detector.get_game_state()
    assert st1.zone_name == "Old Lumière"
    assert st1.checkpoint_name == "Entrance"

    # Second tick: bridge returns empty checkpoint for the same zone;
    # it must retain the last known checkpoint
    bridge_provider.read_game_data.return_value["checkpoint"] = ""
    st2 = detector.get_game_state()
    assert st2.zone_name == "Old Lumière"
    assert st2.checkpoint_name == "Entrance"

    # Third tick: zone changes to Monolith with empty checkpoint; checkpoint should cleanly reset
    bridge_provider.read_game_data.return_value["raw_zone"] = "Level_Main_Monolith"
    st3 = detector.get_game_state()
    assert st3.zone_name == "The Monolith"
    assert st3.checkpoint_name == ""


@pytest.mark.unit
def test_game_process_path_and_win64_dir_propagation(tmp_path: Path) -> None:
    """Verifies that GameDetector exposes exe_path and win64_dir when game process is detected."""
    fake_exe = tmp_path / "Binaries" / "Win64" / "sandfall-win64-shipping.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.write_text("binary", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.pid = 7777
    mock_proc.name.return_value = "sandfall-win64-shipping.exe"
    mock_proc.is_running.return_value = True
    mock_proc.create_time.return_value = 1000.0
    mock_proc.exe.return_value = str(fake_exe)

    detector = GameDetector(
        process_scanner=lambda: [mock_proc],
    )

    assert detector.game_exe_path is None
    assert detector.game_win64_dir is None
    assert detector.exe_path is None
    assert detector.win64_dir is None

    proc = detector.find_game_process()
    assert proc is mock_proc
    assert detector.game_exe_path == os.path.normpath(str(fake_exe))
    assert detector.game_win64_dir == fake_exe.parent
    assert detector.exe_path == os.path.normpath(str(fake_exe))
    assert detector.win64_dir == fake_exe.parent

    # Encapsulation contract: GameState emits process_info, win64_dir, and exe_path
    state = detector.get_game_state()
    assert state.is_running is True
    assert state.process_info is not None
    assert state.process_info.pid == 7777
    assert state.process_info.win64_dir == fake_exe.parent
    assert state.process_info.exe_path == os.path.normpath(str(fake_exe))
    assert state.win64_dir == fake_exe.parent
    assert state.exe_path == os.path.normpath(str(fake_exe))
