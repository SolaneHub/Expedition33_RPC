"""Centralized Win32 and POSIX platform abstraction layer.

Consolidates low-level OS operations:
- Single-instance process synchronization (Win32 Named Mutex / POSIX advisory flock)
- Shared non-blocking file reads across processes (Windows CreateFileW / standard POSIX open)
- Safe registry access with graceful POSIX fallbacks (winreg)
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows Registry Abstraction
# ---------------------------------------------------------------------------
winreg: Any = None
try:
    import winreg
except ImportError:
    winreg = None


def winreg_read_value(
    hkey: Any, subkey: str, value_name: str, winreg_module: Any = None
) -> str | None:
    """Reads a string value from the Windows registry, or None if missing or unsupported."""
    reg = winreg_module if winreg_module is not None else winreg
    if reg is None:
        return None
    try:
        with reg.OpenKey(hkey, subkey, 0, getattr(reg, "KEY_READ", 0)) as key:
            val, _ = reg.QueryValueEx(key, value_name)
            return str(val) if val is not None else None
    except Exception:
        return None


def winreg_set_value(
    hkey: Any, subkey: str, value_name: str, value: str, winreg_module: Any = None
) -> bool:
    """Sets a string value in the Windows registry, returning True on success."""
    reg = winreg_module if winreg_module is not None else winreg
    if reg is None:
        return False
    try:
        with reg.OpenKey(hkey, subkey, 0, getattr(reg, "KEY_SET_VALUE", 0)) as key:
            reg.SetValueEx(key, value_name, 0, getattr(reg, "REG_SZ", 1), value)
            return True
    except Exception as e:
        logger.error("[Platform] winreg_set_value error: %s", e)
        return False


def winreg_delete_value(hkey: Any, subkey: str, value_name: str, winreg_module: Any = None) -> bool:
    """Deletes a value from the Windows registry, returning True on success."""
    reg = winreg_module if winreg_module is not None else winreg
    if reg is None:
        return False
    try:
        with reg.OpenKey(hkey, subkey, 0, getattr(reg, "KEY_SET_VALUE", 0)) as key:
            with contextlib.suppress(FileNotFoundError, OSError):
                reg.DeleteValue(key, value_name)
            return True
    except Exception as e:
        logger.error("[Platform] winreg_delete_value error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Single-Instance Mutex & Process Locking
# ---------------------------------------------------------------------------
_MUTEX_HANDLE: Any = None
_FLOCK_FILE: Any = None


def is_already_running(
    mutex_name: str | None = None,
    lock_path: Path | str | None = None,
) -> bool:
    """Checks if another instance of Expedition 33 RPC is already running across Windows (Named Mutex) and POSIX (flock)."""
    if sys.platform == "win32":
        target_name = (
            mutex_name
            if mutex_name is not None
            else os.environ.get("EXPEDITION33_MUTEX_NAME", "Local\\Expedition33_Discord_RPC_Mutex")
        )
        global _MUTEX_HANDLE
        if _kernel32 is None:
            return False
        handle = _kernel32.CreateMutexW(None, False, target_name)
        last_error = ctypes.get_last_error()
        # ERROR_ALREADY_EXISTS = 183, ERROR_ACCESS_DENIED = 5
        if last_error in (183, 5):
            if handle:
                with contextlib.suppress(Exception):
                    _kernel32.CloseHandle(handle)
            return True
        if _MUTEX_HANDLE is not None and handle != _MUTEX_HANDLE:
            with contextlib.suppress(Exception):
                _kernel32.CloseHandle(_MUTEX_HANDLE)
        _MUTEX_HANDLE = handle
        return False

    return not acquire_posix_file_lock(lock_path=lock_path)


def acquire_posix_file_lock(lock_path: Path | str | None = None) -> bool:
    """Acquires an exclusive advisory file lock on POSIX systems (Linux / Steam Deck / macOS)."""
    global _FLOCK_FILE
    if sys.platform == "win32":
        return True
    try:
        import fcntl
    except ImportError:
        return True

    target_path = (
        Path(
            os.environ.get(
                "EXPEDITION33_LOCK_FILE", Path(tempfile.gettempdir()) / "expedition33_rpc.lock"
            )
        )
        if lock_path is None
        else Path(lock_path)
    )

    # If this process already holds this exact lock file, consider it successfully acquired
    if _FLOCK_FILE is not None and not getattr(_FLOCK_FILE, "closed", False):
        try:
            if Path(_FLOCK_FILE.name).resolve() == target_path.resolve():
                return True
        except Exception:
            pass
        release_posix_file_lock()

    f: Any = None
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(target_path, "a+")
        fcntl_mod: Any = fcntl
        fcntl_mod.flock(f, fcntl_mod.LOCK_EX | fcntl_mod.LOCK_NB)
        _FLOCK_FILE = f
        return True
    except (BlockingIOError, OSError):
        if f is not None:
            with contextlib.suppress(Exception):
                f.close()
        return False


def release_posix_file_lock() -> None:
    """Releases the POSIX advisory file lock held by the current process, if any."""
    global _FLOCK_FILE
    if _FLOCK_FILE is not None:
        with contextlib.suppress(Exception):
            import fcntl

            fcntl_mod: Any = fcntl
            fcntl_mod.flock(_FLOCK_FILE, fcntl_mod.LOCK_UN)
        with contextlib.suppress(Exception):
            _FLOCK_FILE.close()
        _FLOCK_FILE = None


def release_single_instance_lock() -> None:
    """Releases any single-instance mutex or file lock held by this process."""
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE is not None:
        if sys.platform == "win32" and _kernel32 is not None:
            with contextlib.suppress(Exception):
                _kernel32.CloseHandle(_MUTEX_HANDLE)
        _MUTEX_HANDLE = None
    release_posix_file_lock()


# ---------------------------------------------------------------------------
# Shared Non-Blocking File Reading (Win32 / POSIX)
# ---------------------------------------------------------------------------
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE_VALUE = -1

_kernel32: Any = None
_msvcrt: Any = None

if sys.platform == "win32":
    try:
        import msvcrt as _msvcrt_mod
        from ctypes import wintypes

        _sec_attr = getattr(wintypes, "LPSECURITY_ATTRIBUTES", wintypes.LPVOID)
        _msvcrt = _msvcrt_mod
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateMutexW.restype = wintypes.HANDLE
        _kernel32.CreateMutexW.argtypes = [
            _sec_attr,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        _kernel32.CreateFileW.restype = wintypes.HANDLE
        _kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32.PeekNamedPipe.restype = wintypes.BOOL
        _kernel32.PeekNamedPipe.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
    except Exception:
        _kernel32 = None
        _msvcrt = None


def read_file_shared_text(path: str | Path) -> str:
    """Reads a text file allowing concurrent reads, writes, and deletions on Windows NTFS,

    with graceful fallback for POSIX and standard file access.
    """
    path_str = str(path)
    if sys.platform == "win32" and _kernel32 is not None and _msvcrt is not None:
        raw: bytes | None = None
        try:
            handle = _kernel32.CreateFileW(
                path_str,
                _GENERIC_READ,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
                None,
                _OPEN_EXISTING,
                _FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if handle in (_INVALID_HANDLE_VALUE, None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                err = ctypes.get_last_error()
                # ERROR_FILE_NOT_FOUND = 2, ERROR_PATH_NOT_FOUND = 3
                if err in (2, 3):
                    raise FileNotFoundError(path_str)
                raise OSError(None, ctypes.FormatError(err), path_str, err)
            try:
                fd = _msvcrt.open_osfhandle(handle, os.O_RDONLY)
            except Exception:
                _kernel32.CloseHandle(handle)
                raise

            try:
                chunk = os.read(fd, 65536)
                if len(chunk) < 65536:
                    raw = chunk
                else:
                    chunks = [chunk]
                    while True:
                        more = os.read(fd, 65536)
                        if not more:
                            break
                        chunks.append(more)
                        if len(more) < 65536:
                            break
                    raw = b"".join(chunks)
            finally:
                os.close(fd)
        except FileNotFoundError:
            raise
        except Exception:
            # Fall back to standard read if custom Win32 handle creation fails with unexpected errors
            pass

        if raw is not None:
            return raw.decode("utf-8")

    with open(path_str, "rb") as f:
        return f.read().decode("utf-8")


def peek_named_pipe_ready(pipe_or_fd: Any, timeout: float = 0.0) -> bool:
    """Checks whether bytes are available to read from a Win32 named pipe without blocking.

    On POSIX or non-Windows platforms, returns True immediately (sockets/files handled via standard I/O).
    On Windows:
    - Resolves the underlying Win32 HANDLE from an int file descriptor, an object with fileno(),
      or an already raw handle integer.
    - If no valid handle can be resolved (e.g. non-file objects / custom mocks), returns True immediately.
    - Polls PeekNamedPipe until data is available, the pipe is broken/closed (ConnectionError),
      or the timeout expires (False).
    """
    if sys.platform != "win32":
        return True

    handle: Any = None
    if isinstance(pipe_or_fd, int):
        if _msvcrt is not None:
            try:
                handle = _msvcrt.get_osfhandle(pipe_or_fd)
            except (AttributeError, OSError, ValueError):
                handle = pipe_or_fd
        else:
            handle = pipe_or_fd
    else:
        fileno_fn = getattr(pipe_or_fd, "fileno", None)
        if callable(fileno_fn):
            try:
                fd = fileno_fn()
                if isinstance(fd, int) and _msvcrt is not None:
                    handle = _msvcrt.get_osfhandle(fd)
            except (AttributeError, OSError, ValueError):
                pass

    if handle is None or handle in (_INVALID_HANDLE_VALUE, -1, 0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        return True

    peek_fn = getattr(_kernel32, "PeekNamedPipe", None)
    if peek_fn is None:
        return True

    avail = ctypes.c_ulong(0)
    deadline = time.monotonic() + max(0.0, timeout)

    while True:
        res = peek_fn(handle, None, 0, None, ctypes.byref(avail), None)
        if res == 0:
            raise ConnectionError("Named pipe broken or closed")
        if avail.value > 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# Native Win32 Folder Dialog
# ---------------------------------------------------------------------------
def prompt_folder_selection(
    title: str = "Select Clair Obscur: Expedition 33 Folder",
) -> str | None:
    """Displays a native Win32 folder selection dialog.

    Returns the selected directory path, or None if cancelled or on non-Windows platforms.
    """
    if sys.platform != "win32":
        return None

    try:
        from ctypes import wintypes

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", wintypes.LPCVOID),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", wintypes.LPVOID),
                ("lParam", wintypes.LPARAM),
                ("iImage", ctypes.c_int),
            ]

        bif_returnonlyfsdirs = 0x0001
        bif_newdialogstyle = 0x0040
        bi = BROWSEINFO()
        bi.lpszTitle = title
        bi.ulFlags = bif_returnonlyfsdirs | bif_newdialogstyle

        ole_inited = False
        with contextlib.suppress(Exception):
            hr = ctypes.windll.ole32.OleInitialize(None)
            ole_inited = hr in (0, 1)

        try:
            pidl = ctypes.windll.shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return None
            path_buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetPathFromIDListW(pidl, path_buf)
            ctypes.windll.ole32.CoTaskMemFree(pidl)
            return path_buf.value or None
        finally:
            if ole_inited:
                with contextlib.suppress(Exception):
                    ctypes.windll.ole32.OleUninitialize()
    except Exception:
        return None


__all__ = [
    "acquire_posix_file_lock",
    "is_already_running",
    "peek_named_pipe_ready",
    "prompt_folder_selection",
    "read_file_shared_text",
    "release_posix_file_lock",
    "release_single_instance_lock",
    "winreg",
    "winreg_delete_value",
    "winreg_read_value",
    "winreg_set_value",
]
