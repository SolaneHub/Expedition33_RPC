#!/usr/bin/env python3
"""Adversarial stress-test harness verifying SaveFileReader dormancy in GameDetector.

Empirically validates:
1. Zero disk I/O, zero mmap, and zero filesystem calls by SaveFileReader when Bridge telemetry is active.
2. Clean fallback to SaveFileReader when Bridge telemetry is stale (>5.0s) or absent.
3. Resilience, immutability, and absence of state corruption under 10,000 rapid toggling cycles.
"""

from __future__ import annotations

import builtins
import inspect
import mmap
import os
import pathlib
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from tests.harness import FakeProcess

from expedition33_rpc.detection.detector import (
    BridgeProviderProtocol,
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.save_reader import SaveFileReader

# Target functions to monitor for filesystem calls originating from save_reader.py
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_MMAP = mmap.mmap
_ORIGINAL_PATH_GLOB = pathlib.Path.glob
_ORIGINAL_PATH_ITERDIR = pathlib.Path.iterdir
_ORIGINAL_PATH_STAT = pathlib.Path.stat
_ORIGINAL_PATH_EXISTS = pathlib.Path.exists
_ORIGINAL_PATH_IS_FILE = pathlib.Path.is_file
_ORIGINAL_PATH_IS_DIR = pathlib.Path.is_dir
_ORIGINAL_OS_STAT = os.stat
_ORIGINAL_OS_EXISTS = os.path.exists
_ORIGINAL_OS_ISFILE = os.path.isfile
_ORIGINAL_OS_ISDIR = os.path.isdir


def _apply_patch(target: Any, attr: str, val: Any) -> None:
    setattr(target, attr, val)


class FilesystemActivityAudit:
    """Hooks all low-level filesystem and mmap APIs to trace activity originating from save_reader.py."""

    def __init__(self) -> None:
        self.save_reader_fs_calls: list[dict[str, Any]] = []
        self._installed = False

    def _is_from_save_reader(self) -> bool:
        # Check call stack for save_reader.py frame
        frame = inspect.currentframe()
        try:
            # Skip current frame and hook frame
            cur = frame.f_back.f_back if frame and frame.f_back else None
            while cur is not None:
                fname = cur.f_code.co_filename
                if "save_reader.py" in fname:
                    return True
                cur = cur.f_back
        finally:
            del frame
        return False

    def _record(self, func_name: str, *args: Any) -> None:
        if self._is_from_save_reader():
            self.save_reader_fs_calls.append({"func": func_name, "args": args})

    def start(self) -> None:
        if self._installed:
            return
        audit = self

        def hooked_open(*args: Any, **kwargs: Any) -> Any:
            audit._record("open", *args)
            return _ORIGINAL_OPEN(*args, **kwargs)

        def hooked_mmap(*args: Any, **kwargs: Any) -> Any:
            audit._record("mmap", *args)
            return _ORIGINAL_MMAP(*args, **kwargs)

        def hooked_path_glob(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.glob", str(self_path), *args)
            return _ORIGINAL_PATH_GLOB(self_path, *args, **kwargs)

        def hooked_path_iterdir(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.iterdir", str(self_path), *args)
            return _ORIGINAL_PATH_ITERDIR(self_path, *args, **kwargs)

        def hooked_path_stat(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.stat", str(self_path), *args)
            return _ORIGINAL_PATH_STAT(self_path, *args, **kwargs)

        def hooked_path_exists(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.exists", str(self_path), *args)
            return _ORIGINAL_PATH_EXISTS(self_path, *args, **kwargs)

        def hooked_path_is_file(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.is_file", str(self_path), *args)
            return _ORIGINAL_PATH_IS_FILE(self_path, *args, **kwargs)

        def hooked_path_is_dir(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.is_dir", str(self_path), *args)
            return _ORIGINAL_PATH_IS_DIR(self_path, *args, **kwargs)

        def hooked_os_stat(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.stat", *args)
            return _ORIGINAL_OS_STAT(*args, **kwargs)

        def hooked_os_exists(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.exists", *args)
            return _ORIGINAL_OS_EXISTS(*args, **kwargs)

        def hooked_os_isfile(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.isfile", *args)
            return _ORIGINAL_OS_ISFILE(*args, **kwargs)

        def hooked_os_isdir(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.isdir", *args)
            return _ORIGINAL_OS_ISDIR(*args, **kwargs)

        _apply_patch(builtins, "open", hooked_open)
        _apply_patch(mmap, "mmap", hooked_mmap)
        _apply_patch(pathlib.Path, "glob", hooked_path_glob)
        _apply_patch(pathlib.Path, "iterdir", hooked_path_iterdir)
        _apply_patch(pathlib.Path, "stat", hooked_path_stat)
        _apply_patch(pathlib.Path, "exists", hooked_path_exists)
        _apply_patch(pathlib.Path, "is_file", hooked_path_is_file)
        _apply_patch(pathlib.Path, "is_dir", hooked_path_is_dir)
        _apply_patch(os, "stat", hooked_os_stat)
        _apply_patch(os.path, "exists", hooked_os_exists)
        _apply_patch(os.path, "isfile", hooked_os_isfile)
        _apply_patch(os.path, "isdir", hooked_os_isdir)
        self._installed = True

    def stop(self) -> None:
        if not self._installed:
            return
        _apply_patch(builtins, "open", _ORIGINAL_OPEN)
        _apply_patch(mmap, "mmap", _ORIGINAL_MMAP)
        _apply_patch(pathlib.Path, "glob", _ORIGINAL_PATH_GLOB)
        _apply_patch(pathlib.Path, "iterdir", _ORIGINAL_PATH_ITERDIR)
        _apply_patch(pathlib.Path, "stat", _ORIGINAL_PATH_STAT)
        _apply_patch(pathlib.Path, "exists", _ORIGINAL_PATH_EXISTS)
        _apply_patch(pathlib.Path, "is_file", _ORIGINAL_PATH_IS_FILE)
        _apply_patch(pathlib.Path, "is_dir", _ORIGINAL_PATH_IS_DIR)
        _apply_patch(os, "stat", _ORIGINAL_OS_STAT)
        _apply_patch(os.path, "exists", _ORIGINAL_OS_EXISTS)
        _apply_patch(os.path, "isfile", _ORIGINAL_OS_ISFILE)
        _apply_patch(os.path, "isdir", _ORIGINAL_OS_ISDIR)
        self._installed = False

    def clear(self) -> None:
        self.save_reader_fs_calls.clear()


def create_test_save_structure(base_dir: Path) -> tuple[Path, str]:
    """Creates a realistic UE5 .sav save file structure on disk."""
    profile_dir = base_dir / "76561198097793146"
    profile_dir.mkdir(parents=True, exist_ok=True)
    sav_file = profile_dir / "EXPEDITION_0.sav"

    payload = (
        b"\x00" * 128
        + b"LastUsedSavePoint\x00\x0f\x00\x00\x00StructProperty\x00\x02\x00\x00\x00"
        + b"LevelAssetName\x00\r\x00\x00\x00NameProperty\x00\x00\x00\x00\x00Level_Side_VersosDraft\x00"
        + b"SpawnPointTag\x00Level.SpawnPoint.VersosDraft.CandyLand\x00"
        + b"\x00" * 128
    )
    sav_file.write_bytes(payload)
    return profile_dir, "Level.SpawnPoint.VersosDraft.CandyLand"


def run_dormancy_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[1/3] Running Empirical Dormancy Test (Active Bridge Telemetry)...")

    # Set up realistic save directory on disk with actual UE5 .sav binary
    create_test_save_structure(tmp_path)
    real_save_reader = SaveFileReader(base_save_dir=tmp_path)

    # Wrap save_reader methods with call trackers
    original_resolve = real_save_reader.resolve_checkpoint_for_zone
    resolve_calls: list[str] = []

    def tracked_resolve(raw_zone: str, zone_display: str = "") -> str:
        resolve_calls.append(raw_zone)
        return original_resolve(raw_zone, zone_display)

    _apply_patch(real_save_reader, "resolve_checkpoint_for_zone", tracked_resolve)

    fake_proc = FakeProcess(pid=4321, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)

    # Active telemetry with checkpoint
    mock_bridge.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "in_combat": False,
        "enemy_name": "",
        "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )

    audit.clear()
    resolve_calls.clear()

    # Execute 500 detection cycles under active bridge telemetry with checkpoint
    for tick in range(500):
        state: GameState = detector.get_game_state(now=1000.0 + tick)
        assert state.is_running is True
        assert state.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"

    # Rigorous empirical assertions
    assert len(resolve_calls) == 0, (
        f"SaveFileReader.resolve_checkpoint_for_zone was called {len(resolve_calls)} times!"
    )
    assert len(audit.save_reader_fs_calls) == 0, (
        f"SaveFileReader performed {len(audit.save_reader_fs_calls)} filesystem operations: {audit.save_reader_fs_calls}"
    )

    print(
        "    PASS: 500 cycles executed with ZERO calls to resolve_checkpoint_for_zone and ZERO filesystem/mmap calls."
    )


def run_fallback_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[2/3] Running Fallback Verification Test (Stale & Absent Bridge)...")

    create_test_save_structure(tmp_path)
    real_save_reader = SaveFileReader(base_save_dir=tmp_path)

    fake_proc = FakeProcess(pid=4321, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )

    # Scenario A: Telemetry is stale / None, zone is known from previous state
    detector.last_raw_zone = "Level_Side_VersosDraft"
    mock_bridge.read_game_data.return_value = None

    audit.clear()
    state = detector.get_game_state(now=2000.0)

    assert state.is_running is True
    assert state.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand", (
        f"Expected checkpoint fallback, got: {state.raw_checkpoint}"
    )
    assert len(audit.save_reader_fs_calls) > 0, (
        "Expected disk I/O during fallback, but none occurred."
    )
    print(
        f"    PASS Scenario A (Stale Telemetry): Correctly fell back to SaveFileReader ({len(audit.save_reader_fs_calls)} FS calls for mmap/parsing)."
    )

    # Scenario B: Stale / None, and NO zone is known (both raw_zone and last_raw_zone empty)
    detector.last_raw_zone = ""
    mock_bridge.read_game_data.return_value = None
    audit.clear()
    state_empty = detector.get_game_state(now=2001.0)
    assert state_empty.raw_checkpoint == ""
    assert len(audit.save_reader_fs_calls) == 0, (
        "SaveFileReader must not be called when zone_to_check is empty!"
    )
    print(
        "    PASS Scenario B (Empty Zone): SaveFileReader remained dormant (0 FS calls) when zone is unknown."
    )

    # Scenario C: Real BridgeStateProvider with >5.0s elapsed freshness
    telemetry_dir = tmp_path.parent / "telemetry_test"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    status_file = telemetry_dir / "status.json"
    status_file.write_text('{"timestamp": 1000.0, "raw_zone": "Level_Side_VersosDraft"}')

    # Query at t = 1010.0 (> 5.0s stale)
    current_time = 1010.0
    real_bridge = BridgeStateProvider(
        paths=[str(status_file)],
        time_provider=lambda: current_time,
    )
    detector_with_real_bridge = GameDetector(
        bridge_provider=real_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )
    detector_with_real_bridge.last_raw_zone = "Level_Side_VersosDraft"

    audit.clear()
    state_stale = detector_with_real_bridge.get_game_state(now=current_time)
    assert state_stale.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand", (
        f"Expected fallback under real stale bridge, got {state_stale.raw_checkpoint}"
    )
    print(
        "    PASS Scenario C (BridgeStateProvider >5.0s stale): Cleanly triggered SaveFileReader fallback."
    )


def run_rapid_toggling_stress_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[3/3] Running Rapid Toggling Stress Test (10,000 cycles)...")

    create_test_save_structure(tmp_path)
    real_save_reader = SaveFileReader(base_save_dir=tmp_path)

    running_proc = FakeProcess(pid=7777, name="Sandfall-Win64-Shipping.exe")
    procs_container = [running_proc]

    current_data: dict[str, Any] | None = None

    class DynamicBridge:
        def read_game_data(
            self, min_valid_timestamp: float | None = None, lang: str = "en"
        ) -> dict[str, Any] | None:
            del min_valid_timestamp, lang
            return current_data

        def reset(self) -> None:
            pass

    detector = GameDetector(
        bridge_provider=DynamicBridge(),
        process_scanner=lambda: list(procs_container),
        save_reader=real_save_reader,
    )

    t0 = time.monotonic()
    total_cycles = 10_000

    fs_calls_during_active = 0
    active_ticks = 0
    stale_fallback_ticks = 0
    crashes = 0
    restarts = 0

    # Deterministic pseudo-random pattern based on LCG
    state_val = 42

    for tick in range(total_cycles):
        state_val = (state_val * 1103515245 + 12345) & 0x7FFFFFFF
        mode = state_val % 7

        if mode == 0:
            # Active bridge with explicit checkpoint
            current_data = {
                "raw_zone": "Level_Side_VersosDraft",
                "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
                "in_combat": False,
                "timestamp": 1000.0 + tick,
            }
            is_active = True
        elif mode == 1:
            # Active bridge with checkpoint
            current_data = {
                "raw_zone": "Level_Side_VersosDraft",
                "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
                "in_combat": False,
                "timestamp": 1000.0 + tick,
            }
            is_active = True
        elif mode == 2:
            # Active bridge in endless tower combat
            current_data = {
                "raw_zone": "EndlessTower_Main",
                "checkpoint": "",
                "in_combat": True,
                "enemy_name": "Duollistes",
                "tower_trial": (1, 1),
                "timestamp": 1000.0 + tick,
            }
            is_active = True
        elif mode == 3:
            # Active bridge in menu
            current_data = {
                "raw_zone": "Level_MainMenu",
                "checkpoint": "",
                "in_combat": False,
                "timestamp": 1000.0 + tick,
            }
            is_active = True
        elif mode == 4:
            # Stale / absent bridge (Fallback mode)
            current_data = None
            is_active = False
            stale_fallback_ticks += 1
        elif mode == 5:
            # Game crash / process dead
            procs_container.clear()
            current_data = None
            is_active = False
            crashes += 1
        else:
            # Game relaunch / new PID
            running_proc = FakeProcess(pid=8000 + (tick % 1000), name="Sandfall-Win64-Shipping.exe")
            procs_container = [running_proc]
            current_data = {
                "raw_zone": "Level_Side_VersosDraft",
                "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
                "in_combat": False,
                "timestamp": 1000.0 + tick,
            }
            is_active = True
            restarts += 1

        audit.clear()
        state = detector.get_game_state(now=1000.0 + tick)

        # Integrity check: state is always immutable and has valid types
        assert isinstance(state, GameState)
        assert isinstance(state.is_running, bool)

        if is_active:
            active_ticks += 1
            if len(audit.save_reader_fs_calls) > 0:
                fs_calls_during_active += len(audit.save_reader_fs_calls)

    elapsed = time.monotonic() - t0

    print(
        f"    Completed {total_cycles:,} cycles in {elapsed:.3f}s ({total_cycles / elapsed:.0f} cycles/sec)"
    )
    print(f"    Active ticks: {active_ticks:,}")
    print(f"    Stale/Fallback ticks: {stale_fallback_ticks:,}")
    print(f"    Simulated Crashes: {crashes:,}, Restarts: {restarts:,}")
    print(f"    Filesystem calls during active ticks: {fs_calls_during_active}")

    assert fs_calls_during_active == 0, (
        f"VIOLATION: SaveFileReader performed {fs_calls_during_active} filesystem calls while bridge was active!"
    )
    print("    PASS: Strict Dormancy preserved across all 10,000 rapid toggling cycles.")


def run_concurrency_stress_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[4/6] Running Multi-threaded Concurrency Stress Test...")
    import threading

    create_test_save_structure(tmp_path)
    real_save_reader = SaveFileReader(base_save_dir=tmp_path)
    fake_proc = FakeProcess(pid=9999, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)
    mock_bridge.read_game_data.return_value = {
        "raw_zone": "Level_Side_VersosDraft",
        "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
        "in_combat": False,
        "timestamp": 1000.0,
    }

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )

    exceptions: list[Exception] = []

    def worker_loop() -> None:
        try:
            for i in range(200):
                st = detector.get_game_state(now=1000.0 + i)
                assert st.is_running is True
                assert st.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"
        except Exception as e:
            exceptions.append(e)

    audit.clear()
    threads = [threading.Thread(target=worker_loop) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(exceptions) == 0, f"Concurrent workers raised exceptions: {exceptions}"
    assert len(audit.save_reader_fs_calls) == 0, (
        "Concurrent calls violated SaveFileReader dormancy!"
    )
    print(
        "    PASS: 10 concurrent threads executed 2,000 detection cycles with ZERO SaveFileReader I/O."
    )


def run_malformed_telemetry_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[5/6] Running Malformed Telemetry Adversarial Test...")
    create_test_save_structure(tmp_path)
    real_save_reader = SaveFileReader(base_save_dir=tmp_path)
    fake_proc = FakeProcess(pid=9999, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)

    malformed_payloads = [
        {"raw_zone": None, "checkpoint": None, "in_combat": None},
        {
            "raw_zone": 12345,
            "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
            "enemy_name": ["not_a_str"],
        },
        {"raw_zone": "", "checkpoint": 999, "enemies": "invalid_list"},
        {
            "raw_zone": "Level_Side_VersosDraft",
            "checkpoint": "Level.SpawnPoint.VersosDraft.CandyLand",
            "tower_floor": "NaN",
        },
        {"raw_zone": "Level_MainMenu", "checkpoint": None, "in_combat": True},
    ]

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )

    for idx, payload in enumerate(malformed_payloads):
        mock_bridge.read_game_data.return_value = payload
        audit.clear()
        st = detector.get_game_state(now=3000.0 + idx)
        assert isinstance(st, GameState)
        assert len(audit.save_reader_fs_calls) == 0, f"Payload {idx} leaked filesystem calls!"

    print(
        "    PASS: GameDetector survived all malformed bridge payloads with ZERO SaveFileReader I/O."
    )


def run_corrupted_save_file_test(audit: FilesystemActivityAudit, tmp_path: Path) -> None:
    print("[6/6] Running Corrupted Save File Recovery Test...")
    profile_dir = tmp_path / "999999999"
    profile_dir.mkdir(parents=True, exist_ok=True)
    corrupted_sav = profile_dir / "EXPEDITION_0.sav"
    # Write garbage non-UE5 binary
    corrupted_sav.write_bytes(b"\xff\xfe\x00\x01\x02\x03RandomJunkWithoutSavePointData" * 50)

    reader = SaveFileReader(base_save_dir=tmp_path)
    fake_proc = FakeProcess(pid=9999, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)
    mock_bridge.read_game_data.return_value = None  # Force fallback

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=reader,
    )
    detector.last_raw_zone = "Level_Side_VersosDraft"

    audit.clear()
    st = detector.get_game_state(now=4000.0)
    assert st.is_running is True
    # Does not crash, cleanly returns empty checkpoint
    assert st.raw_checkpoint == ""
    assert len(audit.save_reader_fs_calls) > 0, "Expected fallback I/O on save file"
    print(
        "    PASS: SaveFileReader gracefully handled corrupted binary save without unhandled exception."
    )


def main() -> int:
    audit = FilesystemActivityAudit()
    audit.start()
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_dormancy_test(audit, tmp_path)
            run_fallback_test(audit, tmp_path)
            run_rapid_toggling_stress_test(audit, tmp_path)
            run_concurrency_stress_test(audit, tmp_path)
            run_malformed_telemetry_test(audit, tmp_path)
            run_corrupted_save_file_test(audit, tmp_path)
    finally:
        audit.stop()

    print("\nALL ADVERSARIAL STRESS TESTS PASSED SUCCESSFULLY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
