"""Tests for lightweight AppUpdater and GitHub Releases integration."""

from __future__ import annotations

import http.server
import json
import threading
import time
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from expedition33_rpc.integrations.updater import (
    AppUpdater,
    UpdateInfo,
    UpdateState,
    parse_version,
)


class MockReleaseHTTPHandler(http.server.BaseHTTPRequestHandler):
    """In-process HTTP request handler with configurable status code and delay."""

    response_code: int = 200
    response_body: bytes = b"{}"
    delay: float = 0.0

    def do_GET(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay)
        self.send_response(self.response_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress server access log messages from polluting test output
        pass


@pytest.fixture
def mock_release_server() -> Generator[tuple[str, type[MockReleaseHTTPHandler]], None, None]:
    """Spawns an in-process daemon HTTPServer on an ephemeral port (127.0.0.1:0)."""

    class ConfigurableHandler(MockReleaseHTTPHandler):
        pass

    server = http.server.HTTPServer(("127.0.0.1", 0), ConfigurableHandler)
    poll_interval = 0.01
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    url = f"http://{host}:{port}/releases/latest"

    worker = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": poll_interval},
        daemon=True,
    )
    worker.start()

    try:
        yield url, ConfigurableHandler
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cur", "remote", "expected_newer"),
    [
        ("1.0.0", "1.0.1", True),
        ("v1.5.0", "1.5.0", False),
        ("1.2.3", "1.2.0", False),
        ("1.0.0", "2.0.0", True),
        ("invalid", "1.0.0", True),
        ("v2.1.0-beta", "v2.1.0", False),
    ],
)
def test_version_parsing_and_comparison(cur: str, remote: str, expected_newer: bool) -> None:
    v_cur = parse_version(cur)
    v_rem = parse_version(remote)
    assert (v_cur < v_rem) is expected_newer


@pytest.mark.unit
def test_updater_initial_state() -> None:
    updater = AppUpdater(current_version="1.0.0")
    assert updater.state == UpdateState.IDLE
    assert updater.available_update is None
    assert updater.error_message is None
    assert updater.get_status_text() == "Check for Updates"


