"""Tests for VirusTotal report fetching and hashing utilities."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is importable in CI test run
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from virustotal_scan import (  # noqa: E402
    RateLimiter,
    check_file_report,
    compute_sha256,
    main,
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
