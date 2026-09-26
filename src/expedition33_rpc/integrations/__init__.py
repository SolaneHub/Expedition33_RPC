"""External service integrations: Discord Rich Presence, UE4SS Mod Bridge, and GitHub Updater."""

from expedition33_rpc.integrations.bridge_installer import (
    find_game_win64_directory,
    install_bridge,
    is_bridge_installed,
    uninstall_bridge,
)
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState

__all__ = [
    "DiscordRPCManager",
    "is_bridge_installed",
    "install_bridge",
    "uninstall_bridge",
    "find_game_win64_directory",
    "AppUpdater",
    "UpdateInfo",
    "UpdateState",
]
