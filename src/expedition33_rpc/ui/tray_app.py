"""Win32 System Tray application using pystray for Expedition 33 RPC."""

from __future__ import annotations

import contextlib
import os
import threading
from typing import Any

import pystray
from PIL import Image
from pystray import Menu, MenuItem

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState
from expedition33_rpc.ui.presentation import (
    format_tray_combat_status,
    format_tray_title,
    format_tray_zone_status,
)


class ExpeditionTrayApp:
    """Manages system tray icon rendering, user interactions, and menu bindings."""

    def __init__(
        self,
        script_dir: str = "",
        orchestrator: AppOrchestrator | None = None,
        *,
        detector: GameDetector | None = None,
        rpc_manager: DiscordRPCManager | None = None,
        updater: AppUpdater | None = None,
        settings_service: SettingsService | None = None,
        auto_install_bridge: bool = False,
        sync_startup: bool = False,
    ):
        self.script_dir = script_dir
        self._menu_lock = threading.Lock()
        self.icon: Any = None
        self._last_menu_state: tuple[Any, ...] | None = None

        if orchestrator is not None:
            self.orchestrator = orchestrator
        else:
            self.orchestrator = AppOrchestrator(
                detector=detector,
                rpc_manager=rpc_manager,
                updater=updater,
                settings_service=settings_service,
                auto_install_bridge=auto_install_bridge,
                sync_startup=sync_startup,
            )

        self.orchestrator.on_state_change = self.on_orchestrator_state_change
        self.orchestrator.on_update_available = self.on_update_available

    @property
    def current_state(self) -> GameState:
        return self.orchestrator.current_state

    @property
    def _state_lock(self) -> threading.Lock:
        return self.orchestrator._state_lock

    @property
    def detector(self) -> GameDetector:
        return self.orchestrator.detector

    @property
    def rpc_manager(self) -> DiscordRPCManager:
        return self.orchestrator.rpc_manager

    @property
    def updater(self) -> AppUpdater:
        return self.orchestrator.updater

    @property
    def settings_service(self) -> SettingsService:
        return self.orchestrator.settings_service

    @property
    def running(self) -> bool:
        return self.orchestrator.running

    @running.setter
    def running(self, val: bool) -> None:
        self.orchestrator.running = val

    def _safe_update_menu(self) -> None:
        if self.icon is not None:
            with self._menu_lock, contextlib.suppress(Exception):
                self.icon.update_menu()

    def on_orchestrator_state_change(self, state: GameState, anti_spoiler: bool) -> None:
        if self.icon is not None:
            menu_state = (
                state.is_running,
                state.process_pid,
                state.zone_name,
                state.in_combat,
                state.enemy_name,
                state.tower_floor,
                state.tower_stage_trial,
                state.checkpoint_name,
                self.rpc_manager.is_connected,
                anti_spoiler,
            )
            if menu_state != self._last_menu_state:
                self._last_menu_state = menu_state
                self._safe_update_menu()

            self.icon.title = format_tray_title(state, anti_spoiler=anti_spoiler)

    def on_update_available(self, update_info: UpdateInfo) -> None:
        if self.icon is not None:
            with contextlib.suppress(Exception):
                self.icon.notify(
                    f"Version {update_info.tag_name} is available. Open the tray menu to view release.",
                    "Expedition 33 RPC Update",
                )
        self._safe_update_menu()

    def get_icon_image(self) -> Image.Image:
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            try:
                return Image.open(icon_path).convert("RGBA")
            except Exception as e:
                print(f"[TrayApp] Warning loading icon file: {e}")

        # Controlled fallback: 64x64 solid golden icon without binary blobs
        return Image.new("RGBA", (64, 64), color=(212, 175, 55, 255))

    def step_update(self) -> GameState | None:
        """Delegates synchronous polling tick to the application orchestrator."""
        return self.orchestrator.step_update()

    def menu_game_status(self, *_) -> str:
        if self.current_state.is_running:
            return f"Game: Running (PID: {self.current_state.process_pid})"
        return "Game: Not running"

    def menu_zone_status(self, *_) -> str:
        return format_tray_zone_status(
            self.current_state, anti_spoiler=self.settings_service.is_anti_spoiler_enabled()
        )

    def menu_combat_status(self, *_) -> str:
        return format_tray_combat_status(
            self.current_state, anti_spoiler=self.settings_service.is_anti_spoiler_enabled()
        )

    def menu_discord_status(self, *_) -> str:
        if self.rpc_manager.is_connected:
            return "Discord: Connected"
        return "Discord: Standby (Listening)"

    def menu_anti_spoiler_toggle(self, *_) -> str:
        if self.settings_service.is_anti_spoiler_enabled():
            return "Anti-Spoiler Mode  [Enabled]"
        return "Anti-Spoiler Mode  [Disabled]"

    def action_toggle_anti_spoiler(self, *_):
        new_val = self.orchestrator.toggle_anti_spoiler()
        print(f"[TrayApp] Anti-Spoiler toggled to: {new_val}")
        self._safe_update_menu()

    def menu_bridge_toggle(self, *_) -> str:
        if self.orchestrator.is_bridge_installed():
            return "Combat Bridge  [Installed]"
        return "Combat Bridge  [Install Now]"

    def action_toggle_bridge(self, *_):
        self.orchestrator.toggle_bridge()
        self._safe_update_menu()

    def menu_startup_toggle(self, *_) -> str:
        if self.orchestrator.is_startup_enabled():
            return "Start with Windows  [X]"
        return "Start with Windows  [ ]"

    def action_toggle_startup(self, *_):
        self.orchestrator.toggle_startup()
        self._safe_update_menu()

    def menu_update_status(self, *_) -> str:
        return self.updater.get_status_text()

    def action_update_click(self, *_):
        if self.updater.state == UpdateState.AVAILABLE:
            self.updater.open_release_page()
        elif self.updater.state in (UpdateState.IDLE, UpdateState.UP_TO_DATE, UpdateState.ERROR):
            self.updater.check_in_background(
                delay_seconds=0.0, on_complete=self.orchestrator.on_update_check_complete
            )

    def action_exit(self, *_):
        self.orchestrator.stop()
        if self.icon is not None:
            self.icon.stop()

    def create_menu(self) -> Menu:
        return Menu(
            MenuItem("Clair Obscur: Expedition 33 RPC", lambda *_: None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(self.menu_game_status, lambda *_: None, enabled=False),
            MenuItem(self.menu_zone_status, lambda *_: None, enabled=False),
            MenuItem(self.menu_combat_status, lambda *_: None, enabled=False),
            MenuItem(self.menu_discord_status, lambda *_: None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(self.menu_anti_spoiler_toggle, self.action_toggle_anti_spoiler),
            MenuItem(self.menu_bridge_toggle, self.action_toggle_bridge),
            MenuItem(self.menu_startup_toggle, self.action_toggle_startup),
            MenuItem(self.menu_update_status, self.action_update_click),
            Menu.SEPARATOR,
            MenuItem("Exit", self.action_exit),
        )

    def run(self) -> None:
        self.orchestrator.start()
        img = self.get_icon_image()
        self.icon = pystray.Icon(
            name="Expedition33RPC",
            icon=img,
            title="Expedition 33 Discord RPC",
            menu=self.create_menu(),
        )
        if self.icon is not None:
            # Hook Win32 notification to guarantee menu items refresh dynamically on every right click
            icon_obj: Any = self.icon
            orig_on_notify = getattr(icon_obj, "_on_notify", None)
            if callable(orig_on_notify):

                def hooked_on_notify(wparam: Any, lparam: Any) -> Any:
                    # 517 is WM_RBUTTONUP (right mouse button released on tray icon)
                    if lparam == 517 and self.icon is not None:
                        with contextlib.suppress(Exception):
                            self.icon.update_menu()
                    return orig_on_notify(wparam, lparam)

                icon_obj._on_notify = hooked_on_notify

            self.icon.run()


__all__ = ["ExpeditionTrayApp"]
