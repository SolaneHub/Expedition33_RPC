"""Core application engine, settings, and lifecycle."""

from expedition33_rpc.core.app import is_already_running, main
from expedition33_rpc.core.settings import (
    is_anti_spoiler_enabled,
    set_anti_spoiler_enabled,
    toggle_anti_spoiler,
)
from expedition33_rpc.core.startup import (
    is_startup_enabled,
    set_startup_enabled,
    toggle_startup,
)

__all__ = [
    "main",
    "is_already_running",
    "is_anti_spoiler_enabled",
    "set_anti_spoiler_enabled",
    "toggle_anti_spoiler",
    "is_startup_enabled",
    "set_startup_enabled",
    "toggle_startup",
]
