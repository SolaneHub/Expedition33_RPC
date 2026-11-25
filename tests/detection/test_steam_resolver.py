"""Unit tests for SteamCompatResolver and centralized Steam/Proton/Wine path discovery."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.harness.fake_process import FakeProcess

from expedition33_rpc.detection.steam_resolver import (
    DEFAULT_STEAM_APP_ID,
    STANDARD_LINUX_STEAM_ROOTS,
    STEAM_REGISTRY_SUBKEYS,
    SteamCompatResolver,
)
from expedition33_rpc.integrations.bridge_installer import find_game_win64_directory

pytestmark = pytest.mark.unit


def test_steam_resolver_defaults() -> None:
    assert DEFAULT_STEAM_APP_ID == "1903340"
    assert SteamCompatResolver.DEFAULT_STEAM_APP_ID == "1903340"
    assert len(STANDARD_LINUX_STEAM_ROOTS) == 4
    assert len(STEAM_REGISTRY_SUBKEYS) == 3


def test_steam_resolver_windows_registry(tmp_path: Path) -> None:
    mock_root = tmp_path / "ProgramFiles" / "Steam"
    mock_winreg = MagicMock()
    mock_winreg.HKEY_CURRENT_USER = 1
    mock_winreg.HKEY_LOCAL_MACHINE = 2
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = (str(mock_root), 1)

    resolver = SteamCompatResolver(is_windows=True, winreg_module=mock_winreg)
    roots = resolver.get_steam_roots(existing_only=False)
    assert len(roots) >= 1
    assert roots[0] == mock_root


def test_steam_resolver_linux_standard_roots(tmp_path: Path) -> None:
    fake_home = tmp_path / "home" / "deck"
    resolver = SteamCompatResolver(
        is_windows=False,
        home_dir=fake_home,
        winreg_module=None,
    )
    roots = resolver.get_steam_roots(existing_only=False)
    assert len(roots) == 4
    assert roots[0] == fake_home / ".local" / "share" / "Steam"
    assert roots[1] == fake_home / ".steam" / "steam"


def test_steam_resolver_vdf_parsing(tmp_path: Path) -> None:
    vdf_file = tmp_path / "libraryfolders.vdf"
    lib1 = tmp_path / "SteamLibrary1"
    lib2 = tmp_path / "SteamLibrary2"
    vdf_content = f'''"libraryfolders"
{{
\t"0"
\t{{
\t\t"path"\t\t"{lib1}"
\t}}
\t"1"
\t{{
\t\t"path"\t\t"{lib2}"
\t}}
}}'''
    vdf_file.write_text(vdf_content, encoding="utf-8")

    libs = SteamCompatResolver.parse_libraryfolders_vdf(vdf_file)
    assert len(libs) == 2
    assert libs[0] == lib1
    assert libs[1] == lib2


def test_steam_resolver_proton_prefixes_and_env(tmp_path: Path) -> None:
    fake_home = tmp_path / "home" / "deck"
    compat_data = tmp_path / "compat_override"
    wine_pfx = tmp_path / "wine_pfx"

    resolver = SteamCompatResolver(
        app_id="1903340",
        is_windows=False,
        home_dir=fake_home,
        environ={"STEAM_COMPAT_DATA_PATH": str(compat_data), "WINEPREFIX": str(wine_pfx)},
        winreg_module=None,
    )
    prefixes = resolver.get_proton_prefixes()
    assert prefixes[0] == compat_data / "pfx"
    assert prefixes[1] == wine_pfx
    assert any("1903340" in str(p) for p in prefixes[2:])


def test_steam_resolver_candidates(tmp_path: Path) -> None:
    fake_home = tmp_path / "home" / "deck"
    resolver = SteamCompatResolver(is_windows=False, home_dir=fake_home, winreg_module=None)

    telemetry = resolver.resolve_telemetry_candidates()
    assert any(os.path.normpath("/tmp/expedition33_status.json") in p for p in telemetry)

    configs = resolver.resolve_config_candidates()
    assert any("GameUserSettings.ini" in p for p in configs)

    saves = resolver.resolve_save_games_candidates()
    assert any("SaveGames" in p for p in saves)


def test_steam_resolver_instance_methods() -> None:
    resolver = SteamCompatResolver(app_id="1903340")
    pfx_list = resolver.get_proton_prefixes()
    assert isinstance(pfx_list, list)

    candidates = resolver.resolve_telemetry_candidates()
    assert isinstance(candidates, list)
    assert len(candidates) > 0


def test_find_game_win64_directory_with_process_scanner(tmp_path: Path) -> None:
    win64_dir = tmp_path / "Expedition33" / "Sandfall" / "Binaries" / "Win64"
    win64_dir.mkdir(parents=True)
    exe_file = win64_dir / "Sandfall-Win64-Shipping.exe"
    exe_file.touch()

    fake_proc = FakeProcess(
        pid=1234,
        name="Sandfall-Win64-Shipping.exe",
        exe_path=str(exe_file),
    )

    result = find_game_win64_directory(
        process_scanner=lambda: [fake_proc],
    )
    assert result is not None
    assert os.path.normpath(result) == os.path.normpath(str(win64_dir))


def test_steam_resolver_vdf_parsing_robustness(tmp_path: Path) -> None:
    vdf_file = tmp_path / "libraryfolders.vdf"
    valid_lib = tmp_path / "valid_lib"
    inline_lib = tmp_path / "inline_lib"
    commented_lib = tmp_path / "commented_lib"
    hash_commented_lib = tmp_path / "hash_commented_lib"

    vdf_content = f'''"libraryfolders"
{{
    "0"
    {{
        "path"    "{valid_lib}"
        "label"   "fast nvme path"
    }}
    "1" {{ "path" "{inline_lib}" }}
    // "path" "{commented_lib}"
    # "path" "{hash_commented_lib}"
}}'''
    vdf_file.write_text(vdf_content, encoding="utf-8")

    libs = SteamCompatResolver.parse_libraryfolders_vdf(vdf_file)
    assert valid_lib in libs
    assert inline_lib in libs
    assert Path("fast nvme path") not in libs
    assert Path("path") not in libs
    assert commented_lib not in libs
    assert hash_commented_lib not in libs


def test_steam_resolver_permission_error_handling(tmp_path: Path) -> None:
    locked_dir = tmp_path / "locked_home"
    locked_dir.mkdir()

    # 1. Test unreadable directory handling on POSIX when chmod is supported
    try:
        os.chmod(locked_dir, 0o400)
        chmod_supported = True
    except OSError:
        chmod_supported = False

    try:
        if chmod_supported:
            resolver = SteamCompatResolver(
                is_windows=False,
                home_dir=locked_dir,
                winreg_module=None,
            )
            # Must safely return without raising PermissionError
            roots = resolver.get_steam_roots(existing_only=True)
            assert isinstance(roots, list)

            # Unreadable VDF file or candidate directory must safely return empty list
            locked_vdf = locked_dir / "libraryfolders.vdf"
            libs = SteamCompatResolver.parse_libraryfolders_vdf(locked_vdf)
            assert libs == []

            dirs = resolver.get_steam_libraries()
            assert dirs == []
    finally:
        if chmod_supported:
            os.chmod(locked_dir, 0o700)

    # 2. Test deterministic OSError/PermissionError handling via mocking
    existing_file = tmp_path / "existing.vdf"
    existing_file.write_text('"libraryfolders" { "0" { "path" "/test" } }', encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        libs = SteamCompatResolver.parse_libraryfolders_vdf(existing_file)
        assert libs == []


def test_steam_resolver_proton_sd_card_via_libraryfolders_vdf(tmp_path: Path) -> None:
    """Verifies Proton prefix discovery on an external SD card library via libraryfolders.vdf."""
    fake_home = tmp_path / "home" / "deck"
    steam_root = fake_home / ".local" / "share" / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)

    sd_library = tmp_path / "run" / "media" / "mmcblk0p1" / "SteamLibrary"
    sd_pfx = sd_library / "steamapps" / "compatdata" / "1903340" / "pfx"
    sd_pfx.mkdir(parents=True)

    vdf_file = steamapps / "libraryfolders.vdf"
    vdf_file.write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{steam_root}"\n\t}}\n\t"1"\n\t{{\n\t\t"path"\t\t"{sd_library}"\n\t}}\n}}\n',
        encoding="utf-8",
    )

    resolver = SteamCompatResolver(
        app_id="1903340",
        is_windows=False,
        home_dir=fake_home,
        environ={},
        winreg_module=None,
    )
    prefixes = resolver.get_proton_prefixes()
    assert sd_pfx in prefixes


def test_steam_resolver_windows_environ_purity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies self._environ isolation and purity on simulated Windows."""
    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", "/leaked/from/os/environ")
    injected_env = {"LOCALAPPDATA": str(tmp_path / "LocalAppData")}
    resolver = SteamCompatResolver(
        is_windows=True,
        environ=injected_env,
        winreg_module=None,
    )
    assert resolver._environ == injected_env
    assert resolver._environ is not injected_env or resolver._environ["LOCALAPPDATA"] == str(
        tmp_path / "LocalAppData"
    )
    prefixes = resolver.get_proton_prefixes()
    assert all("leaked" not in str(p) for p in prefixes)
