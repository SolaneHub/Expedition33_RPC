"""Unit tests for FakeProcess test double stream formatting, lifecycle, and protocol conformance."""

from __future__ import annotations

import pytest
from tests.harness import FakeProcess

from expedition33_rpc.detection.detector import ProcessLike

# ---------------------------------------------------------------------------
# Stream Edge Cases Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fake_process_empty_stream_lists() -> None:
    """Verifies that empty lists (`stdout_lines=[]`, `stderr_lines=[]`) produce empty streams and EOF."""
    proc = FakeProcess(stdout_lines=[], stderr_lines=[])

    assert proc.stdout is not None
    assert proc.stderr is not None

    # Entire stream read must be completely empty
    assert proc.stdout.read() == ""
    assert proc.stderr.read() == ""

    # Reset position and test line-oriented reads
    proc.stdout.seek(0)
    proc.stderr.seek(0)
    assert proc.stdout.readline() == ""  # Immediate EOF
    assert proc.stderr.readline() == ""  # Immediate EOF
    assert proc.stdout.readlines() == []
    assert proc.stderr.readlines() == []


@pytest.mark.unit
def test_fake_process_distinguishes_empty_list_from_empty_string_element() -> None:
    """Verifies that an empty list (0 lines) is distinguishable from a list containing an empty line."""
    proc_empty = FakeProcess(stdout_lines=[])
    proc_blank_line = FakeProcess(stdout_lines=[""])

    assert proc_empty.stdout is not None
    assert proc_blank_line.stdout is not None

    # Empty list represents 0 bytes written (empty stream)
    assert proc_empty.stdout.read() == ""
    proc_empty.stdout.seek(0)
    assert proc_empty.stdout.readlines() == []

    # List with empty string represents 1 blank line (contains newline)
    assert proc_blank_line.stdout.read() == "\n"
    proc_blank_line.stdout.seek(0)
    assert proc_blank_line.stdout.readlines() == ["\n"]


@pytest.mark.unit
def test_fake_process_populated_streams() -> None:
    """Verifies that populated streams format lines with correct newlines."""
    proc = FakeProcess(
        stdout_lines=["line 1", "line 2"],
        stderr_lines=["warning: deprecated flag", "error: retry limit"],
    )

    assert proc.stdout is not None
    assert proc.stderr is not None

    assert proc.stdout.read() == "line 1\nline 2\n"
    assert proc.stderr.read() == "warning: deprecated flag\nerror: retry limit\n"

    # Line-by-line consumption and EOF
    proc.stdout.seek(0)
    assert proc.stdout.readline() == "line 1\n"
    assert proc.stdout.readline() == "line 2\n"
    assert proc.stdout.readline() == ""  # EOF

    proc.stdout.seek(0)
    assert proc.stdout.readlines() == ["line 1\n", "line 2\n"]


@pytest.mark.unit
def test_fake_process_unset_streams_remain_none() -> None:
    """Verifies that unsupplied or explicitly None streams remain None."""
    proc_default = FakeProcess()
    assert proc_default.stdout is None
    assert proc_default.stderr is None

    proc_explicit = FakeProcess(stdout_lines=None, stderr_lines=None)
    assert proc_explicit.stdout is None
    assert proc_explicit.stderr is None


@pytest.mark.unit
def test_fake_process_asymmetric_streams() -> None:
    """Verifies that stdout and stderr can be configured independently."""
    proc_stdout_only = FakeProcess(stdout_lines=["output"], stderr_lines=None)
    assert proc_stdout_only.stdout is not None
    assert proc_stdout_only.stderr is None
    assert proc_stdout_only.stdout.read() == "output\n"

    proc_stderr_only = FakeProcess(stdout_lines=None, stderr_lines=["error"])
    assert proc_stderr_only.stdout is None
    assert proc_stderr_only.stderr is not None
    assert proc_stderr_only.stderr.read() == "error\n"

    proc_mixed = FakeProcess(stdout_lines=[], stderr_lines=["err"])
    assert proc_mixed.stdout is not None
    assert proc_mixed.stderr is not None
    assert proc_mixed.stdout.read() == ""
    assert proc_mixed.stderr.read() == "err\n"


# ---------------------------------------------------------------------------
# Lifecycle and Idempotency Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fake_process_poll_idempotency_running() -> None:
    """Verifies that poll() returns None repeatedly while the process is running."""
    proc = FakeProcess(pid=4001, is_running=True)
    for _ in range(50):
        assert proc.poll() is None
    assert proc.is_running() is True


@pytest.mark.unit
def test_fake_process_poll_idempotency_terminated() -> None:
    """Verifies that poll() returns returncode repeatedly when terminated."""
    proc = FakeProcess(pid=4002, is_running=False, returncode=42)
    for _ in range(50):
        assert proc.poll() == 42
    assert proc.is_running() is False


@pytest.mark.unit
def test_fake_process_kill_idempotency() -> None:
    """Verifies that repeated kill() calls are safe, idempotent, and terminate the process."""
    proc = FakeProcess(pid=4003, is_running=True, returncode=0)
    assert proc.is_running() is True

    proc.kill()
    assert proc.is_running() is False
    assert proc.poll() == 0

    # Subsequent repeated kills cause no errors and maintain state
    for _ in range(50):
        proc.kill()
        assert proc.is_running() is False
        assert proc.poll() == 0


