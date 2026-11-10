"""Tests for VirusTotal report fetching and hashing utilities."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from virustotal_scan import (
    RateLimiter,
    check_file_report,
    compute_sha256,
    main,
    poll_analysis,
)

pytestmark = pytest.mark.ci


@pytest.fixture
def test_artifact(tmp_path: Path) -> tuple[Path, str]:
    test_file = tmp_path / "test_artifact.bin"
    payload = b"test binary content for virustotal scan"
    test_file.write_bytes(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()
    return test_file, expected_hash


def test_compute_sha256(test_artifact: tuple[Path, str]) -> None:
    test_file, expected_hash = test_artifact
    sha = compute_sha256(test_file)
    assert sha == expected_hash


def test_check_file_report_cache_hit(test_artifact: tuple[Path, str]) -> None:
    _, expected_hash = test_artifact
    limiter = RateLimiter(requests_per_minute=0)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(
        {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "harmless": 0,
                        "malicious": 1,
                        "suspicious": 0,
                        "undetected": 67,
                        "timeout": 0,
                    }
                }
            }
        }
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        found, stats, ratio = check_file_report(expected_hash, "fake_key", limiter)
        assert found is True
        assert stats is not None
        assert ratio == "67/68 Clean"


def test_check_file_report_cache_miss(test_artifact: tuple[Path, str]) -> None:
    _, expected_hash = test_artifact
    limiter = RateLimiter(requests_per_minute=0)

    mock_err = urllib.error.HTTPError(
        url="https://www.virustotal.com",
        code=404,
        msg="Not Found",
        hdrs=MagicMock(),
        fp=MagicMock(read=lambda: b'{"error": {"code": "NotFoundError"}}'),
    )

    with patch("urllib.request.urlopen", side_effect=mock_err):
        found, stats, ratio = check_file_report(expected_hash, "fake_key", limiter)
        assert found is False
        assert stats is None
        assert ratio is None


def test_main_report_generation_clean_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_artifact: tuple[Path, str]
) -> None:
    test_file, _ = test_artifact
    report_file = tmp_path / "report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "virustotal_scan.py",
            str(test_file),
            "--api-key",
            "dummy_key",
            "--output-report",
            str(report_file),
        ],
    )

    with (
        patch("virustotal_scan.check_file_report", return_value=(True, {}, "71/72 Clean")),
        patch("virustotal_scan.append_step_summary"),
        patch("virustotal_scan.set_github_output"),
    ):
        ret = main()
        assert ret == 0
        assert report_file.exists()
        data = json.loads(report_file.read_text(encoding="utf-8"))
        file_info = data["files"][test_file.name]
        assert file_info["positives"] == 1
        assert file_info["total"] == 72
        assert file_info["status"] == "CACHED"


def test_main_report_generation_zero_positives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_artifact: tuple[Path, str]
) -> None:
    test_file, _ = test_artifact
    report_file = tmp_path / "report_zero.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "virustotal_scan.py",
            str(test_file),
            "--api-key",
            "dummy_key",
            "--output-report",
            str(report_file),
        ],
    )

    with (
        patch("virustotal_scan.check_file_report", return_value=(True, {}, "72/72 Clean")),
        patch("virustotal_scan.append_step_summary"),
        patch("virustotal_scan.set_github_output"),
    ):
        ret = main()
        assert ret == 0
        assert report_file.exists()
        data = json.loads(report_file.read_text(encoding="utf-8"))
        file_info = data["files"][test_file.name]
        assert file_info["positives"] == 0
        assert file_info["total"] == 72
        assert file_info["status"] == "CACHED"


def test_main_report_generation_malformed_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_artifact: tuple[Path, str]
) -> None:
    test_file, _ = test_artifact
    report_file = tmp_path / "report_malformed.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "virustotal_scan.py",
            str(test_file),
            "--api-key",
            "dummy_key",
            "--output-report",
            str(report_file),
        ],
    )

    with (
        patch("virustotal_scan.check_file_report", return_value=(True, {}, "invalid/ratio")),
        patch("virustotal_scan.append_step_summary"),
        patch("virustotal_scan.set_github_output"),
    ):
        ret = main()
        assert ret == 0
        assert report_file.exists()
        data = json.loads(report_file.read_text(encoding="utf-8"))
        file_info = data["files"][test_file.name]
        assert file_info["positives"] == 0
        assert file_info["total"] == 0


def test_main_report_generation_no_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_artifact: tuple[Path, str]
) -> None:
    monkeypatch.delenv("VT_API_KEY", raising=False)
    test_file, _ = test_artifact
    report_file = tmp_path / "report_no_key.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "virustotal_scan.py",
            str(test_file),
            "--output-report",
            str(report_file),
        ],
    )

    with (
        patch("virustotal_scan.append_step_summary"),
        patch("virustotal_scan.set_github_output"),
    ):
        ret = main()
        assert ret == 0
        assert report_file.exists()
        data = json.loads(report_file.read_text(encoding="utf-8"))
        file_info = data["files"][test_file.name]
        assert file_info["positives"] == 0
        assert file_info["total"] == 0
        assert "NO API KEY" in file_info["status"]


def test_rate_limiter_min_interval_property() -> None:
    limiter = RateLimiter(requests_per_minute=4.0)
    assert limiter.min_interval == 15.0

    limiter_disabled = RateLimiter(requests_per_minute=0.0)
    assert limiter_disabled.min_interval == 0.0

    limiter.min_interval = 20.0
    assert limiter.interval == 20.0
    assert limiter.min_interval == 20.0


def test_poll_analysis_completed_immediately() -> None:
    limiter = RateLimiter(requests_per_minute=4.0)
    completed_response = (
        200,
        {
            "data": {
                "attributes": {
                    "status": "completed",
                    "stats": {
                        "harmless": 65,
                        "undetected": 5,
                        "malicious": 0,
                        "suspicious": 0,
                    },
                }
            }
        },
        {},
    )

    with (
        patch("virustotal_scan.vt_api_request", return_value=completed_response) as mock_req,
        patch("time.sleep") as mock_sleep,
    ):
        found, stats, ratio = poll_analysis("id_123", "fake_key", timeout=30, rate_limiter=limiter)
        assert found is True
        assert stats is not None
        assert ratio == "70/70 Clean"
        assert mock_req.call_count == 1
        mock_sleep.assert_not_called()


def test_poll_analysis_respects_minimum_wait_on_queued() -> None:
    # Rate limiter disabled (min_interval = 0.0); must enforce minimum wait of 5.0s
    limiter = RateLimiter(requests_per_minute=0.0)
    queued_response = (
        200,
        {"data": {"attributes": {"status": "queued"}}},
        {},
    )
    completed_response = (
        200,
        {
            "data": {
                "attributes": {
                    "status": "completed",
                    "stats": {
                        "harmless": 50,
                        "undetected": 0,
                        "malicious": 0,
                        "suspicious": 0,
                    },
                }
            }
        },
        {},
    )

    with (
        patch(
            "virustotal_scan.vt_api_request",
            side_effect=[queued_response, completed_response],
        ) as mock_req,
        patch("time.sleep") as mock_sleep,
    ):
        found, stats, ratio = poll_analysis("id_123", "fake_key", timeout=30, rate_limiter=limiter)
        assert found is True
        assert stats is not None
        assert ratio == "50/50 Clean"
        assert mock_req.call_count == 2
        mock_sleep.assert_called_once_with(5.0)


def test_poll_analysis_respects_rate_limiter_min_interval() -> None:
    # 2 requests/min => min_interval = 30.0s > 5.0s
    limiter = RateLimiter(requests_per_minute=2.0)
    queued_response = (
        200,
        {"data": {"attributes": {"status": "in-progress"}}},
        {},
    )
    completed_response = (
        200,
        {
            "data": {
                "attributes": {
                    "status": "completed",
                    "stats": {
                        "harmless": 10,
                        "undetected": 0,
                        "malicious": 0,
                        "suspicious": 0,
                    },
                }
            }
        },
        {},
    )

    with (
        patch(
            "virustotal_scan.vt_api_request",
            side_effect=[queued_response, completed_response],
        ) as mock_req,
        patch("time.sleep") as mock_sleep,
    ):
        found, stats, ratio = poll_analysis("id_123", "fake_key", timeout=60, rate_limiter=limiter)
        assert found is True
        assert stats is not None
        assert ratio == "10/10 Clean"
        assert mock_req.call_count == 2
        mock_sleep.assert_called_once_with(30.0)


def test_poll_analysis_terminates_on_timeout() -> None:
    limiter = RateLimiter(requests_per_minute=0.0)
    queued_response = (
        200,
        {"data": {"attributes": {"status": "queued"}}},
        {},
    )

    current_time = 100.0

    def fake_time() -> float:
        return current_time

    def fake_sleep(secs: float) -> None:
        nonlocal current_time
        current_time += secs

    with (
        patch("virustotal_scan.vt_api_request", return_value=queued_response) as mock_req,
        patch("time.time", side_effect=fake_time),
        patch("time.sleep", side_effect=fake_sleep) as mock_sleep,
    ):
        found, stats, ratio = poll_analysis("id_123", "fake_key", timeout=12, rate_limiter=limiter)
        assert found is False
        assert stats is None
        assert ratio is None
        # With timeout=12 and step=5s: requests at t=100, t=105, t=110, sleep to 115 terminates loop
        assert mock_req.call_count >= 2
        assert mock_sleep.call_count >= 2
        for call_arg in mock_sleep.call_args_list:
            assert call_arg[0][0] >= 5.0


def test_poll_analysis_zero_or_negative_timeout() -> None:
    limiter = RateLimiter(requests_per_minute=4.0)
    with patch("virustotal_scan.vt_api_request") as mock_req:
        found_zero, stats_zero, ratio_zero = poll_analysis(
            "id_123", "fake_key", timeout=0, rate_limiter=limiter
        )
        assert found_zero is False
        assert stats_zero is None
        assert ratio_zero is None

        found_neg, stats_neg, ratio_neg = poll_analysis(
            "id_123", "fake_key", timeout=-10, rate_limiter=limiter
        )
        assert found_neg is False
        assert stats_neg is None
        assert ratio_neg is None

        mock_req.assert_not_called()
