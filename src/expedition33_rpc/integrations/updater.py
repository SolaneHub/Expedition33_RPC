"""Lightweight GitHub Releases update checker for Expedition 33 RPC."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from expedition33_rpc._version import __version__

logger = logging.getLogger(__name__)

GITHUB_REPO = "SolaneHub/Expedition33_RPC"
DEFAULT_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"Expedition33-RPC-Updater/{__version__}"
_ALLOWED_REPO_PATH = f"/{GITHUB_REPO}"
_ALLOWED_REPO_PREFIX = f"{_ALLOWED_REPO_PATH}/"


def validate_release_url(url: str | None) -> str:
    """Validates that a release URL points strictly to the official GitHub repository.

    Accepts only ``https://github.com/SolaneHub/Expedition33_RPC`` or subpaths
    under ``https://github.com/SolaneHub/Expedition33_RPC/`` with no userinfo,
    no backslashes, no ``..`` traversal segments (raw or percent-decoded), and
    no whitespace or control characters. Invalid URLs log a warning and fall
    back safely to ``DEFAULT_RELEASE_URL``.
    """
    if not isinstance(url, str) or not url:
        logger.warning(
            "Rejected invalid release URL %r; falling back to %s",
            url,
            DEFAULT_RELEASE_URL,
        )
        return DEFAULT_RELEASE_URL

    if "\\" in url or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        logger.warning(
            "Rejected unsafe release URL %r; falling back to %s",
            url,
            DEFAULT_RELEASE_URL,
        )
        return DEFAULT_RELEASE_URL

    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        logger.warning(
            "Rejected unparseable release URL %r; falling back to %s",
            url,
            DEFAULT_RELEASE_URL,
        )
        return DEFAULT_RELEASE_URL

    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.username is not None
        or parsed.password is not None
    ):
        logger.warning(
            "Rejected untrusted release URL %r; falling back to %s",
            url,
            DEFAULT_RELEASE_URL,
        )
        return DEFAULT_RELEASE_URL

    path = parsed.path
    if path != _ALLOWED_REPO_PATH and not path.startswith(_ALLOWED_REPO_PREFIX):
        logger.warning(
            "Rejected off-repo release URL %r; falling back to %s",
            url,
            DEFAULT_RELEASE_URL,
        )
        return DEFAULT_RELEASE_URL

    decoded_path = path
    for _ in range(4):
        if (
            "\\" in decoded_path
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded_path)
            or any(seg == ".." for seg in decoded_path.split("/"))
        ):
            logger.warning(
                "Rejected unsafe or path-traversal release URL %r; falling back to %s",
                url,
                DEFAULT_RELEASE_URL,
            )
            return DEFAULT_RELEASE_URL
        next_path = urllib.parse.unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path

    return url


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "html_url", validate_release_url(self.html_url))


type UpdateCallback = Callable[[UpdateInfo | None], None]


def parse_version(v_str: str) -> tuple[int, ...]:
    """Parses a version string into a comparable tuple of integers."""
    clean = v_str.strip().lstrip("vV")
    numeric_part = clean.split("-")[0]
    nums: list[int] = []
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
        http_opener: Callable[..., Any] | None = None,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self.current_version = current_version
        self.current_version_tuple = parse_version(current_version)
        self.on_state_change = on_state_change
        self.api_url = api_url
        self.timeout = timeout
        self._http_opener = http_opener
        self._browser_opener = browser_opener

        self.state = UpdateState.IDLE
        self.available_update: UpdateInfo | None = None
        self.error_message: str | None = None
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._active_cancel_events: set[threading.Event] = set()
        self._worker_thread: threading.Thread | None = None
        self._active_threads: set[threading.Thread] = set()
        self._generation = 0

    def _notify_state_change(self) -> None:
        if self.on_state_change:
            try:
                self.on_state_change()
            except Exception as e:
                logger.error("Callback error on state change: %s", e)

    def _is_cancelled_locked(
        self,
        expected_generation: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        if self._cancel_event.is_set():
            return True
        return expected_generation is not None and self._generation != expected_generation

    def _set_state(
        self,
        new_state: UpdateState,
        error_msg: str | None = None,
        *,
        available_update: UpdateInfo | None = None,
        expected_generation: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        with self._lock:
            if self._is_cancelled_locked(expected_generation, cancel_event):
                return False
            self.state = new_state
            if error_msg is not None:
                self.error_message = error_msg
            if available_update is not None:
                self.available_update = available_update

        self._notify_state_change()
        return True

    def check_for_updates(self) -> UpdateInfo | None:
        """Queries GitHub Releases API for the latest release."""
        return self._check_for_updates()

    def _check_for_updates(
        self,
        expected_generation: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> UpdateInfo | None:
        """Queries GitHub Releases API bound to an optional worker generation and cancel event."""
        notify_checking = False
        with self._lock:
            if self._is_cancelled_locked(expected_generation, cancel_event):
                return None
            start_generation = (
                expected_generation if expected_generation is not None else self._generation
            )
            if self.state != UpdateState.CHECKING:
                self.state = UpdateState.CHECKING
                notify_checking = True
        if notify_checking:
            self._notify_state_change()

        logger.info("Checking for updates against %s...", self.api_url)

        try:
            req = urllib.request.Request(
                self.api_url,
                headers={"User-Agent": USER_AGENT},
            )
            opener: Callable[..., Any] = (
                self._http_opener if self._http_opener is not None else urllib.request.urlopen
            )
            with opener(req, timeout=self.timeout) as response:
                with self._lock:
                    if self._is_cancelled_locked(start_generation, cancel_event):
                        return None
                raw_bytes = cast(bytes, response.read())
                data = cast(object, json.loads(raw_bytes.decode("utf-8")))

            with self._lock:
                if self._is_cancelled_locked(start_generation, cancel_event):
                    return None

            if not isinstance(data, dict):
                msg = f"Invalid release data format: expected dict, got {type(data).__name__}"
                logger.error(msg)
                self._set_state(
                    UpdateState.ERROR,
                    error_msg=msg,
                    expected_generation=start_generation,
                    cancel_event=cancel_event,
                )
                return None

            raw_dict = cast(dict[str, Any], data)
            raw_tag = raw_dict.get("tag_name")
            if not isinstance(raw_tag, str) or not raw_tag.strip():
                msg = "Release missing valid tag_name"
                logger.error(msg)
                self._set_state(
                    UpdateState.ERROR,
                    error_msg=msg,
                    expected_generation=start_generation,
                    cancel_event=cancel_event,
                )
                return None

            tag_name: str = raw_tag.strip()
            remote_tuple = parse_version(tag_name)
            raw_html_url = raw_dict.get("html_url", DEFAULT_RELEASE_URL)
            html_url = validate_release_url(raw_html_url if isinstance(raw_html_url, str) else None)

            logger.info(
                "Remote version: %s (%s) | Current: %s (%s)",
                tag_name,
                remote_tuple,
                self.current_version,
                self.current_version_tuple,
            )

            if remote_tuple > self.current_version_tuple:
                info = UpdateInfo(
                    tag_name=tag_name,
                    version_tuple=remote_tuple,
                    html_url=html_url,
                )
                if not self._set_state(
                    UpdateState.AVAILABLE,
                    available_update=info,
                    expected_generation=start_generation,
                    cancel_event=cancel_event,
                ):
                    return None
                logger.info("Update available: %s", tag_name)
                return info

            if not self._set_state(
                UpdateState.UP_TO_DATE,
                expected_generation=start_generation,
                cancel_event=cancel_event,
            ):
                return None
            logger.info("Application is up to date.")
            return None

        except urllib.error.HTTPError as e:
            with self._lock:
                if self._is_cancelled_locked(start_generation, cancel_event):
                    return None
            msg = f"HTTP error {e.code}: {e.reason}"
            logger.error("HTTP error %s: %s", e.code, e.reason)
            self._set_state(
                UpdateState.ERROR,
                error_msg=msg,
                expected_generation=start_generation,
                cancel_event=cancel_event,
            )
            return None
        except urllib.error.URLError as e:
            with self._lock:
                if self._is_cancelled_locked(start_generation, cancel_event):
                    return None
            msg = f"Network connection error: {e.reason}"
            logger.error("Network connection error: %s", e.reason)
            self._set_state(
                UpdateState.ERROR,
                error_msg=msg,
                expected_generation=start_generation,
                cancel_event=cancel_event,
            )
            return None

        except Exception as e:
            with self._lock:
                if self._is_cancelled_locked(start_generation, cancel_event):
                    return None
            msg = f"Update check failed: {e}"
            logger.error("Update check failed: %s", e)
            self._set_state(
                UpdateState.ERROR,
                error_msg=msg,
                expected_generation=start_generation,
                cancel_event=cancel_event,
            )
            return None

    def cancel(self) -> None:
        """Signals waiting threads to cancel pending update checks."""
        state_changed = False
        with self._lock:
            self._cancel_event.set()
            for ev in self._active_cancel_events:
                ev.set()
            self._generation += 1
            if self.state == UpdateState.CHECKING:
                self.state = UpdateState.IDLE
                state_changed = True
        if state_changed:
            self._notify_state_change()

    def join(self, timeout: float | None = None) -> None:
        """Waits for all background update threads to finish, if running."""
        with self._lock:
            threads = set(self._active_threads)
            if self._worker_thread is not None:
                threads.add(self._worker_thread)
        current = threading.current_thread()
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        for t in threads:
            if t is current or not t.is_alive():
                continue
            if deadline is None:
                t.join()
            else:
                remaining = max(0.0, deadline - time.monotonic())
                t.join(timeout=remaining)

    def check_in_background(
        self,
        delay_seconds: float = 0.0,
        on_complete: UpdateCallback | None = None,
    ) -> None:
        """Spawns a background thread to check for updates."""

        def _worker(expected_gen: int, gen_cancel_event: threading.Event) -> None:
            try:
                if delay_seconds > 0 and gen_cancel_event.wait(delay_seconds):
                    return
                with self._lock:
                    if self._is_cancelled_locked(expected_gen, gen_cancel_event):
                        return
                info = self._check_for_updates(
                    expected_generation=expected_gen,
                    cancel_event=gen_cancel_event,
                )
                with self._lock:
                    if self._is_cancelled_locked(expected_gen, gen_cancel_event):
                        return
                if on_complete:
                    try:
                        on_complete(info)
                    except Exception as e:
                        logger.error("on_complete callback error: %s", e)
            finally:
                current = threading.current_thread()
                with self._lock:
                    self._active_cancel_events.discard(gen_cancel_event)
                    self._active_threads.discard(current)
                    if (
                        self._generation == expected_gen
                        and (self._cancel_event.is_set() or gen_cancel_event.is_set())
                        and self.state == UpdateState.CHECKING
                    ):
                        self.state = UpdateState.IDLE

        with self._lock:
            if self.state == UpdateState.CHECKING:
                return
            self.state = UpdateState.CHECKING
            self._cancel_event.clear()
            self._generation += 1
            expected_gen = self._generation
            gen_cancel_event = threading.Event()
            self._active_cancel_events.add(gen_cancel_event)
            t = threading.Thread(
                target=_worker,
                args=(expected_gen, gen_cancel_event),
                name="AppUpdaterWorkerThread",
                daemon=True,
            )
            self._worker_thread = t
            self._active_threads.add(t)
            t.start()

        self._notify_state_change()

    def open_release_page(self) -> bool:
        """Opens the GitHub release page in the default web browser."""
        with self._lock:
            raw_url = (
                self.available_update.html_url if self.available_update else DEFAULT_RELEASE_URL
            )
        url = validate_release_url(raw_url)
        launcher: Callable[[str], bool] = (
            self._browser_opener if self._browser_opener is not None else webbrowser.open
        )
        try:
            return bool(launcher(url))
        except Exception as e:
            logger.error("Error opening browser: %s", e)
            return False

    def get_status_text(self) -> str:
        """Returns the formatted menu item label based on the current updater state."""
        with self._lock:
            state = self.state
            update = self.available_update
        match state:
            case UpdateState.CHECKING:
                return "Checking for Updates..."
            case UpdateState.AVAILABLE if update:
                return f"Update to {update.tag_name}  [Open Release]"
            case UpdateState.UP_TO_DATE:
                return f"Version {self.current_version}  [Up to Date]"
            case UpdateState.ERROR:
                return "Update Check Failed  [Click to Retry]"
            case _:
                return "Check for Updates"


__all__ = [
    "GITHUB_REPO",
    "DEFAULT_RELEASE_URL",
    "API_LATEST_RELEASE_URL",
    "USER_AGENT",
    "UpdateState",
    "UpdateInfo",
    "AppUpdater",
    "parse_version",
    "validate_release_url",
]
