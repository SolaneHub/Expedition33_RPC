"""Tests for core lifecycle, settings persistence, startup, and smoke test."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from expedition33_rpc.core import startup
from expedition33_rpc.core.app import main
from expedition33_rpc.core.platform import (
    SingleInstanceLock,
    is_already_running,
    release_single_instance_lock,
)
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService

# ---------------------------------------------------------------------------
# Settings Persistence Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_settings_save_atomic_failure_preserves_ram_and_disk_consistency(tmp_path: Path) -> None:
    """Verifies that disk I/O / file lock errors during atomic save prevent RAM-disk desynchronization."""
    from expedition33_rpc.core.orchestrator import AppOrchestrator
    from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager

    custom_json = tmp_path / "locked_settings.json"
    service = SettingsService(path=custom_json)

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
    assert snapshot.anti_spoiler is False
    assert not orchestrator.settings_service.is_anti_spoiler_enabled()


# ---------------------------------------------------------------------------
# Startup Autostart Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_current_executable_command() -> None:
    # 1. Non-frozen mode
    with patch.object(sys, "frozen", False, create=True):
        cmd = startup.get_current_executable_command()
        assert isinstance(cmd, str)
        assert cmd.startswith('"')
        assert "-m expedition33_rpc" in cmd
        assert cmd.endswith("-m expedition33_rpc")

    # 2. Frozen mode (compiled binary)
    fake_exe = r"C:\Games\Expedition33_RPC\Expedition33_RPC.exe"
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", fake_exe),
    ):
        frozen_cmd = startup.get_current_executable_command()
        assert frozen_cmd == f'"{fake_exe}"'


@pytest.mark.unit
def test_is_startup_enabled_command_validation(tmp_path: Path) -> None:
    """Verifies that is_startup_enabled correctly extracts the binary path from both frozen and module commands."""
    from tests.harness.fake_services import FakeWinreg

    run_key = (FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY)

    fake_py = tmp_path / "python.exe"
    fake_py.touch()

    # Module command format: "path/to/python.exe" -m expedition33_rpc
    module_cmd = f'"{fake_py}" -m expedition33_rpc'
    reg_module = FakeWinreg(initial={run_key: {startup.APP_NAME: (module_cmd, FakeWinreg.REG_SZ)}})
    with patch("expedition33_rpc.core.startup.winreg", reg_module):
        assert startup.is_startup_enabled() is True

    # Frozen command format: "path/to/Expedition33_RPC.exe"
    fake_exe = tmp_path / "Expedition33_RPC.exe"
    fake_exe.touch()
    frozen_cmd = f'"{fake_exe}"'
    reg_frozen = FakeWinreg(initial={run_key: {startup.APP_NAME: (frozen_cmd, FakeWinreg.REG_SZ)}})
    with patch("expedition33_rpc.core.startup.winreg", reg_frozen):
        assert startup.is_startup_enabled() is True

    # Missing binary returns False
    missing_cmd = f'"{tmp_path / "nonexistent.exe"}"'
    reg_missing = FakeWinreg(
        initial={run_key: {startup.APP_NAME: (missing_cmd, FakeWinreg.REG_SZ)}}
    )
    with patch("expedition33_rpc.core.startup.winreg", reg_missing):
        assert startup.is_startup_enabled() is False


@pytest.mark.unit
def test_startup_frozen_constants_contract() -> None:
    """Frozen contract test: asserts registry autostart constants exactly match OS requirements."""
    assert startup.RUN_KEY == r"Software\Microsoft\Windows\CurrentVersion\Run"
    assert startup.APP_NAME == "Expedition33_DiscordRPC"


@pytest.mark.unit
def test_startup_enable_disable_and_toggle() -> None:
    from tests.harness.fake_services import FakeWinreg

    run_key = (FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY)
    fake = FakeWinreg(initial={run_key: {}})
    with patch("expedition33_rpc.core.startup.winreg", fake):
        assert startup.set_startup_enabled(True) is True
        assert (
            startup.APP_NAME in fake.keys[(FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY.lower())]
        )
        assert startup.is_startup_enabled() is True

        assert startup.set_startup_enabled(False) is True
        assert (
            startup.APP_NAME
            not in fake.keys[(FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY.lower())]
        )
        assert startup.is_startup_enabled() is False


@pytest.mark.unit
def test_toggle_startup_when_winreg_absent_or_permission_error() -> None:
    """Verifies toggle_startup returns False (never True) when winreg is absent or raises PermissionError."""
    from tests.harness.fake_services import FakeWinreg

    with patch("expedition33_rpc.core.startup.winreg", None):
        assert startup.toggle_startup() is False

    fake_perm_err = FakeWinreg()
    fake_perm_err.open_error = PermissionError("Access denied")
    with patch("expedition33_rpc.core.startup.winreg", fake_perm_err):
        assert startup.toggle_startup() is False


@pytest.mark.unit
def test_startup_disabled_when_winreg_none() -> None:
    with patch.object(startup, "winreg", None):
        assert startup.is_startup_enabled() is False
        assert startup.set_startup_enabled(True) is False
        assert startup.toggle_startup() is False
        startup.sync_startup_path()


@pytest.mark.unit
def test_startup_toggle_failure_returns_real_unchanged_state(tmp_path: Path) -> None:
    """Verifies toggle_startup returns real is_startup_enabled() state when registry mutation fails."""
    from tests.harness.fake_services import FakeWinreg

    run_key_tuple = (FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY)

    # 1. Initially disabled; SetValueEx fails -> toggle_startup must return False
    fake_enable_fail = FakeWinreg(initial={run_key_tuple: {}})
    fake_enable_fail.set_error = PermissionError("Access is denied")
    with patch("expedition33_rpc.core.startup.winreg", fake_enable_fail):
        assert startup.is_startup_enabled() is False
        assert startup.toggle_startup() is False
        assert startup.is_startup_enabled() is False

    # 2. Initially enabled; OpenKey(KEY_SET_VALUE) fails -> toggle_startup must return True
    class WriteDeniedWinreg(FakeWinreg):
        def OpenKey(
            self,
            key: int,
            sub_key: str,
            reserved: int = 0,
            access: int = FakeWinreg.KEY_READ,
        ) -> Any:
            if access == self.KEY_SET_VALUE:
                raise PermissionError("Access is denied")
            return super().OpenKey(key, sub_key, reserved=reserved, access=access)

    fake_exe = tmp_path / "Expedition33_RPC.exe"
    fake_exe.touch()
    fake_disable_fail = WriteDeniedWinreg(
        initial={
            run_key_tuple: {
                startup.APP_NAME: (f'"{fake_exe}"', FakeWinreg.REG_SZ),
            }
        }
    )
    with patch("expedition33_rpc.core.startup.winreg", fake_disable_fail):
        assert startup.is_startup_enabled() is True
        assert startup.toggle_startup() is True
        assert startup.is_startup_enabled() is True


@pytest.mark.unit
def test_startup_toggle_delete_value_permission_error_preserves_enabled_state(
    tmp_path: Path,
) -> None:
    """Regression test for Finding 1: winreg_delete_value must not swallow PermissionError."""
    import errno

    from tests.harness.fake_services import FakeWinreg

    from expedition33_rpc.core.platform import winreg_delete_value

    run_key_tuple = (FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY)
    fake_exe = tmp_path / "Expedition33_RPC.exe"
    fake_exe.touch()

    reg = FakeWinreg(
        initial={
            run_key_tuple: {
                startup.APP_NAME: (f'"{fake_exe}"', FakeWinreg.REG_SZ),
            }
        }
    )
    reg.delete_error = PermissionError("Access is denied")

    with patch("expedition33_rpc.core.startup.winreg", reg):
        assert startup.is_startup_enabled() is True
        assert startup.toggle_startup() is True
        assert startup.is_startup_enabled() is True

    # Non-ENOENT OSError also fails cleanly; ENOENT / FileNotFoundError succeeds cleanly
    reg.delete_error = OSError(errno.EACCES, "Permission denied")
    assert (
        winreg_delete_value(FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY, startup.APP_NAME, reg)
        is False
    )

    reg.delete_error = OSError(errno.ENOENT, "Value not found")
    assert (
        winreg_delete_value(FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY, startup.APP_NAME, reg)
        is True
    )

    reg.delete_error = None
    assert (
        winreg_delete_value(FakeWinreg.HKEY_CURRENT_USER, startup.RUN_KEY, "MissingValue", reg)
        is True
    )


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
            patch("expedition33_rpc.core.platform.SingleInstanceLock.acquire", return_value=False),
        ):
            assert is_already_running() is True
    finally:
        release_single_instance_lock()


@pytest.mark.unit
def test_posix_file_lock_lifecycle_and_cleanup(tmp_path: Path) -> None:
    """Verifies that POSIX flock lifecycle, idempotency, fd leaks, and release work cleanly."""
    if sys.platform == "win32":
        pytest.skip("POSIX flock is only tested on POSIX platforms")

    test_lock = tmp_path / "lifecycle.lock"
    try:
        # 1. Acquire lock cleanly
        assert is_already_running(lock_path=test_lock) is False
        assert test_lock.is_file()

        # 2. Idempotent re-acquisition in same process returns False (not already running)
        assert is_already_running(lock_path=test_lock) is False

        # 3. Switching lock paths closes old file and acquires new one
        other_lock = tmp_path / "other.lock"
        assert is_already_running(lock_path=other_lock) is False
        assert other_lock.is_file()

        # 4. Release closes file
        release_single_instance_lock()

        # 5. Subsequent release is a safe no-op
        release_single_instance_lock()

        # 6. Verify contention detection on second instance
        lock_a = SingleInstanceLock(lock_path=test_lock)
        assert lock_a.acquire() is True
        lock_b = SingleInstanceLock(lock_path=test_lock)
        assert lock_b.acquire() is False
        lock_a.release()
    finally:
        release_single_instance_lock()


@pytest.mark.unit
def test_single_instance_lock_contention_and_atomic_removal(tmp_path: Path) -> None:
    """Verifies SingleInstanceLock contention, context manager, and cleanup across Windows and POSIX."""
    if sys.platform == "win32":
        test_mutex = f"Local\\TestInstanceMutex_{os.getpid()}_{time.monotonic_ns()}"

        # 1. First instance acquires mutex successfully
        lock1 = SingleInstanceLock(mutex_name=test_mutex)
        assert lock1.acquire() is True

        # 2. Second instance attempts to acquire same mutex -> contention detected
        lock2 = SingleInstanceLock(mutex_name=test_mutex)
        assert lock2.acquire() is False

        # 3. Context manager usage respects contention
        with SingleInstanceLock(mutex_name=test_mutex) as ctx_lock:
            assert ctx_lock.acquire() is False

        # 4. Release primary lock cleanly
        lock1.release()

        # 5. Secondary lock can now acquire following primary release
        assert lock2.acquire() is True
        lock2.release()

        # 6. Context manager releases even on exception
        with pytest.raises(RuntimeError, match="boom"), SingleInstanceLock(mutex_name=test_mutex):
            assert lock2.acquire() is False
            raise RuntimeError("boom")
        assert lock2.acquire() is True
        lock2.release()

        # 7. is_already_running integration test on isolated mutex
        release_single_instance_lock()
        try:
            assert is_already_running(mutex_name=test_mutex) is False
            # Secondary lock detects contention with active is_already_running lock
            assert lock1.acquire() is False
        finally:
            release_single_instance_lock()
    else:
        lock_file = tmp_path / "app_instance.lock"

        # 1. First instance acquires lock successfully
        lock1 = SingleInstanceLock(lock_path=lock_file)
        assert lock1.acquire() is True
        assert lock_file.is_file()

        # 2. Second instance attempts to acquire on same path -> contention detected
        lock2 = SingleInstanceLock(lock_path=lock_file)
        assert lock2.acquire() is False

        # 3. Context manager usage respects contention
        with SingleInstanceLock(lock_path=lock_file) as ctx_lock:
            assert ctx_lock.acquire() is False

        # 4. Atomic removal of lock file from disk while still locked
        assert lock_file.is_file()
        lock_file.unlink()
        assert not lock_file.exists()

        # 5. Release primary lock cleanly
        lock1.release()

        # 6. Secondary lock can now acquire following primary release
        assert lock2.acquire() is True
        assert lock_file.is_file()
        lock2.release()

        # 7. Context manager releases even on exception
        with pytest.raises(RuntimeError, match="boom"), SingleInstanceLock(lock_path=lock_file):
            assert lock2.acquire() is False
            raise RuntimeError("boom")
        assert lock2.acquire() is True
        lock2.release()

        # 8. is_already_running integration test on isolated lock path
        release_single_instance_lock()
        try:
            assert is_already_running(lock_path=lock_file) is False
            # Secondary lock detects contention with active is_already_running lock
            assert lock1.acquire() is False
        finally:
            release_single_instance_lock()


@pytest.mark.unit
def test_win32_kernel32_typing_and_last_error_flag() -> None:
    """Verifies that Win32 kernel32 function bindings are strictly typed with use_last_error=True."""
    import expedition33_rpc.core.platform as platform

    if sys.platform != "win32":
        pytest.skip("Win32 ctypes bindings are only initialized on Windows")

    assert platform._kernel32 is not None
    # Check that CreateMutexW and PeekNamedPipe exist and are configured
    assert hasattr(platform._kernel32, "CreateMutexW")
    assert hasattr(platform._kernel32, "PeekNamedPipe")
    assert hasattr(platform._kernel32, "CreateFileW")
    assert hasattr(platform._kernel32, "CloseHandle")

    # Verify argtypes and restype
    from ctypes import wintypes

    expected_sec_attr = getattr(wintypes, "LPSECURITY_ATTRIBUTES", wintypes.LPVOID)
    assert platform._kernel32.CreateMutexW.restype == wintypes.HANDLE
    assert list(platform._kernel32.CreateMutexW.argtypes) == [
        expected_sec_attr,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    assert platform._kernel32.CloseHandle.restype == wintypes.BOOL
    assert list(platform._kernel32.CloseHandle.argtypes) == [wintypes.HANDLE]
    assert platform._kernel32.PeekNamedPipe.restype == wintypes.BOOL
    expected_peek_argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    assert [getattr(t, "_type_", t) for t in platform._kernel32.PeekNamedPipe.argtypes] == [
        getattr(t, "_type_", t) for t in expected_peek_argtypes
    ]

    # Verify use_last_error works by verifying ctypes get_last_error updates after a Win32 call
    ctypes.set_last_error(0)
    # PeekNamedPipe with an invalid handle (0) should fail and set last_error (e.g. ERROR_INVALID_HANDLE = 6)
    res = platform._kernel32.PeekNamedPipe(0, None, 0, None, None, None)
    assert res == 0
    assert ctypes.get_last_error() != 0


@pytest.mark.unit
def test_read_file_shared_text_nonexistent_raises_immediately_without_open(tmp_path: Path) -> None:
    """Verifies that read_file_shared_text() raises FileNotFoundError immediately on Win32 without calling open()."""
    from expedition33_rpc.core.platform import read_file_shared_text

    if sys.platform != "win32":
        pytest.skip("Win32 CreateFileW specific behavior")

    nonexistent = tmp_path / "does_not_exist_file.json"

    with patch("builtins.open") as mock_open:
        with pytest.raises(FileNotFoundError):
            read_file_shared_text(str(nonexistent))
        # open() must NOT have been called on Windows when Win32 CreateFileW reports missing file
        mock_open.assert_not_called()


@pytest.mark.unit
def test_peek_named_pipe_ready_cross_platform_and_handles() -> None:
    """Verifies peek_named_pipe_ready behaviour across platforms, mocks, and invalid handles."""
    from expedition33_rpc.core.platform import peek_named_pipe_ready

    # 1. Non-Windows fallback returns True immediately
    with patch("sys.platform", "linux"):
        assert peek_named_pipe_ready(123) is True
        assert peek_named_pipe_ready(None) is True

    # 2. On Windows, invalid/None/mock objects without valid handles return True immediately
    class MockStream:
        def fileno(self) -> int:
            raise OSError("Not a real fd")

    assert peek_named_pipe_ready(None) is True
    assert peek_named_pipe_ready(MockStream()) is True
    assert peek_named_pipe_ready(-1) is True

    # 3. Handle closing or broken pipe triggers ConnectionError
    class FakeKernel32:
        def __init__(self, ret_val: int = 1, avail_bytes: int = 0) -> None:
            self.ret_val = ret_val
            self.avail_bytes = avail_bytes

        def PeekNamedPipe(
            self, _h: Any, _buf: Any, _sz: Any, _read: Any, avail_ref: Any, _left: Any
        ) -> int:
            if avail_ref is not None and hasattr(avail_ref, "_obj"):
                avail_ref._obj.value = self.avail_bytes
            return self.ret_val

    broken_kernel32 = FakeKernel32(ret_val=0)
    with (
        patch("sys.platform", "win32"),
        patch("expedition33_rpc.core.platform._kernel32", broken_kernel32),
        pytest.raises(ConnectionError, match="Named pipe broken or closed"),
    ):
        peek_named_pipe_ready(999)

    # 4. Handle with bytes available returns True immediately
    ready_kernel32 = FakeKernel32(ret_val=1, avail_bytes=42)
    with (
        patch("sys.platform", "win32"),
        patch("expedition33_rpc.core.platform._kernel32", ready_kernel32),
    ):
        assert peek_named_pipe_ready(999, timeout=0.1) is True

    # 5. Handle with 0 bytes available returns False on timeout
    empty_kernel32 = FakeKernel32(ret_val=1, avail_bytes=0)
    with (
        patch("sys.platform", "win32"),
        patch("expedition33_rpc.core.platform._kernel32", empty_kernel32),
    ):
        start = time.perf_counter()
        assert peek_named_pipe_ready(999, timeout=0.03) is False
        assert time.perf_counter() - start >= 0.02


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


@pytest.mark.unit
def test_smoke_test_runs_without_tkinter() -> None:
    """Verifies that run_smoke_test succeeds even if tkinter is uninstalled/unavailable."""
    from expedition33_rpc.core.smoke import run_smoke_test

    with patch.dict(sys.modules, {"tkinter": None, "_tkinter": None}):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test()
        assert exc_info.value.code == 0


@pytest.mark.unit
def test_smoke_test_missing_assets_exits_one() -> None:
    """Verifies that run_smoke_test exits with code 1 if critical assets are missing."""
    from expedition33_rpc.core.smoke import run_smoke_test

    with patch("os.path.isfile", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test()
        assert exc_info.value.code == 1


@pytest.mark.unit
def test_smoke_test_missing_icon_exits_one() -> None:
    """Verifies that run_smoke_test exits with code 1 if tray icon cannot be decoded."""
    from expedition33_rpc.core.smoke import run_smoke_test

    with patch("expedition33_rpc.ui.tray_app.ExpeditionTrayApp.get_icon_image", return_value=None):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test()
        assert exc_info.value.code == 1


@pytest.mark.unit
def test_smoke_test_default_isolates_user_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies run_smoke_test() uses TemporaryDirectory by default and never touches APPDATA/XDG_CONFIG_HOME."""
    from expedition33_rpc.core.smoke import run_smoke_test

    isolated_config = tmp_path / "user_config"
    monkeypatch.setenv("APPDATA", str(isolated_config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_config))

    with pytest.raises(SystemExit) as exc_info:
        run_smoke_test()
    assert exc_info.value.code == 0
    assert not isolated_config.exists()


