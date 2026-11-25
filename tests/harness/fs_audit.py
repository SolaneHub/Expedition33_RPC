"""Filesystem activity auditing for SaveFileReader dormancy verification."""

from __future__ import annotations

import builtins
import contextlib
import inspect
import mmap
import os
import pathlib
from pathlib import Path
from typing import Any, Self

type FsViolation = dict[str, Any]

# 12 Target functions to monitor for filesystem calls originating from save_reader.py or on .sav files
_ORIGINAL_OPEN = builtins.open
_ORIGINAL_MMAP = mmap.mmap
_ORIGINAL_PATH_STAT = pathlib.Path.stat
_ORIGINAL_PATH_ITERDIR = pathlib.Path.iterdir
_ORIGINAL_PATH_GLOB = pathlib.Path.glob
_ORIGINAL_PATH_EXISTS = pathlib.Path.exists
_ORIGINAL_PATH_IS_FILE = pathlib.Path.is_file
_ORIGINAL_PATH_IS_DIR = pathlib.Path.is_dir
_ORIGINAL_OS_STAT = os.stat
_ORIGINAL_OS_EXISTS = os.path.exists
_ORIGINAL_OS_ISFILE = os.path.isfile
_ORIGINAL_OS_ISDIR = os.path.isdir


def _apply_patch(target: Any, attr: str, val: Any) -> None:
    setattr(target, attr, val)


class FilesystemActivityAudit:
    """Audits filesystem syscalls to enforce SaveFileReader dormancy and detect illegal .sav accesses."""

    def __init__(self) -> None:
        self.save_reader_fs_calls: list[FsViolation] = []
        self.sav_file_accesses: list[FsViolation] = []
        self.violations: list[FsViolation] = []
        self._sav_fds: set[int] = set()
        self._installed: bool = False

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _is_from_save_reader(self) -> bool:
        # Check call stack for save_reader.py frame
        frame = inspect.currentframe()
        try:
            cur = frame.f_back.f_back if frame and frame.f_back else None
            while cur is not None:
                fname = cur.f_code.co_filename
                if "save_reader.py" in fname:
                    return True
                cur = cur.f_back
        finally:
            del frame
        return False

    def _is_sav_target(self, *args: Any) -> bool:
        for arg in args:
            if isinstance(arg, int) and arg in self._sav_fds:
                return True
            if isinstance(arg, (str, bytes, os.PathLike)):
                p = (
                    os.fspath(arg)
                    if not isinstance(arg, bytes)
                    else arg.decode("latin1", "replace")
                )
                p_lower = p.lower()
                if p_lower.endswith(".sav") or ".sav" in p_lower:
                    return True
        return False

    def _record(self, func_name: str, *args: Any) -> None:
        from_save_reader = self._is_from_save_reader()
        is_sav = self._is_sav_target(*args)
        if from_save_reader or is_sav:
            entry: FsViolation = {"func": func_name, "args": args}
            self.violations.append(entry)
            if from_save_reader:
                self.save_reader_fs_calls.append(entry)
            if is_sav:
                self.sav_file_accesses.append(entry)

    def start(self) -> None:
        if self._installed:
            return
        audit = self

        def hooked_open(*args: Any, **kwargs: Any) -> Any:
            audit._record("open", *args)
            handle = _ORIGINAL_OPEN(*args, **kwargs)
            if audit._is_sav_target(*args):
                with contextlib.suppress(Exception):
                    audit._sav_fds.add(handle.fileno())
            return handle

        def hooked_mmap(*args: Any, **kwargs: Any) -> Any:
            audit._record("mmap", *args)
            return _ORIGINAL_MMAP(*args, **kwargs)

        def hooked_path_stat(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.stat", str(self_path), *args)
            return _ORIGINAL_PATH_STAT(self_path, *args, **kwargs)

        def hooked_path_iterdir(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.iterdir", str(self_path), *args)
            return _ORIGINAL_PATH_ITERDIR(self_path, *args, **kwargs)

        def hooked_path_glob(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.glob", str(self_path), *args)
            return _ORIGINAL_PATH_GLOB(self_path, *args, **kwargs)

        def hooked_path_exists(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.exists", str(self_path), *args)
            return _ORIGINAL_PATH_EXISTS(self_path, *args, **kwargs)

        def hooked_path_is_file(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.is_file", str(self_path), *args)
            return _ORIGINAL_PATH_IS_FILE(self_path, *args, **kwargs)

        def hooked_path_is_dir(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            audit._record("Path.is_dir", str(self_path), *args)
            return _ORIGINAL_PATH_IS_DIR(self_path, *args, **kwargs)

        def hooked_os_stat(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.stat", *args)
            return _ORIGINAL_OS_STAT(*args, **kwargs)

        def hooked_os_exists(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.exists", *args)
            return _ORIGINAL_OS_EXISTS(*args, **kwargs)

        def hooked_os_isfile(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.isfile", *args)
            return _ORIGINAL_OS_ISFILE(*args, **kwargs)

        def hooked_os_isdir(*args: Any, **kwargs: Any) -> Any:
            audit._record("os.path.isdir", *args)
            return _ORIGINAL_OS_ISDIR(*args, **kwargs)

        _apply_patch(builtins, "open", hooked_open)
        _apply_patch(mmap, "mmap", hooked_mmap)
        _apply_patch(pathlib.Path, "stat", hooked_path_stat)
        _apply_patch(pathlib.Path, "iterdir", hooked_path_iterdir)
        _apply_patch(pathlib.Path, "glob", hooked_path_glob)
        _apply_patch(pathlib.Path, "exists", hooked_path_exists)
        _apply_patch(pathlib.Path, "is_file", hooked_path_is_file)
        _apply_patch(pathlib.Path, "is_dir", hooked_path_is_dir)
        _apply_patch(os, "stat", hooked_os_stat)
        _apply_patch(os.path, "exists", hooked_os_exists)
        _apply_patch(os.path, "isfile", hooked_os_isfile)
        _apply_patch(os.path, "isdir", hooked_os_isdir)
        self._installed = True

    def stop(self) -> None:
        if not self._installed:
            return
        _apply_patch(builtins, "open", _ORIGINAL_OPEN)
        _apply_patch(mmap, "mmap", _ORIGINAL_MMAP)
        _apply_patch(pathlib.Path, "stat", _ORIGINAL_PATH_STAT)
        _apply_patch(pathlib.Path, "iterdir", _ORIGINAL_PATH_ITERDIR)
        _apply_patch(pathlib.Path, "glob", _ORIGINAL_PATH_GLOB)
        _apply_patch(pathlib.Path, "exists", _ORIGINAL_PATH_EXISTS)
        _apply_patch(pathlib.Path, "is_file", _ORIGINAL_PATH_IS_FILE)
        _apply_patch(pathlib.Path, "is_dir", _ORIGINAL_PATH_IS_DIR)
        _apply_patch(os, "stat", _ORIGINAL_OS_STAT)
        _apply_patch(os.path, "exists", _ORIGINAL_OS_EXISTS)
        _apply_patch(os.path, "isfile", _ORIGINAL_OS_ISFILE)
        _apply_patch(os.path, "isdir", _ORIGINAL_OS_ISDIR)
        self._installed = False

    def clear(self) -> None:
        self.save_reader_fs_calls.clear()
        self.sav_file_accesses.clear()
        self.violations.clear()
        self._sav_fds.clear()
