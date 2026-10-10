"""Headless application orchestrator coordinating telemetry, presence, updates, and settings."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

from expedition33_rpc.core import startup
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations import bridge_installer
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState


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
        bridge_installer_service: Any = None,
        startup_service: Any = None,
        auto_install_bridge: bool = False,
        sync_startup: bool = False,
        on_state_change: Callable[[GameState, bool], None] | None = None,
        on_update_available: Callable[[UpdateInfo], None] | None = None,
        polling_interval: float = 2.0,
    ):
        self.settings_service = (
            settings_service if settings_service is not None else SettingsService()
        )
        self.detector = detector if detector is not None else GameDetector()
        self.rpc_manager = rpc_manager if rpc_manager is not None else DiscordRPCManager()
        self.updater = (
            updater
            if updater is not None
            else AppUpdater(on_state_change=self._on_updater_state_change)
        )
        self.bridge_installer: Any = (
            bridge_installer_service if bridge_installer_service is not None else bridge_installer
        )
        self.startup_service: Any = startup_service if startup_service is not None else startup

        self.auto_install_bridge = auto_install_bridge
        self.sync_startup = sync_startup
        self.polling_interval = polling_interval

        self.on_state_change: Callable[[GameState, bool], None] | None = on_state_change
        self.on_update_available: Callable[[UpdateInfo], None] | None = on_update_available

        self.current_state = GameState()
        self._state_lock = threading.Lock()
        self.running = False
        self.worker_thread: threading.Thread | None = None
        self.bridge_auto_installed = False

        self.bridge_install_min_cooldown: float = 30.0
        self.bridge_install_max_cooldown: float = 300.0
        self.bridge_install_cooldown: float = self.bridge_install_min_cooldown
        self.last_bridge_install_attempt: float = -float("inf")

        self._bridge_installed: bool = False
        self._last_detected_pid: int | None = None
        self._last_detected_start_time: float | None = None

        if self.sync_startup:
            self.startup_service.sync_startup_path()

    def _on_updater_state_change(self) -> None:
        pass

    def on_update_check_complete(self, update_info: UpdateInfo | None) -> None:
        if update_info and self.on_update_available is not None:
            try:
                self.on_update_available(update_info)
            except Exception as e:
                print(f"[Orchestrator] Update listener error: {e}")

    def check_and_auto_install_bridge(
        self,
        now: float | None = None,
        known_win64_dir: str | None = None,
        known_exe_path: str | None = None,
    ) -> bool:
        """Checks game installation directory and automatically deploys the bridge mod with backoff."""
        current_time = time.monotonic() if now is None else now
        if current_time - self.last_bridge_install_attempt < self.bridge_install_cooldown:
            return False

        self.last_bridge_install_attempt = current_time
        try:
            target_dir = known_win64_dir or (
                str(self.detector.win64_dir) if self.detector.win64_dir else None
            )
            target_exe = known_exe_path or self.detector.exe_path
            game_dir = self.bridge_installer.find_game_win64_directory(
                known_win64_dir=target_dir, known_exe_path=target_exe
            )
            if game_dir:
                if self.bridge_installer.is_bridge_installed(game_dir):
                    self.bridge_auto_installed = True
                    self._bridge_installed = True
                    self.bridge_install_cooldown = self.bridge_install_min_cooldown
                    return True

                success, msg = self.bridge_installer.install_bridge(game_dir)
                if success:
                    self.bridge_auto_installed = True
                    self._bridge_installed = True
                    self.bridge_install_cooldown = self.bridge_install_min_cooldown
                    print(f"[Orchestrator] Automatically deployed Combat Bridge to: {game_dir}")
                    return True
                else:
                    self.bridge_install_cooldown = min(
                        self.bridge_install_cooldown * 2, self.bridge_install_max_cooldown
                    )
                    print(
                        f"[Orchestrator] Combat Bridge auto-install failed ({msg}), "
                        f"backing off for {self.bridge_install_cooldown:.1f}s"
                    )
        except Exception as e:
            self.bridge_install_cooldown = min(
                self.bridge_install_cooldown * 2, self.bridge_install_max_cooldown
            )
            print(f"[Orchestrator] Bridge auto-install check failed: {e}")
        return False

    def step_update(self) -> GameState | None:
        """Executes a single synchronous telemetry polling and presence update tick."""
        try:
            anti_spoiler = self.settings_service.is_anti_spoiler_enabled()
            state = self.detector.get_game_state()
            with self._state_lock:
                self.current_state = state
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
                target_dir = self.detector.win64_dir
                if self.auto_install_bridge:
                    self.check_and_auto_install_bridge(
                        now=time.monotonic(),
                        known_win64_dir=str(target_dir) if target_dir else None,
                        known_exe_path=self.detector.exe_path,
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
        while self.running:
            self.step_update()
            time.sleep(self.polling_interval)

    def start(self) -> None:
        """Starts the background worker thread and checks for updates."""
        if self.running:
            return
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
                    self.detector.win64_dir
                )
        return self._bridge_installed

    def is_startup_enabled(self) -> bool:
        """Checks if Windows autostart is enabled."""
        return self.startup_service.is_startup_enabled()

    def toggle_bridge(self) -> bool:
        """Installs or uninstalls the UE4SS Lua bridge mod."""
        self.last_bridge_install_attempt = -float("inf")
        self.bridge_install_cooldown = self.bridge_install_min_cooldown
        target_dir = self.detector.win64_dir
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


__all__ = ["AppOrchestrator"]
