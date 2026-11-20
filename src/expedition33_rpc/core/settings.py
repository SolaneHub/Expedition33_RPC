"""Settings management for Expedition 33 RPC."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
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

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        custom_path: str | Path | None = None,
    ) -> None:
        target_path = custom_path if custom_path is not None else config_path
        self.path = (
            Path(target_path)
            if target_path is not None
            else get_default_settings_dir() / "settings.json"
        )
        self._anti_spoiler: bool = False
        self._raw_data: dict[str, Any] = {}
        self._lock = threading.RLock()
        with contextlib.suppress(Exception):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self) -> bool:
        """Loads settings from the JSON configuration file, falling back to defaults."""
        with self._lock:
            if self.path.is_file():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._raw_data = dict(data)
                        self._anti_spoiler = bool(data.get("anti_spoiler", False))
                        return self._anti_spoiler
                except Exception:
                    pass
            self._raw_data = {}
            self._anti_spoiler = False
            return self._anti_spoiler

    def _save(self) -> bool:
        """Saves current settings atomically to the JSON configuration file."""
        with self._lock:
            tmp_path: Path | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_file():
                    with contextlib.suppress(Exception):
                        loaded = json.loads(self.path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            loaded.update(self._raw_data)
                            self._raw_data = loaded

                payload = dict(self._raw_data)
                payload["anti_spoiler"] = self._anti_spoiler
                data_str = json.dumps(payload, indent=2)

                tmp_path = self.path.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
                tmp_path.write_text(data_str, encoding="utf-8")
                tmp_path.replace(self.path)
                return True
            except OSError:
                if tmp_path is not None:
                    with contextlib.suppress(OSError):
                        if tmp_path.exists():
                            tmp_path.unlink()
                return False

    def is_anti_spoiler_enabled(self) -> bool:
        """Checks if anti-spoiler mode is enabled."""
        with self._lock:
            return self._anti_spoiler

    def set_anti_spoiler_enabled(self, enabled: bool) -> bool:
        """Persists anti-spoiler setting to the configuration file."""
        with self._lock:
            old_val = self._anti_spoiler
            self._anti_spoiler = bool(enabled)
            if not self._save():
                self._anti_spoiler = old_val
                return False
            return True

    def toggle_anti_spoiler(self) -> bool:
        """Toggles anti-spoiler mode and persists the new state."""
        with self._lock:
            target = not self._anti_spoiler
            if self.set_anti_spoiler_enabled(target):
                return target
            return self._anti_spoiler


__all__ = ["SettingsService", "get_default_settings_dir"]
