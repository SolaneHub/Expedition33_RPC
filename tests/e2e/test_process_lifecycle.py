"""Real subprocess lifecycle and single-instance kernel concurrency tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Named Mutex requires win32")
def test_single_instance_windows_mutex_subprocess() -> None:
    """Verifies at OS kernel level that a secondary instance exits immediately with 0 on Win32 mutex collision."""
    repo_root = Path(__file__).resolve().parents[2]
    test_mutex = f"Local\\Test_Lifecycle_{uuid.uuid4().hex}"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["EXPEDITION33_MUTEX_NAME"] = test_mutex

    # 1. Spawn primary process running -m expedition33_rpc which acquires the mutex
    proc1 = subprocess.Popen(
        [sys.executable, "-m", "expedition33_rpc"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Give proc1 time to acquire the mutex and enter its main loop
        time.sleep(1.0)
        assert proc1.poll() is None, f"Primary process terminated prematurely: {proc1.poll()}"

        # 2. Spawn secondary process via -m expedition33_rpc - must detect mutex and exit with 0
        proc2 = subprocess.Popen(
            [sys.executable, "-m", "expedition33_rpc"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        returncode = proc2.wait(timeout=5.0)
        assert returncode == 0, f"Secondary process exited with non-zero code {returncode}"
    finally:
        # Clean termination of primary process
        proc1.terminate()
        try:
            proc1.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc1.kill()
            proc1.wait(timeout=5.0)


def test_posix_file_lock_subprocess_concurrency(tmp_path: Path) -> None:
    """Verifies advisory process file locking concurrency between two real OS subprocesses."""
    lock_file = tmp_path / "test_lifecycle.lock"
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
        # Wait for proc1 to acquire the lock
        assert proc1.stdout is not None
        line = proc1.stdout.readline().strip()
        assert line == "LOCKED"

        if sys.platform != "win32":
            # On POSIX, verify second process fails to acquire lock
            check_script = (
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
        proc1.terminate()
        try:
            proc1.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc1.kill()
            proc1.wait(timeout=5.0)
