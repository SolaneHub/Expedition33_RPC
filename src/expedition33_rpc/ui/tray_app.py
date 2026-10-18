"""Win32 System Tray application using pystray for Expedition 33 RPC."""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

if (
    sys.platform not in ("win32", "darwin")
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
):
    os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

import pystray
from PIL import Image
from pystray import Menu, MenuItem

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.detector import GameState
from expedition33_rpc.integrations.updater import UpdateInfo
from expedition33_rpc.ui.presentation import (
    format_tray_combat_status,
    format_tray_title,
    format_tray_zone_status,
)


class ExpeditionTrayApp:
    """Manages system tray icon rendering, user interactions, and menu bindings."""

    def __init__(
        self,
        orchestrator: AppOrchestrator | None = None,
        script_dir: str = "",
    ):
        del script_dir
        self._menu_lock = threading.Lock()
        self.icon: Any = None
        self._last_menu_state: tuple[Any, ...] | None = None

        self.orchestrator = orchestrator if orchestrator is not None else AppOrchestrator()
        self._unsubscribe_state: Callable[[], None] | None = None
        if hasattr(self.orchestrator, "subscribe_state_change"):
            self._unsubscribe_state = self.orchestrator.subscribe_state_change(
                self.on_orchestrator_state_change
            )
        self._unsubscribe_update: Callable[[], None] | None = None
        if hasattr(self.orchestrator, "subscribe_update_available"):
            self._unsubscribe_update = self.orchestrator.subscribe_update_available(
                self._on_update_available_wrapper
            )

    def _on_update_available_wrapper(self, update_info: UpdateInfo) -> None:
        self.on_update_available(update_info)

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
                self.orchestrator.is_rpc_connected(),
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

    def menu_game_status(self, *_) -> str:
        if self.orchestrator.current_state.is_running:
            return f"Game: Running (PID: {self.orchestrator.current_state.process_pid})"
        return "Game: Not running"

    def menu_zone_status(self, *_) -> str:
        return format_tray_zone_status(
            self.orchestrator.current_state,
            anti_spoiler=self.orchestrator.is_anti_spoiler_enabled(),
        )

    def menu_combat_status(self, *_) -> str:
        return format_tray_combat_status(
            self.orchestrator.current_state,
            anti_spoiler=self.orchestrator.is_anti_spoiler_enabled(),
        )

    def menu_discord_status(self, *_) -> str:
        if self.orchestrator.is_rpc_connected():
            return "Discord: Connected"
        return "Discord: Standby (Listening)"

    def menu_anti_spoiler_toggle(self, *_) -> str:
        if self.orchestrator.is_anti_spoiler_enabled():
            return "Anti-Spoiler Mode  [Enabled]"
        return "Anti-Spoiler Mode  [Disabled]"

    def action_toggle_anti_spoiler(self, *_):
        self.orchestrator.toggle_anti_spoiler()
        self._safe_update_menu()

    def menu_bridge_toggle(self, *_) -> str:
        if self.orchestrator.is_bridge_installed():
            return "Combat Bridge  [Installed]"
        return "Combat Bridge  [Install Now]"

    def action_toggle_bridge(self, *_):
        self.orchestrator.toggle_bridge()
        self._safe_update_menu()

    def action_select_game_folder(self, *_):
        folder = self._prompt_folder_selection()
        if folder:
            success, msg = self.orchestrator.install_bridge_to(folder)
            if self.icon is not None:
                with contextlib.suppress(Exception):
                    self.icon.notify(
                        "Combat Bridge installed successfully!"
                        if success
                        else f"Installation failed: {msg}",
                        "Expedition 33 RPC",
                    )
            self._safe_update_menu()

    def _prompt_folder_selection(self) -> str | None:
        result: list[str | None] = [None]

        def _ask() -> None:
            root = None
            try:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                try:
                    selected = filedialog.askdirectory(
                        parent=root,
                        title="Select Expedition 33 Win64 or WinGDK Directory",
                    )
                    result[0] = str(selected) if selected else None
                finally:
                    with contextlib.suppress(Exception):
                        root.attributes("-topmost", False)
                        root.update_idletasks()
                        root.update()
                        root.destroy()
            except Exception as e:
                print(f"[TrayApp] Directory dialog error: {e}")
                result[0] = None

        thread = threading.Thread(target=_ask, daemon=True)
        thread.start()
        thread.join()
        return result[0]

    def menu_startup_toggle(self, *_) -> str:
        if self.orchestrator.is_startup_enabled():
            return "Start with Windows  [X]"
        return "Start with Windows  [ ]"

    def action_toggle_startup(self, *_):
        self.orchestrator.toggle_startup()
        self._safe_update_menu()

    def menu_update_status(self, *_) -> str:
        return self.orchestrator.get_updater_status_text()

    def action_update_click(self, *_):
        self.orchestrator.trigger_update_action()

    def action_exit(self, *_):
        if self._unsubscribe_state is not None:
            self._unsubscribe_state()
            self._unsubscribe_state = None
        if self._unsubscribe_update is not None:
            self._unsubscribe_update()
            self._unsubscribe_update = None
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
            MenuItem("Select Game Folder...", self.action_select_game_folder),
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
            self.icon.run()


__all__ = ["ExpeditionTrayApp"]
