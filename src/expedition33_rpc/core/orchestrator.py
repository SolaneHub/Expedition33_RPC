"""Headless application orchestrator coordinating telemetry, presence, updates, and settings."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from expedition33_rpc.core import startup
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations import bridge_installer
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState


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


class _DefaultBridgeInstaller:
    """Default adapter delegating to expedition33_rpc.integrations.bridge_installer module."""

    def find_game_win64_directory(
        self,
        target_process_names: Iterable[str] | str | None = None,
        known_win64_dir: Path | str | None = None,
        known_exe_path: Path | str | None = None,
    ) -> str | None:
        return bridge_installer.find_game_win64_directory(
            target_process_names=target_process_names,
            known_win64_dir=known_win64_dir,
            known_exe_path=known_exe_path,
        )

    def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
        return bridge_installer.is_bridge_installed(win64_dir=win64_dir)

    def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        return bridge_installer.install_bridge(win64_dir=win64_dir)

    def uninstall_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        return bridge_installer.uninstall_bridge(win64_dir=win64_dir)


class _DefaultStartupService:
    """Default adapter delegating to expedition33_rpc.core.startup module."""

    def is_startup_enabled(self) -> bool:
        return startup.is_startup_enabled()

    def set_startup_enabled(self, enable: bool) -> bool:
        return startup.set_startup_enabled(enable)

    def sync_startup_path(self) -> None:
        startup.sync_startup_path()

    def toggle_startup(self) -> bool:
        return startup.toggle_startup()


class AppOrchestrator:
    """Headless controller coordinating telemetry detection, Discord RPC, auto-updates, and settings."""

    on_state_change: Callable[[GameState, bool], None] | None = None
    on_update_available: Callable[[UpdateInfo], None] | None = None

    def __init__(
        self,
        detector: GameDetector | None = None,
        rpc_manager: DiscordRPCManager | None = None,
        updater: AppUpdater | None = None,
        settings_service: SettingsService | None = None,
        bridge_installer: BridgeInstallerProtocol | None = None,
        startup_service: StartupProtocol | None = None,
        auto_install_bridge: bool = False,
        sync_startup: bool = False,
        on_state_change: Callable[[GameState, bool], None] | None = None,
        on_update_available: Callable[[UpdateInfo], None] | None = None,
        polling_interval: float = 2.0,
        time_provider: Callable[[], float] | None = None,
    ):
        self.settings_service = (
            settings_service if settings_service is not None else SettingsService()
        )
        self.detector = detector if detector is not None else GameDetector()
        self.time_provider = time_provider if time_provider is not None else time.monotonic
        self.updater = (
            updater
            if updater is not None
            else AppUpdater(on_state_change=self._on_updater_state_change)
        )
        self.bridge_installer: BridgeInstallerProtocol = (
            bridge_installer if bridge_installer is not None else _DefaultBridgeInstaller()
        )
        self.startup_service: StartupProtocol = (
            startup_service if startup_service is not None else _DefaultStartupService()
        )

        self.auto_install_bridge = auto_install_bridge
        self.sync_startup = sync_startup
        self.polling_interval = polling_interval

        # Threading and deterministic shutdown
        self._stop_event = threading.Event()
        self.running = False
        self._started = False
        self.worker_thread: threading.Thread | None = None

        # RPC manager with stop predicate injection
        if rpc_manager is not None:
            self.rpc_manager = rpc_manager
            if self.rpc_manager.is_stopping is None:
                self.rpc_manager.is_stopping = self._is_stopping
        else:
            self.rpc_manager = DiscordRPCManager(is_stopping=self._is_stopping)

        # 1-to-1 event callbacks
        self.on_state_change: Callable[[GameState, bool], None] | None = on_state_change
        self.on_update_available: Callable[[UpdateInfo], None] | None = on_update_available

        # Current state - immutable GameState DTO, assignment is atomic
        self.current_state = GameState()
        self.bridge_auto_installed = False

        self.bridge_install_cooldown: float = 30.0
        self.last_bridge_install_attempt: float = -float("inf")

        self._bridge_installed: bool = False
        self._last_detected_pid: int | None = None
        self._last_detected_start_time: float | None = None

        if self.sync_startup:
            self.startup_service.sync_startup_path()

    def _is_stopping(self) -> bool:
        return self._stop_event.is_set() or (self._started and not self.running)

    def subscribe_state_change(self, callback: Callable[[GameState, bool], None]) -> None:
        """Sets the observer callback to receive game state changes."""
        self.on_state_change = callback

    def unsubscribe_state_change(
        self, callback: Callable[[GameState, bool], None] | None = None
    ) -> None:
        """Unsubscribes the observer callback from game state changes."""
        if callback is None or self.on_state_change == callback:
            self.on_state_change = None

    def subscribe_update_available(self, callback: Callable[[UpdateInfo], None]) -> None:
        """Sets the observer callback to receive update notifications."""
        self.on_update_available = callback

    def unsubscribe_update_available(
        self, callback: Callable[[UpdateInfo], None] | None = None
    ) -> None:
        """Unsubscribes the observer callback from update notifications."""
        if callback is None or self.on_update_available == callback:
            self.on_update_available = None

    def _on_updater_state_change(self) -> None:
        pass

    def on_update_check_complete(self, update_info: UpdateInfo | None) -> None:
        if update_info is not None and self.on_update_available is not None:
            try:
                self.on_update_available(update_info)
            except Exception as e:
                print(f"[Orchestrator] Update listener error: {e}")

    def install_bridge_to(self, folder: str | Path) -> tuple[bool, str]:
        """Atomically installs the bridge to the specified folder and updates internal state."""
        try:
            target_path = Path(folder) if isinstance(folder, str) else folder
            success, msg = self.bridge_installer.install_bridge(target_path)
            if success:
                self.bridge_auto_installed = True
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
                    self.bridge_auto_installed = True
                    self._bridge_installed = True
                    return True

                success, msg = self.bridge_installer.install_bridge(game_dir)
                if success:
                    self.bridge_auto_installed = True
                    self._bridge_installed = True
                    print(f"[Orchestrator] Automatically deployed Combat Bridge to: {game_dir}")
                    return True
                else:
                    print(f"[Orchestrator] Combat Bridge auto-install failed: {msg}")
        except Exception as e:
            print(f"[Orchestrator] Bridge auto-install check failed: {e}")
        return False

    def step_update(self) -> GameState | None:
        """Executes a single synchronous telemetry polling and presence update tick."""
        if self._is_stopping():
            return None
        try:
            anti_spoiler = self.settings_service.is_anti_spoiler_enabled()
            state = self.detector.get_game_state()
            self.current_state = state

            if self._is_stopping():
                return None

            self.rpc_manager.update(state, anti_spoiler=anti_spoiler)

            # Event-driven bridge check on game process detection
            current_pid = (
                state.process_pid
                if state.process_pid is not None
                else (1 if state.is_running else None)
            )
            current_start_time = state.start_time
            is_new_process = current_pid is not None and (
                self._last_detected_pid is None
                or current_pid != self._last_detected_pid
                or (
                    current_start_time is not None
                    and current_start_time != self._last_detected_start_time
                )
            )

            if is_new_process:
                target_dir = state.win64_dir
                if self.auto_install_bridge:
                    self.check_and_auto_install_bridge(
                        now=self.time_provider(),
                        known_win64_dir=str(target_dir) if target_dir else None,
                        known_exe_path=state.exe_path,
                    )
                else:
                    with contextlib.suppress(Exception):
                        self._bridge_installed = self.bridge_installer.is_bridge_installed(
                            target_dir
                        )

            self._last_detected_pid = current_pid
            self._last_detected_start_time = current_start_time if current_pid is not None else None

            if self.on_state_change is not None:
                try:
                    self.on_state_change(state, anti_spoiler)
                except Exception as e:
                    print(f"[Orchestrator] State change callback error: {e}")

            return state
        except Exception as e:
            print(f"[Orchestrator] Worker step error: {e}")
            return None

    def run_loop(self) -> None:
        """Background worker loop executing periodic step_update calls."""
        while self.running and not self._stop_event.is_set():
            self.step_update()
            if self._stop_event.wait(timeout=self.polling_interval):
                break

    def start(self) -> None:
        """Starts the background worker thread and checks for updates."""
        if self.running:
            return
        self._stop_event.clear()
        self._started = True
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
        if self.worker_thread is not None and self.worker_thread.is_alive():
            if threading.current_thread() != self.worker_thread:
                self.worker_thread.join(timeout=3.0)
            self.worker_thread = None
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
            self.bridge_auto_installed = False
            self._bridge_installed = False
            return False
        else:
            success, _msg = self.bridge_installer.install_bridge(target_dir)
            if success:
                self.bridge_auto_installed = True
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


__all__ = ["AppOrchestrator", "BridgeInstallerProtocol", "StartupProtocol"]
