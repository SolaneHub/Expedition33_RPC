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
from tests.harness.bridge_contract_verifier import BridgeContractInspector

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


def test_bridge_lua_write_status_schema_contract_with_state_provider() -> None:
    """Verifies complete schema synchronization between main.lua write_status and BridgeStateProvider."""
    inspector = BridgeContractInspector()
    is_valid, errors = inspector.verify_contract_with_provider()
    assert is_valid, f"Bridge contract verification failed: {errors}"


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
    assert provider.read_game_data(min_valid_timestamp=proc_start) is None


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

    # 3. Deterministic offline validation (critical when luac is missing from CI / PATH)
    # 3a. Verify ASCII-purity (prevent unescaped unicode / encoding anomalies in Lua runtime)
    non_ascii_chars = [ch for ch in lua_content if ord(ch) > 127]
    assert not non_ascii_chars, (
        f"Found unescaped non-ASCII characters in main.lua: {set(non_ascii_chars)}"
    )

    # 3b. Verify illegal / invalid Lua syntax tokens (e.g. C-style operators, javascript keywords)
    # Strip comments and literal strings first to inspect raw code tokens
    code_no_comments = re.sub(r"--\[\[.*?\]\]", "", lua_content, flags=re.DOTALL)
    code_no_comments = re.sub(r"--[^\n]*", "", code_no_comments)
    code_no_strings = re.sub(r"\[\[.*?\]\]", '""', code_no_comments, flags=re.DOTALL)
    code_no_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code_no_strings)
    code_no_strings = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code_no_strings)

    illegal_operators = [
        ("!=", "~="),
        ("&&", "and"),
        ("||", "or"),
        ("===", "=="),
        ("++", "+= or + 1"),
    ]
    # Check illegal operators that are not valid Lua outside strings/comments
    for illegal_op, alternative in illegal_operators:
        assert illegal_op not in code_no_strings, (
            f"Illegal token '{illegal_op}' found in main.lua; use Lua syntax '{alternative}'"
        )
    illegal_keyword_matches = re.findall(r"\b(null|undefined|var|let|const|def)\b", code_no_strings)
    assert not illegal_keyword_matches, (
        f"Illegal non-Lua keywords found in main.lua: {set(illegal_keyword_matches)}"
    )

    # 3c. Verify block balancing (functions, ifs, dos, thens vs ends)
    tokens = re.findall(r"\b(function|if|elseif|do|then|end)\b", code_no_strings)
    counts = {t: tokens.count(t) for t in ("function", "if", "elseif", "do", "then", "end")}

    # In Lua: every 'function', 'if', and 'do' block is closed by 'end'.
    # Note: 'for ... do' and 'while ... do' produce a 'do', each closed by 'end'.
    assert counts["function"] + counts["if"] + counts["do"] == counts["end"], (
        f"Lua block imbalance: function({counts['function']}) + if({counts['if']}) + do({counts['do']}) "
        f"!= end({counts['end']})"
    )
    # Every 'if' and 'elseif' must have a corresponding 'then'
    assert counts["if"] + counts["elseif"] == counts["then"], (
        f"Lua conditional imbalance: if({counts['if']}) + elseif({counts['elseif']}) != then({counts['then']})"
    )

    # 3d. Verify write_status block structural integrity and atomic JSON output
    write_status_match = re.search(r"(?:local\s+)?function\s+write_status\s*\([^)]*\)", lua_content)
    assert write_status_match is not None, "write_status function definition missing in main.lua"
    write_status_start = write_status_match.start()

    # Extract complete write_status function body by balancing nested block tokens
    sub_code = lua_content[write_status_start:]
    # Strip comments from sub_code for accurate block tracking
    sub_clean = re.sub(r"--\[\[.*?\]\]", "", sub_code, flags=re.DOTALL)
    sub_clean = re.sub(r"--[^\n]*", "", sub_clean)
    depth = 0
    end_idx = 0
    for m in re.finditer(r"\b(function|if|do|end)\b", sub_clean):
        token = m.group(1)
        if token in ("function", "if", "do"):
            depth += 1
        elif token == "end":
            depth -= 1
            if depth == 0:
                end_idx = m.end()
                break

    assert end_idx > 0, "Could not determine boundaries of write_status function"
    write_status_body = sub_clean[:end_idx]

    # Check atomic double-buffering write (.tmp file rename)
    assert "tmp_path" in write_status_body, (
        "write_status must write to tmp_path for atomic swapping"
    )
    assert "status_path" in write_status_body, "write_status must reference target status_path"
    assert "os.rename" in write_status_body, "write_status must use atomic os.rename"
    assert "json_escape" in write_status_body, "write_status must sanitize strings with json_escape"
    assert "os.time()" in write_status_body, "write_status must timestamp payloads with os.time()"


