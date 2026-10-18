"""Settings management for Expedition 33 RPC."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Settings:
    """Application settings schema."""

    anti_spoiler: bool = False


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
    """Manages persistent JSON configuration for application settings."""

    def __init__(self, custom_path: Path | None = None):
        self.path = (
            custom_path if custom_path is not None else get_default_settings_dir() / "settings.json"
        )
        self.settings = Settings()
        self._raw_data: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    @property
    def target_path(self) -> Path:
        """Alias for settings file path."""
        return self.path

    @property
    def anti_spoiler(self) -> bool:
        """Checks if anti-spoiler mode is enabled."""
        return self.settings.anti_spoiler

    @anti_spoiler.setter
    def anti_spoiler(self, value: bool) -> None:
        self.settings.anti_spoiler = bool(value)

    def load(self) -> bool:
        """Loads settings from the JSON configuration file, falling back to defaults."""
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._raw_data = dict(data)
                    self.settings.anti_spoiler = bool(data.get("anti_spoiler", False))
                    return self.anti_spoiler
            except Exception:
                pass
        self._raw_data = {}
        self.settings.anti_spoiler = False
        return self.anti_spoiler

    def save(self, settings: Settings | None = None) -> bool:
        """Saves current settings to the JSON configuration file."""
        if settings is not None:
            self.settings = settings

        tmp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file():
                with contextlib.suppress(Exception):
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._raw_data.update(loaded)

            payload = dict(self._raw_data)
            payload["anti_spoiler"] = self.settings.anti_spoiler
            data_str = json.dumps(payload, indent=2)

            tmp_path = self.path.with_suffix(".tmp")
            tmp_path.write_text(data_str, encoding="utf-8")
            tmp_path.replace(self.path)
            return True
        except OSError:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    if tmp_path.exists():
                        tmp_path.unlink()
            return False

    def update(self, anti_spoiler: bool | None = None, **kwargs: Any) -> bool:
        """Updates settings and persists changes to disk."""
        if anti_spoiler is not None:
            self.settings.anti_spoiler = anti_spoiler
        for k, v in kwargs.items():
            if hasattr(self.settings, k):
                setattr(self.settings, k, v)
            else:
                self._raw_data[k] = v
        return self.save()

    def is_anti_spoiler_enabled(self) -> bool:
        """Checks if anti-spoiler mode is enabled."""
        return self.anti_spoiler

    def set_anti_spoiler_enabled(self, enabled: bool) -> bool:
        """Persists anti-spoiler setting to the configuration file."""
        old_val = self.anti_spoiler
        self.anti_spoiler = enabled
        if not self.save():
            self.anti_spoiler = old_val
            return False
        return True

    def toggle_anti_spoiler(self) -> bool:
        """Toggles anti-spoiler mode and persists the new state."""
        target = not self.anti_spoiler
        if self.set_anti_spoiler_enabled(target):
            return target
        return self.anti_spoiler


__all__ = ["Settings", "SettingsService", "get_default_settings_dir"]
