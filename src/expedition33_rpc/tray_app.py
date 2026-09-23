import base64
import io
import os
import sys
import threading
import time

import pystray
from PIL import Image
from pystray import Menu
from pystray import MenuItem as item

from expedition33_rpc import bridge_installer, startup
from expedition33_rpc.detector import GameDetector, GameState
from expedition33_rpc.discord_rpc import DiscordRPCManager

EMBEDDED_ICON_B64 = "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"


def get_resource_path(filename: str) -> str:
    """Resolves resource path across dev environments and PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        base_meipass = getattr(sys, "_MEIPASS", None)
        if base_meipass:
            bundled_pkg = os.path.join(base_meipass, "expedition33_rpc", "assets", filename)
            if os.path.exists(bundled_pkg):
                return bundled_pkg
            flat_bundled = os.path.join(base_meipass, filename)
            if os.path.exists(flat_bundled):
                return flat_bundled

        exe_dir = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(exe_dir, filename)):
            return os.path.join(exe_dir, filename)

    module_dir = os.path.dirname(os.path.abspath(__file__))
    pkg_asset = os.path.join(module_dir, "assets", filename)
    if os.path.exists(pkg_asset):
        return pkg_asset

    return filename


class ExpeditionTrayApp:
    def __init__(self, script_dir: str = ""):
        self.script_dir = script_dir

        self.detector = GameDetector()
        self.rpc_manager = DiscordRPCManager()

        self.current_state = GameState()
        self.running = True
        self.icon = None
        self.worker_thread = None
        self.bridge_auto_installed = False

        # Attempt automatic combat bridge installation on startup if game folder exists
        self.check_and_auto_install_bridge()

    def check_and_auto_install_bridge(self):
        try:
            game_dir = bridge_installer.find_game_win64_directory()
            if game_dir and not bridge_installer.is_bridge_installed(game_dir):
                success, msg = bridge_installer.install_bridge(game_dir)
                if success:
                    self.bridge_auto_installed = True
                    print(f"[TrayApp] Automatically deployed Combat Bridge to: {game_dir}")
        except Exception as e:
            print(f"[TrayApp] Bridge auto-install check failed: {e}")

    def get_icon_image(self) -> Image.Image:
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            try:
                return Image.open(icon_path).convert("RGBA")
            except Exception as e:
                print(f"[TrayApp] Warning loading icon file: {e}")

        # Infallible fallback: load embedded official 33 icon from base64
        try:
            raw = base64.b64decode(EMBEDDED_ICON_B64)
            return Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception as e:
            print(f"[TrayApp] Fallback icon error: {e}")
            return Image.new("RGBA", (64, 64), color=(212, 175, 55, 255))

    def update_loop(self):
        while self.running:
            try:
                state = self.detector.get_game_state()
                self.current_state = state
                self.rpc_manager.update(state)

                # Periodic auto-install check while game is running
                if (
                    state.is_running
                    and not self.bridge_auto_installed
                    and not bridge_installer.is_bridge_installed()
                ):
                    self.check_and_auto_install_bridge()

                if self.icon is not None:
                    if state.is_running:
                        mode = "In Combat" if state.in_combat else "Exploring"
                        self.icon.title = f"Expedition 33: {state.zone_name} ({mode})"
                    else:
                        self.icon.title = "Expedition 33 RPC (Waiting for game...)"
            except Exception as e:
                print(f"[TrayApp] Worker loop error: {e}")

            time.sleep(2)

    def menu_game_status(self, item) -> str:
        if self.current_state.is_running:
            return f"🎮 Game: Running (PID: {self.current_state.process_pid})"
        return "🎮 Game: Not running"

    def menu_zone_status(self, item) -> str:
        if self.current_state.is_running:
            return f"📍 Location: {self.current_state.zone_name}"
        return "📍 Location: --"

    def menu_combat_status(self, item) -> str:
        if self.current_state.is_running:
            if self.current_state.in_combat:
                return "⚔️ Status: In Combat"
            return "🧭 Status: Exploring"
        return "⚔️ Status: --"

    def menu_discord_status(self, item) -> str:
        if self.rpc_manager.is_connected:
            return "🟢 Discord: Connected"
        return "⚪ Discord: Standby (Listening)"

    def menu_bridge_toggle(self, item) -> str:
        if bridge_installer.is_bridge_installed():
            return "⚔️ Combat Bridge  [✓ Installed]"
        return "⚔️ Combat Bridge  [Install Now]"

    def action_toggle_bridge(self, icon, item):
        if bridge_installer.is_bridge_installed():
            bridge_installer.uninstall_bridge()
        else:
            bridge_installer.install_bridge()

    def menu_startup_toggle(self, item) -> str:
        if startup.is_startup_enabled():
            return "🚀 Start with Windows  [✓]"
        return "🚀 Start with Windows  [ ]"

    def action_toggle_startup(self, icon, item):
        startup.toggle_startup()

    def action_exit(self, icon, item):
        self.running = False
        self.rpc_manager.disconnect()
        if self.icon is not None:
            self.icon.stop()

    def create_menu(self) -> Menu:
        return Menu(
            item("✨ Clair Obscur: Expedition 33 RPC", lambda icon, item: None, enabled=False),
            Menu.SEPARATOR,
            item(self.menu_game_status, lambda icon, item: None, enabled=False),
            item(self.menu_zone_status, lambda icon, item: None, enabled=False),
            item(self.menu_combat_status, lambda icon, item: None, enabled=False),
            item(self.menu_discord_status, lambda icon, item: None, enabled=False),
            Menu.SEPARATOR,
            item(self.menu_bridge_toggle, self.action_toggle_bridge),
            item(self.menu_startup_toggle, self.action_toggle_startup),
            Menu.SEPARATOR,
            item("❌ Exit", self.action_exit),
        )

    def run(self):
        self.worker_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.worker_thread.start()

        img = self.get_icon_image()
        self.icon = pystray.Icon(
            name="Expedition33RPC",
            icon=img,
            title="Expedition 33 Discord RPC",
            menu=self.create_menu(),
        )
        if self.icon is not None:
            self.icon.run()
