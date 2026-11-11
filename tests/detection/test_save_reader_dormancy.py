"""Automated Tier 2 integration tests for SaveFileReader dormancy in GameDetector.

Enforces the dormancy invariant:
1. Zero disk I/O, zero mmap, and zero filesystem calls on .sav files or from SaveFileReader
   during active telemetry (< 5.0s TTL).
2. Clean fallback to SaveFileReader when telemetry is stale (> 5.0s TTL) or absent.
3. Dormancy preservation during Endless Tower, Main Menu, Continent, and startup states.
4. Clean restoration of all 12 intercepted filesystem functions with zero global side-effects.
5. Adversarial mutation rejection when fraudulent .sav reads occur during active telemetry.
"""

from __future__ import annotations

import builtins
import contextlib
import inspect
import json
import mmap
import os
import pathlib
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock, patch

import pytest
from tests.harness.fake_process import FakeProcess
from tests.harness.game_session import GameSessionSimulator

from expedition33_rpc.detection.detector import (
    BridgeProviderProtocol,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.save_reader import SaveFileReader

type FsViolation = dict[str, Any]

# 12 Target functions to monitor for filesystem calls originating from save_reader.py or on .sav files
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_MMAP = mmap.mmap
_ORIGINAL_PATH_STAT = pathlib.Path.stat
_ORIGINAL_PATH_ITERDIR = pathlib.Path.iterdir
_ORIGINAL_PATH_GLOB = pathlib.Path.glob
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
    """Audits filesystem syscalls to enforce SaveFileReader dormancy and detect illegal .sav accesses."""

    def __init__(self) -> None:
        self.save_reader_fs_calls: list[FsViolation] = []
        self.sav_file_accesses: list[FsViolation] = []
        self.violations: list[FsViolation] = []
        self._sav_fds: set[int] = set()
        self._installed: bool = False

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _is_from_save_reader(self) -> bool:
        # Check call stack for save_reader.py frame
        frame = inspect.currentframe()
        try:
            cur = frame.f_back.f_back if frame and frame.f_back else None
            while cur is not None:
                fname = cur.f_code.co_filename
                if "save_reader.py" in fname:
                    return True
                cur = cur.f_back
        finally:
            del frame
        return False

    def _is_sav_target(self, *args: Any) -> bool:
        for arg in args:
            if isinstance(arg, int) and arg in self._sav_fds:
                return True
            if isinstance(arg, (str, bytes, os.PathLike)):
                p = (
                    os.fspath(arg)
                    if not isinstance(arg, bytes)
                    else arg.decode("latin1", "replace")
                )
                p_lower = p.lower()
                if p_lower.endswith(".sav") or ".sav" in p_lower:
                    return True
        return False

    def _record(self, func_name: str, *args: Any) -> None:
        from_save_reader = self._is_from_save_reader()
        is_sav = self._is_sav_target(*args)
        if from_save_reader or is_sav:
            entry: FsViolation = {"func": func_name, "args": args}
            self.violations.append(entry)
            if from_save_reader:
                self.save_reader_fs_calls.append(entry)
            if is_sav:
                self.sav_file_accesses.append(entry)

    def start(self) -> None:
        if self._installed:
            return
        audit = self

        def hooked_open(*args: Any, **kwargs: Any) -> Any:
            audit._record("open", *args)
            handle = _ORIGINAL_OPEN(*args, **kwargs)
            if audit._is_sav_target(*args):
                with contextlib.suppress(Exception):
                    audit._sav_fds.add(handle.fileno())
            return handle

        def hooked_mmap(*args: Any, **kwargs: Any) -> Any:
            audit._record("mmap", *args)
            return _ORIGINAL_MMAP(*args, **kwargs)

        def hooked_path_stat(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.stat", str(self_path), *args)
            return _ORIGINAL_PATH_STAT(self_path, *args, **kwargs)

        def hooked_path_iterdir(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.iterdir", str(self_path), *args)
            return _ORIGINAL_PATH_ITERDIR(self_path, *args, **kwargs)

        def hooked_path_glob(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.glob", str(self_path), *args)
            return _ORIGINAL_PATH_GLOB(self_path, *args, **kwargs)

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
        _apply_patch(pathlib.Path, "stat", hooked_path_stat)
        _apply_patch(pathlib.Path, "iterdir", hooked_path_iterdir)
        _apply_patch(pathlib.Path, "glob", hooked_path_glob)
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
        _apply_patch(pathlib.Path, "stat", _ORIGINAL_PATH_STAT)
        _apply_patch(pathlib.Path, "iterdir", _ORIGINAL_PATH_ITERDIR)
        _apply_patch(pathlib.Path, "glob", _ORIGINAL_PATH_GLOB)
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
        self.sav_file_accesses.clear()
        self.violations.clear()
        self._sav_fds.clear()


@pytest.fixture
def fs_audit() -> Generator[FilesystemActivityAudit, None, None]:
    """Provides a filesystem interception audit fixture with guaranteed try/finally restoration."""
    audit = FilesystemActivityAudit()
    audit.start()
    try:
        yield audit
    finally:
        audit.stop()


def create_test_save_structure(base_dir: Path) -> tuple[Path, str]:
    """Creates a realistic UE5 .sav save file structure on tmp_path."""
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


@pytest.mark.integration
def test_save_reader_dormancy_active_telemetry_1000_cycles(
    tmp_path: Path, fs_audit: FilesystemActivityAudit
) -> None:
    """1,000 rapid cycles using GameSessionSimulator asserting zero .sav filesystem calls and SLA < 2.5s."""
    saves_dir = tmp_path / "saves"
    create_test_save_structure(saves_dir)
    real_save_reader = SaveFileReader(base_save_dir=saves_dir)

    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    with GameSessionSimulator(base_dir=telemetry_dir) as session:
        session.start_game()
        session.detector.save_reader = real_save_reader

        fs_audit.clear()
        t0 = time.monotonic()

        for tick in range(1000):
            if tick % 3 == 0:
                session.enter_zone(
                    "Level_Side_VersosDraft",
                    checkpoint="Level.SpawnPoint.VersosDraft.CandyLand",
                )
            elif tick % 3 == 1:
                session.trigger_combat(
                    "Duollistes",
                    checkpoint="Level.SpawnPoint.VersosDraft.CandyLand",
                )
            else:
                session.leave_combat(
                    checkpoint="Level.SpawnPoint.VersosDraft.CandyLand",
                )

            state = session.get_game_state()
            assert state.is_running is True
            assert state.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"

        elapsed = time.monotonic() - t0

    assert len(fs_audit.violations) == 0, (
        f"Dormancy invariant violated: {len(fs_audit.violations)} filesystem calls on .sav files "
        f"or from SaveFileReader during active telemetry: {fs_audit.violations}"
    )
    assert len(fs_audit.sav_file_accesses) == 0
    assert len(fs_audit.save_reader_fs_calls) == 0
    assert elapsed < 2.5, f"Execution time {elapsed:.3f}s exceeded 2.5s SLA gate"


@pytest.mark.integration
def test_save_reader_fallback_when_telemetry_stale(
    tmp_path: Path, fs_audit: FilesystemActivityAudit
) -> None:
    """Verify fallback to SaveFileReader when telemetry timestamp > 5.0s, asserting FS calls > 0 and correct checkpoint resolution."""
    saves_dir = tmp_path / "saves"
    create_test_save_structure(saves_dir)
    real_save_reader = SaveFileReader(base_save_dir=saves_dir)

    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    with GameSessionSimulator(base_dir=telemetry_dir) as session:
        session.start_game()
        session.detector.save_reader = real_save_reader

        # Establish initial active telemetry frame so has_received_telemetry is latched to True
        session.enter_zone(
            "Level_Side_VersosDraft",
            checkpoint="Level.SpawnPoint.VersosDraft.CandyLand",
        )
        st0 = session.get_game_state()
        assert st0.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"
        assert session.detector.has_received_telemetry is True

        # Make bridge telemetry stale (> 5.0s elapsed)
        stale_payload = {
            "timestamp": time.time() - 15.0,
            "raw_zone": "Level_Side_VersosDraft",
            "checkpoint": "",
        }
        session.bridge_path.write_text(json.dumps(stale_payload), encoding="utf-8")

        fs_audit.clear()
        state = session.get_game_state()

        assert state.is_running is True
        assert state.raw_checkpoint == "Level.SpawnPoint.VersosDraft.CandyLand"
        assert len(fs_audit.save_reader_fs_calls) > 0, (
            "Expected SaveFileReader filesystem calls during stale telemetry fallback, got 0"
        )
        assert len(fs_audit.sav_file_accesses) > 0


@pytest.mark.integration
def test_save_reader_dormant_during_tower_and_menu(
    tmp_path: Path, fs_audit: FilesystemActivityAudit
) -> None:
    """Verify SaveFileReader dormancy in menu, continent, and tower zones."""
    saves_dir = tmp_path / "saves"
    create_test_save_structure(saves_dir)
    real_save_reader = SaveFileReader(base_save_dir=saves_dir)

    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    with GameSessionSimulator(base_dir=telemetry_dir) as session:
        session.start_game()
        session.detector.save_reader = real_save_reader

        # Main menu zone: SaveFileReader must remain dormant
        session.enter_zone("Level_MainMenu", checkpoint="")
        fs_audit.clear()
        state_menu = session.get_game_state()
        assert state_menu.raw_checkpoint == ""
        assert len(fs_audit.violations) == 0

        # Continent / World map zone: SaveFileReader must remain dormant
        session.enter_zone("Level_WorldMap", checkpoint="")
        fs_audit.clear()
        state_world = session.get_game_state()
        assert state_world.raw_checkpoint == ""
        assert len(fs_audit.violations) == 0

        # Endless Tower zone: SaveFileReader must remain dormant
        session.enter_zone("Level_EndlessTower", checkpoint="")
        session.trigger_combat("Duollistes", checkpoint="", tower_trial=(1, 1))
        fs_audit.clear()
        state_tower = session.get_game_state()
        assert state_tower.raw_checkpoint == ""
        assert len(fs_audit.violations) == 0


@pytest.mark.integration
def test_save_reader_dormant_during_startup_before_first_telemetry(
    tmp_path: Path, fs_audit: FilesystemActivityAudit
) -> None:
    """Verify dormancy when has_received_telemetry is False."""
    saves_dir = tmp_path / "saves"
    create_test_save_structure(saves_dir)
    real_save_reader = SaveFileReader(base_save_dir=saves_dir)

    fake_proc = FakeProcess(pid=4321, name="Sandfall-Win64-Shipping.exe")
    mock_bridge = MagicMock(spec=BridgeProviderProtocol)
    mock_bridge.read_game_data.return_value = None

    detector = GameDetector(
        bridge_provider=mock_bridge,
        process_scanner=lambda: [fake_proc],
        save_reader=real_save_reader,
    )

    assert detector.has_received_telemetry is False

    fs_audit.clear()
    state = detector.get_game_state()

    assert state.is_running is True
    assert state.is_starting is True
    assert state.raw_checkpoint == ""
    assert detector.has_received_telemetry is False
    assert len(fs_audit.violations) == 0
    assert len(fs_audit.save_reader_fs_calls) == 0
    assert len(fs_audit.sav_file_accesses) == 0


@pytest.mark.integration
def test_adversarial_mutation_sav_read_in_detector_fails(
    tmp_path: Path, fs_audit: FilesystemActivityAudit
) -> None:
    """Intentionally inject a fraudulent .sav read into GameDetector during active telemetry and assert that the test fails with an informative assertion matching the .sav path."""
    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    sav_target = tmp_path / "EXPEDITION_0.sav"
    sav_target.write_bytes(b"fraudulent_payload")

    with GameSessionSimulator(base_dir=telemetry_dir) as session:
        session.start_game()
        session.enter_zone(
            "Level_Side_VersosDraft",
            checkpoint="Level.SpawnPoint.VersosDraft.CandyLand",
        )
        detector = session.detector

        real_get_game_state = detector.get_game_state

        def fraudulent_get_game_state(*args: Any, **kwargs: Any) -> GameState:
            # Adversarial mutation: fraudulent .sav read inside detector during active telemetry
            with open(sav_target, "rb") as f:
                _ = f.read()
            return real_get_game_state(*args, **kwargs)

        with patch.object(detector, "get_game_state", side_effect=fraudulent_get_game_state):
            fs_audit.clear()
            state = detector.get_game_state()
            assert state.is_running is True

            assert len(fs_audit.violations) > 0
            assert any("EXPEDITION_0.sav" in str(v.get("args", ())) for v in fs_audit.violations)

            with pytest.raises(AssertionError, match=r"EXPEDITION_0\.sav"):
                assert len(fs_audit.violations) == 0, (
                    f"Dormancy invariant violated: {len(fs_audit.violations)} filesystem calls on .sav files "
                    f"or from SaveFileReader during active telemetry: {fs_audit.violations}"
                )


@pytest.mark.integration
def test_filesystem_interception_fixture_clean_restoration(
    fs_audit: FilesystemActivityAudit,
) -> None:
    """Assert that all 12 intercepted functions are 100% restored to their original references (is _ORIGINAL_*)."""
    # While fs_audit is started, all 12 functions must be patched
    assert builtins.open is not _ORIGINAL_OPEN
    assert mmap.mmap is not _ORIGINAL_MMAP
    assert pathlib.Path.stat is not _ORIGINAL_PATH_STAT
    assert pathlib.Path.iterdir is not _ORIGINAL_PATH_ITERDIR
    assert pathlib.Path.glob is not _ORIGINAL_PATH_GLOB
    assert pathlib.Path.exists is not _ORIGINAL_PATH_EXISTS
    assert pathlib.Path.is_file is not _ORIGINAL_PATH_IS_FILE
    assert pathlib.Path.is_dir is not _ORIGINAL_PATH_IS_DIR
    assert os.stat is not _ORIGINAL_OS_STAT
    assert os.path.exists is not _ORIGINAL_OS_EXISTS
    assert os.path.isfile is not _ORIGINAL_OS_ISFILE
    assert os.path.isdir is not _ORIGINAL_OS_ISDIR

    # When stopped, all 12 functions must be restored to their original references
    fs_audit.stop()

    assert builtins.open is _ORIGINAL_OPEN
    assert mmap.mmap is _ORIGINAL_MMAP
    assert pathlib.Path.stat is _ORIGINAL_PATH_STAT
    assert pathlib.Path.iterdir is _ORIGINAL_PATH_ITERDIR
    assert pathlib.Path.glob is _ORIGINAL_PATH_GLOB
    assert pathlib.Path.exists is _ORIGINAL_PATH_EXISTS
    assert pathlib.Path.is_file is _ORIGINAL_PATH_IS_FILE
    assert pathlib.Path.is_dir is _ORIGINAL_PATH_IS_DIR
    assert os.stat is _ORIGINAL_OS_STAT
    assert os.path.exists is _ORIGINAL_OS_EXISTS
    assert os.path.isfile is _ORIGINAL_OS_ISFILE
    assert os.path.isdir is _ORIGINAL_OS_ISDIR
