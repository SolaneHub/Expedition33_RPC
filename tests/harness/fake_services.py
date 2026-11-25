"""Protocol-compliant test doubles for orchestrator and integration services."""

from __future__ import annotations

import io
import json
import threading
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any, Self

from expedition33_rpc.core.orchestrator import (
    BridgeInstallerProtocol,
    StartupProtocol,
    UpdaterProtocol,
)
from expedition33_rpc.integrations.updater import UpdateInfo, UpdateState


class FakeBridgeInstaller(BridgeInstallerProtocol):
    """Protocol-compliant fake bridge installer for deterministic unit tests."""

    def __init__(
        self,
        installed: bool = False,
        game_win64_dir: str | None = "/mock/game/win64",
        install_success: bool = True,
        install_msg: str = "Success",
        raise_on_install: Exception | None = None,
    ) -> None:
        self.installed = installed
        self.game_win64_dir = game_win64_dir
        self.install_success = install_success
        self.install_msg = install_msg
        self.raise_on_install = raise_on_install
        self.install_call_count = 0

    def find_game_win64_directory(
        self,
        target_process_names: Any = None,
        known_win64_dir: Path | str | None = None,
        known_exe_path: Path | str | None = None,
    ) -> str | None:
        del target_process_names, known_win64_dir, known_exe_path
        return self.game_win64_dir

    def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
        del win64_dir
        return self.installed

    def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        del win64_dir
        self.install_call_count += 1
        if self.raise_on_install:
            raise self.raise_on_install
        if self.install_success:
            self.installed = True
        return self.install_success, self.install_msg

    def uninstall_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        del win64_dir
        self.installed = False
        return True, "Uninstalled"


class FakeStartupService(StartupProtocol):
    """Protocol-compliant fake Windows startup service for deterministic unit tests."""

    def __init__(self, enabled: bool = False, set_result: bool = True) -> None:
        self.enabled = enabled
        self.set_result = set_result
        self.synced = False

    def is_startup_enabled(self) -> bool:
        return self.enabled

    def set_startup_enabled(self, enable: bool) -> bool:
        if not self.set_result:
            return False
        self.enabled = enable
        return True

    def sync_startup_path(self) -> None:
        self.synced = True

    def toggle_startup(self) -> bool:
        if not self.set_result:
            return self.enabled
        self.enabled = not self.enabled
        return self.enabled


class FakeUpdater(UpdaterProtocol):
    """Protocol-compliant fake updater for deterministic unit tests."""

    def __init__(
        self,
        state: UpdateState = UpdateState.IDLE,
        available_update: UpdateInfo | None = None,
        error_message: str | None = None,
        worker_started_event: threading.Event | None = None,
        release_worker_event: threading.Event | None = None,
        status_text: str = "Fake Updater Status",
    ) -> None:
        self.state = state
        self.available_update = available_update
        self.error_message = error_message
        self.status_text = status_text
        self.cancel_called = False
        self.open_release_page_called = False
        self.check_in_background_calls: list[
            tuple[float, Callable[[UpdateInfo | None], None] | None]
        ] = []
        self.worker_thread: threading.Thread | None = None
        self._worker_started_event = worker_started_event
        self._release_worker_event = release_worker_event

    def cancel(self) -> None:
        self.cancel_called = True
        if self._release_worker_event is not None:
            self._release_worker_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self.worker_thread is not None:
            self.worker_thread.join(timeout=timeout)

    def check_in_background(
        self,
        delay_seconds: float = 0.0,
        on_complete: Callable[[UpdateInfo | None], None] | None = None,
    ) -> None:
        self.check_in_background_calls.append((delay_seconds, on_complete))

        def _run() -> None:
            if self._worker_started_event is not None:
                self._worker_started_event.set()
            if self._release_worker_event is not None:
                self._release_worker_event.wait(timeout=2.0)

        t = threading.Thread(target=_run, name="FakeUpdaterWorker", daemon=True)
        self.worker_thread = t
        t.start()

    def open_release_page(self) -> bool:
        self.open_release_page_called = True
        return True

    def get_status_text(self) -> str:
        return self.status_text


