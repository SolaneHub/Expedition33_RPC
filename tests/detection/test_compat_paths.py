"""Unit tests for cross-platform telemetry path resolution and Proton/Wine prefix discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from expedition33_rpc.detection.compat_paths import (
    DEFAULT_STEAM_APP_ID,
    get_config_file_paths,
    get_game_user_settings_path,
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
    assert DEFAULT_STEAM_APP_ID == "1903340"
    fake_home = tmp_path / "home" / "deck"
    steam_compat = (
        fake_home / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / "1903340" / "pfx"
    )
    temp_dir = steam_compat / "drive_c" / "users" / "steamuser" / "Temp"
    temp_dir.mkdir(parents=True)
    status_file = temp_dir / "expedition33_status.json"
    status_file.write_text('{"in_combat": true}', encoding="utf-8")

    paths = get_telemetry_file_paths(is_windows=False, home_dir=fake_home)
    assert any("1903340" in p for p in paths)
    assert str(status_file) in paths or os.path.normpath(str(status_file)) in paths

    resolved = get_telemetry_file_path(is_windows=False, home_dir=fake_home)
    assert "1903340" in resolved
    assert os.path.normpath(resolved) == os.path.normpath(str(status_file))

    # Test custom steam_app_id parameter
    custom_app_id = "999999"
    custom_compat = (
        fake_home
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
        / custom_app_id
        / "pfx"
    )
    custom_temp = custom_compat / "drive_c" / "users" / "steamuser" / "Temp"
    custom_temp.mkdir(parents=True)
    custom_file = custom_temp / "expedition33_status.json"
    custom_file.write_text('{"in_combat": false}', encoding="utf-8")

    custom_paths = get_telemetry_file_paths(
        app_id=custom_app_id, is_windows=False, home_dir=fake_home
    )
    assert any(custom_app_id in p for p in custom_paths)
    custom_resolved = get_telemetry_file_path(
        app_id=custom_app_id, is_windows=False, home_dir=fake_home
    )
    assert custom_app_id in custom_resolved
    assert os.path.normpath(custom_resolved) == os.path.normpath(str(custom_file))


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


def test_config_file_paths_windows_defaults() -> None:
    paths = get_config_file_paths(is_windows=True)
    assert len(paths) == 2
    assert any("GameUserSettings.ini" in p for p in paths)
    assert any("Windows" in p for p in paths)
    assert any("WindowsNoEditor" in p for p in paths)


def test_config_file_paths_linux_proton_structure(tmp_path: Path) -> None:
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
    cfg_dir = (
        steam_compat
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "Config"
        / "Windows"
    )
    cfg_dir.mkdir(parents=True)
    ini_file = cfg_dir / "GameUserSettings.ini"
    ini_file.write_text("[Internationalization]\nLanguage=it\n", encoding="utf-8")

    paths = get_config_file_paths(is_windows=False, home_dir=fake_home)
    assert str(ini_file) in paths or os.path.normpath(str(ini_file)) in paths

    resolved = get_game_user_settings_path(is_windows=False, home_dir=fake_home)
    assert resolved is not None
    assert os.path.normpath(resolved) == os.path.normpath(str(ini_file))


def test_config_file_paths_linux_wineprefix_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_wineprefix = tmp_path / "wineprefix"
    target_cfg = (
        fake_wineprefix
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "Config"
        / "Windows"
    )
    target_cfg.mkdir(parents=True)
    target_file = target_cfg / "GameUserSettings.ini"
    target_file.write_text("[Internationalization]\nLanguage=de\n", encoding="utf-8")

    monkeypatch.setenv("WINEPREFIX", str(fake_wineprefix))
    paths = get_config_file_paths(is_windows=False, home_dir=tmp_path / "empty_home")
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)

    resolved = get_game_user_settings_path(is_windows=False, home_dir=tmp_path / "empty_home")
    assert resolved is not None
    assert os.path.normpath(resolved) == os.path.normpath(str(target_file))


def test_config_file_paths_linux_steam_compat_data_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_compat_root = tmp_path / "compat_override"
    target_cfg = (
        fake_compat_root
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "Config"
        / "WindowsNoEditor"
    )
    target_cfg.mkdir(parents=True)
    target_file = target_cfg / "GameUserSettings.ini"
    target_file.write_text("[Internationalization]\nLanguage=fr\n", encoding="utf-8")

    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", str(fake_compat_root))
    paths = get_config_file_paths(is_windows=False, home_dir=tmp_path / "empty_home")
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)

    resolved = get_game_user_settings_path(is_windows=False, home_dir=tmp_path / "empty_home")
    assert resolved is not None
    assert os.path.normpath(resolved) == os.path.normpath(str(target_file))


def test_get_game_user_settings_path_custom_override() -> None:
    custom = "/custom/override/path/GameUserSettings.ini"
    assert get_game_user_settings_path(custom_path=custom) == custom


def test_get_game_user_settings_path_fallback() -> None:
    resolved = get_game_user_settings_path(is_windows=True)
    assert resolved is not None
    assert "GameUserSettings.ini" in resolved
