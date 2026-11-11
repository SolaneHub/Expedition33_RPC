"""Protocol-compliant test doubles for orchestrator and integration services."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.synced = False

    def is_startup_enabled(self) -> bool:
        return self.enabled

    def set_startup_enabled(self, enable: bool) -> bool:
        self.enabled = enable
        return True

    def sync_startup_path(self) -> None:
        self.synced = True

    def toggle_startup(self) -> bool:
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
    ) -> None:
        self.state = state
        self.available_update = available_update
        self.error_message = error_message
        self.cancel_called = False
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
        del delay_seconds, on_complete

        def _run() -> None:
            if self._worker_started_event is not None:
                self._worker_started_event.set()
            if self._release_worker_event is not None:
                self._release_worker_event.wait(timeout=2.0)

        t = threading.Thread(target=_run, name="FakeUpdaterWorker", daemon=True)
        self.worker_thread = t
        t.start()

    def open_release_page(self) -> bool:
        return True

    def get_status_text(self) -> str:
        return "Fake Updater Status"


__all__ = [
    "FakeBridgeInstaller",
    "FakeStartupService",
    "FakeUpdater",
]
