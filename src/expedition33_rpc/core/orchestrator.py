"""Headless application orchestrator coordinating telemetry, presence, updates, and settings."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from expedition33_rpc.core import startup
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations import bridge_installer
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo


class AppOrchestrator:
    """Headless controller coordinating telemetry detection, Discord RPC, auto-updates, and settings."""

    def __init__(
        self,
        detector: GameDetector | None = None,
        rpc_manager: DiscordRPCManager | None = None,
        updater: AppUpdater | None = None,
        settings_service: SettingsService | None = None,
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

        self.auto_install_bridge = auto_install_bridge
        self.sync_startup = sync_startup
        self.on_state_change = on_state_change
        self.on_update_available = on_update_available
        self.polling_interval = polling_interval

        self.current_state = GameState()
        self._state_lock = threading.Lock()
        self.running = False
        self.worker_thread: threading.Thread | None = None
        self.bridge_auto_installed = False

        if self.auto_install_bridge:
            self.check_and_auto_install_bridge()

        if self.sync_startup:
            startup.sync_startup_path()

    def _on_updater_state_change(self) -> None:
        pass

    def on_update_check_complete(self, update_info: UpdateInfo | None) -> None:
        if update_info and self.on_update_available:
            self.on_update_available(update_info)

    def check_and_auto_install_bridge(self) -> bool:
        """Checks game installation directory and automatically deploys the bridge mod."""
        try:
            game_dir = bridge_installer.find_game_win64_directory()
            if game_dir and not bridge_installer.is_bridge_installed(game_dir):
                success, _msg = bridge_installer.install_bridge(game_dir)
                if success:
                    self.bridge_auto_installed = True
                    print(f"[Orchestrator] Automatically deployed Combat Bridge to: {game_dir}")
                    return True
        except Exception as e:
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

            # Periodic auto-install check while game is running
            if (
                self.auto_install_bridge
                and state.is_running
                and not self.bridge_auto_installed
                and not self.is_bridge_installed()
            ):
                self.check_and_auto_install_bridge()

            if self.on_state_change:
                self.on_state_change(state, anti_spoiler)

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
        """Toggles anti-spoiler configuration and flushes active presence."""
        new_val = self.settings_service.toggle_anti_spoiler()
        self.rpc_manager.last_update_state = None
        self.rpc_manager.update(self.current_state, anti_spoiler=new_val)
        return new_val

    def is_bridge_installed(self) -> bool:
        """Checks if the UE4SS Lua bridge mod is installed."""
        return bridge_installer.is_bridge_installed()

    def is_startup_enabled(self) -> bool:
        """Checks if Windows autostart is enabled."""
        return startup.is_startup_enabled()

    def toggle_bridge(self) -> bool:
        """Installs or uninstalls the UE4SS Lua bridge mod."""
        if self.is_bridge_installed():
            bridge_installer.uninstall_bridge()
            return False
        else:
            bridge_installer.install_bridge()
            return True

    def toggle_startup(self) -> bool:
        """Toggles Windows autostart configuration."""
        return startup.toggle_startup()


__all__ = ["AppOrchestrator"]
