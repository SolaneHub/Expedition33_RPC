"""Core application engine, settings, and lifecycle."""

from expedition33_rpc.core.app import is_already_running, main
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.core.startup import (
    is_startup_enabled,
    set_startup_enabled,
    toggle_startup,
)

__all__ = [
    "main",
    "get_resource_path",
    "is_already_running",
    "SettingsService",
    "is_startup_enabled",
    "set_startup_enabled",
    "toggle_startup",
]
