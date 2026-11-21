"""Unit tests for SteamCompatResolver instance methods and cross-platform telemetry/prefix resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from expedition33_rpc.detection.steam_resolver import (
    DEFAULT_STEAM_APP_ID,
    SteamCompatResolver,
)

pytestmark = pytest.mark.unit


def test_telemetry_file_paths_windows_defaults() -> None:
    resolver = SteamCompatResolver(is_windows=True)
    paths = resolver.resolve_telemetry_candidates()
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

    resolver = SteamCompatResolver(is_windows=False, home_dir=fake_home)
    paths = resolver.resolve_telemetry_candidates()
    assert any("1903340" in p for p in paths)
    assert str(status_file) in paths or os.path.normpath(str(status_file)) in paths

    # Test custom app_id parameter
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

    custom_resolver = SteamCompatResolver(
        app_id=custom_app_id, is_windows=False, home_dir=fake_home
    )
    custom_paths = custom_resolver.resolve_telemetry_candidates()
    assert any(custom_app_id in p for p in custom_paths)
    assert str(custom_file) in custom_paths or os.path.normpath(str(custom_file)) in custom_paths


def test_telemetry_file_paths_linux_wineprefix_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_wineprefix = tmp_path / "wineprefix"
    target_temp = fake_wineprefix / "drive_c" / "users" / "steamuser" / "Temp"
    target_temp.mkdir(parents=True)
    target_file = target_temp / "expedition33_status.json"
    target_file.write_text('{"zone": "OldLumiere"}', encoding="utf-8")

    monkeypatch.setenv("WINEPREFIX", str(fake_wineprefix))
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_telemetry_candidates()
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)


def test_telemetry_file_paths_linux_steam_compat_data_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_compat_root = tmp_path / "compat_override"
    target_temp = fake_compat_root / "pfx" / "drive_c" / "users" / "steamuser" / "Temp"
    target_temp.mkdir(parents=True)
    target_file = target_temp / "expedition33_status.json"
    target_file.write_text('{"zone": "FlyingManor"}', encoding="utf-8")

    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", str(fake_compat_root))
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_telemetry_candidates()
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)


def test_telemetry_file_paths_linux_fallback_to_tmp(tmp_path: Path) -> None:
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "nonexistent")
    paths = resolver.resolve_telemetry_candidates()
    assert any("/tmp/expedition33_status.json" in p.replace("\\", "/") for p in paths)


def test_config_file_paths_windows_defaults() -> None:
    resolver = SteamCompatResolver(is_windows=True)
    paths = resolver.resolve_config_candidates()
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

    resolver = SteamCompatResolver(is_windows=False, home_dir=fake_home)
    paths = resolver.resolve_config_candidates()
    assert str(ini_file) in paths or os.path.normpath(str(ini_file)) in paths


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
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_config_candidates()
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)


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
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_config_candidates()
    assert any(str(target_file) in p or os.path.normpath(str(target_file)) in p for p in paths)


def test_save_games_paths_windows_defaults() -> None:
    resolver = SteamCompatResolver(is_windows=True)
    paths = resolver.resolve_save_games_candidates()
    assert len(paths) == 1
    assert any("SaveGames" in p for p in paths)


def test_save_games_paths_linux_proton_structure(tmp_path: Path) -> None:
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
    save_dir = (
        steam_compat
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "SaveGames"
    )
    save_dir.mkdir(parents=True)

    resolver = SteamCompatResolver(is_windows=False, home_dir=fake_home)
    paths = resolver.resolve_save_games_candidates()
    assert any(str(save_dir) in p or os.path.normpath(str(save_dir)) in p for p in paths)


def test_save_games_paths_linux_wineprefix_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_wineprefix = tmp_path / "wineprefix"
    target_dir = (
        fake_wineprefix
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "SaveGames"
    )
    target_dir.mkdir(parents=True)

    monkeypatch.setenv("WINEPREFIX", str(fake_wineprefix))
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_save_games_candidates()
    assert any(str(target_dir) in p or os.path.normpath(str(target_dir)) in p for p in paths)


def test_save_games_paths_linux_steam_compat_data_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_compat_root = tmp_path / "compat_override"
    target_dir = (
        fake_compat_root
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "SaveGames"
    )
    target_dir.mkdir(parents=True)

    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", str(fake_compat_root))
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "empty_home")
    paths = resolver.resolve_save_games_candidates()
    assert any(str(target_dir) in p or os.path.normpath(str(target_dir)) in p for p in paths)


def test_save_games_paths_linux_fallback(tmp_path: Path) -> None:
    resolver = SteamCompatResolver(is_windows=False, home_dir=tmp_path / "nonexistent")
    paths = resolver.resolve_save_games_candidates()
    assert any(".config" in p and "SaveGames" in p for p in paths)