@pytest.mark.unit
def test_smoke_test_explicit_settings_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies run_smoke_test(settings_path=...) uses the explicit path without touching default dir."""
    from expedition33_rpc.core.smoke import run_smoke_test

    isolated_config = tmp_path / "user_config"
    monkeypatch.setenv("APPDATA", str(isolated_config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_config))
    custom_settings = tmp_path / "custom" / "settings.json"

    with pytest.raises(SystemExit) as exc_info:
        run_smoke_test(settings_path=custom_settings)
    assert exc_info.value.code == 0
    assert custom_settings.parent.is_dir()
    assert not isolated_config.exists()


@pytest.mark.unit
@pytest.mark.parametrize("bad_content", ["{invalid-json", "[]", "{}"])
def test_smoke_test_invalid_game_data_json_exits_one(tmp_path: Path, bad_content: str) -> None:
    """Verifies run_smoke_test exits with code 1 if game_data.json is invalid or not a non-empty dict."""
    from expedition33_rpc.core.smoke import run_smoke_test

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    for name in ("icon.png", "icon.ico", "bridge.zip"):
        shutil.copy2(get_resource_path(name), assets_dir / name)
    (assets_dir / "game_data.json").write_text(bad_content, encoding="utf-8")

    with patch(
        "expedition33_rpc.core.smoke.get_resource_path",
        side_effect=lambda name: str(assets_dir / name),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test(settings_path=tmp_path / "settings.json")
        assert exc_info.value.code == 1


@pytest.mark.unit
def test_smoke_test_invalid_or_incomplete_bridge_zip_exits_one(tmp_path: Path) -> None:
    """Verifies run_smoke_test exits with code 1 if bridge.zip is corrupt or missing main.lua."""
    from expedition33_rpc.core.smoke import run_smoke_test

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    for name in ("icon.png", "icon.ico", "game_data.json"):
        shutil.copy2(get_resource_path(name), assets_dir / name)

    bridge_zip = assets_dir / "bridge.zip"

    # 1. Corrupt non-zip bytes
    bridge_zip.write_bytes(b"not-a-valid-zip-archive")
    with patch(
        "expedition33_rpc.core.smoke.get_resource_path",
        side_effect=lambda name: str(assets_dir / name),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test(settings_path=tmp_path / "settings1.json")
        assert exc_info.value.code == 1

    # 2. Valid zip missing ue4ss/Mods/Expedition33RPC/scripts/main.lua
    with zipfile.ZipFile(bridge_zip, "w") as zf:
        zf.writestr("dwmapi.dll", b"dummy")
    with patch(
        "expedition33_rpc.core.smoke.get_resource_path",
        side_effect=lambda name: str(assets_dir / name),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_smoke_test(settings_path=tmp_path / "settings2.json")
        assert exc_info.value.code == 1


@pytest.mark.integration
def test_main_runs_and_releases_lock() -> None:
    """Verifies that normal main() execution releases the single instance lock upon exit."""
    app_ran = False
    lock_released = False

    class FakeApp:
        def __init__(self, orchestrator: Any = None) -> None:
            pass

        def run(self) -> None:
            nonlocal app_ran
            app_ran = True

    def fake_release() -> None:
        nonlocal lock_released
        lock_released = True

    with (
        patch("expedition33_rpc.core.app.is_already_running", return_value=False),
        patch("expedition33_rpc.core.orchestrator.AppOrchestrator"),
        patch("expedition33_rpc.ui.tray_app.ExpeditionTrayApp", FakeApp),
        patch("expedition33_rpc.core.app.release_single_instance_lock", side_effect=fake_release),
    ):
        main()
        assert app_ran is True
        assert lock_released is True


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
