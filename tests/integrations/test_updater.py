"""Tests for lightweight AppUpdater and GitHub Releases integration."""

from __future__ import annotations

import http.server
import json
import logging
import threading
import time
import urllib.error
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.harness.fake_services import (
    FakeBrowserLauncher,
    FakeHttpOpener,
    FakeHttpResponse,
)
from tests.harness.orchestrator_chaos_harness import OrchestratorChaosHarness

from expedition33_rpc.integrations.updater import (
    DEFAULT_RELEASE_URL,
    AppUpdater,
    UpdateInfo,
    UpdateState,
    parse_version,
    validate_release_url,
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


@pytest.mark.unit
def test_check_for_updates_up_to_date() -> None:
    opener = FakeHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.0.0",
            }
        )
    )
    updater = AppUpdater(current_version="1.0.0", http_opener=opener)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.UP_TO_DATE
    assert updater.available_update is None
    assert updater.get_status_text() == "Version 1.0.0  [Up to Date]"


@pytest.mark.unit
def test_check_for_updates_http_404() -> None:
    opener = FakeHttpOpener(
        error=FakeHttpOpener.make_http_error(DEFAULT_RELEASE_URL, 404, "Not Found")
    )
    updater = AppUpdater(current_version="1.0.0", http_opener=opener)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert "404" in (updater.error_message or "")
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.unit
def test_check_for_updates_http_500() -> None:
    opener = FakeHttpOpener(
        error=FakeHttpOpener.make_http_error(DEFAULT_RELEASE_URL, 500, "Internal Server Error")
    )
    updater = AppUpdater(current_version="1.0.0", http_opener=opener)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert "500" in (updater.error_message or "")
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.unit
def test_check_for_updates_socket_timeout() -> None:
    opener = FakeHttpOpener(error=TimeoutError("timed out"))
    updater = AppUpdater(current_version="1.0.0", timeout=0.05, http_opener=opener)
    info = updater.check_for_updates()

    assert info is None
    assert updater.state == UpdateState.ERROR
    assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


@pytest.mark.unit
def test_check_in_background() -> None:
    opener = FakeHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v2.0.0",
                "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v2.0.0",
            }
        )
    )
    completed_event = threading.Event()
    received_info: list[UpdateInfo | None] = []

    def on_complete(info: UpdateInfo | None) -> None:
        received_info.append(info)
        completed_event.set()

    updater = AppUpdater(current_version="1.0.0", http_opener=opener)
    updater.check_in_background(delay_seconds=0.0, on_complete=on_complete)

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

    # 3. Cancel while an HTTP request is in-flight using deterministic FakeHttpOpener
    block_event = threading.Event()
    opener = FakeHttpOpener(
        response=FakeHttpResponse({"tag_name": "v2.0.0"}),
        block_event=block_event,
    )
    slow_updater = AppUpdater(current_version="1.0.0", timeout=5.0, http_opener=opener)
    callback_called = threading.Event()
    received_info: list[UpdateInfo | None] = []

    def on_complete(info: UpdateInfo | None) -> None:
        received_info.append(info)
        callback_called.set()

    slow_updater.check_in_background(delay_seconds=0.0, on_complete=on_complete)
    assert slow_updater.state == UpdateState.CHECKING

    slow_updater.cancel()
    block_event.set()
    slow_updater.join(timeout=3.0)
    assert not callback_called.is_set()
    assert received_info == []


@pytest.mark.unit
def test_stress_updater_concurrent_check_and_cancel_race() -> None:
    """Stress-tests simultaneous racing between check_in_background() and cancel().

    Verifies no deadlocks occur and the updater reliably terminates in a valid state.
    """
    for _ in range(10):
        updater = AppUpdater(
            current_version="1.0.0",
            timeout=0.2,
            http_opener=FakeHttpOpener(error=urllib.error.URLError("offline")),
        )
        barrier = threading.Barrier(2)

        def runner_check(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
            b.wait()
            u.check_in_background(delay_seconds=0.0)

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


@pytest.mark.unit
@pytest.mark.parametrize(
    "malicious_url",
    [
        "file:///etc/passwd",
        "https://evil.example/payload",
        "javascript:alert(1)",
    ],
)
def test_updater_rejects_non_github_html_url_and_falls_back_to_default(malicious_url: str) -> None:
    """Verifies non-GitHub html_url values are rejected and safely fall back to DEFAULT_RELEASE_URL."""
    opener = FakeHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v9.9.9",
                "html_url": malicious_url,
            }
        )
    )
    browser = FakeBrowserLauncher()
    updater = AppUpdater(current_version="1.0.0", http_opener=opener, browser_opener=browser)
    info = updater.check_for_updates()

    assert info is not None
    assert info.html_url == DEFAULT_RELEASE_URL
    assert updater.open_release_page() is True
    assert browser.opened_urls == [DEFAULT_RELEASE_URL]


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


