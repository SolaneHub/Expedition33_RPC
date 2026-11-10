"""Headless application orchestrator coordinating telemetry, presence, updates, and settings."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from expedition33_rpc.core import startup
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.detection.save_reader import SaveFileReader
from expedition33_rpc.integrations import bridge_installer as bridge_installer_module
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState
from expedition33_rpc.ui.presentation import build_presence_payload

logger = logging.getLogger(__name__)


@runtime_checkable
class BridgeInstallerProtocol(Protocol):
    """Protocol defining the bridge installer operations."""

    def find_game_win64_directory(
        self,
        target_process_names: Iterable[str] | str | None = None,
        known_win64_dir: Path | str | None = None,
        known_exe_path: Path | str | None = None,
    ) -> str | None: ...

    def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool: ...

    def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]: ...

    def uninstall_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]: ...


@runtime_checkable
class StartupProtocol(Protocol):
    """Protocol defining Windows autostart management operations."""

    def is_startup_enabled(self) -> bool: ...

    def set_startup_enabled(self, enable: bool) -> bool: ...

    def sync_startup_path(self) -> None: ...

    def toggle_startup(self) -> bool: ...


@runtime_checkable
class UpdaterProtocol(Protocol):
    """Protocol defining update checker lifecycle and status operations."""

    state: UpdateState
    available_update: UpdateInfo | None
    error_message: str | None

    def cancel(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def check_in_background(
        self,
        delay_seconds: float = ...,
        on_complete: Callable[[UpdateInfo | None], None] | None = ...,
    ) -> None: ...

    def open_release_page(self) -> bool: ...

    def get_status_text(self) -> str: ...


class AppOrchestrator:
    """Headless controller coordinating telemetry detection, Discord RPC, auto-updates, and settings."""

    on_state_change: Callable[[GameState, bool], None] | None = None
    on_update_available: Callable[[UpdateInfo], None] | None = None

    def __init__(
        self,
        detector: GameDetector | None = None,
        rpc_manager: DiscordRPCManager | None = None,
        updater: UpdaterProtocol | None = None,
        settings_service: SettingsService | None = None,
        bridge_installer: BridgeInstallerProtocol | None = None,
        startup_service: StartupProtocol | None = None,
        auto_install_bridge: bool = False,
        sync_startup: bool = False,
        on_state_change: Callable[[GameState, bool], None] | None = None,
        on_update_available: Callable[[UpdateInfo], None] | None = None,
        polling_interval: float = 2.0,
        idle_polling_interval: float | None = None,
        time_provider: Callable[[], float] | None = None,
    ):
        self.settings_service = (
            settings_service if settings_service is not None else SettingsService()
        )
        self.detector = (
            detector if detector is not None else GameDetector(save_reader=SaveFileReader())
        )
        self.time_provider = time_provider if time_provider is not None else time.monotonic
        self.updater: UpdaterProtocol = updater if updater is not None else AppUpdater()
        self.bridge_installer: BridgeInstallerProtocol = (
            bridge_installer if bridge_installer is not None else bridge_installer_module
        )
        self.startup_service: StartupProtocol = (
            startup_service if startup_service is not None else startup
        )

        self.auto_install_bridge = auto_install_bridge
        self.sync_startup = sync_startup
        self.polling_interval = polling_interval
        self.idle_polling_interval: float = (
            idle_polling_interval
            if idle_polling_interval is not None
            else (max(polling_interval, 5.0) if polling_interval >= 1.0 else polling_interval)
        )

        # Threading and deterministic shutdown
        self._stop_event = threading.Event()
        self.running = False
        self.worker_thread: threading.Thread | None = None

        # RPC manager with stop predicate injection
        if rpc_manager is not None:
            self.rpc_manager = rpc_manager
            if self.rpc_manager.is_stopping is None:
                self.rpc_manager.is_stopping = self._is_stopping
        else:
            self.rpc_manager = DiscordRPCManager(is_stopping=self._is_stopping)

        self._state_subscribers: list[Callable[[GameState, bool], None]] = []
        self.on_state_change: Callable[[GameState, bool], None] | None = on_state_change
        self._update_available_subscribers: list[Callable[[UpdateInfo], None]] = []
        self.on_update_available: Callable[[UpdateInfo], None] | None = on_update_available

        # Current state - immutable GameState DTO, assignment is atomic
        self.current_state = GameState()

        self.bridge_install_cooldown: float = 30.0
        self.last_bridge_install_attempt: float = -float("inf")
        self._bridge_install_thread: threading.Thread | None = None

        self._bridge_installed: bool = False

        if self.sync_startup:
            self.startup_service.sync_startup_path()

    def subscribe_state_change(
        self, callback: Callable[[GameState, bool], None]
    ) -> Callable[[], None]:
        """Subscribes a listener to game presence state changes and returns an unsubscribe callable."""
        self._state_subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._state_subscribers:
                self._state_subscribers.remove(callback)

        return unsubscribe

    def subscribe_update_available(
        self, callback: Callable[[UpdateInfo], None]
    ) -> Callable[[], None]:
        """Subscribes a listener to update available notifications and returns an unsubscribe callable."""
        self._update_available_subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._update_available_subscribers:
                self._update_available_subscribers.remove(callback)

        return unsubscribe

    def _is_stopping(self) -> bool:
        return self._stop_event.is_set()

    def on_update_check_complete(self, update_info: UpdateInfo | None) -> None:
        if update_info is None:
            return

        for subscriber in list(self._update_available_subscribers):
            try:
                subscriber(update_info)
            except Exception as e:
                logger.error("Update subscriber error: %s", e)

        if (
            self.on_update_available is not None
            and self.on_update_available not in self._update_available_subscribers
        ):
            try:
                self.on_update_available(update_info)
            except Exception as e:
                logger.error("Update listener error: %s", e)

    def install_bridge_to(self, folder: str | Path) -> tuple[bool, str]:
        """Atomically installs the bridge to the specified folder and updates internal state."""
        try:
            target_path = Path(folder) if isinstance(folder, str) else folder
            success, msg = self.bridge_installer.install_bridge(target_path)
            if success:
                self._bridge_installed = True
            return success, msg
        except Exception as e:
            return False, f"Bridge installation error: {e}"

    def check_and_auto_install_bridge(
        self,
        now: float | None = None,
        known_win64_dir: str | None = None,
        known_exe_path: str | None = None,
    ) -> bool:
        """Checks game installation directory and automatically deploys the bridge mod with deterministic cooldown."""
        current_time = self.time_provider() if now is None else now
        if current_time - self.last_bridge_install_attempt < self.bridge_install_cooldown:
            return False

        self.last_bridge_install_attempt = current_time
        try:
            target_dir = known_win64_dir or (
                str(self.current_state.win64_dir) if self.current_state.win64_dir else None
            )
            target_exe = known_exe_path or self.current_state.exe_path
            game_dir = self.bridge_installer.find_game_win64_directory(
                known_win64_dir=target_dir, known_exe_path=target_exe
            )
            if game_dir:
                if self.bridge_installer.is_bridge_installed(game_dir):
                    self._bridge_installed = True
                    return True

                success, msg = self.bridge_installer.install_bridge(game_dir)
                if success:
                    self._bridge_installed = True
                    logger.info("Automatically deployed Combat Bridge to: %s", game_dir)
                    return True
                else:
                    logger.error("Combat Bridge auto-install failed: %s", msg)
        except Exception as e:
            logger.error("Bridge auto-install check failed: %s", e)
        return False

    def step_update(self) -> GameState | None:
        """Executes a single synchronous telemetry polling and presence update tick."""
        if self._is_stopping():
            return None
        try:
            anti_spoiler = self.settings_service.is_anti_spoiler_enabled()
            prev_state = self.current_state
            state = self.detector.get_game_state()
            self.current_state = state

            if self._is_stopping():
                return None

            if state.is_running:
                payload = build_presence_payload(state, anti_spoiler=anti_spoiler)
                self.rpc_manager.update(payload, pid=state.process_pid)
            else:
                self.rpc_manager.update(None, pid=state.process_pid)

            # Event-driven bridge check on game process detection
            is_new_process = state.is_running and (
                not prev_state.is_running
                or state.process_pid != prev_state.process_pid
                or (
                    state.process_create_time is not None
                    and prev_state.process_create_time is not None
                    and state.process_create_time != prev_state.process_create_time
                )
            )

            if is_new_process:
                target_dir = state.win64_dir
                if self.auto_install_bridge:
                    is_installing = bool(
                        self._bridge_install_thread and self._bridge_install_thread.is_alive()
                    )
                    if not is_installing:
                        now_val = self.time_provider()
                        win64_dir_str = str(target_dir) if target_dir else None
                        exe_path_val = state.exe_path

                        def _async_install() -> None:
                            try:
                                self.check_and_auto_install_bridge(
                                    now=now_val,
                                    known_win64_dir=win64_dir_str,
                                    known_exe_path=exe_path_val,
                                )
                            except Exception as e:
                                logger.error("Combat Bridge async auto-install failed: %s", e)

                        install_thread = threading.Thread(
                            target=_async_install,
                            name="BridgeAutoInstallerThread",
                            daemon=True,
                        )
                        self._bridge_install_thread = install_thread
                        install_thread.start()
                else:
                    with contextlib.suppress(Exception):
                        self._bridge_installed = self.bridge_installer.is_bridge_installed(
                            target_dir
                        )

            # Notify subscribed listeners and legacy on_state_change
            if self._state_subscribers:
                for sub in list(self._state_subscribers):
                    try:
                        sub(state, anti_spoiler)
                    except Exception as e:
                        logger.error("State subscriber error: %s", e)
            if (
                self.on_state_change is not None
                and self.on_state_change not in self._state_subscribers
            ):
                try:
                    self.on_state_change(state, anti_spoiler)
                except Exception as e:
                    logger.error("State change callback error: %s", e)

            return state
        except Exception as e:
            logger.error("Worker step error: %s", e)
            return None

    @property
    def current_polling_interval(self) -> float:
        """Adaptive polling interval: returns idle_polling_interval when idle, else polling_interval."""
        return (
            self.polling_interval if self.current_state.is_running else self.idle_polling_interval
        )

    def run_loop(self) -> None:
        """Background worker loop executing periodic step_update calls with adaptive idle backoff."""
        while self.running and not self._stop_event.is_set():
            self.step_update()
            if self._stop_event.wait(timeout=self.current_polling_interval):
                break

    def start(self) -> None:
        """Starts the background worker thread and checks for updates."""
        if self.running:
            return
        self._stop_event.clear()
        self.running = True
        self.worker_thread = threading.Thread(target=self.run_loop, daemon=True)
        self.worker_thread.start()

        # Background update check (delayed 3s to prioritize initial game detection)
        self.updater.check_in_background(
            delay_seconds=3.0,
            on_complete=self.on_update_check_complete,
        )

    def stop(self) -> None:
        """Stops the orchestrator and disconnects RPC."""
        self.running = False
        self._stop_event.set()
        current = threading.current_thread()
        deadline = time.monotonic() + 3.0

        if self.worker_thread is not None:
            if self.worker_thread is not current:
                self.worker_thread.join(timeout=max(0.0, deadline - time.monotonic()))
            self.worker_thread = None

        if self._bridge_install_thread is not None:
            if self._bridge_install_thread is not current:
                self._bridge_install_thread.join(timeout=max(0.0, deadline - time.monotonic()))
            self._bridge_install_thread = None

        with contextlib.suppress(Exception):
            self.updater.cancel()
        if hasattr(self.updater, "join"):
            with contextlib.suppress(Exception):
                self.updater.join(timeout=max(0.0, deadline - time.monotonic()))
        else:
            updater_thread = getattr(self.updater, "_worker_thread", None)
            if isinstance(updater_thread, threading.Thread) and updater_thread is not current:
                updater_thread.join(timeout=max(0.0, deadline - time.monotonic()))

        self.rpc_manager.disconnect()

    def toggle_anti_spoiler(self) -> bool:
        """Toggles anti-spoiler configuration and flushes presence."""
        new_val = self.settings_service.toggle_anti_spoiler()
        self.rpc_manager.invalidate()
        return new_val

    def is_bridge_installed(self, force_probe: bool = False) -> bool:
        """Checks if the UE4SS Lua bridge mod is installed from in-memory cache in O(1)."""
        if force_probe:
            with contextlib.suppress(Exception):
                self._bridge_installed = self.bridge_installer.is_bridge_installed(
                    self.current_state.win64_dir
                )
        return self._bridge_installed

    def is_startup_enabled(self) -> bool:
        """Checks if Windows autostart is enabled."""
        return self.startup_service.is_startup_enabled()

    def toggle_bridge(self) -> bool:
        """Installs or uninstalls the UE4SS Lua bridge mod."""
        self.last_bridge_install_attempt = -float("inf")
        target_dir = self.current_state.win64_dir
        if self.is_bridge_installed():
            self.bridge_installer.uninstall_bridge(target_dir)
            self._bridge_installed = False
            return False
        else:
            success, _msg = self.bridge_installer.install_bridge(target_dir)
            if success:
                self._bridge_installed = True
            return success

    def toggle_startup(self) -> bool:
        """Toggles Windows autostart configuration."""
        return self.startup_service.toggle_startup()

    def is_rpc_connected(self) -> bool:
        """Returns True if the Discord IPC wire client is actively connected."""
        return self.rpc_manager.is_connected

    def is_anti_spoiler_enabled(self) -> bool:
        """Returns True if anti-spoiler mode is active in persistent settings."""
        return self.settings_service.is_anti_spoiler_enabled()

    def get_updater_status_text(self) -> str:
        """Returns player-facing update status text from the updater component."""
        return self.updater.get_status_text()

    def is_update_available(self) -> bool:
        """Returns True if a newer version has been discovered and is ready to download."""
        return self.updater.state == UpdateState.AVAILABLE

    def trigger_update_action(self) -> None:
        """Opens GitHub releases if an update is available, or requests immediate background check."""
        if self.updater.state == UpdateState.AVAILABLE:
            self.updater.open_release_page()
        elif self.updater.state in (
            UpdateState.IDLE,
            UpdateState.UP_TO_DATE,
            UpdateState.ERROR,
        ):
            self.updater.check_in_background(
                delay_seconds=0.0, on_complete=self.on_update_check_complete
            )

    def get_status_snapshot(self) -> dict[str, Any]:
        """Returns an exposed status snapshot across all orchestrator subsystems."""
        return {
            "running": self.running,
            "game_state": self.current_state,
            "rpc_connected": self.is_rpc_connected(),
            "anti_spoiler": self.is_anti_spoiler_enabled(),
            "bridge_installed": self.is_bridge_installed(),
            "startup_enabled": self.is_startup_enabled(),
            "update_available": self.is_update_available(),
            "updater_status": self.get_updater_status_text(),
        }


__all__ = ["AppOrchestrator", "BridgeInstallerProtocol", "StartupProtocol", "UpdaterProtocol"]
