"""Cross-platform IPC and telemetry path resolution supporting Windows, Linux, and Steam Deck Proton prefixes."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_STEAM_APP_ID = "1903340"


def get_telemetry_file_paths(
    app_id: str = DEFAULT_STEAM_APP_ID,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> list[str]:
    """Returns candidate telemetry IPC status file paths across Windows, Linux, and Steam Deck Proton environments.

    Args:
        app_id: The Steam AppID for Expedition 33 (defaults to 1903340).
        is_windows: Optional platform override (defaults to sys.platform == 'win32' or os.name == 'nt').
        home_dir: Optional user home directory override (defaults to Path.home()).
    """
    win_flag = (
        is_windows if is_windows is not None else (sys.platform == "win32" or os.name == "nt")
    )

    if win_flag:
        return [
            os.path.expandvars(r"%TEMP%\expedition33_status.json"),
            os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\rpc_status.json"),
        ]

    paths: list[str] = []

    # 1. Non-Windows / Linux / SteamOS: Check explicit environment overrides
    env_compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
    if env_compat:
        pfx = Path(env_compat) / "pfx"
        paths.append(
            str(pfx / "drive_c" / "users" / "steamuser" / "Temp" / "expedition33_status.json")
        )
        paths.append(
            str(
                pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "rpc_status.json"
            )
        )

    env_wineprefix = os.environ.get("WINEPREFIX")
    if env_wineprefix:
        pfx = Path(env_wineprefix)
        paths.append(
            str(pfx / "drive_c" / "users" / "steamuser" / "Temp" / "expedition33_status.json")
        )
        paths.append(
            str(
                pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "rpc_status.json"
            )
        )

    # 2. Known Steam installation roots on Linux / Steam Deck
    home = home_dir if home_dir is not None else Path.home()
    steam_roots = [
        home / ".local" / "share" / "Steam",
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]

    for root in steam_roots:
        compat_pfx = root / "steamapps" / "compatdata" / app_id / "pfx"
        paths.append(
            str(
                compat_pfx / "drive_c" / "users" / "steamuser" / "Temp" / "expedition33_status.json"
            )
        )
        paths.append(
            str(
                compat_pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "rpc_status.json"
            )
        )

    # 3. Standard Linux host fallback
    paths.append("/tmp/expedition33_status.json")

    # Remove duplicates preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for p in paths:
        norm = os.path.normpath(p)
        if norm not in seen:
            seen.add(norm)
            unique_paths.append(norm)

    return unique_paths


def get_telemetry_file_path(
    app_id: str = DEFAULT_STEAM_APP_ID,
    custom_path: str | None = None,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> str:
    """Finds the first existing telemetry file, or returns the most likely candidate path."""
    if custom_path:
        return custom_path

    candidates = get_telemetry_file_paths(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    for p in candidates:
        if os.path.exists(p):
            return p

    return candidates[0] if candidates else "/tmp/expedition33_status.json"


def get_config_file_paths(
    app_id: str = DEFAULT_STEAM_APP_ID,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> list[str]:
    """Returns candidate GameUserSettings.ini file paths across Windows, Linux, and Steam Deck Proton environments.

    Args:
        app_id: The Steam AppID for Expedition 33 (defaults to 1903340).
        is_windows: Optional platform override (defaults to sys.platform == 'win32' or os.name == 'nt').
        home_dir: Optional user home directory override (defaults to Path.home()).
    """
    win_flag = (
        is_windows if is_windows is not None else (sys.platform == "win32" or os.name == "nt")
    )

    if win_flag:
        return [
            os.path.expandvars(
                r"%LOCALAPPDATA%\Sandfall\Saved\Config\Windows\GameUserSettings.ini"
            ),
            os.path.expandvars(
                r"%LOCALAPPDATA%\Sandfall\Saved\Config\WindowsNoEditor\GameUserSettings.ini"
            ),
        ]

    paths: list[str] = []

    # 1. Non-Windows / Linux / SteamOS: Check explicit environment overrides
    env_compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
    if env_compat:
        pfx = Path(env_compat) / "pfx"
        sandfall_saved = (
            pfx
            / "drive_c"
            / "users"
            / "steamuser"
            / "AppData"
            / "Local"
            / "Sandfall"
            / "Saved"
            / "Config"
        )
        paths.append(str(sandfall_saved / "Windows" / "GameUserSettings.ini"))
        paths.append(str(sandfall_saved / "WindowsNoEditor" / "GameUserSettings.ini"))

    env_wineprefix = os.environ.get("WINEPREFIX")
    if env_wineprefix:
        pfx = Path(env_wineprefix)
        sandfall_saved = (
            pfx
            / "drive_c"
            / "users"
            / "steamuser"
            / "AppData"
            / "Local"
            / "Sandfall"
            / "Saved"
            / "Config"
        )
        paths.append(str(sandfall_saved / "Windows" / "GameUserSettings.ini"))
        paths.append(str(sandfall_saved / "WindowsNoEditor" / "GameUserSettings.ini"))

    # 2. Known Steam installation roots on Linux / Steam Deck
    home = home_dir if home_dir is not None else Path.home()
    steam_roots = [
        home / ".local" / "share" / "Steam",
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]

    for root in steam_roots:
        compat_pfx = root / "steamapps" / "compatdata" / app_id / "pfx"
        sandfall_saved = (
            compat_pfx
            / "drive_c"
            / "users"
            / "steamuser"
            / "AppData"
            / "Local"
            / "Sandfall"
            / "Saved"
            / "Config"
        )
        paths.append(str(sandfall_saved / "Windows" / "GameUserSettings.ini"))
        paths.append(str(sandfall_saved / "WindowsNoEditor" / "GameUserSettings.ini"))

    # 3. Standard Linux host fallback
    paths.append(
        str(home / ".config" / "Sandfall" / "Saved" / "Config" / "Windows" / "GameUserSettings.ini")
    )

    # Remove duplicates preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for p in paths:
        norm = os.path.normpath(p)
        if norm not in seen:
            seen.add(norm)
            unique_paths.append(norm)

    return unique_paths


def get_game_user_settings_path(
    app_id: str = DEFAULT_STEAM_APP_ID,
    custom_path: str | None = None,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> str | None:
    """Finds the first existing GameUserSettings.ini file, or returns the most likely candidate path."""
    if custom_path:
        return custom_path

    candidates = get_config_file_paths(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0] if candidates else None


def get_save_games_paths(
    app_id: str = DEFAULT_STEAM_APP_ID,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> list[str]:
    """Returns candidate SaveGames directory paths across Windows, Linux, and Steam Deck Proton environments."""
    win_flag = (
        is_windows if is_windows is not None else (sys.platform == "win32" or os.name == "nt")
    )

    if win_flag:
        return [
            os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames"),
        ]

    paths: list[str] = []

    # 1. Non-Windows / Linux / SteamOS: Check explicit environment overrides
    env_compat = os.environ.get("STEAM_COMPAT_DATA_PATH")
    if env_compat:
        pfx = Path(env_compat) / "pfx"
        paths.append(
            str(
                pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "Saved"
                / "SaveGames"
            )
        )

    env_wineprefix = os.environ.get("WINEPREFIX")
    if env_wineprefix:
        pfx = Path(env_wineprefix)
        paths.append(
            str(
                pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "Saved"
                / "SaveGames"
            )
        )

    # 2. Known Steam installation roots on Linux / Steam Deck
    home = home_dir if home_dir is not None else Path.home()
    steam_roots = [
        home / ".local" / "share" / "Steam",
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]

    for root in steam_roots:
        compat_pfx = root / "steamapps" / "compatdata" / app_id / "pfx"
        paths.append(
            str(
                compat_pfx
                / "drive_c"
                / "users"
                / "steamuser"
                / "AppData"
                / "Local"
                / "Sandfall"
                / "Saved"
                / "SaveGames"
            )
        )

    # 3. Standard Linux host fallback
    paths.append(str(home / ".config" / "Sandfall" / "Saved" / "SaveGames"))

    # Remove duplicates preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for p in paths:
        norm = os.path.normpath(p)
        if norm not in seen:
            seen.add(norm)
            unique_paths.append(norm)

    return unique_paths


def resolve_user_data_path(
    app_id: str = DEFAULT_STEAM_APP_ID,
    custom_path: str | None = None,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> str:
    """Finds the first existing user data / save directory, or returns the most likely candidate path."""
    if custom_path:
        return custom_path

    candidates = get_save_games_paths(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    for p in candidates:
        if os.path.isdir(p):
            return p

    return (
        candidates[0]
        if candidates
        else os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames")
    )


__all__ = [
    "DEFAULT_STEAM_APP_ID",
    "get_config_file_paths",
    "get_game_user_settings_path",
    "get_save_games_paths",
    "get_telemetry_file_path",
    "get_telemetry_file_paths",
    "resolve_user_data_path",
]
