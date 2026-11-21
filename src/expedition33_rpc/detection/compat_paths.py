"""Cross-platform IPC and telemetry path resolution supporting Windows, Linux, and Steam Deck Proton prefixes.

Deprecated wrapper: route path resolution directly through SteamCompatResolver instance methods.
"""

from __future__ import annotations

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
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_telemetry_file_path(custom_path=custom_path)


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
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_game_user_settings_path(custom_path=custom_path)


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
    resolver = SteamCompatResolver(app_id=app_id, is_windows=is_windows, home_dir=home_dir)
    return resolver.resolve_user_data_path(custom_path=custom_path)


__all__ = [
    "DEFAULT_STEAM_APP_ID",
    "get_config_file_paths",
    "get_game_user_settings_path",
    "get_save_games_paths",
    "get_telemetry_file_path",
    "get_telemetry_file_paths",
    "resolve_user_data_path",
]