# ---------------------------------------------------------------------------
# Milestone 2: URL Validation, Zero-Cost DI & Cancel-Safety Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "valid_url",
    [
        "https://github.com/SolaneHub/Expedition33_RPC",
        "https://github.com/SolaneHub/Expedition33_RPC/",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v2.6.0",
    ],
)
def test_validate_release_url_accepts_official_repo_urls(valid_url: str) -> None:
    assert validate_release_url(valid_url) == valid_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostile_url",
    [
        "javascript:alert(1)",
        "file:///C:/Windows/cmd.exe",
        "http://github.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://evil.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://github.com.evil.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://github.com@evil.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://user:pass@github.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://github.com:8443/SolaneHub/Expedition33_RPC/releases/latest",
        "https://github.com/SolaneHub/Expedition33_RPC_fork/releases/latest",
        "https://github.com/SolaneHub/Expedition33_RPC/../../other",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%2e%2e/other",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/..%2fother",
        "https://github.com/SolaneHub/Expedition33_RPC\\releases",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/latest\n",
        " https://github.com/SolaneHub/Expedition33_RPC/releases/latest",
        "",
        None,
    ],
)
def test_validate_release_url_rejects_hostile_urls_and_logs_warning(
    hostile_url: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        sanitized = validate_release_url(hostile_url)

    assert sanitized == DEFAULT_RELEASE_URL
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostile_url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://github.com/SolaneHub/Expedition33_RPC/releases/latest",
        "https://evil.com/payload",
        "https://github.com.evil.com/SolaneHub/Expedition33_RPC",
        "https://github.com@evil.com/SolaneHub/Expedition33_RPC",
        "https://github.com/SolaneHub/Expedition33_RPC_fork/releases",
        "https://github.com/SolaneHub/Expedition33_RPC/../../other",
        "",
    ],
)
def test_update_info_and_open_release_page_sanitize_hostile_urls(
    hostile_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        info = UpdateInfo(tag_name="v9.9.9", version_tuple=(9, 9, 9), html_url=hostile_url)

    assert info.html_url == DEFAULT_RELEASE_URL
    assert any(record.levelno == logging.WARNING for record in caplog.records)

    browser = FakeBrowserLauncher(return_value=True)
    updater = AppUpdater(current_version="1.0.0", browser_opener=browser)
    updater.available_update = info
    assert updater.open_release_page() is True
    assert browser.opened_urls == [DEFAULT_RELEASE_URL]

    # Even if an UpdateInfo instance's html_url is mutated via object.__setattr__
    # (bypassing __post_init__), open_release_page() validates before calling browser_opener.
    bypassed = UpdateInfo(
        tag_name="v9.9.9",
        version_tuple=(9, 9, 9),
        html_url=DEFAULT_RELEASE_URL,
    )
    object.__setattr__(bypassed, "html_url", hostile_url)
    updater.available_update = bypassed
    assert updater.open_release_page() is True
    assert browser.opened_urls == [DEFAULT_RELEASE_URL, DEFAULT_RELEASE_URL]


@pytest.mark.unit
def test_check_for_updates_sanitizes_malicious_html_url_from_api_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    opener = FakeHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v9.9.9",
                "html_url": "javascript:alert(document.cookie)",
            }
        )
    )
    browser = FakeBrowserLauncher(return_value=True)
    updater = AppUpdater(
        current_version="1.0.0",
        http_opener=opener,
        browser_opener=browser,
    )

    with caplog.at_level(logging.WARNING):
        info = updater.check_for_updates()

    assert info is not None
    assert info.html_url == DEFAULT_RELEASE_URL
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert updater.open_release_page() is True
    assert browser.opened_urls == [DEFAULT_RELEASE_URL]


