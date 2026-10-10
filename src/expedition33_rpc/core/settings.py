"""Settings management for Expedition 33 RPC."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


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
        self.anti_spoiler: bool = False
        self.load()

    def load(self) -> bool:
        """Loads anti-spoiler setting from the JSON configuration file."""
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.anti_spoiler = bool(data.get("anti_spoiler", False))
            except Exception:
                pass
        return self.anti_spoiler

    def load_settings(self) -> SettingsService:
        """Loads and returns the current settings service."""
        self.load()
        return self

    def is_anti_spoiler_enabled(self) -> bool:
        """Checks if anti-spoiler mode is enabled."""
        return self.anti_spoiler

    def set_anti_spoiler_enabled(self, enabled: bool) -> bool:
        """Atomically persists anti-spoiler setting to the JSON configuration file."""
        tmp_path = self.path.with_name(
            f"{self.path.stem}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
        )
        try:
            data: dict[str, Any] = {}
            if self.path.is_file():
                with contextlib.suppress(Exception):
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
            data["anti_spoiler"] = enabled
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self.path)
            self.anti_spoiler = enabled
            return True
        except Exception:
            with contextlib.suppress(Exception):
                if tmp_path.exists():
                    tmp_path.unlink()
            return False

    def toggle_anti_spoiler(self) -> bool:
        """Toggles anti-spoiler mode and persists the new state."""
        target = not self.anti_spoiler
        if self.set_anti_spoiler_enabled(target):
            return target
        return self.anti_spoiler


__all__ = ["SettingsService", "get_default_settings_dir"]
