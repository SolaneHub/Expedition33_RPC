"""Core application engine, settings, and lifecycle."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from expedition33_rpc.core.app import is_already_running, main
    from expedition33_rpc.core.platform import release_single_instance_lock
    from expedition33_rpc.core.resources import get_resource_path
    from expedition33_rpc.core.settings import Settings, SettingsService
    from expedition33_rpc.core.startup import (
        is_startup_enabled,
        set_startup_enabled,
        toggle_startup,
    )


def __getattr__(name: str) -> Any:
    match name:
        case "is_already_running" | "main":
            import expedition33_rpc.core.app as app

            return getattr(app, name)
        case "release_single_instance_lock":
            import expedition33_rpc.core.platform as platform

            return getattr(platform, name)
        case "get_resource_path":
            import expedition33_rpc.core.resources as res

            return res.get_resource_path
        case "Settings":
            import expedition33_rpc.core.settings as settings

            return settings.Settings
        case "SettingsService":
            import expedition33_rpc.core.settings as settings

            return settings.SettingsService
        case "is_startup_enabled" | "set_startup_enabled" | "toggle_startup":
            import expedition33_rpc.core.startup as startup

            return getattr(startup, name)
        case _:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "main",
    "get_resource_path",
    "is_already_running",
    "release_single_instance_lock",
    "Settings",
    "SettingsService",
    "is_startup_enabled",
    "set_startup_enabled",
    "toggle_startup",
]


def __dir__() -> list[str]:
    return sorted(__all__)
