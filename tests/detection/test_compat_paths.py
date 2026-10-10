"""Unit tests for cross-platform telemetry path resolution and Proton/Wine prefix discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from expedition33_rpc.detection.compat_paths import (
    DEFAULT_STEAM_APP_ID,
    get_telemetry_file_path,
    get_telemetry_file_paths,
)

pytestmark = pytest.mark.unit


def test_telemetry_file_paths_windows_defaults() -> None:
    paths = get_telemetry_file_paths(is_windows=True)
    assert len(paths) == 2
    assert any("expedition33_status.json" in p for p in paths)
    assert any("rpc_status.json" in p for p in paths)


def test_telemetry_file_paths_linux_proton_structure(tmp_path: Path) -> None:
    fake_home = tmp_path / "home" / "deck"
    steam_compat = (
        fake_home
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
        / DEFAULT_STEAM_APP_ID
        / "pfx"
    )
    temp_dir = steam_compat / "drive_c" / "users" / "steamuser" / "Temp"
    temp_dir.mkdir(parents=True)
    status_file = temp_dir / "expedition33_status.json"
    status_file.write_text('{"in_combat": true}', encoding="utf-8")

    paths = get_telemetry_file_paths(is_windows=False, home_dir=fake_home)
    assert str(status_file) in paths or os.path.normpath(str(status_file)) in paths

    resolved = get_telemetry_file_path(is_windows=False, home_dir=fake_home)
    assert os.path.normpath(resolved) == os.path.normpath(str(status_file))


def test_telemetry_file_paths_linux_wineprefix_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_wineprefix = tmp_path / "wineprefix"
    target_temp = fake_wineprefix / "drive_c" / "users" / "steamuser" / "Temp"
    target_temp.mkdir(parents=True)
    target_file = target_temp / "expedition33_status.json"
    target_file.write_text('{"zone": "OldLumiere"}', encoding="utf-8")

    monkeypatch.setenv("WINEPREFIX", str(fake_wineprefix))
    paths = get_telemetry_file_paths(is_windows=False, home_dir=tmp_path / "empty_home")
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)

    resolved = get_telemetry_file_path(is_windows=False, home_dir=tmp_path / "empty_home")
    assert os.path.normpath(resolved) == os.path.normpath(str(target_file))


def test_telemetry_file_paths_linux_steam_compat_data_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_compat_root = tmp_path / "compat_override"
    target_temp = fake_compat_root / "pfx" / "drive_c" / "users" / "steamuser" / "Temp"
    target_temp.mkdir(parents=True)
    target_file = target_temp / "expedition33_status.json"
    target_file.write_text('{"zone": "FlyingManor"}', encoding="utf-8")

    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", str(fake_compat_root))
    paths = get_telemetry_file_paths(is_windows=False, home_dir=tmp_path / "empty_home")
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)

    resolved = get_telemetry_file_path(is_windows=False, home_dir=tmp_path / "empty_home")
    assert os.path.normpath(resolved) == os.path.normpath(str(target_file))


def test_telemetry_file_paths_linux_fallback_to_tmp(tmp_path: Path) -> None:
    paths = get_telemetry_file_paths(is_windows=False, home_dir=tmp_path / "nonexistent")
    assert any("/tmp/expedition33_status.json" in p.replace("\\", "/") for p in paths)


def test_get_telemetry_file_path_custom_override() -> None:
    custom = "/custom/override/path/status.json"
    assert get_telemetry_file_path(custom_path=custom) == custom