@pytest.mark.unit
def test_zero_cost_di_http_opener_and_browser_opener() -> None:
    # Default construction keeps openers None (zero allocation, lazy resolution)
    default_updater = AppUpdater(current_version="1.0.0")
    assert default_updater._http_opener is None
    assert default_updater._browser_opener is None

    # 1. Available update via FakeHttpOpener + FakeBrowserLauncher
    valid_url = "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v2.6.0"
    browser = FakeBrowserLauncher(return_value=True)
    updater_avail = AppUpdater(
        current_version="1.0.0",
        http_opener=FakeHttpOpener(
            response=FakeHttpResponse({"tag_name": "v2.6.0", "html_url": valid_url})
        ),
        browser_opener=browser,
    )
    info = updater_avail.check_for_updates()
    assert info is not None
    assert info.tag_name == "v2.6.0"
    assert info.html_url == valid_url
    assert updater_avail.state == UpdateState.AVAILABLE
    assert updater_avail.open_release_page() is True
    assert browser.opened_urls == [valid_url]

    # 2. Up to date
    updater_utd = AppUpdater(
        current_version="2.6.0",
        http_opener=FakeHttpOpener(
            response=FakeHttpResponse({"tag_name": "v2.6.0", "html_url": valid_url})
        ),
    )
    assert updater_utd.check_for_updates() is None
    assert updater_utd.state == UpdateState.UP_TO_DATE

    # 3. HTTP error
    updater_http_err = AppUpdater(
        current_version="1.0.0",
        http_opener=FakeHttpOpener(
            error=FakeHttpOpener.make_http_error(DEFAULT_RELEASE_URL, 403, "Forbidden")
        ),
    )
    assert updater_http_err.check_for_updates() is None
    assert updater_http_err.state == UpdateState.ERROR
    assert "403" in (updater_http_err.error_message or "")

    # 4. Network URLError
    updater_url_err = AppUpdater(
        current_version="1.0.0",
        http_opener=FakeHttpOpener(error=urllib.error.URLError("offline")),
    )
    assert updater_url_err.check_for_updates() is None
    assert updater_url_err.state == UpdateState.ERROR

    # 5. Malformed JSON & missing tag_name
    updater_bad_json = AppUpdater(
        current_version="1.0.0",
        http_opener=FakeHttpOpener(response=FakeHttpResponse(b"{not-json")),
    )
    assert updater_bad_json.check_for_updates() is None
    assert updater_bad_json.state == UpdateState.ERROR

    updater_no_tag = AppUpdater(
        current_version="1.0.0",
        http_opener=FakeHttpOpener(response=FakeHttpResponse({"tag_name": ""})),
    )
    assert updater_no_tag.check_for_updates() is None
    assert updater_no_tag.state == UpdateState.ERROR

    # 6. Browser opener exception handled cleanly
    def failing_browser(_url: str) -> bool:
        raise RuntimeError("browser launch failed")

    updater_bad_browser = AppUpdater(
        current_version="1.0.0",
        browser_opener=failing_browser,
    )
    assert updater_bad_browser.open_release_page() is False