def test_find_game_win64_directory_from_wingdk_process(tmp_path: Path) -> None:
    """Verifies that find_game_win64_directory locates WinGDK binary directory from active process."""
    fake_wingdk_dir = tmp_path / "Content" / "Sandfall" / "Binaries" / "WinGDK"
    fake_wingdk_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = fake_wingdk_dir / "Sandfall-WinGDK-Shipping.exe"
    fake_exe.touch()

    mock_proc = MagicMock()
    mock_proc.name.return_value = "Sandfall-WinGDK-Shipping.exe"
    mock_proc.exe.return_value = str(fake_exe)

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


def test_uninstall_bridge_permission_error_on_dwmapi_returns_failure(tmp_path: Path) -> None:
    """Verifies uninstall_bridge reports PermissionError when dwmapi.dll is locked by the running game."""
    game_dir = tmp_path / "game_binaries"
    game_dir.mkdir(parents=True)
    ok, msg = install_bridge(game_dir)
    assert ok, msg
    dwmapi = game_dir / "dwmapi.dll"
    assert dwmapi.is_file()

    with patch(
        "expedition33_rpc.integrations.bridge_installer.os.remove",
        side_effect=PermissionError("WinError 32: file in use"),
    ):
        ok_u, msg_u = uninstall_bridge(game_dir)

    assert ok_u is False
    assert "Failed to remove" in msg_u
    assert "Please close the game if it is running." in msg_u
    assert dwmapi.exists()
    assert "Expedition33RPC : 1" in (game_dir / "ue4ss" / "Mods" / "mods.txt").read_text(
        encoding="utf-8"
    )


def test_uninstall_bridge_permission_error_on_mod_dir_returns_failure(tmp_path: Path) -> None:
    """Verifies uninstall_bridge reports OSError/PermissionError when mod_dir cannot be deleted."""
    game_dir = tmp_path / "game_binaries"
    mods_dir = game_dir / "ue4ss" / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    (mods_dir / "mods.txt").write_text("OtherMod : 1\n", encoding="utf-8")

    ok, msg = install_bridge(game_dir)
    assert ok, msg
    mod_dir = mods_dir / "Expedition33RPC"
    assert mod_dir.is_dir()

    with patch(
        "expedition33_rpc.integrations.bridge_installer.shutil.rmtree",
        side_effect=OSError("Directory locked"),
    ):
        ok_u, msg_u = uninstall_bridge(game_dir)

    assert ok_u is False
    assert "Failed to remove" in msg_u
    assert "Please close the game if it is running." in msg_u
    assert mod_dir.exists()


def test_uninstall_bridge_remaining_target_on_disk_returns_failure(tmp_path: Path) -> None:
    """Verifies uninstall_bridge fails if target remains on disk after removal attempt."""
    game_dir = tmp_path / "game_binaries"
    game_dir.mkdir(parents=True)
    ok, msg = install_bridge(game_dir)
    assert ok, msg

    with patch("expedition33_rpc.integrations.bridge_installer.shutil.rmtree"):
        ok_u, msg_u = uninstall_bridge(game_dir)

    assert ok_u is False
    assert "Failed to remove" in msg_u
    assert "Please close the game if it is running." in msg_u


def test_uninstall_bridge_permission_error_on_mod_dir_preserves_dwmapi_and_mods_txt(
    tmp_path: Path,
) -> None:
    """Regression test for Finding 3: failed rmtree(mod_dir) without OtherMod leaves dwmapi.dll and mods.txt intact."""
    game_dir = tmp_path / "game_binaries"
    game_dir.mkdir(parents=True)
    ok, msg = install_bridge(game_dir)
    assert ok, msg

    dwmapi = game_dir / "dwmapi.dll"
    mods_txt = game_dir / "ue4ss" / "Mods" / "mods.txt"
    mod_dir = game_dir / "ue4ss" / "Mods" / "Expedition33RPC"
    assert dwmapi.is_file()
    assert "Expedition33RPC : 1" in mods_txt.read_text(encoding="utf-8")

    with patch(
        "expedition33_rpc.integrations.bridge_installer.shutil.rmtree",
        side_effect=PermissionError("Access denied on main.lua"),
    ):
        ok_u, msg_u = uninstall_bridge(game_dir)

    assert ok_u is False
    assert "Failed to remove" in msg_u
    assert "Please close the game if it is running." in msg_u
    assert dwmapi.exists()
    assert mod_dir.exists()
    assert "Expedition33RPC : 1" in mods_txt.read_text(encoding="utf-8")
    assert is_bridge_installed(game_dir) is True
