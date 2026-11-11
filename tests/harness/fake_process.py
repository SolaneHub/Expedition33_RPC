"""FakeProcess test double implementing ProcessLike static protocol and subprocess.Popen interface."""

from __future__ import annotations

import io
from typing import Any, Self


class FakeProcess:
    """Mock process implementing ProcessLike static protocol and subprocess.Popen interface."""

    def __init__(
        self,
        pid: int = 1234,
        name: str = "Sandfall-Win64-Shipping.exe",
        is_running: bool | None = None,
        create_time: float = 100.0,
        exe_path: str | None = None,
        returncode: int | None = None,
        stdout_lines: list[str] | None = None,
        stderr_lines: list[str] | None = None,
    ) -> None:
        self._pid = pid
        self._name = name
        self._create_time = create_time
        self._exe_path = exe_path
        self._target_returncode: int = 0 if returncode is None else returncode
        if is_running is None:
            self._is_running: bool = returncode is None
        else:
            self._is_running = is_running

        self.returncode: int | None = None if self._is_running else self._target_returncode
        self.stdout: io.StringIO | None = (
            io.StringIO(("\n".join(stdout_lines) + "\n") if stdout_lines else "")
            if stdout_lines is not None
            else None
        )
        self.stderr: io.StringIO | None = (
            io.StringIO(("\n".join(stderr_lines) + "\n") if stderr_lines else "")
            if stderr_lines is not None
            else None
        )

    @property
    def pid(self) -> int:
        return self._pid

    def name(self) -> str:
        return self._name

    def exe(self) -> str | None:
        return self._exe_path

    def is_running(self) -> bool:
        return self._is_running

    def create_time(self) -> float:
        return self._create_time

    def set_create_time(self, val: float) -> None:
        self._create_time = val

    def poll(self) -> int | None:
        if not self._is_running:
            self.returncode = self._target_returncode
            return self.returncode
        return None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self._is_running = False
        self.returncode = self._target_returncode
        return self._target_returncode

    def kill(self) -> None:
        self._is_running = False
        self.returncode = self._target_returncode

    def terminate(self) -> None:
        self._is_running = False
        self.returncode = self._target_returncode

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.kill()