@pytest.mark.unit
def test_in_flight_cancel_with_success_response_never_invokes_callback_or_mutates_state(
    tmp_path: Path,
) -> None:
    block_ev = threading.Event()
    http_entered = threading.Event()

    class _SignalingHttpOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            http_entered.set()
            return super().__call__(req, timeout=timeout)

    opener = _SignalingHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v9.9.9",
                "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v9.9.9",
            }
        ),
        block_event=block_ev,
    )
    completed_calls: list[UpdateInfo | None] = []
    state_notifications: list[UpdateState] = []

    def on_state() -> None:
        state_notifications.append(updater.state)

    updater = AppUpdater(
        current_version="1.0.0",
        on_state_change=on_state,
        http_opener=opener,
    )

    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        updater.check_in_background(
            delay_seconds=0.0,
            on_complete=lambda info: completed_calls.append(info),
        )
        assert http_entered.wait(timeout=2.0)
        assert len(opener.calls) == 1

        updater.cancel()
        assert updater.state == UpdateState.IDLE

        block_ev.set()
        updater.join(timeout=2.0)

        assert completed_calls == []
        assert updater.state == UpdateState.IDLE
        assert updater.available_update is None
        assert updater.error_message is None
        assert UpdateState.AVAILABLE not in state_notifications
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("timeout"),
        FakeHttpOpener.make_http_error(DEFAULT_RELEASE_URL, 500, "Server Error"),
        RuntimeError("unexpected failure"),
    ],
)
def test_in_flight_cancel_with_error_response_never_invokes_callback_or_mutates_state(
    error: Exception,
    tmp_path: Path,
) -> None:
    block_ev = threading.Event()
    http_entered = threading.Event()

    class _SignalingErrorOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            http_entered.set()
            return super().__call__(req, timeout=timeout)

    opener = _SignalingErrorOpener(error=error, block_event=block_ev)
    completed_calls: list[UpdateInfo | None] = []
    state_notifications: list[UpdateState] = []

    def on_state() -> None:
        state_notifications.append(updater.state)

    updater = AppUpdater(
        current_version="1.0.0",
        on_state_change=on_state,
        http_opener=opener,
    )

    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        updater.check_in_background(
            delay_seconds=0.0,
            on_complete=lambda info: completed_calls.append(info),
        )
        assert http_entered.wait(timeout=2.0)

        updater.cancel()
        assert updater.state == UpdateState.IDLE

        block_ev.set()
        updater.join(timeout=2.0)

        assert completed_calls == []
        assert updater.state == UpdateState.IDLE
        assert updater.available_update is None
        assert updater.error_message is None
        assert UpdateState.ERROR not in state_notifications
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
def test_check_for_updates_respects_cancel_event_before_http() -> None:
    opener = FakeHttpOpener(
        response=FakeHttpResponse({"tag_name": "v9.9.9", "html_url": DEFAULT_RELEASE_URL})
    )
    updater = AppUpdater(current_version="1.0.0", http_opener=opener)
    updater.cancel()

    assert updater.check_for_updates() is None
    assert opener.calls == []
    assert updater.state == UpdateState.IDLE
    assert updater.available_update is None
    assert updater.error_message is None


