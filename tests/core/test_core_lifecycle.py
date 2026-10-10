"""Tests for core lifecycle, settings persistence, startup, and smoke test."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from expedition33_rpc.core import startup
from expedition33_rpc.core.app import is_already_running, main
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import AppSettings, SettingsService

# ---------------------------------------------------------------------------
# Settings Persistence Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_json_file_persistence(tmp_path: Path) -> None:
    custom_json = tmp_path / "test_settings.json"
    service = SettingsService(custom_path=custom_json)

    assert service.is_anti_spoiler_enabled() is False
    service.set_anti_spoiler_enabled(True)
    assert service.is_anti_spoiler_enabled() is True
    assert custom_json.is_file()

    # Read back raw JSON content and typed dataclass
    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1
    assert data.get("anti_spoiler") is True

    loaded_settings = service.load_settings()
    assert isinstance(loaded_settings, AppSettings)
    assert loaded_settings.anti_spoiler is True


@pytest.mark.unit
def test_settings_service_in_memory_caching_and_atomic_update(tmp_path: Path) -> None:
    custom_json = tmp_path / "cached_settings.json"
    service = SettingsService(custom_path=custom_json)

    # Initial query returns default without requiring a file on disk
    assert service.is_anti_spoiler_enabled() is False

    # Calling is_anti_spoiler_enabled() returns from memory without disk reads
    with patch(
        "builtins.open", side_effect=AssertionError("Should not read from disk on cached query")
    ):
        assert service.is_anti_spoiler_enabled() is False

    # Atomic write updates in-memory cache and writes to file
    success = service.set_anti_spoiler_enabled(True)
    assert success is True
    assert service.is_anti_spoiler_enabled() is True
    assert custom_json.is_file()

    # Querying after update continues to read from memory without disk reads
    with patch(
        "builtins.open", side_effect=AssertionError("Should not read from disk on cached query")
    ):
        assert service.is_anti_spoiler_enabled() is True

    # Toggle updates in-memory cache and persists
    new_val = service.toggle_anti_spoiler()
    assert new_val is False
    assert service.is_anti_spoiler_enabled() is False

    # Verify persistence by reading from a fresh service instance
    fresh_service = SettingsService(custom_path=custom_json)
    assert fresh_service.is_anti_spoiler_enabled() is False


# ---------------------------------------------------------------------------
# Startup Autostart Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_current_executable_command() -> None:
    cmd = startup.get_current_executable_command()
    assert isinstance(cmd, str)
    assert cmd.startswith('"')
    assert cmd.endswith('"')


@pytest.mark.unit
def test_startup_enable_disable_and_toggle() -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
    mock_winreg.REG_SZ = 1

    with patch.object(startup, "winreg", mock_winreg):
        # Enable
        assert startup.set_startup_enabled(True) is True
        mock_winreg.SetValueEx.assert_called_once()

        # Disable
        assert startup.set_startup_enabled(False) is True
        mock_winreg.DeleteValue.assert_called_once_with(mock_key, startup.APP_NAME)


@pytest.mark.unit
def test_startup_disabled_when_winreg_none() -> None:
    with patch.object(startup, "winreg", None):
        assert startup.is_startup_enabled() is False
        assert startup.set_startup_enabled(True) is False
        startup.sync_startup_path()


# ---------------------------------------------------------------------------
# Resources & Single Instance Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_resource_path_bundled_assets() -> None:
    assert Path(get_resource_path("icon.png")).is_file()
    assert Path(get_resource_path("bridge.zip")).is_file()


@pytest.mark.unit
def test_get_resource_path_frozen_meipass(tmp_path: Path) -> None:
    test_file = tmp_path / "custom_asset.dat"
    test_file.write_text("dummy", encoding="utf-8")

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "_MEIPASS", str(tmp_path), create=True),
    ):
        res = get_resource_path("custom_asset.dat")
        assert os.path.normpath(res) == os.path.normpath(str(test_file))


@pytest.mark.unit
def test_single_instance_cross_platform_guards() -> None:
    with patch("sys.platform", "darwin"):
        assert is_already_running() is False
    with patch("sys.platform", "linux"):
        assert is_already_running() is False


# ---------------------------------------------------------------------------
# Smoke Test for main() Entrypoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_main_smoke_test_invocation() -> None:
    """Verifies that main() executes cleanly under --smoke-test flag."""
    with patch("sys.argv", ["expedition33_rpc", "--smoke-test"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
