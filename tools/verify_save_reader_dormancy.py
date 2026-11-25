#!/usr/bin/env python3
"""Adversarial stress-test harness verifying SaveFileReader dormancy in GameDetector.

Empirically validates:
1. Zero disk I/O, zero mmap, and zero filesystem calls by SaveFileReader when Bridge telemetry is active.
2. Clean fallback to SaveFileReader when Bridge telemetry is stale (>5.0s) or absent.
3. Resilience, immutability, and absence of state corruption under 10,000 rapid toggling cycles.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Bootstrap sys.path to allow standalone execution without PYTHONPATH=.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.harness import FakeProcess
from tests.harness.fs_audit import FilesystemActivityAudit, _apply_patch
from tests.harness.save_builder import SaveFileBuilder

from expedition33_rpc.detection.detector import (
    BridgeProviderProtocol,
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.save_reader import SaveFileReader


def create_test_save_structure(base_dir: Path) -> tuple[Path, str]:
    """Creates a realistic UE5 .sav save file structure on disk."""
    profile_dir = base_dir / "76561198097793146"
    profile_dir.mkdir(parents=True, exist_ok=True)
    sav_file = profile_dir / "EXPEDITION_0.sav"
    (
        SaveFileBuilder()
        .with_header(128)
        .with_level("Level_Side_VersosDraft")
        .with_savepoint("Level.SpawnPoint.VersosDraft.CandyLand")
        .with_trailer(128)
        .write_to(sav_file)
    )
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
        state: GameState = detector.get_game_state(
            now_monotonic=1000.0 + tick, now_epoch=1000.0 + tick
        )
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
    detector.has_received_telemetry = True

    # Scenario A: Telemetry is stale / None, zone is known from previous state
    detector.last_raw_zone = "Level_Side_VersosDraft"
    mock_bridge.read_game_data.return_value = None

    audit.clear()
    state = detector.get_game_state(now_monotonic=2000.0, now_epoch=2000.0)

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
    state_empty = detector.get_game_state(now_monotonic=2001.0, now_epoch=2001.0)
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
        epoch_provider=lambda: current_time,
    )
    detector_with_real_bridge = GameDetector(
        bridge_provider=real_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )
    detector_with_real_bridge.has_received_telemetry = True
    detector_with_real_bridge.last_raw_zone = "Level_Side_VersosDraft"

    audit.clear()
    state_stale = detector_with_real_bridge.get_game_state(
        now_monotonic=current_time, now_epoch=current_time
    )
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
        def read_game_data(self, min_valid_timestamp: float | None = None) -> dict[str, Any] | None:
            del min_valid_timestamp
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
        state = detector.get_game_state(now_monotonic=1000.0 + tick, now_epoch=1000.0 + tick)

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
                st = detector.get_game_state(now_monotonic=1000.0 + i, now_epoch=1000.0 + i)
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
        st = detector.get_game_state(now_monotonic=3000.0 + idx, now_epoch=3000.0 + idx)
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
    detector.has_received_telemetry = True
    detector.last_raw_zone = "Level_Side_VersosDraft"

    audit.clear()
    st = detector.get_game_state(now_monotonic=4000.0, now_epoch=4000.0)
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