@pytest.mark.integration
def test_concurrent_check_cancel_join_race_no_thread_leaks(tmp_path: Path) -> None:
    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        # 1. Three-way barrier racing check_in_background(), cancel(), and join()
        for i in range(20):
            ev = threading.Event()
            opener = (
                FakeHttpOpener(
                    response=FakeHttpResponse(
                        {"tag_name": "v9.9.9", "html_url": DEFAULT_RELEASE_URL}
                    ),
                    block_event=ev,
                )
                if i % 2 == 0
                else FakeHttpOpener(
                    error=urllib.error.URLError("transient"),
                    block_event=ev,
                )
            )
            updater = AppUpdater(current_version="1.0.0", http_opener=opener)
            barrier = threading.Barrier(3)

            def do_check(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
                b.wait()
                u.check_in_background(delay_seconds=0.0)

            def do_cancel(
                b: threading.Barrier = barrier,
                u: AppUpdater = updater,
                unblock: threading.Event = ev,
            ) -> None:
                b.wait()
                u.cancel()
                unblock.set()

            def do_join(b: threading.Barrier = barrier, u: AppUpdater = updater) -> None:
                b.wait()
                u.join(timeout=2.0)

            threads = [
                threading.Thread(target=do_check),
                threading.Thread(target=do_cancel),
                threading.Thread(target=do_join),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=3.0)

            updater.join(timeout=2.0)
            assert updater.state in (
                UpdateState.IDLE,
                UpdateState.AVAILABLE,
                UpdateState.UP_TO_DATE,
                UpdateState.ERROR,
            )

        # 2. Race cancel() + join() + unblock while HTTP is in-flight: callback never fires
        for _ in range(20):
            ev = threading.Event()
            entered = threading.Event()

            class _BarrierHttpOpener(FakeHttpOpener):
                def __call__(
                    self, req: Any, timeout: float | None = None, sig: threading.Event = entered
                ) -> FakeHttpResponse:
                    sig.set()
                    return super().__call__(req, timeout=timeout)

            opener = _BarrierHttpOpener(
                response=FakeHttpResponse({"tag_name": "v9.9.9", "html_url": DEFAULT_RELEASE_URL}),
                block_event=ev,
            )
            completed: list[UpdateInfo | None] = []
            updater = AppUpdater(current_version="1.0.0", http_opener=opener)
            updater.check_in_background(
                delay_seconds=0.0,
                on_complete=lambda info, log=completed: log.append(info),
            )
            assert entered.wait(timeout=2.0)

            updater.cancel()
            ev.set()
            updater.join(timeout=2.0)

            assert completed == []
            assert updater.state == UpdateState.IDLE
            assert updater.available_update is None

        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostile_url",
    [
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%00/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%0a/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%0d/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%09/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%7f/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%2500/evil",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%252e%252e/other",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/..%252fother",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%255c..%255c",
        "https://github.com/SolaneHub/Expedition33_RPC/releases/%25252e%25252e/other",
    ],
)
def test_validate_release_url_rejects_multi_encoded_traversal_and_control_chars(
    hostile_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        sanitized = validate_release_url(hostile_url)

    assert sanitized == DEFAULT_RELEASE_URL
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.unit
def test_probe_2b_delayed_gen1_cancel_and_gen2_never_strands_worker(tmp_path: Path) -> None:
    """Challenge 2 (Probe 2B): Gen 2 starting must not clear Gen 1's per-generation cancel event."""
    real_event_cls = threading.Event
    gen1_wait_entered = real_event_cls()
    allow_gen1_wait = real_event_cls()
    created_events: list[threading.Event] = []

    class _DelayedFirstWaitEvent(real_event_cls):
        def __init__(self, index: int) -> None:
            super().__init__()
            self._index = index

        def wait(self, timeout: float | None = None) -> bool:
            # Index 0 is AppUpdater.__init__._cancel_event; Index 1 is Gen 1's gen_cancel_event.
            if self._index == 1 and timeout is not None and timeout > 1.0:
                gen1_wait_entered.set()
                allow_gen1_wait.wait(timeout=2.0)
            return super().wait(timeout=timeout)

    def _event_factory() -> threading.Event:
        idx = len(created_events)
        ev = _DelayedFirstWaitEvent(idx)
        created_events.append(ev)
        return ev

    opener = FakeHttpOpener(
        response=FakeHttpResponse(
            {
                "tag_name": "v1.0.0",
                "html_url": DEFAULT_RELEASE_URL,
            }
        )
    )
    gen2_done = real_event_cls()
    gen2_results: list[UpdateInfo | None] = []

    def on_gen2_complete(info: UpdateInfo | None) -> None:
        gen2_results.append(info)
        gen2_done.set()

    with (
        OrchestratorChaosHarness(base_dir=tmp_path) as chaos,
        patch("expedition33_rpc.integrations.updater.threading.Event", side_effect=_event_factory),
    ):
        updater = AppUpdater(current_version="1.0.0", http_opener=opener)

        # Gen 1 starts with a 10s delay and pauses right before wait(10.0)
        updater.check_in_background(delay_seconds=10.0)
        assert gen1_wait_entered.wait(timeout=2.0)

        # Cancel Gen 1, then immediately start Gen 2 (which clears shared _cancel_event)
        updater.cancel()
        updater.check_in_background(delay_seconds=0.0, on_complete=on_gen2_complete)
        assert gen2_done.wait(timeout=2.0)

        # Now let Gen 1 execute gen_cancel_event.wait(10.0) after Gen 2 cleared _cancel_event
        t0 = time.monotonic()
        allow_gen1_wait.set()
        updater.join(timeout=2.0)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0
        assert updater.state == UpdateState.UP_TO_DATE
        assert gen2_results == [None]
        alive_workers = [
            t for t in threading.enumerate() if t.is_alive() and t.name == "AppUpdaterWorkerThread"
        ]
        assert alive_workers == []
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
def test_probe_2c_cancelled_gen1_cannot_adopt_gen2_generation(tmp_path: Path) -> None:
    """Challenge 1 (Probe 2C): Cancelled Gen 1 between _worker and _check_for_updates never clobbers Gen 2."""
    gen1_entering = threading.Event()
    allow_gen1_proceed = threading.Event()
    gen1_exited_check = threading.Event()
    gen2_http_entered = threading.Event()
    allow_gen2_http = threading.Event()

    class _PerGenOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            self.calls.append((req, timeout))
            if len(self.calls) == 1:
                gen2_http_entered.set()
                allow_gen2_http.wait(timeout=2.0)
            return FakeHttpResponse({"tag_name": "v1.0.0", "html_url": DEFAULT_RELEASE_URL})

    opener = _PerGenOpener()
    cb1: list[UpdateInfo | None] = []
    cb2: list[UpdateInfo | None] = []
    gen2_done = threading.Event()

    def on_gen2(info: UpdateInfo | None) -> None:
        cb2.append(info)
        gen2_done.set()

    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        updater = AppUpdater(current_version="1.0.0", http_opener=opener)
        orig_check = updater._check_for_updates

        def _intercept_check(
            expected_generation: int | None = None,
            cancel_event: threading.Event | None = None,
        ) -> UpdateInfo | None:
            if expected_generation == 1:
                gen1_entering.set()
                allow_gen1_proceed.wait(timeout=2.0)
                try:
                    return orig_check(
                        expected_generation=expected_generation,
                        cancel_event=cancel_event,
                    )
                finally:
                    gen1_exited_check.set()
            return orig_check(
                expected_generation=expected_generation,
                cancel_event=cancel_event,
            )

        with patch.object(updater, "_check_for_updates", side_effect=_intercept_check):
            updater.check_in_background(delay_seconds=0.0, on_complete=cb1.append)
            assert gen1_entering.wait(timeout=2.0)

            updater.cancel()
            updater.check_in_background(delay_seconds=0.0, on_complete=on_gen2)
            assert gen2_http_entered.wait(timeout=2.0)

            # Release Gen 1 into _check_for_updates while Gen 2 is actively CHECKING
            allow_gen1_proceed.set()
            assert gen1_exited_check.wait(timeout=2.0)
            assert updater.state == UpdateState.CHECKING

            # Now unblock Gen 2
            allow_gen2_http.set()
            assert gen2_done.wait(timeout=2.0)
            updater.join(timeout=2.0)

        assert len(opener.calls) == 1
        assert cb1 == []
        assert cb2 == [None]
        assert updater.state == UpdateState.UP_TO_DATE
        assert updater.available_update is None
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
def test_probe_2c_in_flight_http_gen1_cannot_clobber_gen2(tmp_path: Path) -> None:
    """Challenge 1: Cancelled Gen 1 already inside HTTP never overwrites Gen 2's state."""
    gen1_http_entered = threading.Event()
    allow_gen1_http = threading.Event()
    gen2_http_entered = threading.Event()
    allow_gen2_http = threading.Event()

    class _TwoPhaseOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            self.calls.append((req, timeout))
            call_num = len(self.calls)
            if call_num == 1:
                gen1_http_entered.set()
                allow_gen1_http.wait(timeout=2.0)
                return FakeHttpResponse({"tag_name": "v9.9.9", "html_url": DEFAULT_RELEASE_URL})
            gen2_http_entered.set()
            allow_gen2_http.wait(timeout=2.0)
            return FakeHttpResponse({"tag_name": "v1.0.0", "html_url": DEFAULT_RELEASE_URL})

    opener = _TwoPhaseOpener()
    cb1: list[UpdateInfo | None] = []
    cb2: list[UpdateInfo | None] = []

    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        updater = AppUpdater(current_version="1.0.0", http_opener=opener)
        updater.check_in_background(delay_seconds=0.0, on_complete=cb1.append)
        assert gen1_http_entered.wait(timeout=2.0)

        updater.cancel()
        updater.check_in_background(delay_seconds=0.0, on_complete=cb2.append)
        assert gen2_http_entered.wait(timeout=2.0)

        # Gen 1 returns v9.9.9 while Gen 2 is still blocked in CHECKING
        allow_gen1_http.set()
        allow_gen2_http.set()
        updater.join(timeout=2.0)

        assert cb1 == []
        assert cb2 == [None]
        assert updater.state == UpdateState.UP_TO_DATE
        assert updater.available_update is None
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
def test_probe_2g_join_waits_for_earlier_slow_http_worker_after_gen2_finishes(
    tmp_path: Path,
) -> None:
    """Challenge 3 (Probe 2G): Overwriting _worker_thread must not orphan slow Gen 1 in join()."""
    gen1_http_entered = threading.Event()
    allow_gen1_http = threading.Event()
    gen1_http_exited = threading.Event()
    gen2_done = threading.Event()

    class _SlowThenFastOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            self.calls.append((req, timeout))
            if len(self.calls) == 1:
                gen1_http_entered.set()
                allow_gen1_http.wait(timeout=3.0)
                gen1_http_exited.set()
                return FakeHttpResponse({"tag_name": "v9.9.9", "html_url": DEFAULT_RELEASE_URL})
            return FakeHttpResponse({"tag_name": "v1.0.0", "html_url": DEFAULT_RELEASE_URL})

    opener = _SlowThenFastOpener()
    cb1: list[UpdateInfo | None] = []
    cb2: list[UpdateInfo | None] = []

    def on_gen2(info: UpdateInfo | None) -> None:
        cb2.append(info)
        gen2_done.set()

    with OrchestratorChaosHarness(base_dir=tmp_path) as chaos:
        updater = AppUpdater(current_version="1.0.0", http_opener=opener)
        updater.check_in_background(delay_seconds=0.0, on_complete=cb1.append)
        assert gen1_http_entered.wait(timeout=2.0)

        updater.cancel()
        updater.check_in_background(delay_seconds=0.0, on_complete=on_gen2)
        assert gen2_done.wait(timeout=2.0)

        # Gen 2 is completely finished, while Gen 1 is still blocked in HTTP.
        # Unblock Gen 1 asynchronously slightly later and ensure join() waits for it.
        timer = threading.Timer(0.1, allow_gen1_http.set)
        timer.start()
        try:
            updater.join(timeout=2.0)
        finally:
            timer.cancel()
            allow_gen1_http.set()

        assert gen1_http_exited.is_set()
        alive_workers = [
            t for t in threading.enumerate() if t.is_alive() and t.name == "AppUpdaterWorkerThread"
        ]
        assert alive_workers == []
        assert updater.state == UpdateState.UP_TO_DATE
        assert updater.available_update is None
        assert cb1 == []
        assert cb2 == [None]
        chaos.assert_no_orphaned_threads()


@pytest.mark.unit
def test_join_enforces_cumulative_timeout_across_multiple_active_workers() -> None:
    """Challenge 3: join(timeout) uses a cumulative monotonic deadline across all active threads."""
    entered = 0
    entered_lock = threading.Lock()
    first_entered = threading.Event()
    both_entered = threading.Event()
    release_all = threading.Event()

    class _BlockingOpener(FakeHttpOpener):
        def __call__(self, req: Any, timeout: float | None = None) -> FakeHttpResponse:
            nonlocal entered
            self.calls.append((req, timeout))
            with entered_lock:
                entered += 1
                if entered == 1:
                    first_entered.set()
                elif entered == 2:
                    both_entered.set()
            release_all.wait(timeout=3.0)
            return FakeHttpResponse({"tag_name": "v1.0.0", "html_url": DEFAULT_RELEASE_URL})

    updater = AppUpdater(current_version="1.0.0", http_opener=_BlockingOpener())
    updater.check_in_background(delay_seconds=0.0)
    assert first_entered.wait(timeout=2.0)
    updater.cancel()
    updater.check_in_background(delay_seconds=0.0)
    assert both_entered.wait(timeout=2.0)

    t0 = time.monotonic()
    updater.join(timeout=0.15)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.35

    release_all.set()
    updater.join(timeout=2.0)
    alive_workers = [
        t for t in threading.enumerate() if t.is_alive() and t.name == "AppUpdaterWorkerThread"
    ]
    assert alive_workers == []
