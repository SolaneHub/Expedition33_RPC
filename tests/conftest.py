from pathlib import Path

import pytest
from tests.harness import DiscordPipeSimulator

from expedition33_rpc.core.settings import SettingsService


@pytest.fixture
def settings_service(tmp_path: Path) -> SettingsService:
    """Provides a fresh isolated SettingsService writing to a temporary directory."""
    return SettingsService(custom_path=tmp_path / "settings.json")


@pytest.fixture
def pipe_simulator() -> DiscordPipeSimulator:
    """Fixture providing a clean in-memory Discord duplex pipe simulator."""
    return DiscordPipeSimulator(auto_respond_set_activity=True)