@pytest.mark.unit
def test_fake_process_terminate_idempotency() -> None:
    """Verifies that repeated terminate() calls are safe, idempotent, and terminate the process."""
    proc = FakeProcess(pid=4004, is_running=True, returncode=137)
    assert proc.is_running() is True

    proc.terminate()
    assert proc.is_running() is False
    assert proc.poll() == 137

    # Subsequent repeated terminate calls cause no errors and maintain state
    for _ in range(50):
        proc.terminate()
        assert proc.is_running() is False
        assert proc.poll() == 137


@pytest.mark.unit
def test_fake_process_wait_idempotency() -> None:
    """Verifies that repeated wait() calls return returncode and terminate running process."""
    proc = FakeProcess(pid=4005, is_running=True, returncode=0)
    res1 = proc.wait(timeout=5.0)
    assert res1 == 0
    assert proc.is_running() is False
    assert proc.poll() == 0

    # Repeated waits with various timeouts return same returncode
    for timeout in (None, 0.0, 10.0, -1.0):
        assert proc.wait(timeout=timeout) == 0
        assert proc.poll() == 0


@pytest.mark.unit
def test_fake_process_lifecycle_method_sequences() -> None:
    """Verifies that arbitrary sequences of lifecycle methods maintain consistent state."""
    proc = FakeProcess(pid=4006, is_running=True, returncode=15)
    assert proc.poll() is None

    proc.kill()
    assert proc.poll() == 15

    proc.terminate()
    assert proc.poll() == 15

    assert proc.wait(timeout=1.0) == 15
    assert proc.poll() == 15
    assert proc.is_running() is False


@pytest.mark.unit
def test_fake_process_returncode_lifecycle_synchronization() -> None:
    """Verifies returncode synchronization: None while running, integer when terminated."""
    # 1. Default running process has returncode None and poll None
    proc_running = FakeProcess(pid=7001, is_running=True)
    assert proc_running.returncode is None
    assert proc_running.poll() is None
    assert proc_running.is_running() is True

    proc_running.kill()
    assert proc_running.returncode == 0
    assert proc_running.poll() == 0
    assert proc_running.is_running() is False

    # 2. Running process with explicit non-zero target returncode
    proc_nonzero = FakeProcess(pid=7002, returncode=42, is_running=True)
    assert proc_nonzero.returncode is None
    assert proc_nonzero.poll() is None

    proc_nonzero.terminate()
    assert proc_nonzero.returncode == 42
    assert proc_nonzero.poll() == 42

    # 3. Explicit completed double (returncode provided, is_running omitted)
    proc_done = FakeProcess(pid=7003, returncode=0)
    assert proc_done.is_running() is False
    assert proc_done.returncode == 0
    assert proc_done.poll() == 0
    assert proc_done.wait(timeout=5.0) == 0

    # 4. Explicitly non-running process
    proc_stopped = FakeProcess(pid=7004, is_running=False, returncode=1)
    assert proc_stopped.is_running() is False
    assert proc_stopped.returncode == 1
    assert proc_stopped.poll() == 1

    # 5. wait() resolves target returncode
    proc_wait = FakeProcess(pid=7005, returncode=99, is_running=True)
    assert proc_wait.returncode is None
    res = proc_wait.wait(timeout=1.0)
    assert res == 99
    assert proc_wait.returncode == 99
    assert proc_wait.is_running() is False


# ---------------------------------------------------------------------------
# Protocol Conformance & Context Manager Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fake_process_process_like_protocol_conformance() -> None:
    """Verifies that FakeProcess satisfies the runtime and static ProcessLike protocol."""
    proc = FakeProcess(
        pid=9876,
        name="Sandfall-Win64-Shipping.exe",
        is_running=True,
        create_time=12345.67,
        exe_path="C:\\Games\\Sandfall\\Binaries\\Win64\\Sandfall-Win64-Shipping.exe",
    )

    assert isinstance(proc, ProcessLike)
    assert proc.pid == 9876
    assert proc.name() == "Sandfall-Win64-Shipping.exe"
    assert proc.exe() == "C:\\Games\\Sandfall\\Binaries\\Win64\\Sandfall-Win64-Shipping.exe"
    assert proc.create_time() == 12345.67
    assert proc.is_running() is True


@pytest.mark.unit
def test_fake_process_context_manager_lifecycle() -> None:
    """Verifies context manager protocol: enter returns self, exit terminates process."""
    proc = FakeProcess(pid=5001, is_running=True)
    with proc as p:
        assert p is proc
        assert p.is_running() is True

    assert proc.is_running() is False
    assert proc.poll() == 0


@pytest.mark.unit
def test_fake_process_context_manager_exception_propagation() -> None:
    """Verifies that exceptions inside context manager propagate and still terminate process."""
    proc = FakeProcess(pid=5002, is_running=True)
    with pytest.raises(ValueError, match="Simulated crash"), proc:
        assert proc.is_running() is True
        raise ValueError("Simulated crash")

    assert proc.is_running() is False
    assert proc.poll() == 0
