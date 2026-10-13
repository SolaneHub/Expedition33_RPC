from __future__ import annotations

import os
import sys
from pathlib import Path

# On Linux/POSIX systems without an active display server, use headless dummy pystray backend
if (
    sys.platform not in ("win32", "darwin")
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
):
    os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

import pytest
from tests.harness.discord_pipe import DiscordPipeSimulator

from expedition33_rpc.core.settings import SettingsService


@pytest.fixture
def settings_service(tmp_path: Path) -> SettingsService:
    """Provides a fresh isolated SettingsService writing to a temporary directory."""
    return SettingsService(custom_path=tmp_path / "settings.json")


@pytest.fixture
def pipe_simulator() -> DiscordPipeSimulator:
    """Fixture providing a clean in-memory Discord duplex pipe simulator."""
    return DiscordPipeSimulator(auto_respond_set_activity=True)
