"""Tests for GameDetector process discovery, timer tracking, and telemetry providers."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import sys
import threading
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.harness import FakeProcess

from expedition33_rpc.detection.detector import (
    BridgeStateProvider,
    GameDetector,
    GameState,
    SaveReaderProtocol,
    _read_file_shared_text,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

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
        bridge_provider=None,
    )
    state = detector.get_game_state()
    assert state.is_running is True
    assert state.process_pid == 7777


@pytest.mark.unit
def test_detector_custom_target_process_names_injection() -> None:
    proc_b = FakeProcess(pid=8888, name="GameVariantB.exe")
    detector = GameDetector(
        process_scanner=lambda: [proc_b],
        target_process_names=["gamevarianta.exe", "gamevariantb.exe"],
        bridge_provider=None,
    )
    state = detector.get_game_state()
    assert state.is_running is True
    assert state.process_pid == 8888


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
@pytest.mark.parametrize(
    "menu_token",
    [
        "MainMenu",
        "Level_MainMenu",
        "WBP_MM_MainMenu",
        "Map_GameBootstrap",
        "WBP_MM_TitleScreen",
        "WBP_MM_Settings",
        "WBP_MM_NewGame",
        "WBP_MM_LoadScreen",
    ],
)
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


@pytest.mark.unit
def test_detector_startup_state_when_telemetry_pending() -> None:
    """Verifies that GameDetector identifies initial process startup when telemetry is not yet ready."""
    mock_proc = FakeProcess(pid=9999, name="Sandfall-Win64-Shipping.exe")
    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = None

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
    )

    state = detector.get_game_state()
    assert state.is_running is True
    assert state.is_starting is True
    assert state.raw_zone == "Starting"
    assert state.zone_name == "Starting..."


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
    attr_zone = "zone_name"
    with pytest.raises(FrozenInstanceError):
        setattr(state, attr_zone, "New Lumiere")

    attr_combat = "in_combat"
    with pytest.raises(FrozenInstanceError):
        setattr(state, attr_combat, True)


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

    status_file = tmp_path / "expedition33_status.json"
    status_file.write_text(
        json.dumps(
            {
                "timestamp": 1000.0,
                "zone": "Level_Main_OldLumiere",
                "in_combat": True,
                "enemy_name": "Duollistes",
                "tower_floor": None,
                "checkpoint": "",
            }
        ),
        encoding="utf-8",
    )

    current_clock = 1000.0
    bridge_provider = BridgeStateProvider(
        paths=[str(status_file)],
        grace_period=2.5,
        time_provider=lambda: current_clock,
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

    # Tick 2: Bridge glitch (file removed), bridge internal grace period returns cached state
    status_file.unlink()
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
    """Verifies that GameState exposes exe_path and win64_dir when game process is detected."""
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
        bridge_provider=None,
    )

    # Encapsulation contract: GameState emits process_info, win64_dir, and exe_path
    state = detector.get_game_state()
    assert state.is_running is True
    assert state.process_info is not None
    assert state.process_info.pid == 7777
    assert state.process_info.win64_dir == fake_exe.parent
    assert state.process_info.exe_path == os.path.normpath(str(fake_exe))
    assert state.win64_dir == fake_exe.parent
    assert state.exe_path == os.path.normpath(str(fake_exe))


@pytest.mark.integration
def test_read_file_shared_text_basic_and_error(tmp_path: Path) -> None:
    p = tmp_path / "test.json"
    p.write_text('{"status": "ok"}', encoding="utf-8")
    assert _read_file_shared_text(str(p)) == '{"status": "ok"}'

    with pytest.raises(OSError):
        _read_file_shared_text(str(tmp_path / "nonexistent.json"))


@pytest.mark.integration
def test_read_file_shared_text_large_file_and_unicode(tmp_path: Path) -> None:
    # 1. Empty file
    empty_p = tmp_path / "empty.txt"
    empty_p.write_text("", encoding="utf-8")
    assert _read_file_shared_text(str(empty_p)) == ""

    # 2. Large file exceeding 64KB chunk size with non-ASCII UTF-8 characters
    large_p = tmp_path / "large_unicode.txt"
    unicode_snippet = "Expédition 33 — Lumière & Renoir: caffè, naïve, 🎮, 日本語\n"
    target_content = unicode_snippet * 1500  # ~90KB
    large_p.write_text(target_content, encoding="utf-8", newline="\n")
    assert _read_file_shared_text(str(large_p)) == target_content

    # 3. Multibyte UTF-8 sequence straddling precisely across the 65536-byte chunk boundary
    boundary_p = tmp_path / "boundary_unicode.txt"
    # 65534 ASCII bytes + 4-byte UTF-8 emoji (🎮: b'\xf0\x9f\x8e\xae') + trailing text
    boundary_bytes = b"A" * 65534 + "🎮_boundary_ok\n".encode()
    boundary_p.write_bytes(boundary_bytes)
    assert _read_file_shared_text(str(boundary_p)) == boundary_bytes.decode("utf-8")

    # 4. Corrupted bytes raise UnicodeDecodeError directly without redundant re-reads
    corrupt_p = tmp_path / "corrupt_utf8.bin"
    corrupt_p.write_bytes(b"\x80\x81\x82\xff")
    with pytest.raises(UnicodeDecodeError):
        _read_file_shared_text(str(corrupt_p))


@pytest.mark.integration
def test_read_file_shared_text_windows_deletion_resilience(tmp_path: Path) -> None:
    # 1. Standard open on Windows blocks deletion while open (reproducing WinError 32)
    p = tmp_path / "locked.json"
    p.write_text('{"locked": true}', encoding="utf-8")
    if sys.platform == "win32":
        with open(p, encoding="utf-8"), pytest.raises(PermissionError):
            os.remove(p)

    # 2. FILE_SHARE_DELETE permits unlinking while the handle is open
    p_shared = tmp_path / "shared.json"
    p_shared.write_text('{"shared": true}', encoding="utf-8")
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        windll: Any = getattr(ctypes, "windll", None)
        k32: Any = getattr(windll, "kernel32", None) if windll is not None else None
        assert k32 is not None
        handle = k32.CreateFileW(
            str(p_shared),
            0x80000000,
            1 | 2 | 4,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
            None,
            3,
            0x80,
            None,
        )
        assert handle not in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, None)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        with open(fd, encoding="utf-8") as f:
            # File unlinks successfully while the handle is open without WinError 32
            p_shared.unlink()
            assert not p_shared.exists()
            assert f.read() == '{"shared": true}'

    # 3. High-churn concurrent write/delete/read loop
    churn_path = tmp_path / "churn.json"
    churn_path.write_text('{"cycle": 0}', encoding="utf-8")
    stop_event = threading.Event()
    errors: list[Exception] = []

    def writer_churn() -> None:
        try:
            for i in range(25):
                if stop_event.is_set():
                    break
                with contextlib.suppress(OSError):
                    churn_path.write_text(f'{{"cycle": {i}}}', encoding="utf-8")
                time.sleep(0.0005)
                with contextlib.suppress(OSError):
                    churn_path.unlink(missing_ok=True)
                time.sleep(0.0005)
        except Exception as e:
            errors.append(e)

    writer_thread = threading.Thread(target=writer_churn, daemon=True)
    writer_thread.start()

    try:
        for _ in range(30):
            with contextlib.suppress(OSError):
                _read_file_shared_text(str(churn_path))
            time.sleep(0.0005)
    finally:
        stop_event.set()
        writer_thread.join(timeout=2.0)

    assert not errors, f"Writer churn raised unexpected exceptions: {errors}"


@pytest.mark.integration
def test_game_detector_get_game_language_caching(tmp_path: Path) -> None:
    ini = tmp_path / "GameUserSettings.ini"
    ini.write_text("[Internationalization]\nLanguage=it\n", encoding="utf-8")

    detector = GameDetector()
    lang = detector.get_game_language(ini)
    assert lang == "it"

    # Reading again returns cached value
    assert detector.get_game_language(ini) == "it"

    # Update file content and mtime
    time.sleep(0.01)
    ini.write_text("[Internationalization]\nLanguage=fr\n", encoding="utf-8")
    new_mtime = ini.stat().st_mtime + 1.0
    os.utime(ini, (new_mtime, new_mtime))

    assert detector.get_game_language(ini) == "fr"


@pytest.mark.integration
def test_game_detector_get_game_language_injected_path(tmp_path: Path) -> None:
    ini = tmp_path / "GameUserSettings.ini"
    ini.write_text("[Internationalization]\nLanguage=de\n", encoding="utf-8")

    detector = GameDetector(game_user_settings_path=ini)
    assert detector.get_game_language() == "de"


@pytest.mark.unit
def test_game_detector_get_game_language_fallback_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent_settings.ini"
    detector = GameDetector(game_user_settings_path=missing)
    # When file does not exist, fallback returns cached default ("en")
    assert detector.get_game_language() == "en"


@pytest.mark.unit
def test_game_detector_get_game_language_with_now_propagation(tmp_path: Path) -> None:
    """Verifies that now parameter propagates deterministically to get_game_language."""
    ini = tmp_path / "GameUserSettings.ini"
    ini.write_text("[Internationalization]\nLanguage=it\n", encoding="utf-8")

    time_calls = 0

    def mock_time():
        nonlocal time_calls
        time_calls += 1
        return 50.0

    detector = GameDetector(game_user_settings_path=ini, time_provider=mock_time)
    lang = detector.get_game_language(now=100.0)
    assert lang == "it"
    # time_provider should not be called because now was provided
    assert time_calls == 0
    assert detector._last_language_check_time == 100.0


@pytest.mark.unit
def test_detector_idle_polling_backoff_for_psutil_process_iter() -> None:
    """Verifies adaptive idle backoff throttling psutil.process_iter scans when game is inactive."""
    from unittest.mock import patch

    scan_calls = 0

    def mock_process_iter(_attrs: Any = None) -> list[Any]:
        nonlocal scan_calls
        scan_calls += 1
        return []

    detector = GameDetector(idle_poll_interval=5.0)

    with patch("psutil.process_iter", side_effect=mock_process_iter):
        # 1. First scan at t=0 executes global process_iter
        proc1 = detector.find_game_process(now=0.0)
        assert proc1 is None
        assert scan_calls == 1

        # 2. Query at t=2.0 (before 5s idle interval) throttles and returns None without scanning
        proc2 = detector.find_game_process(now=2.0)
        assert proc2 is None
        assert scan_calls == 1

        # 3. Query at t=4.9 throttles
        proc3 = detector.find_game_process(now=4.9)
        assert proc3 is None
        assert scan_calls == 1

        # 4. Query at t=5.1 (after idle interval) performs second global scan
        proc4 = detector.find_game_process(now=5.1)
        assert proc4 is None
        assert scan_calls == 2

        # 5. Query with force=True bypasses idle backoff
        proc5 = detector.find_game_process(now=5.5, force=True)
        assert proc5 is None
        assert scan_calls == 3


@pytest.mark.unit
def test_cleas_workshop_is_not_detected_as_tower() -> None:
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Side_CleasWorkshop",
        "in_combat": True,
        "enemy_name": "Gargoyle",
        "checkpoint": "Workshop Entrance",
        "timestamp": 1000.0,
    }
    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
    )

    state = detector.get_game_state(now=1000.0)
    assert state.is_running is True
    assert state.raw_zone == "Level_Side_CleasWorkshop"
    assert state.zone_name == "Painting Workshop"
    assert state.tower_stage_trial is None
    assert state.tower_floor is None


@pytest.mark.unit
def test_get_game_state_propagates_now_timestamp() -> None:
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    mock_timer_tracker = MagicMock(spec=ZoneTimerTracker)
    mock_timer_tracker.current_zone_id = None
    mock_timer_tracker.update.return_value = 1700000000.0

    detector = GameDetector(
        timer_tracker=mock_timer_tracker,
        process_scanner=lambda: [mock_proc],
        bridge_provider=None,
    )

    fixed_now = 1700000000.0
    state = detector.get_game_state(now=fixed_now)

    assert state.start_time == fixed_now
    mock_timer_tracker.update.assert_called_once()
    _, kwargs = mock_timer_tracker.update.call_args
    assert kwargs.get("now") == fixed_now


@pytest.mark.unit
def test_save_reader_protocol_runtime_checkable() -> None:
    class DummySaveReader:
        def resolve_checkpoint_for_zone(self, raw_zone: str, zone_display: str = "") -> str:
            del raw_zone, zone_display
            return "Checkpoint_1"

        def reset(self) -> None:
            pass

    dummy = DummySaveReader()
    assert isinstance(dummy, SaveReaderProtocol)


@pytest.mark.unit
def test_detector_save_reader_defaults_to_none() -> None:
    """Verifies that GameDetector defaults without save_reader and produces clean empty checkpoints."""
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    detector = GameDetector(
        process_scanner=lambda: [mock_proc],
        bridge_provider=None,
    )
    state = detector.get_game_state()
    assert state.is_running is True
    assert state.raw_checkpoint == ""
    assert state.checkpoint_name == ""


@pytest.mark.unit
def test_detector_fallback_to_save_reader_when_provided() -> None:
    """Verifies that GameDetector falls back to SaveReader when bridge becomes stale/inactive."""
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    mock_save_reader = MagicMock(spec=SaveReaderProtocol)
    mock_save_reader.resolve_checkpoint_for_zone.return_value = "SpawnPoint_VersosDraft"

    bridge_provider = MagicMock(spec=BridgeStateProvider)
    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        save_reader=mock_save_reader,
    )

    # Tick 1: Bridge active in Versos Draft with its own checkpoint
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "in_combat": False,
        "checkpoint": "BridgeCheckpoint",
        "timestamp": 1000.0,
    }
    st1 = detector.get_game_state(now=1000.0)
    assert st1.is_running is True
    assert st1.raw_zone == "Level_Side_VersosDraft"
    assert st1.raw_checkpoint == "BridgeCheckpoint"

    # Tick 2: Bridge telemetry drops (returns None) -> Clean fallback to save reader
    bridge_provider.read_game_data.return_value = None
    st2 = detector.get_game_state(now=1002.0)
    assert st2.is_running is True
    assert st2.raw_checkpoint == "SpawnPoint_VersosDraft"
    assert st2.checkpoint_name == "Spawn Point_Versos Draft"
    mock_save_reader.resolve_checkpoint_for_zone.assert_called_once_with("Level_Side_VersosDraft")


@pytest.mark.unit
def test_tower_trial_cleared_when_leaving_tower_combat() -> None:
    """Verifies that current_tower_trial is cleared when transitioning out of tower or combat."""
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    bridge_provider = MagicMock(spec=BridgeStateProvider)
    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
    )

    # Tick 1: In tower combat with active trial
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_EndlessTower_Trial",
        "in_combat": True,
        "enemy_name": "Boss_Trial_1_2",
        "enemies": ["Boss_Trial_1_2"],
        "tower_trial": (1, 2),
        "timestamp": 1000.0,
    }
    st1 = detector.get_game_state(now=1000.0)
    assert st1.tower_stage_trial == (1, 2)

    # Tick 2: Player warps to non-tower zone while still in combat -> trial must clear
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Main_OldLumiere",
        "in_combat": True,
        "enemy_name": "Duollistes",
        "enemies": ["Duollistes"],
        "tower_trial": None,
        "timestamp": 1002.0,
    }
    st2 = detector.get_game_state(now=1002.0)
    assert st2.tower_stage_trial is None

    # Tick 3: Back to tower but out of combat -> trial must remain None
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_EndlessTower_Trial",
        "in_combat": False,
        "enemy_name": "",
        "enemies": [],
        "tower_trial": None,
        "timestamp": 1004.0,
    }
    st3 = detector.get_game_state(now=1004.0)
    assert st3.tower_stage_trial is None


@pytest.mark.unit
def test_detector_save_reader_strictly_dormant_when_bridge_fresh() -> None:
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    mock_save_reader = MagicMock(spec=SaveReaderProtocol)
    mock_save_reader.resolve_checkpoint_for_zone.return_value = "SpawnPoint_VersosDraft"

    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "in_combat": False,
        "enemy_name": "",
        "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        save_reader=mock_save_reader,
    )

    state = detector.get_game_state(now=1000.0)
    assert state.is_running is True
    assert state.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"
    mock_save_reader.resolve_checkpoint_for_zone.assert_not_called()


@pytest.mark.unit
def test_detector_save_reader_resolves_checkpoint_when_bridge_checkpoint_empty() -> None:
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    mock_save_reader = MagicMock(spec=SaveReaderProtocol)
    mock_save_reader.resolve_checkpoint_for_zone.return_value = "SpawnPoint_VersosDraft"

    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "in_combat": False,
        "enemy_name": "",
        "checkpoint": "",
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        save_reader=mock_save_reader,
    )

    # First tick: resolves checkpoint from save reader and caches
    st1 = detector.get_game_state(now=1000.0)
    assert st1.raw_checkpoint == "SpawnPoint_VersosDraft"
    mock_save_reader.resolve_checkpoint_for_zone.assert_called_once_with("Level_Side_VersosDraft")

    # Second tick: player fast travels to new checkpoint in same zone; detector queries save reader and updates
    mock_save_reader.resolve_checkpoint_for_zone.return_value = "SpawnPoint_VersosDraft_NewCamp"
    st2 = detector.get_game_state(now=1002.0)
    assert st2.raw_checkpoint == "SpawnPoint_VersosDraft_NewCamp"
    assert mock_save_reader.resolve_checkpoint_for_zone.call_count == 2


@pytest.mark.unit
def test_detector_no_save_reader_fallback_when_none() -> None:
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "in_combat": False,
        "enemy_name": "",
        "checkpoint": "",
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
        save_reader=None,
    )

    state = detector.get_game_state(now=1000.0)
    assert state.is_running is True
    assert state.raw_checkpoint == ""


@pytest.mark.unit
def test_detector_resets_save_reader_when_game_stops() -> None:
    mock_save_reader = MagicMock(spec=SaveReaderProtocol)
    detector = GameDetector(
        process_scanner=lambda: [],
        save_reader=mock_save_reader,
    )

    state = detector.get_game_state()
    assert state.is_running is False
    mock_save_reader.reset.assert_called_once()


@pytest.mark.unit
def test_detector_is_starting_consecutive_ticks_without_telemetry() -> None:
    """Verifies that is_starting remains True over multiple consecutive ticks when telemetry is absent,

    self.last_raw_zone is not polluted with 'Starting', and timer tracker zone_id is not polluted.
    """
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    detector = GameDetector(
        process_scanner=lambda: [mock_proc],
        bridge_provider=None,
    )

    for tick in range(1, 5):
        state = detector.get_game_state(now=1700000000.0 + tick)
        assert state.is_running is True
        assert state.is_starting is True, f"Failed on tick {tick}"
        assert state.raw_zone == "Starting"
        assert state.zone_name == "Starting..."
        assert detector.last_raw_zone != "Starting"
        assert detector.timer_tracker.current_zone_id != "Starting"


@pytest.mark.unit
def test_detector_endless_tower_canonical_boss_override() -> None:
    """Verifies that when tower_trial is provided in bridge payload with non-canonical enemy name,

    the canonical boss name from ENDLESS_TOWER_TRIALS is resolved (e.g. Painted Love for trial [11, 3]).
    """
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    bridge_provider = MagicMock(spec=BridgeStateProvider)
    bridge_provider.read_game_data.return_value = {
        "raw_zone": "Level_EndlessTower",
        "in_combat": True,
        "enemy_name": "Unknown Grunt",
        "tower_trial": [11, 3],
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=bridge_provider,
        process_scanner=lambda: [mock_proc],
    )

    state = detector.get_game_state(now=1000.0)
    assert state.is_running is True
    assert state.in_combat is True
    assert state.enemy_name == "Painted Love"


@pytest.mark.unit
def test_detector_clock_epoch_does_not_corrupt_monotonic_scan_backoff() -> None:
    """Verifies that passing epoch timestamp to get_game_state does not corrupt monotonic scan backoff."""
    mock_proc = FakeProcess(pid=1234, name="Sandfall-Win64-Shipping.exe")
    detector = GameDetector(
        process_scanner=lambda: [mock_proc],
        bridge_provider=None,
    )

    # Initial call with epoch timestamp (e.g. year 2026 / 1.7e9)
    epoch_now = 1770000000.0
    state = detector.get_game_state(now=epoch_now)
    assert state.is_running is True

    # _last_process_scan_time should be tracked via monotonic clock, NOT epoch
    # If it was contaminated with epoch_now (~1.7e9), monotonic time (usually thousands of seconds)
    # would make (current_time - _last_process_scan_time) strongly negative, breaking idle backoff.
    assert detector._last_process_scan_time < 100000000.0
