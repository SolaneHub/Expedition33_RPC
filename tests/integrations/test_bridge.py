"""Tests for UE4SS Bridge contract, payload parsing, and installation."""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.detector import BridgeStateProvider
from expedition33_rpc.integrations import bridge_installer
from expedition33_rpc.integrations.bridge_installer import (
    find_game_win64_directory,
    install_bridge,
    is_bridge_installed,
    uninstall_bridge,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Bridge Mod Contract & ZIP Packaging Tests
# ---------------------------------------------------------------------------


def test_bridge_zip_contains_required_runtime_files() -> None:
    bridge_zip_path = Path(get_resource_path("bridge.zip"))
    assert bridge_zip_path.is_file(), f"bridge.zip must exist at {bridge_zip_path}"

    with zipfile.ZipFile(bridge_zip_path, "r") as z:
        names = set(z.namelist())
        expected = {
            "dwmapi.dll",
            "ue4ss/UE4SS.dll",
            "ue4ss/UE4SS-settings.ini",
            "ue4ss/Mods/mods.txt",
            "ue4ss/Mods/Expedition33RPC/scripts/main.lua",
        }
        for exp in expected:
            assert exp in names, f"bridge.zip is missing essential file: {exp}"


def test_bridge_lua_script_emits_expected_json_contract() -> None:
    """Contract test: verifies that main.lua inside bridge.zip emits the required JSON keys."""
    bridge_zip_path = Path(get_resource_path("bridge.zip"))
    with zipfile.ZipFile(bridge_zip_path, "r") as z:
        lua_content = z.read("ue4ss/Mods/Expedition33RPC/scripts/main.lua").decode("utf-8")

    # Required keys that the Python BridgeStateProvider expects
    required_keys = [
        "in_combat",
        "enemy_name",
        "enemies",
        "zone",
        "checkpoint",
        "tower_floor",
        "tower_trial",
        "timestamp",
    ]
    for key in required_keys:
        pattern = rf'"{key}"\s*:'
        assert re.search(pattern, lua_content), f"main.lua does not emit required JSON key '{key}'"


def test_bridge_state_provider_parses_lua_emitted_payload(tmp_path: Path) -> None:
    now = time.time()
    sample_payload = {
        "in_combat": True,
        "enemy_name": "Duollistes",
        "enemies": ["Duollistes", "Alpha Gold Chevaliere"],
        "zone": "Level_Main_OldLumiere",
        "checkpoint": "Entrance",
        "tower_floor": 4,
        "tower_trial": [2, 1],
        "timestamp": now,
    }
    status_file = tmp_path / "expedition33_status.json"
    status_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    provider = BridgeStateProvider(paths=[str(status_file)])
    data = provider.read_game_data(min_valid_timestamp=now - 5.0, lang="en")

    assert data is not None
    assert data["in_combat"] is True
    assert data["enemy_name"] == "Duollistes"
    assert data["enemies"] == ["Duollistes", "Alpha Gold Chevaliere"]
    assert data["raw_zone"] == "Level_Main_OldLumiere"
    assert data["checkpoint"] == "Entrance"
    assert data["tower_floor"] == 4
    assert data["tower_trial"] == (2, 1)


def test_bridge_state_provider_enforces_stale_timestamp_rejection(tmp_path: Path) -> None:
    proc_start = time.time()
    stale_timestamp = proc_start - 30.0
    status_file = tmp_path / "expedition33_status.json"
    status_file.write_text(
        json.dumps(
            {
                "in_combat": False,
                "enemy_name": "",
                "zone": "Level_Main_OldLumiere",
                "checkpoint": "",
                "timestamp": stale_timestamp,
            }
        ),
        encoding="utf-8",
    )

    provider = BridgeStateProvider(paths=[str(status_file)])
    assert provider.read_game_data(min_valid_timestamp=proc_start, lang="en") is None


# ---------------------------------------------------------------------------
# Bridge Installer Surgical Behavior
# ---------------------------------------------------------------------------


def test_fresh_bridge_installation_and_uninstallation(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_binaries"
    game_dir.mkdir(parents=True)

    # 1. Initially not installed
    assert not is_bridge_installed(str(game_dir))

    # 2. Install
    ok, msg = install_bridge(str(game_dir))
    assert ok, f"Install failed: {msg}"
    assert is_bridge_installed(str(game_dir))

    # Verify files created
    assert (game_dir / "dwmapi.dll").is_file()
    mods_txt = game_dir / "ue4ss" / "Mods" / "mods.txt"
    assert mods_txt.is_file()
    assert "Expedition33RPC : 1" in mods_txt.read_text(encoding="utf-8")

    # 3. Uninstall (no other mods) -> removes dwmapi.dll
    ok_u, msg_u = uninstall_bridge(str(game_dir))
    assert ok_u, f"Uninstall failed: {msg_u}"
    assert not is_bridge_installed(str(game_dir))
    assert not (game_dir / "dwmapi.dll").exists()


def test_install_preserves_pre_existing_user_mods_and_settings(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_binaries"
    mods_dir = game_dir / "ue4ss" / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    mods_txt = mods_dir / "mods.txt"
    mods_txt.write_text("CustomCheatsMod : 1\nSomeOtherMod : 1\n", encoding="utf-8")

    custom_ini = game_dir / "ue4ss" / "UE4SS-settings.ini"
    custom_ini.write_text("[Overrides]\nCustomUserConfig = True\n", encoding="utf-8")

    # Install bridge
    ok, _ = install_bridge(str(game_dir))
    assert ok

    # 1. Custom settings must NOT be overwritten
    assert custom_ini.read_text(encoding="utf-8") == "[Overrides]\nCustomUserConfig = True\n"

    # 2. Existing mods must remain intact alongside Expedition33RPC
    mods_content = mods_txt.read_text(encoding="utf-8")
    assert "CustomCheatsMod : 1" in mods_content
    assert "SomeOtherMod : 1" in mods_content
    assert "Expedition33RPC : 1" in mods_content


def test_uninstall_preserves_ue4ss_dlls_when_other_mods_active(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_binaries"
    mods_dir = game_dir / "ue4ss" / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    mods_txt = mods_dir / "mods.txt"
    mods_txt.write_text("AnotherMod : 1\n", encoding="utf-8")

    # Install bridge
    install_bridge(str(game_dir))
    assert (game_dir / "dwmapi.dll").exists()

    # Uninstall bridge: because AnotherMod is active, dwmapi.dll must be preserved
    ok, _ = uninstall_bridge(str(game_dir))
    assert ok
    assert (game_dir / "dwmapi.dll").exists(), (
        "dwmapi.dll must NOT be deleted when another mod is active"
    )
    assert not is_bridge_installed(str(game_dir))


def test_find_game_win64_directory_parses_synthetic_libraryfolders_vdf(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    steamapps_dir = steam_root / "steamapps"
    steamapps_dir.mkdir(parents=True, exist_ok=True)

    custom_lib = tmp_path / "CustomSteamLib"
    game_win64 = (
        custom_lib / "steamapps" / "common" / "Expedition 33" / "Sandfall" / "Binaries" / "Win64"
    )
    game_win64.mkdir(parents=True, exist_ok=True)
    exe_file = game_win64 / "SandFall-Win64-Shipping.exe"
    exe_file.write_text("dummy binary", encoding="utf-8")

    vdf_content = f'''"libraryfolders"
{{
\t"0"
\t{{
\t\t"path"\t\t"{steam_root}"
\t}}
\t"1"
\t{{
\t\t"path"\t\t"{custom_lib}"
\t}}
}}'''
    vdf_file = steamapps_dir / "libraryfolders.vdf"
    vdf_file.write_text(vdf_content, encoding="utf-8")

    mock_winreg = MagicMock()
    mock_winreg.HKEY_CURRENT_USER = 1
    mock_winreg.HKEY_LOCAL_MACHINE = 2
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (str(steam_root), 1)

    with (
        patch.object(bridge_installer, "winreg", mock_winreg),
        patch("psutil.process_iter", return_value=[]),
    ):
        result = find_game_win64_directory()
        assert result is not None
        assert os.path.normpath(str(result)) == os.path.normpath(str(game_win64))