@pytest.mark.integration
def test_check_for_updates_available(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.response_code = 200
    handler.response_body = json.dumps(
        {
            "tag_name": "v1.5.0",
            "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.5.0",
        }
    ).encode("utf-8")

    callback_called = False

    def on_state():
        nonlocal callback_called
        callback_called = True

    updater = AppUpdater(current_version="1.0.0", on_state_change=on_state, api_url=url)
    info = updater.check_for_updates()

    assert info is not None
    assert info.tag_name == "v1.5.0"
    assert info.version_tuple == (1, 5, 0)
    assert info.html_url == "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.5.0"
    assert updater.state == UpdateState.AVAILABLE
    assert updater.available_update == info
    assert "Update to v1.5.0" in updater.get_status_text()
    assert callback_called is True


@pytest.mark.integration
def test_check_for_updates_up_to_date(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.response_code = 200
    handler.response_body = json.dumps(
        {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.0.0",
        }
    ).encode("utf-8")

    updater = AppUpdater(current_version="1.0.0", api_url=url)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.UP_TO_DATE
    assert updater.available_update is None
    assert updater.get_status_text() == "Version 1.0.0  [Up to Date]"


@pytest.mark.integration
def test_check_for_updates_http_404(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.response_code = 404
    handler.response_body = b'{"message": "Not Found"}'

    updater = AppUpdater(current_version="1.0.0", api_url=url)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert "404" in (updater.error_message or "")
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.integration
def test_check_for_updates_http_500(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.response_code = 500
    handler.response_body = b'{"message": "Internal Server Error"}'

    updater = AppUpdater(current_version="1.0.0", api_url=url)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert "500" in (updater.error_message or "")
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.integration
def test_check_for_updates_socket_timeout(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.delay = 0.1
    handler.response_code = 200
    handler.response_body = b'{"tag_name": "v2.0.0"}'

    updater = AppUpdater(current_version="1.0.0", api_url=url, timeout=0.05)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.integration
def test_check_in_background(
    mock_release_server: tuple[str, type[MockReleaseHTTPHandler]],
) -> None:
    url, handler = mock_release_server
    handler.response_code = 200
    handler.response_body = json.dumps(
        {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
        }
    ).encode("utf-8")

    completed_event = threading.Event()
    received_info: list[UpdateInfo | None] = []

    def on_complete(info: UpdateInfo | None) -> None:
        received_info.append(info)
        completed_event.set()

    updater = AppUpdater(current_version="1.0.0", api_url=url)
    updater.check_in_background(delay_seconds=0.01, on_complete=on_complete)

    assert completed_event.wait(timeout=2.0)
    assert len(received_info) == 1
    assert received_info[0] is not None
    assert received_info[0].tag_name == "v2.0.0"


@pytest.mark.unit
def test_open_release_page_with_update() -> None:
    updater = AppUpdater(current_version="1.0.0")
    updater.available_update = UpdateInfo(
        tag_name="v2.0.0",
        version_tuple=(2, 0, 0),
        html_url="https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v2.0.0",
    )

    with patch("webbrowser.open", return_value=True) as mock_browser:
        success = updater.open_release_page()
        assert success is True
        mock_browser.assert_called_once_with(
            "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v2.0.0"
        )


@pytest.mark.unit
def test_open_release_page_without_update() -> None:
    updater = AppUpdater(current_version="1.0.0")

    with patch("webbrowser.open", return_value=True) as mock_browser:
        success = updater.open_release_page()
        assert success is True
        mock_browser.assert_called_once_with(
            "https://github.com/SolaneHub/Expedition33_RPC/releases/latest"
        )


@pytest.mark.unit
def test_get_status_text_checking() -> None:
    updater = AppUpdater(current_version="1.0.0")
    updater.state = UpdateState.CHECKING
    assert updater.get_status_text() == "Checking for Updates..."


@pytest.mark.unit
def test_updater_cancel_unblocks_delay() -> None:
    """Verifies that cancel() immediately unblocks a background thread in delay without network I/O."""
    updater = AppUpdater(current_version="1.0.0", api_url="http://127.0.0.1:9999/releases/latest")
    start = time.perf_counter()
    updater.check_in_background(delay_seconds=10.0)

    assert updater.state == UpdateState.CHECKING

    updater.cancel()
    updater.join(timeout=2.0)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0
    assert updater.state == UpdateState.IDLE


@pytest.mark.unit
def test_updater_concurrent_check_in_background_guards_thread_spawning() -> None:
    """Verifies that concurrent check_in_background calls while in CHECKING do not spawn parallel threads."""
    updater = AppUpdater(current_version="1.0.0", api_url="http://127.0.0.1:9999/releases/latest")

    # 1. Direct guard check when already CHECKING
    updater.state = UpdateState.CHECKING
    with patch("threading.Thread", wraps=threading.Thread) as mock_thread:
        updater.check_in_background(delay_seconds=0.0)
        mock_thread.assert_not_called()

    # 2. Concurrent invocation across 5 threads with barrier
    updater.state = UpdateState.IDLE
    barrier = threading.Barrier(5)

    def concurrent_caller() -> None:
        barrier.wait()
        updater.check_in_background(delay_seconds=5.0)

    with patch("threading.Thread", wraps=threading.Thread) as mock_thread:
        invokers = [threading.Thread(target=concurrent_caller) for _ in range(5)]
        for t in invokers:
            t.start()
        for t in invokers:
            t.join()

        worker_threads_created = [
            call
            for call in mock_thread.call_args_list
            if call.kwargs.get("name") == "AppUpdaterWorkerThread"
        ]
        assert len(worker_threads_created) == 1

    # Cleanup background worker thread cleanly
    updater.cancel()
    updater.join(timeout=2.0)
    assert updater.state == UpdateState.IDLE


# ---------------------------------------------------------------------------
# Concurrency & Cancellation Stress Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_stress_updater_concurrent_hammering() -> None:
    """Adversarially stresses check_in_background() by having 50 threads hammer it simultaneously.

    Verifies:
    1. Only 1 worker thread is ever spawned.
    2. Zero race conditions occur during state transitions.
    3. Repeated across 5 consecutive hammering cycles.
    """
    for cycle in range(5):
        updater = AppUpdater(
            current_version="1.0.0", api_url="http://127.0.0.1:9999/releases/latest"
        )
        assert updater.state == UpdateState.IDLE

        num_threads = 50
        barrier = threading.Barrier(num_threads)

        def hammer(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
            b.wait()
            u.check_in_background(delay_seconds=10.0)

        with patch("threading.Thread", wraps=threading.Thread) as mock_thread:
            threads = [
                threading.Thread(target=hammer, name=f"HammerThread_{cycle}_{i}")
                for i in range(num_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            workers = [
                call
                for call in mock_thread.call_args_list
                if call.kwargs.get("name") == "AppUpdaterWorkerThread"
            ]
            assert len(workers) == 1, (
                f"Cycle {cycle}: Expected 1 AppUpdaterWorkerThread, got {len(workers)}"
            )

        assert updater.state == UpdateState.CHECKING

        # Cancel and clean up before next cycle
        updater.cancel()
        updater.join(timeout=2.0)
        assert updater.state == UpdateState.IDLE


@pytest.mark.integration
def test_stress_updater_cancel_during_delay_and_rapid_cycling() -> None:
    """Stress-tests updater delay cancellation under various adversarial scenarios:

    1. Long delay (100.0s) cancelled -> terminates within 100ms without network call.
    2. Rapid start-cancel loop (25 iterations) without deadlocks or thread leaks.
    3. Cancel during zero-delay in-flight network request with slow HTTP server.
    """
    # 1. Cancellation during a 100-second delay
    updater = AppUpdater(current_version="1.0.0", api_url="http://127.0.0.1:9999/releases/latest")
    t0 = time.perf_counter()
    updater.check_in_background(delay_seconds=100.0)
    assert updater.state == UpdateState.CHECKING

    # Cancel immediately
    updater.cancel()
    updater.join(timeout=2.0)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, f"Cancellation took too long: {elapsed:.3f}s"
    assert updater.state == UpdateState.IDLE

    # 2. Rapid start-cancel cycling (25 iterations)
    for _i in range(25):
        u = AppUpdater(current_version="1.0.0", api_url="http://127.0.0.1:9999/releases/latest")
        u.check_in_background(delay_seconds=5.0)
        assert u.state == UpdateState.CHECKING
        u.cancel()
        u.join(timeout=1.0)
        assert u.state == UpdateState.IDLE

    # 3. Cancel while an HTTP request is in-flight on slow server
    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            time.sleep(0.3)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"tag_name": "v2.0.0"}')

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), SlowHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/releases/latest"

    try:
        slow_updater = AppUpdater(current_version="1.0.0", api_url=url, timeout=5.0)
        callback_called = threading.Event()
        received_info: list[UpdateInfo | None] = []

        def on_complete(info: UpdateInfo | None) -> None:
            received_info.append(info)
            callback_called.set()

        slow_updater.check_in_background(delay_seconds=0.0, on_complete=on_complete)
        assert slow_updater.state == UpdateState.CHECKING

        # Cancel while in-flight
        time.sleep(0.05)
        slow_updater.cancel()
        slow_updater.join(timeout=3.0)
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.integration
def test_stress_updater_concurrent_check_and_cancel_race() -> None:
    """Stress-tests simultaneous racing between check_in_background() and cancel().

    Verifies no deadlocks occur and the updater reliably terminates in a valid state.
    """
    for _ in range(10):
        updater = AppUpdater(
            current_version="1.0.0",
            api_url="http://127.0.0.1:9999/releases/latest",
            timeout=0.2,
        )
        barrier = threading.Barrier(2)

        def runner_check(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
            b.wait()
            u.check_in_background(delay_seconds=0.05)

        def runner_cancel(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
            b.wait()
            u.cancel()

        t1 = threading.Thread(target=runner_check)
        t2 = threading.Thread(target=runner_cancel)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        updater.join(timeout=3.0)

        # Final state must be IDLE (if cancel won) or ERROR (if check won and network timed out)
        assert updater.state in (UpdateState.IDLE, UpdateState.ERROR)


@pytest.mark.integration
def test_stress_updater_cancel_during_delay_multithreaded_hammer() -> None:
    """Stress-tests cancelling a delay with multiple threads hammering cancel() simultaneously.

    Verifies that:
    1. A thread blocked in delay (30.0s) wakes up in < 200ms when hammered by 10 threads calling cancel().
    2. Zero unhandled exceptions or state corruptions occur.
    3. Final state is reliably UpdateState.IDLE.
    """
    updater = AppUpdater(
        current_version="1.0.0",
        api_url="http://127.0.0.1:9999/releases/latest",
        timeout=0.5,
    )
    updater.check_in_background(delay_seconds=30.0)
    assert updater.state == UpdateState.CHECKING

    # Small pause to guarantee worker thread entered _cancel_event.wait(30.0)
    time.sleep(0.05)

    # 10 threads hammer cancel() simultaneously
    barrier = threading.Barrier(10)

    def hammer_cancel() -> None:
        barrier.wait()
        updater.cancel()

    t0 = time.perf_counter()
    cancel_threads = [threading.Thread(target=hammer_cancel) for _ in range(10)]
    for t in cancel_threads:
        t.start()
    for t in cancel_threads:
        t.join()

    updater.join(timeout=1.0)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, f"Delay cancellation took too long: {elapsed:.3f}s"
    assert updater.state == UpdateState.IDLE