class FakeWinregKey:
    """In-memory handle for a simulated Windows registry key."""

    def __init__(self, store: dict[str, tuple[Any, int]], subkey: str) -> None:
        self._store = store
        self.subkey = subkey
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.closed = True


class FakeWinreg:
    """Deterministic in-memory emulation of Python's winreg module."""

    HKEY_CURRENT_USER: int = 0x80000001
    HKEY_LOCAL_MACHINE: int = 0x80000002
    KEY_READ: int = 0x20019
    KEY_SET_VALUE: int = 0x0002
    REG_SZ: int = 1

    def __init__(
        self,
        initial: dict[tuple[int, str], dict[str, tuple[Any, int]]] | None = None,
    ) -> None:
        self.keys: dict[tuple[int, str], dict[str, tuple[Any, int]]] = {}
        if initial:
            for k, v in initial.items():
                self.keys[(k[0], k[1].lower())] = dict(v)
        self.open_error: Exception | None = None
        self.query_error: Exception | None = None
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None

    def OpenKey(
        self,
        key: int,
        sub_key: str,
        reserved: int = 0,
        access: int = KEY_READ,
    ) -> FakeWinregKey:
        del reserved, access
        if self.open_error is not None:
            raise self.open_error
        lookup = (key, sub_key.lower())
        if lookup not in self.keys:
            raise FileNotFoundError(f"Registry key not found: {sub_key}")
        return FakeWinregKey(self.keys[lookup], sub_key)

    def QueryValueEx(self, key: FakeWinregKey, value_name: str) -> tuple[Any, int]:
        if self.query_error is not None:
            raise self.query_error
        if value_name not in key._store:
            raise FileNotFoundError(f"Registry value not found: {value_name}")
        return key._store[value_name]

    def SetValueEx(
        self,
        key: FakeWinregKey,
        value_name: str,
        reserved: int,
        value_type: int,
        value: Any,
    ) -> None:
        del reserved
        if self.set_error is not None:
            raise self.set_error
        key._store[value_name] = (value, value_type)

    def DeleteValue(self, key: FakeWinregKey, value_name: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        if value_name not in key._store:
            raise FileNotFoundError(f"Registry value not found: {value_name}")
        del key._store[value_name]


class FakeHttpResponse:
    """Deterministic in-memory HTTP response context manager."""

    def __init__(
        self,
        body: bytes | str | dict[str, Any] | list[Any],
        status: int = 200,
    ) -> None:
        if isinstance(body, (dict, list)):
            self._raw = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            self._raw = body.encode("utf-8")
        else:
            self._raw = body
        self.status = status
        self.closed = False

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.closed = True


class FakeHttpOpener:
    """Deterministic in-memory replacement for urllib.request.urlopen."""

    def __init__(
        self,
        response: FakeHttpResponse | None = None,
        error: Exception | None = None,
        block_event: threading.Event | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.block_event = block_event
        self.calls: list[tuple[Any, float | None]] = []

    def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
        self.calls.append((req, timeout))
        if self.block_event is not None:
            self.block_event.wait(timeout=5.0)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        raise urllib.error.URLError("No response configured in FakeHttpOpener")

    @staticmethod
    def make_http_error(url: str, code: int, msg: str = "Error") -> urllib.error.HTTPError:
        return urllib.error.HTTPError(url, code, msg, Message(), io.BytesIO(b""))


class FakeBrowserLauncher:
    """Deterministic callable recording opened URLs."""

    def __init__(self, return_value: bool = True) -> None:
        self.return_value = return_value
        self.opened_urls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.opened_urls.append(url)
        return self.return_value


__all__ = [
    "FakeBridgeInstaller",
    "FakeBrowserLauncher",
    "FakeHttpOpener",
    "FakeHttpResponse",
    "FakeStartupService",
    "FakeUpdater",
    "FakeWinreg",
    "FakeWinregKey",
]
