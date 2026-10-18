"""Lightweight GitHub Releases update checker for Expedition 33 RPC."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from expedition33_rpc import __version__

GITHUB_REPO = "SolaneHub/Expedition33_RPC"
API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"Expedition33-RPC-Updater/{__version__}"


class UpdateState(Enum):
    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    tag_name: str
    version_tuple: tuple[int, ...]
    html_url: str


type UpdateCallback = Callable[[UpdateInfo | None], None]


def parse_version(v_str: str) -> tuple[int, ...]:
    """Parses a version string into a comparable tuple of integers."""
    clean = v_str.strip().lstrip("vV")
    numeric_part = clean.split("-")[0]
    nums = []
    for part in numeric_part.split("."):
        try:
            nums.append(int(part))
        except ValueError:
            break
    return tuple(nums) if nums else (0, 0, 0)


class AppUpdater:
    """Manages lightweight background checking for application updates via GitHub Releases API."""

    def __init__(
        self,
        current_version: str = __version__,
        on_state_change: Callable[[], None] | None = None,
        api_url: str = API_LATEST_RELEASE_URL,
        timeout: float = 10.0,
    ):
        self.current_version = current_version
        self.current_version_tuple = parse_version(current_version)
        self.on_state_change = on_state_change
        self.api_url = api_url
        self.timeout = timeout

        self.state = UpdateState.IDLE
        self.available_update: UpdateInfo | None = None
        self.error_message: str | None = None
        self._lock = threading.Lock()

    def _set_state(
        self,
        new_state: UpdateState,
        error_msg: str | None = None,
    ) -> None:
        with self._lock:
            self.state = new_state
            if error_msg is not None:
                self.error_message = error_msg

        if self.on_state_change:
            try:
                self.on_state_change()
            except Exception as e:
                print(f"[Updater] Callback error on state change: {e}")

    def check_for_updates(self) -> UpdateInfo | None:
        """Queries GitHub Releases API for the latest release."""
        self._set_state(UpdateState.CHECKING)
        print(f"[Updater] Checking for updates against {self.api_url}...")

        try:
            req = urllib.request.Request(
                self.api_url,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

            tag_name = data.get("tag_name", "")
            remote_tuple = parse_version(tag_name)
            html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")

            print(
                f"[Updater] Remote version: {tag_name} ({remote_tuple}) | Current: {self.current_version} ({self.current_version_tuple})"
            )

            if remote_tuple > self.current_version_tuple:
                info = UpdateInfo(
                    tag_name=tag_name,
                    version_tuple=remote_tuple,
                    html_url=html_url,
                )
                with self._lock:
                    self.available_update = info
                self._set_state(UpdateState.AVAILABLE)
                print(f"[Updater] Update available: {tag_name}")
                return info
            else:
                self._set_state(UpdateState.UP_TO_DATE)
                print("[Updater] Application is up to date.")
                return None

        except urllib.error.HTTPError as e:
            msg = f"HTTP error {e.code}: {e.reason}"
            print(f"[Updater] {msg}")
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return None
        except urllib.error.URLError as e:
            msg = f"Network connection error: {e.reason}"
            print(f"[Updater] {msg}")
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return None

        except Exception as e:
            msg = f"Update check failed: {e}"
            print(f"[Updater] {msg}")
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return None

    def check_in_background(
        self,
        delay_seconds: float = 0.0,
        on_complete: UpdateCallback | None = None,
    ) -> None:
        """Spawns a background thread to check for updates."""

        def _worker():
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            info = self.check_for_updates()
            if on_complete:
                try:
                    on_complete(info)
                except Exception as e:
                    print(f"[Updater] on_complete callback error: {e}")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def open_release_page(self) -> bool:
        """Opens the GitHub release page in the default web browser."""
        with self._lock:
            url = (
                self.available_update.html_url
                if self.available_update
                else f"https://github.com/{GITHUB_REPO}/releases/latest"
            )
        try:
            return webbrowser.open(url)
        except Exception as e:
            print(f"[Updater] Error opening browser: {e}")
            return False

    def get_status_text(self) -> str:
        """Returns the formatted menu item label based on the current updater state."""
        match self.state:
            case UpdateState.CHECKING:
                return "Checking for Updates..."
            case UpdateState.AVAILABLE if self.available_update:
                return f"Update to {self.available_update.tag_name}  [Open Release]"
            case UpdateState.UP_TO_DATE:
                return f"Version {self.current_version}  [Up to Date]"
            case UpdateState.ERROR:
                return "Update Check Failed  [Click to Retry]"
            case _:
                return "Check for Updates"


__all__ = [
    "GITHUB_REPO",
    "API_LATEST_RELEASE_URL",
    "USER_AGENT",
    "UpdateState",
    "UpdateInfo",
    "AppUpdater",
    "parse_version",
]
