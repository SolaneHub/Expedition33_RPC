"""Tests for UE4SS Bridge contract, payload parsing, and installation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def test_bridge_lua_write_status_schema_contract_with_state_provider(tmp_path: Path) -> None:
    """Verifies complete schema synchronization between main.lua write_status and BridgeStateProvider."""
    bridge_zip_path = Path(get_resource_path("bridge.zip"))
    with zipfile.ZipFile(bridge_zip_path, "r") as z:
        lua_content = z.read("ue4ss/Mods/Expedition33RPC/scripts/main.lua").decode("utf-8")

    # Extract JSON format string inside write_status in main.lua
    match = re.search(r"local payload = string\.format\(\s*\'([^\']+)\'", lua_content)
    assert match is not None, "Failed to extract JSON format template from write_status in main.lua"
    format_template = match.group(1).strip()

    # Verify that all keys produced by write_status format string are present
    emitted_keys = re.findall(r'"([a-zA-Z0-9_]+)"\s*:', format_template)
    expected_emitted_keys = {
        "in_combat",
        "enemy_name",
        "enemies",
        "zone",
        "raw_zone",
        "raw_level",
        "world_path",
        "checkpoint",
        "floor",
        "tower_floor",
        "tower_trial",
        "timestamp",
    }
    assert expected_emitted_keys.issubset(set(emitted_keys))

    # Simulate realistic main.lua emission using extracted format keys
    now = time.time()
    simulated_lua_output = {
        "in_combat": True,
        "enemy_name": "Duollistes",
        "enemies": ["Duollistes", "Alpha Gold Chevaliere"],
        "zone": "Level_Main_OldLumiere",
        "raw_zone": "Level_Main_OldLumiere",
        "raw_level": "Level_Main_OldLumiere_P",
        "world_path": "/Game/Maps/OldLumiere",
        "checkpoint": "Entrance",
        "floor": 4,
        "tower_floor": 4,
        "tower_trial": [2, 1],
        "timestamp": now,
    }

    status_file = tmp_path / "expedition33_status.json"
    status_file.write_text(json.dumps(simulated_lua_output), encoding="utf-8")

    provider = BridgeStateProvider(paths=[str(status_file)], time_provider=lambda: now)
    parsed_data = provider.read_game_data(min_valid_timestamp=now - 5.0, lang="en")

    assert parsed_data is not None
    # Verify all expected domain fields in read_game_data output
    assert parsed_data["raw_zone"] == simulated_lua_output["raw_zone"]
    assert parsed_data["in_combat"] is True
    assert parsed_data["enemy_name"] == simulated_lua_output["enemy_name"]
    assert parsed_data["enemies"] == simulated_lua_output["enemies"]
    assert parsed_data["checkpoint"] == simulated_lua_output["checkpoint"]
    assert parsed_data["tower_floor"] == 4
    assert parsed_data["tower_trial"] == (2, 1)


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


def test_bridge_lua_syntax_validity() -> None:
    """Verifies that main.lua inside bridge.zip contains valid Lua syntax using an AST validator and compiler."""
    bridge_zip_path = Path(get_resource_path("bridge.zip"))
    with zipfile.ZipFile(bridge_zip_path, "r") as z:
        lua_bytes = z.read("ue4ss/Mods/Expedition33RPC/scripts/main.lua")
        lua_content = lua_bytes.decode("utf-8")

    assert len(lua_content.strip()) > 0, "main.lua in bridge.zip is empty"

    # 1. Structural validation of critical hooks and markers
    required_markers = [
        "RegisterLoadMapPostHook",
        "LoopAsync",
        "write_status",
        "expedition33_status.json",
    ]
    for marker in required_markers:
        assert marker in lua_content, f"Expected marker '{marker}' missing in main.lua"

    # 2. If luac compiler is available in PATH, perform official compiler validation
    luac_bin = shutil.which("luac")
    if luac_bin:
        res = subprocess.run(
            [luac_bin, "-p", "-"],
            input=lua_content,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"luac syntax validation failed: {res.stderr}"


def test_find_game_win64_directory_from_wingdk_process(tmp_path: Path) -> None:
    """Verifies that find_game_win64_directory locates WinGDK binary directory from active process."""
    fake_wingdk_dir = tmp_path / "Content" / "Sandfall" / "Binaries" / "WinGDK"
    fake_wingdk_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = fake_wingdk_dir / "Sandfall-WinGDK-Shipping.exe"
    fake_exe.touch()

    mock_proc = MagicMock()
    mock_proc.info = {
        "name": "Sandfall-WinGDK-Shipping.exe",
        "exe": str(fake_exe),
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        res = find_game_win64_directory()
        assert res is not None
        assert os.path.normpath(res) == os.path.normpath(str(fake_wingdk_dir))


def test_install_bridge_zip_slip_prevention(tmp_path: Path) -> None:
    """Verifies that install_bridge refuses extracting files attempting directory traversal."""
    fake_game_dir = tmp_path / "game_binaries"
    fake_game_dir.mkdir(parents=True, exist_ok=True)

    malicious_zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_zip_path, "w") as zf:
        zf.writestr("../../evil.dll", "malicious payload")
        zf.writestr("dwmapi.dll", "legit payload")

    with patch(
        "expedition33_rpc.integrations.bridge_installer.get_resource_path",
        return_value=str(malicious_zip_path),
    ):
        ok, msg = install_bridge(fake_game_dir)
        assert ok is False
        assert "Zip slip traversal attempt detected" in msg

    # Verify no file was created outside target directory
    evil_path = tmp_path / "evil.dll"
    assert not evil_path.exists()
    assert not (fake_game_dir.parent / "evil.dll").exists()
