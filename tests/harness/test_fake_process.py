"""Unit tests for FakeProcess test double protocol conformance and lifecycle contracts."""

from __future__ import annotations

import pytest
from tests.harness import FakeProcess

from expedition33_rpc.detection.detector import ProcessLike


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
def test_fake_process_lifecycle_state_transitions() -> None:
    """Verifies state transitions from running to killed/terminated with returncode sync."""
    proc = FakeProcess(pid=4001, is_running=True, returncode=42)
    assert proc.is_running() is True
    assert proc.returncode is None
    assert proc.poll() is None

    # Terminate transitions state cleanly
    proc.terminate()
    assert proc.is_running() is False
    assert proc.returncode == 42
    assert proc.poll() == 42

    # Subsequent kill is idempotent and maintains exit state
    proc.kill()
    assert proc.is_running() is False
    assert proc.poll() == 42


@pytest.mark.unit
def test_fake_process_wait_and_poll_contract() -> None:
    """Verifies wait() forces termination and returns returncode, poll() tracks status."""
    proc_running = FakeProcess(pid=5001, returncode=0, is_running=True)
    assert proc_running.poll() is None

    ret = proc_running.wait(timeout=1.0)
    assert ret == 0
    assert proc_running.is_running() is False
    assert proc_running.poll() == 0

    proc_stopped = FakeProcess(pid=5002, returncode=137)
    assert proc_stopped.is_running() is False
    assert proc_stopped.poll() == 137
    assert proc_stopped.wait() == 137


@pytest.mark.unit
def test_fake_process_stream_io_configuration() -> None:
    """Verifies stdout and stderr stream initialization, reading, and None defaults."""
    proc_default = FakeProcess()
    assert proc_default.stdout is None
    assert proc_default.stderr is None

    proc_streams = FakeProcess(
        stdout_lines=["out_line_1", "out_line_2"],
        stderr_lines=["err_warning"],
    )
    assert proc_streams.stdout is not None
    assert proc_streams.stderr is not None
    assert proc_streams.stdout.read() == "out_line_1\nout_line_2\n"
    assert proc_streams.stderr.read() == "err_warning\n"


@pytest.mark.unit
def test_fake_process_context_manager_lifecycle() -> None:
    """Verifies context manager protocol: enter returns self, exit terminates process."""
    proc = FakeProcess(pid=6001, is_running=True)
    with proc as p:
        assert p is proc
        assert p.is_running() is True

    assert proc.is_running() is False
    assert proc.poll() == 0


@pytest.mark.unit
def test_fake_process_context_manager_exception_safety() -> None:
    """Verifies exceptions propagate through context manager and process is still terminated."""
    proc = FakeProcess(pid=6002, is_running=True)
    with pytest.raises(RuntimeError, match="Simulated crash"), proc:
        assert proc.is_running() is True
        raise RuntimeError("Simulated crash")

    assert proc.is_running() is False
    assert proc.poll() == 0
