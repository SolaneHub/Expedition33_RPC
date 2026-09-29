import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.virustotal_scan import (
    RateLimiter,
    build_multipart_payload,
    check_file_report,
    compute_sha256,
    main,
    poll_analysis,
    upload_file,
)


class TestVirusTotalScan(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_artifact.bin"
        self.test_file.write_bytes(b"test binary content for virustotal scan")
        self.expected_hash = hashlib.sha256(b"test binary content for virustotal scan").hexdigest()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compute_sha256(self):
        sha = compute_sha256(self.test_file)
        self.assertEqual(sha, self.expected_hash)

    def test_rate_limiter(self):
        limiter = RateLimiter(requests_per_minute=60.0)  # 1s interval
        self.assertEqual(limiter.interval, 1.0)
        limiter.last_request_time = 0.0

        with (
            patch("time.sleep") as mock_sleep,
            patch("time.time", side_effect=[100.0, 100.0, 100.4, 101.4]),
        ):
            limiter.wait()  # First request, no sleep
            mock_sleep.assert_not_called()

            limiter.wait()  # Second request after 0.4s -> sleeps 0.6s
            mock_sleep.assert_called_once()
            self.assertAlmostEqual(mock_sleep.call_args[0][0], 0.6, places=1)

    def test_build_multipart_payload(self):
        body, content_type = build_multipart_payload("file", self.test_file)
        self.assertIn(
            b'Content-Disposition: form-data; name="file"; filename="test_artifact.bin"', body
        )
        self.assertIn(b"test binary content for virustotal scan", body)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))

    @patch("urllib.request.urlopen")
    def test_check_file_report_cache_hit(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
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
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        limiter = RateLimiter(requests_per_minute=0)
        found, stats, ratio = check_file_report(self.expected_hash, "fake_key", limiter)
        self.assertTrue(found)
        self.assertIsNotNone(stats)
        self.assertEqual(ratio, "67/68 Clean")

    @patch("urllib.request.urlopen")
    def test_check_file_report_cache_miss(self, mock_urlopen):
        import urllib.error

        mock_err = urllib.error.HTTPError(
            url="https://www.virustotal.com",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=MagicMock(read=lambda: b'{"error": {"code": "NotFoundError"}}'),
        )
        mock_urlopen.side_effect = mock_err

        limiter = RateLimiter(requests_per_minute=0)
        found, stats, ratio = check_file_report(self.expected_hash, "fake_key", limiter)
        self.assertFalse(found)
        self.assertIsNone(stats)
        self.assertIsNone(ratio)

    @patch("urllib.request.urlopen")
    def test_upload_file_direct(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.read.return_value = json.dumps({"data": {"id": "analysis-12345"}}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        limiter = RateLimiter(requests_per_minute=0)
        success, analysis_id = upload_file(self.test_file, "fake_key", limiter)
        self.assertTrue(success)
        self.assertEqual(analysis_id, "analysis-12345")

    @patch("urllib.request.urlopen")
    def test_upload_large_file_with_upload_url(self, mock_urlopen):
        # Mock GET upload_url response, then POST file response
        resp_upload_url = MagicMock()
        resp_upload_url.status = 200
        resp_upload_url.headers = {}
        resp_upload_url.read.return_value = json.dumps(
            {"data": "https://custom.virustotal.com/upload-endpoint"}
        ).encode("utf-8")

        resp_post = MagicMock()
        resp_post.status = 200
        resp_post.headers = {}
        resp_post.read.return_value = json.dumps({"data": {"id": "large-analysis-999"}}).encode(
            "utf-8"
        )

        mock_urlopen.return_value.__enter__.side_effect = [resp_upload_url, resp_post]

        limiter = RateLimiter(requests_per_minute=0)
        # Patch stat to pretend file is > 32MB
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 35 * 1024 * 1024
            success, analysis_id = upload_file(self.test_file, "fake_key", limiter)

        self.assertTrue(success)
        self.assertEqual(analysis_id, "large-analysis-999")

    @patch("urllib.request.urlopen")
    def test_poll_analysis_completed(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.read.return_value = json.dumps(
            {
                "data": {
                    "attributes": {
                        "status": "completed",
                        "stats": {
                            "harmless": 2,
                            "malicious": 0,
                            "suspicious": 0,
                            "undetected": 68,
                        },
                    }
                }
            }
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        limiter = RateLimiter(requests_per_minute=0)
        done, stats, ratio = poll_analysis(
            "analysis-123", "fake_key", timeout=10, rate_limiter=limiter
        )
        self.assertTrue(done)
        self.assertEqual(ratio, "70/70 Clean")

    @patch("sys.argv")
    def test_main_cli_execution_dry_run(self, mock_argv):
        out_file = Path(self.temp_dir.name) / "github_output.txt"
        summary_file = Path(self.temp_dir.name) / "github_summary.md"

        mock_argv.__getitem__.side_effect = lambda s: [
            "virustotal_scan.py",
            str(self.test_file),
            "--api-key",
            "",
        ][s]

        with patch.dict(
            os.environ, {"GITHUB_OUTPUT": str(out_file), "GITHUB_STEP_SUMMARY": str(summary_file)}
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())
        out_content = out_file.read_text(encoding="utf-8")
        self.assertIn("analysis=", out_content)
        self.assertIn(self.expected_hash, out_content)

        self.assertTrue(summary_file.exists())
        summary_content = summary_file.read_text(encoding="utf-8")
        self.assertIn("VirusTotal Inspection Results", summary_content)
        self.assertIn(self.expected_hash[:16], summary_content)


if __name__ == "__main__":
    unittest.main()
