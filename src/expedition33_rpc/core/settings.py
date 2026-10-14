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
        self._lock = threading.RLock()
        self._cached_data: dict[str, Any] = {}
        self._last_mtime: float = 0.0
        with contextlib.suppress(Exception):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> bool:
        """Loads anti-spoiler setting from the JSON configuration file."""
        with self._lock:
            if self.path.is_file():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._cached_data = dict(data)
                        self.anti_spoiler = bool(data.get("anti_spoiler", False))
                        self._last_mtime = self.path.stat().st_mtime
                except Exception:
                    pass
            return self.anti_spoiler

    def is_anti_spoiler_enabled(self) -> bool:
        """Checks if anti-spoiler mode is enabled."""
        with self._lock:
            return self.anti_spoiler

    def set_anti_spoiler_enabled(self, enabled: bool) -> bool:
        """Atomically persists anti-spoiler setting to the JSON configuration file."""
        with self._lock:
            try:
                disk_mtime = self.path.stat().st_mtime
            except OSError:
                disk_mtime = 0.0

            if disk_mtime != self._last_mtime and disk_mtime > 0.0:
                with contextlib.suppress(Exception):
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._cached_data = dict(loaded)
                        self._last_mtime = disk_mtime

            new_data = dict(self._cached_data)
            new_data["anti_spoiler"] = enabled

            tmp_path = self.path.with_name(
                f"{self.path.stem}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
            )
            try:
                payload = json.dumps(new_data, indent=2).encode("utf-8")
                try:
                    with open(tmp_path, "wb") as f:
                        f.write(payload)
                except FileNotFoundError:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(tmp_path, "wb") as f:
                        f.write(payload)

                tmp_path.replace(self.path)
                self._cached_data = new_data
                self.anti_spoiler = enabled
                with contextlib.suppress(OSError):
                    self._last_mtime = self.path.stat().st_mtime
                return True
            except Exception:
                with contextlib.suppress(Exception):
                    if tmp_path.exists():
                        tmp_path.unlink()
                return False

    def toggle_anti_spoiler(self) -> bool:
        """Toggles anti-spoiler mode and persists the new state."""
        with self._lock:
            target = not self.anti_spoiler
            if self.set_anti_spoiler_enabled(target):
                return target
            return self.anti_spoiler


__all__ = ["SettingsService", "get_default_settings_dir"]
