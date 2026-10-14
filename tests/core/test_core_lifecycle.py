"""Tests for core lifecycle, settings persistence, startup, and smoke test."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from expedition33_rpc.core import startup
from expedition33_rpc.core.app import main
from expedition33_rpc.core.platform import (
    acquire_posix_file_lock,
    is_already_running,
    release_posix_file_lock,
    release_single_instance_lock,
)
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService

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

    # Read back raw JSON content
    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data.get("anti_spoiler") is True

    fresh_service = SettingsService(custom_path=custom_json)
    assert fresh_service.is_anti_spoiler_enabled() is True


@pytest.mark.unit
def test_settings_preserves_existing_keys_on_update(tmp_path: Path) -> None:
    custom_json = tmp_path / "custom_settings.json"
    custom_json.write_text(
        json.dumps({"theme": "dark", "locale": "it", "custom_option": 42}),
        encoding="utf-8",
    )
    service = SettingsService(custom_path=custom_json)
    service.set_anti_spoiler_enabled(True)

    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True
    assert data["theme"] == "dark"
    assert data["locale"] == "it"
    assert data["custom_option"] == 42


@pytest.mark.unit
def test_settings_service_in_memory_caching_and_atomic_update(tmp_path: Path) -> None:
    custom_json = tmp_path / "cached_settings.json"
    service = SettingsService(custom_path=custom_json)

    # Initial query returns default without requiring a file on disk
    assert not custom_json.exists()
    assert service.is_anti_spoiler_enabled() is False

    # Atomic write updates in-memory cache and writes to file
    success = service.set_anti_spoiler_enabled(True)
    assert success is True
    assert service.is_anti_spoiler_enabled() is True
    assert custom_json.is_file()

    # Black-box cache verification: query succeeds from in-memory cache even if disk file is removed
    custom_json.unlink()
    assert not custom_json.exists()
    assert service.is_anti_spoiler_enabled() is True

    # Toggle updates in-memory cache and persists back to disk
    new_val = service.toggle_anti_spoiler()
    assert new_val is False
    assert service.is_anti_spoiler_enabled() is False
    assert custom_json.is_file()

    # Verify persistence by reading from a fresh service instance
    fresh_service = SettingsService(custom_path=custom_json)
    assert fresh_service.is_anti_spoiler_enabled() is False


@pytest.mark.unit
def test_settings_save_atomic_failure_preserves_ram_and_disk_consistency(tmp_path: Path) -> None:
    """Verifies that disk I/O / file lock errors during atomic save prevent RAM-disk desynchronization."""
    from expedition33_rpc.core.orchestrator import AppOrchestrator
    from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager

    custom_json = tmp_path / "locked_settings.json"
    service = SettingsService(custom_path=custom_json)

    # 1. Initial save: anti_spoiler = False
    assert service.set_anti_spoiler_enabled(False) is True
    assert service.is_anti_spoiler_enabled() is False
    assert custom_json.is_file()

    # 2. Simulate permission/lock error during atomic rename
    with patch("pathlib.Path.replace", side_effect=PermissionError("File locked")):
        success = service.set_anti_spoiler_enabled(True)
        assert success is False

    # 3. Verify in-memory state did NOT flip to True (no desync with disk)
    assert service.is_anti_spoiler_enabled() is False
    assert service.load() is False

    # 4. Verify disk file remains intact and uncorrupted
    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is False

    # 5. Verify AppOrchestrator handles toggle failure without desync
    from tests.harness import DiscordPipeSimulator

    from expedition33_rpc.integrations.discord_rpc import DiscordIPCClient

    pipe = DiscordPipeSimulator()
    rpc = DiscordRPCManager(client=DiscordIPCClient(client_id="test", transport=pipe))
    rpc.last_update_state = "prior_fingerprint"

    orchestrator = AppOrchestrator(
        settings_service=service,
        rpc_manager=rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    with patch("pathlib.Path.replace", side_effect=OSError("Lock failure")):
        toggled_val = orchestrator.toggle_anti_spoiler()
        assert toggled_val is False
        assert service.is_anti_spoiler_enabled() is False

    snapshot = orchestrator.get_status_snapshot()
    assert snapshot["anti_spoiler"] is False
    assert not orchestrator.is_anti_spoiler_enabled()


@pytest.mark.unit
def test_settings_service_nested_directory_creation_and_recovery(tmp_path: Path) -> None:
    """Verifies that SettingsService creates nested parent directories and recovers if deleted."""
    nested_json = tmp_path / "deep" / "nested" / "dir" / "settings.json"
    assert not nested_json.parent.exists()

    service = SettingsService(custom_path=nested_json)
    assert nested_json.parent.is_dir()
    assert not nested_json.exists()

    assert service.set_anti_spoiler_enabled(True) is True
    assert nested_json.is_file()
    assert service.is_anti_spoiler_enabled() is True

    # Simulate external deletion of parent directory
    shutil.rmtree(tmp_path / "deep")
    assert not nested_json.parent.exists()

    # EAFP recovery should recreate parent directory and persist setting cleanly
    assert service.set_anti_spoiler_enabled(False) is True
    assert nested_json.is_file()
    assert service.is_anti_spoiler_enabled() is False

    data = json.loads(nested_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is False


@pytest.mark.unit
def test_settings_service_corrupt_json_safe_recovery(tmp_path: Path) -> None:
    """Verifies that corrupted JSON files do not crash SettingsService and are cleanly recoverable."""
    custom_json = tmp_path / "corrupt_settings.json"
    custom_json.write_text("{ this is corrupt json !!!", encoding="utf-8")

    service = SettingsService(custom_path=custom_json)
    # Default value returned safely without exception
    assert service.is_anti_spoiler_enabled() is False

    # Overwriting with valid setting recovers file cleanly
    assert service.set_anti_spoiler_enabled(True) is True
    assert service.is_anti_spoiler_enabled() is True

    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True


@pytest.mark.unit
def test_settings_service_detects_external_file_modifications(tmp_path: Path) -> None:
    """Verifies that external modifications to settings.json are detected and merged."""
    custom_json = tmp_path / "external_settings.json"
    service = SettingsService(custom_path=custom_json)
    service.set_anti_spoiler_enabled(False)

    # External program updates settings.json with extra fields
    custom_json.write_text(
        json.dumps({"theme": "solarized", "anti_spoiler": False, "volume": 80}),
        encoding="utf-8",
    )
    # Ensure mtime is strictly different
    new_mtime = custom_json.stat().st_mtime + 2.0
    os.utime(custom_json, (new_mtime, new_mtime))

    # Toggling anti-spoiler preserves the externally added fields
    assert service.toggle_anti_spoiler() is True
    assert service.is_anti_spoiler_enabled() is True

    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True
    assert data["theme"] == "solarized"
    assert data["volume"] == 80


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
def test_single_instance_cross_platform_guards(tmp_path: Path) -> None:
    try:
        with (
            patch.dict(os.environ, {"EXPEDITION33_LOCK_FILE": str(tmp_path / "darwin.lock")}),
            patch("sys.platform", "darwin"),
        ):
            assert is_already_running() is False
        release_single_instance_lock()

        with (
            patch.dict(os.environ, {"EXPEDITION33_LOCK_FILE": str(tmp_path / "linux.lock")}),
            patch("sys.platform", "linux"),
        ):
            assert is_already_running() is False
        release_single_instance_lock()

        with (
            patch("sys.platform", "linux"),
            patch("expedition33_rpc.core.platform.acquire_posix_file_lock", return_value=False),
        ):
            assert is_already_running() is True
    finally:
        release_single_instance_lock()


@pytest.mark.unit
def test_posix_file_lock_lifecycle_and_cleanup(tmp_path: Path) -> None:
    """Verifies that POSIX flock lifecycle, idempotency, fd leaks, and release work cleanly."""
    mock_fcntl = MagicMock()
    mock_fcntl.LOCK_EX = 2
    mock_fcntl.LOCK_NB = 4
    mock_fcntl.LOCK_UN = 8

    test_lock = tmp_path / "lifecycle.lock"

    try:
        with (
            patch.dict(sys.modules, {"fcntl": mock_fcntl}),
            patch("sys.platform", "linux"),
        ):
            # 1. Acquire lock cleanly
            assert acquire_posix_file_lock(test_lock) is True
            assert mock_fcntl.flock.called

            # 2. Idempotent re-acquisition in same process returns True
            assert acquire_posix_file_lock(test_lock) is True

            # 3. Switching lock paths closes old file and acquires new one
            other_lock = tmp_path / "other.lock"
            assert acquire_posix_file_lock(other_lock) is True

            # 4. Release closes file and calls LOCK_UN
            release_posix_file_lock()
            assert mock_fcntl.flock.call_args[0][1] == mock_fcntl.LOCK_UN

            # 5. Subsequent release is a safe no-op
            release_posix_file_lock()

            # 6. Verify fd is NOT leaked when flock raises BlockingIOError
            mock_fcntl.flock.side_effect = BlockingIOError("Lock collision")
            with patch("builtins.open") as mock_open:
                mock_file = MagicMock()
                mock_open.return_value = mock_file
                result = acquire_posix_file_lock(tmp_path / "failed.lock")
                assert result is False
                assert mock_file.close.called
    finally:
        release_single_instance_lock()


@pytest.mark.unit
def test_single_instance_windows_mutex() -> None:
    mock_kernel32 = MagicMock()
    mock_windll = MagicMock()
    mock_windll.kernel32 = mock_kernel32

    # Case 1: First instance (last_error == 0)
    mock_kernel32.GetLastError.return_value = 0
    with (
        patch("sys.platform", "win32"),
        patch.object(ctypes, "windll", mock_windll, create=True),
    ):
        assert is_already_running() is False

    # Case 2: Already running (ERROR_ALREADY_EXISTS = 183) - closes duplicate handle
    mock_kernel32.GetLastError.return_value = 183
    mock_dup_handle = MagicMock()
    mock_kernel32.CreateMutexW.return_value = mock_dup_handle
    with (
        patch("sys.platform", "win32"),
        patch.object(ctypes, "windll", mock_windll, create=True),
    ):
        assert is_already_running() is True
        mock_kernel32.CloseHandle.assert_called_with(mock_dup_handle)

    # Case 3: Access denied (ERROR_ACCESS_DENIED = 5)
    mock_kernel32.GetLastError.return_value = 5
    with (
        patch("sys.platform", "win32"),
        patch.object(ctypes, "windll", mock_windll, create=True),
    ):
        assert is_already_running() is True


# ---------------------------------------------------------------------------
# Smoke Test and Early Exit for main() Entrypoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_main_already_running_exits() -> None:
    """Verifies that main() exits cleanly with status 0 if another instance is already running."""
    with (
        patch("sys.platform", "win32"),
        patch("expedition33_rpc.core.app.is_already_running", return_value=True),
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


@pytest.mark.integration
def test_main_smoke_test_invocation() -> None:
    """Verifies that main() executes cleanly under --smoke-test flag."""
    with patch("sys.argv", ["expedition33_rpc", "--smoke-test"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


@pytest.mark.integration
def test_main_runs_and_releases_lock() -> None:
    """Verifies that normal main() execution releases the single instance lock upon exit."""
    mock_app = MagicMock()
    mock_orchestrator = MagicMock()
    with (
        patch("expedition33_rpc.core.app.is_already_running", return_value=False),
        patch("expedition33_rpc.core.orchestrator.AppOrchestrator", return_value=mock_orchestrator),
        patch("expedition33_rpc.ui.tray_app.ExpeditionTrayApp", return_value=mock_app),
        patch("expedition33_rpc.core.app.release_single_instance_lock") as mock_release,
    ):
        main()
        mock_app.run.assert_called_once()
        mock_release.assert_called_once()


@pytest.mark.unit
def test_pep562_dir_and_lazy_exports() -> None:
    """Verifies PEP 562 __dir__() and lazy exports across package namespaces."""
    import expedition33_rpc
    import expedition33_rpc.core
    import expedition33_rpc.detection

    for name in expedition33_rpc.__all__:
        assert hasattr(expedition33_rpc, name)
    for name in expedition33_rpc.core.__all__:
        assert hasattr(expedition33_rpc.core, name)
    for name in expedition33_rpc.detection.__all__:
        assert hasattr(expedition33_rpc.detection, name)

    # Verify lazy attribute resolution via __getattr__
    assert expedition33_rpc.main is not None
    assert expedition33_rpc.core.get_resource_path is not None
    assert expedition33_rpc.detection.GameDetector is not None

    bad_name = "non_existent_attribute_xyz"
    with pytest.raises(AttributeError):
        _ = getattr(expedition33_rpc, bad_name)
    with pytest.raises(AttributeError):
        _ = getattr(expedition33_rpc.core, bad_name)
    with pytest.raises(AttributeError):
        _ = getattr(expedition33_rpc.detection, bad_name)
