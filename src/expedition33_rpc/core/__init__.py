"""Core application engine, settings, and lifecycle."""

from typing import TYPE_CHECKING, Any

from expedition33_rpc.core.platform import is_already_running, release_single_instance_lock
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.core.startup import (
    is_startup_enabled,
    set_startup_enabled,
    toggle_startup,
)

if TYPE_CHECKING:
    from expedition33_rpc.core.app import main

__all__ = [
    "SettingsService",
    "get_resource_path",
    "is_already_running",
    "is_startup_enabled",
    "main",
    "release_single_instance_lock",
    "set_startup_enabled",
    "toggle_startup",
]


def __getattr__(name: str) -> Any:
    if name == "main":
        from expedition33_rpc.core.app import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))
