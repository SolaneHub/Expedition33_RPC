"""Tests for lightweight AppUpdater and GitHub Releases integration."""

from __future__ import annotations

import json
import threading
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from expedition33_rpc.integrations.updater import (
    AppUpdater,
    UpdateInfo,
    UpdateState,
    parse_version,
)

pytestmark = pytest.mark.unit


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


def test_updater_initial_state() -> None:
    updater = AppUpdater(current_version="1.0.0")
    assert updater.state == UpdateState.IDLE
    assert updater.available_update is None
    assert updater.error_message is None
    assert updater.get_status_text() == "Check for Updates"


def test_check_for_updates_available() -> None:
    payload = json.dumps(
        {
            "tag_name": "v1.5.0",
            "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.5.0",
        }
    ).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__.return_value = mock_resp

    callback_called = False

    def on_state():
        nonlocal callback_called
        callback_called = True

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        updater = AppUpdater(current_version="1.0.0", on_state_change=on_state)
        info = updater.check_for_updates()

        assert info is not None
        assert info.tag_name == "v1.5.0"
        assert info.version_tuple == (1, 5, 0)
        assert info.html_url == "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.5.0"
        assert updater.state == UpdateState.AVAILABLE
        assert updater.available_update == info
        assert "Update to v1.5.0" in updater.get_status_text()
        assert callback_called is True
        mock_urlopen.assert_called_once()


def test_check_for_updates_up_to_date() -> None:
    payload = json.dumps(
        {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v1.0.0",
        }
    ).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        updater = AppUpdater(current_version="1.0.0")
        info = updater.check_for_updates()

        assert info is None
        assert updater.state == UpdateState.UP_TO_DATE
        assert updater.available_update is None
        assert updater.get_status_text() == "Version 1.0.0  [Up to Date]"


def test_check_for_updates_network_error() -> None:
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        updater = AppUpdater(current_version="1.0.0")
        info = updater.check_for_updates()

        assert info is None
        assert updater.state == UpdateState.ERROR
        assert updater.error_message == "Network connection error: Connection refused"
        assert updater.get_status_text() == "Update Check Failed  [Click to Retry]"


def test_check_for_updates_unexpected_error() -> None:
    with patch("urllib.request.urlopen", side_effect=RuntimeError("Unexpected crash")):
        updater = AppUpdater(current_version="1.0.0")
        info = updater.check_for_updates()

        assert info is None
        assert updater.state == UpdateState.ERROR
        assert "Update check failed: Unexpected crash" in (updater.error_message or "")


def test_check_in_background() -> None:
    payload = json.dumps({"tag_name": "v2.0.0", "html_url": "https://example.com"}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__.return_value = mock_resp

    completed_event = threading.Event()
    received_info: list[UpdateInfo | None] = []

    def on_complete(info: UpdateInfo | None) -> None:
        received_info.append(info)
        completed_event.set()

    with patch("urllib.request.urlopen", return_value=mock_resp):
        updater = AppUpdater(current_version="1.0.0")
        updater.check_in_background(delay_seconds=0.01, on_complete=on_complete)

        assert completed_event.wait(timeout=2.0)
        assert len(received_info) == 1
        assert received_info[0] is not None
        assert received_info[0].tag_name == "v2.0.0"


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


def test_open_release_page_without_update() -> None:
    updater = AppUpdater(current_version="1.0.0")

    with patch("webbrowser.open", return_value=True) as mock_browser:
        success = updater.open_release_page()
        assert success is True
        mock_browser.assert_called_once_with(
            "https://github.com/SolaneHub/Expedition33_RPC/releases/latest"
        )


def test_get_status_text_checking() -> None:
    updater = AppUpdater(current_version="1.0.0")
    updater.state = UpdateState.CHECKING
    assert updater.get_status_text() == "Checking for Updates..."
