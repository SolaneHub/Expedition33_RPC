"""Settings management for Expedition 33 RPC.

Uses versioned JSON configuration in AppData / XDG as the sole source of truth.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class AppSettings:
    """Typed application configuration schema."""

    anti_spoiler: bool = False
    schema_version: int = SCHEMA_VERSION

    def __contains__(self, key: object) -> bool:
        return key in self.__dict__

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def get_default_settings_dir() -> Path:
    """Returns the platform-appropriate configuration directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "Expedition33_RPC"


class SettingsService:
    """Encapsulates persistent JSON configuration without relying on global module state."""

    def __init__(self, custom_path: Path | None = None):
        self._custom_settings_path = custom_path
        self._in_memory_anti_spoiler: bool = False
        self._cached_settings: AppSettings | None = None
        self._lock = threading.RLock()
        self.load_settings()

    def get_settings_path(self) -> Path:
        """Returns the path to the settings JSON file."""
        if self._custom_settings_path is not None:
            return self._custom_settings_path
        return get_default_settings_dir() / "settings.json"

    def set_custom_settings_path(self, path: Path | None) -> None:
        """Allows tests or runtime environments to override the settings file location."""
        with self._lock:
            self._custom_settings_path = path
            self._cached_settings = None

    def load_settings(self, force_reload: bool = False) -> AppSettings:
        """Loads settings from atomic JSON file or cached in-memory instance."""
        with self._lock:
            if self._cached_settings is not None and not force_reload:
                return self._cached_settings
            path = self.get_settings_path()
            if path.is_file():
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            loaded = AppSettings(
                                anti_spoiler=bool(
                                    data.get("anti_spoiler", self._in_memory_anti_spoiler)
                                ),
                                schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
                            )
                            self._cached_settings = loaded
                            self._in_memory_anti_spoiler = loaded.anti_spoiler
                            return loaded
                except Exception:
                    pass
            loaded = AppSettings(
                anti_spoiler=self._in_memory_anti_spoiler,
                schema_version=SCHEMA_VERSION,
            )
            self._cached_settings = loaded
            return loaded

    def save_settings(self, settings: AppSettings) -> bool:
        """Atomically saves settings to JSON configuration."""
        with self._lock:
            self._cached_settings = settings
            self._in_memory_anti_spoiler = settings.anti_spoiler
            path = self.get_settings_path()
            tmp_path = path.with_suffix(".tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "schema_version": settings.schema_version,
                    "anti_spoiler": settings.anti_spoiler,
                }
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                tmp_path.replace(path)
                return True
            except Exception as e:
                with contextlib.suppress(Exception):
                    if tmp_path.exists():
                        tmp_path.unlink()
                print(f"[Settings] Error saving configuration to {path}: {e}")
                return False

    def is_anti_spoiler_enabled(self) -> bool:
        """Checks if Anti-Spoiler mode is enabled in configuration in O(1)."""
        with self._lock:
            if self._cached_settings is None:
                return self.load_settings().anti_spoiler
            return self._cached_settings.anti_spoiler

    def set_anti_spoiler_enabled(self, enabled: bool) -> bool:
        """Persists the Anti-Spoiler setting atomically to versioned JSON configuration."""
        current = self.load_settings()
        current.anti_spoiler = enabled
        return self.save_settings(current)

    def toggle_anti_spoiler(self) -> bool:
        """Toggles Anti-Spoiler mode and returns the new state."""
        new_val = not self.is_anti_spoiler_enabled()
        self.set_anti_spoiler_enabled(new_val)
        return new_val

    def reset_fallback_anti_spoiler(self) -> None:
        """Resets in-memory state and custom settings path for test isolation."""
        with self._lock:
            self._in_memory_anti_spoiler = False
            self._custom_settings_path = None
            self._cached_settings = None


__all__ = [
    "SCHEMA_VERSION",
    "AppSettings",
    "SettingsService",
    "get_default_settings_dir",
]
