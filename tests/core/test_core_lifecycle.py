"""Tests for core lifecycle, settings persistence, startup, and smoke test."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from expedition33_rpc.core import startup
from expedition33_rpc.core.app import main
from expedition33_rpc.core.platform import (
    SingleInstanceLock,
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
    assert snapshot["anti_spoiler"] is False
    assert not orchestrator.is_anti_spoiler_enabled()


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

    class FakeWinregKey:
        def __init__(self, store: dict[str, str]) -> None:
            self.store = store

        def __enter__(self) -> FakeWinregKey:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeWinreg:
        HKEY_CURRENT_USER = 0x80000001
        KEY_SET_VALUE = 0x0002
        KEY_READ = 0x20019
        REG_SZ = 1

        def __init__(self, val: str) -> None:
            self.store: dict[str, str] = {startup.APP_NAME: val}

        def OpenKey(
            self, _root: Any, _subkey: str, _res: int = 0, _access: int = 0
        ) -> FakeWinregKey:
            return FakeWinregKey(self.store)

        def QueryValueEx(self, key: FakeWinregKey, name: str) -> tuple[str, int]:
            if name in key.store:
                return key.store[name], self.REG_SZ
            raise FileNotFoundError(name)

    fake_py = tmp_path / "python.exe"
    fake_py.touch()

    # Module command format: "path/to/python.exe" -m expedition33_rpc
    module_cmd = f'"{fake_py}" -m expedition33_rpc'
    with patch("expedition33_rpc.core.startup.winreg", FakeWinreg(module_cmd)):
        assert startup.is_startup_enabled() is True

    # Frozen command format: "path/to/Expedition33_RPC.exe"
    fake_exe = tmp_path / "Expedition33_RPC.exe"
    fake_exe.touch()
    frozen_cmd = f'"{fake_exe}"'
    with patch("expedition33_rpc.core.startup.winreg", FakeWinreg(frozen_cmd)):
        assert startup.is_startup_enabled() is True

    # Missing binary returns False
    missing_cmd = f'"{tmp_path / "nonexistent.exe"}"'
    with patch("expedition33_rpc.core.startup.winreg", FakeWinreg(missing_cmd)):
        assert startup.is_startup_enabled() is False


@pytest.mark.unit
def test_startup_frozen_constants_contract() -> None:
    """Frozen contract test: asserts registry autostart constants exactly match OS requirements."""
    assert startup.RUN_KEY == r"Software\Microsoft\Windows\CurrentVersion\Run"
    assert startup.APP_NAME == "Expedition33_DiscordRPC"


@pytest.mark.unit
def test_startup_enable_disable_and_toggle() -> None:
    class FakeWinregKey:
        def __init__(self, store: dict[str, str]) -> None:
            self.store = store

        def __enter__(self) -> FakeWinregKey:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    class FakeWinreg:
        HKEY_CURRENT_USER = 0x80000001
        KEY_SET_VALUE = 0x0002
        KEY_READ = 0x20019
        REG_SZ = 1

        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def OpenKey(
            self, _root: Any, _subkey: str, _res: int = 0, _access: int = 0
        ) -> FakeWinregKey:
            return FakeWinregKey(self.store)

        def SetValueEx(
            self, key: FakeWinregKey, name: str, _res: int, _type: int, value: str
        ) -> None:
            key.store[name] = value

        def QueryValueEx(self, key: FakeWinregKey, name: str) -> tuple[str, int]:
            if name in key.store:
                return key.store[name], self.REG_SZ
            raise FileNotFoundError(name)

        def DeleteValue(self, key: FakeWinregKey, name: str) -> None:
            if name in key.store:
                del key.store[name]
            else:
                raise FileNotFoundError(name)

    fake = FakeWinreg()
    with patch("expedition33_rpc.core.startup.winreg", fake):
        assert startup.set_startup_enabled(True) is True
        assert startup.APP_NAME in fake.store
        assert startup.is_startup_enabled() is True

        assert startup.set_startup_enabled(False) is True
        assert startup.APP_NAME not in fake.store
        assert startup.is_startup_enabled() is False


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
    if sys.platform == "win32":
        pytest.skip("POSIX flock is only tested on POSIX platforms")

    test_lock = tmp_path / "lifecycle.lock"
    try:
        # 1. Acquire lock cleanly
        assert acquire_posix_file_lock(test_lock) is True
        assert test_lock.is_file()

        # 2. Idempotent re-acquisition in same process returns True
        assert acquire_posix_file_lock(test_lock) is True

        # 3. Switching lock paths closes old file and acquires new one
        other_lock = tmp_path / "other.lock"
        assert acquire_posix_file_lock(other_lock) is True
        assert other_lock.is_file()

        # 4. Release closes file
        release_posix_file_lock()

        # 5. Subsequent release is a safe no-op
        release_posix_file_lock()

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
        assert lock1._is_locked is True

        # 2. Second instance attempts to acquire same mutex -> contention detected
        lock2 = SingleInstanceLock(mutex_name=test_mutex)
        assert lock2.acquire() is False
        assert lock2._is_locked is False

        # 3. Context manager usage respects contention
        with SingleInstanceLock(mutex_name=test_mutex) as ctx_lock:
            assert ctx_lock._is_locked is False

        # 4. Release primary lock cleanly
        lock1.release()
        assert lock1._is_locked is False

        # 5. Secondary lock can now acquire following primary release
        assert lock2.acquire() is True
        assert lock2._is_locked is True
        lock2.release()
        assert lock2._is_locked is False

        # 6. is_already_running integration test on isolated mutex
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
        assert lock1._is_locked is True
        assert lock_file.is_file()

        # 2. Second instance attempts to acquire on same path -> contention detected
        lock2 = SingleInstanceLock(lock_path=lock_file)
        assert lock2.acquire() is False
        assert lock2._is_locked is False
        assert lock2._flock_file is None

        # 3. Context manager usage respects contention
        with SingleInstanceLock(lock_path=lock_file) as ctx_lock:
            assert ctx_lock._is_locked is False

        # 4. Atomic removal of lock file from disk while still locked
        assert lock_file.is_file()
        lock_file.unlink()
        assert not lock_file.exists()

        # 5. Release primary lock cleanly
        lock1.release()
        assert lock1._is_locked is False
        assert lock1._flock_file is None

        # 6. Secondary lock can now acquire following primary release
        assert lock2.acquire() is True
        assert lock2._is_locked is True
        assert lock_file.is_file()
        lock2.release()
        assert lock2._is_locked is False

        # 7. is_already_running integration test on isolated lock path
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
    from expedition33_rpc.core import platform

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
