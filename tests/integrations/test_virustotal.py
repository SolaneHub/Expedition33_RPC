"""Tests for VirusTotal report fetching and hashing utilities."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scripts.virustotal_scan import (
    RateLimiter,
    check_file_report,
    compute_sha256,
)

pytestmark = pytest.mark.unit


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
