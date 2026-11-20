"""Cross-platform IPC and telemetry path resolution supporting Windows, Linux, and Steam Deck Proton prefixes."""

from __future__ import annotations

import os
from pathlib import Path

from expedition33_rpc.detection.steam_resolver import (
    DEFAULT_STEAM_APP_ID,
    SteamCompatResolver,
)


def get_telemetry_file_paths(
    app_id: str = DEFAULT_STEAM_APP_ID,
    *,
    is_windows: bool | None = None,
    home_dir: Path | None = None,
) -> list[str]:
    """Returns candidate telemetry IPC status file paths across Windows, Linux, and Steam Deck Proton environments."""
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_telemetry_candidates()


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
    """Returns candidate GameUserSettings.ini file paths across Windows, Linux, and Steam Deck Proton environments."""
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_config_candidates()


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
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_save_games_candidates()


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
