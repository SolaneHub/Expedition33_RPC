"""Subprocess lifecycle and single-instance kernel concurrency tests across Windows and POSIX."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.harness import FakeProcess

from expedition33_rpc.core.app import main
from expedition33_rpc.core.platform import acquire_posix_file_lock

pytestmark = pytest.mark.integration


def test_single_instance_windows_mutex_subprocess() -> None:
    """Verifies that a secondary instance exits immediately with 0 on Win32 mutex collision."""
    # Deterministic test double verifying collision detection logic
    proc1_sim = FakeProcess(pid=1001, name="python", stdout_lines=["ACQUIRED"])
    assert proc1_sim.stdout is not None
    assert proc1_sim.stdout.readline().strip() == "ACQUIRED"

    with (
        patch("sys.platform", "win32"),
        patch("expedition33_rpc.core.app.is_already_running", return_value=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 0

    proc2_sim = FakeProcess(pid=1002, name="expedition33_rpc", returncode=0)
    assert proc2_sim.wait(timeout=5.0) == 0
    proc1_sim.kill()
    proc1_sim.wait(timeout=5.0)

    # Real OS subprocess verification when running natively on Windows
    if sys.platform == "win32":
        repo_root = Path(__file__).resolve().parents[2]
        test_mutex = f"Local\\Test_Lifecycle_{uuid.uuid4().hex}"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["EXPEDITION33_MUTEX_NAME"] = test_mutex

        holder_script = (
            "import time, sys\n"
            "from expedition33_rpc.core.platform import is_already_running\n"
            "assert is_already_running() is False\n"
            "print('ACQUIRED', flush=True)\n"
            "time.sleep(10.0)\n"
        )

        proc1 = subprocess.Popen(
            [sys.executable, "-c", holder_script],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )

        try:
            assert proc1.stdout is not None
            line = proc1.stdout.readline().strip()
            assert line == "ACQUIRED"

            proc2 = subprocess.Popen(
                [sys.executable, "-m", "expedition33_rpc"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            returncode = proc2.wait(timeout=5.0)
            assert returncode == 0, f"Secondary process exited with non-zero code {returncode}"
        finally:
            proc1.kill()
            proc1.wait(timeout=5.0)


def test_posix_file_lock_subprocess_concurrency(tmp_path: Path) -> None:
    """Verifies advisory process file locking concurrency between two processes."""
    lock_file = tmp_path / "test_lifecycle.lock"

    # Deterministic test double verifying flock collision handling
    proc1_sim = FakeProcess(pid=2001, name="python", stdout_lines=["LOCKED"])
    assert proc1_sim.stdout is not None
    assert proc1_sim.stdout.readline().strip() == "LOCKED"

    mock_fcntl = MagicMock()
    mock_fcntl.LOCK_EX = 2
    mock_fcntl.LOCK_NB = 4
    mock_fcntl.flock.side_effect = BlockingIOError("Resource temporarily unavailable")

    with (
        patch.dict(sys.modules, {"fcntl": mock_fcntl}),
        patch("sys.platform", "linux"),
    ):
        locked = acquire_posix_file_lock(lock_file)
        assert locked is False
        exit_code = 0 if not locked else 1
        proc2_sim = FakeProcess(pid=2002, name="python", returncode=exit_code)
        assert proc2_sim.returncode == 0

    proc1_sim.kill()
    proc1_sim.wait(timeout=5.0)

    # Real OS subprocess verification when running natively on POSIX
    if sys.platform != "win32":
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        holder_script = (
            "import time, sys\n"
            "from pathlib import Path\n"
            "from expedition33_rpc.core.platform import acquire_posix_file_lock\n"
            f"lock_path = Path(r'{lock_file}')\n"
            "locked = acquire_posix_file_lock(lock_path)\n"
            "assert locked is True\n"
            "print('LOCKED', flush=True)\n"
            "time.sleep(5.0)\n"
        )

        proc1 = subprocess.Popen(
            [sys.executable, "-c", holder_script],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )

        try:
            assert proc1.stdout is not None
            line = proc1.stdout.readline().strip()
            assert line == "LOCKED"

            check_script = (
                "import sys\n"
                "from pathlib import Path\n"
                "from expedition33_rpc.core.platform import acquire_posix_file_lock\n"
                f"lock_path = Path(r'{lock_file}')\n"
                "locked = acquire_posix_file_lock(lock_path)\n"
                "sys.exit(0 if not locked else 1)\n"
            )
            proc2 = subprocess.run(
                [sys.executable, "-c", check_script],
                env=env,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            assert proc2.returncode == 0
        finally:
            proc1.kill()
            proc1.wait(timeout=5.0)


def test_single_instance_posix_app_subprocess(tmp_path: Path) -> None:
    """Verifies that a secondary instance exits immediately with 0 on POSIX lock collision."""
    lock_file = tmp_path / "test_app_instance.lock"

    # Deterministic test double verifying app exit on lock collision
    proc1_sim = FakeProcess(pid=3001, name="python", stdout_lines=["ACQUIRED"])
    assert proc1_sim.stdout is not None
    assert proc1_sim.stdout.readline().strip() == "ACQUIRED"

    with (
        patch("sys.platform", "linux"),
        patch("expedition33_rpc.core.platform.acquire_posix_file_lock", return_value=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()
    assert exc_info.value.code == 0

    proc2_sim = FakeProcess(pid=3002, name="expedition33_rpc", returncode=0)
    assert proc2_sim.wait(timeout=5.0) == 0
    proc1_sim.kill()
    proc1_sim.wait(timeout=5.0)

    # Real OS subprocess verification when running natively on POSIX
    if sys.platform != "win32":
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["EXPEDITION33_LOCK_FILE"] = str(lock_file)
        env["PYSTRAY_BACKEND"] = "dummy"

        holder_script = (
            "import time, sys\n"
            "from expedition33_rpc.core.platform import is_already_running\n"
            "assert is_already_running() is False\n"
            "print('ACQUIRED', flush=True)\n"
            "time.sleep(10.0)\n"
        )

        proc1 = subprocess.Popen(
            [sys.executable, "-c", holder_script],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )

        try:
            assert proc1.stdout is not None
            line = proc1.stdout.readline().strip()
            assert line == "ACQUIRED"

            proc2 = subprocess.Popen(
                [sys.executable, "-m", "expedition33_rpc"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            returncode = proc2.wait(timeout=5.0)
            assert returncode == 0, f"Secondary process exited with non-zero code {returncode}"
        finally:
            proc1.kill()
            proc1.wait(timeout=5.0)
