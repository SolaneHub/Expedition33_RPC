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
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    url = f"http://{host}:{port}/releases/latest"

    worker = threading.Thread(target=server.serve_forever, daemon=True)
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
    handler.delay = 0.5
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
