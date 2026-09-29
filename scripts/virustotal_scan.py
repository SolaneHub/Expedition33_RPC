#!/usr/bin/env python3
"""VirusTotal Scan Optimizer for GitHub Actions Release Workflow.

Optimizes file scanning against VirusTotal API v3:
1. Computes local SHA-256 for all target files.
2. Checks VT cache via GET /api/v3/files/{sha256} to avoid re-uploading existing files (e.g. bridge.zip).
3. If not found (404), uploads the file:
   - <= 32MB: POST /api/v3/files
   - > 32MB: GET /api/v3/files/upload_url -> POST to upload URL
4. Strictly respects VirusTotal rate limits (4 requests/minute for public API keys).
5. Emits permanent GUI permalinks https://www.virustotal.com/gui/file/{sha256} to $GITHUB_OUTPUT and $GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class RateLimiter:
    """Enforces maximum requests per minute (e.g. 4 req/min for VirusTotal public API)."""

    def __init__(self, requests_per_minute: float = 4.0):
        self.interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self.last_request_time = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        now = time.time()
        elapsed = now - self.last_request_time
        if self.last_request_time > 0 and elapsed < self.interval:
            to_sleep = self.interval - elapsed
            print(f"[RateLimiter] Waiting {to_sleep:.1f}s to respect VirusTotal rate limit...")
            time.sleep(to_sleep)
        self.last_request_time = time.time()


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_multipart_payload(field_name: str, file_path: Path) -> tuple[bytes, str]:
    """Encodes file into multipart/form-data payload without external libraries."""
    boundary = f"----VirusTotalBoundary{uuid.uuid4().hex}"
    filename = file_path.name
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    footer = f"\r\n--{boundary}--\r\n".encode()

    file_bytes = file_path.read_bytes()
    body = header + file_bytes + footer
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def vt_api_request(
    url: str,
    api_key: str,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
    rate_limiter: RateLimiter | None = None,
    max_retries: int = 2,
) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
    """Performs HTTP request to VirusTotal API v3 with retries and rate limit handling."""
    if rate_limiter:
        rate_limiter.wait()

    headers = {
        "x-apikey": api_key,
        "Accept": "application/json",
        "User-Agent": "Expedition33-RPC-CI/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                raw_body = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw_body) if raw_body else None
                return status, parsed, resp_headers
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = dict(e.headers)
            raw_body = e.read().decode("utf-8", errors="replace")
            parsed = None
            with contextlib.suppress(Exception):
                parsed = json.loads(raw_body)

            if status == 429:
                retry_after_hdr = resp_headers.get("Retry-After")
                retry_after = (
                    int(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else 15
                )
                if attempt < max_retries:
                    print(
                        f"[VirusTotal] Rate limit (429) received. Waiting {retry_after}s before retry..."
                    )
                    time.sleep(retry_after)
                    if rate_limiter:
                        rate_limiter.last_request_time = time.time()
                    continue
            return status, parsed, resp_headers
        except urllib.error.URLError as e:
            if attempt < max_retries:
                print(f"[VirusTotal] Network error ({e}). Retrying in 5s...")
                time.sleep(5)
                continue
            print(f"[VirusTotal] Network error: {e}")
            return 0, None, {}

    return 0, None, {}


def check_file_report(
    sha256: str,
    api_key: str,
    rate_limiter: RateLimiter,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Queries GET /api/v3/files/{sha256} to check if the file is already analyzed."""
    url = f"https://www.virustotal.com/api/v3/files/{sha256}"
    status, data, _ = vt_api_request(url, api_key, method="GET", rate_limiter=rate_limiter)
    if status == 200 and data and "data" in data:
        stats = data["data"].get("attributes", {}).get("last_analysis_stats", {})
        harmless = stats.get("harmless", 0)
        undetected = stats.get("undetected", 0)
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        clean = harmless + undetected
        total = clean + malicious + suspicious
        ratio_str = f"{clean}/{total} Clean" if total > 0 else "Clean"
        return True, stats, ratio_str
    return False, None, None


def upload_file(
    file_path: Path,
    api_key: str,
    rate_limiter: RateLimiter,
) -> tuple[bool, str | None]:
    """Uploads file to VirusTotal v3 via POST /files (or upload_url if >32MB)."""
    file_size = file_path.stat().st_size
    max_direct_size = 32 * 1024 * 1024  # 32 MB

    upload_url = "https://www.virustotal.com/api/v3/files"
    if file_size > max_direct_size:
        print(
            f"[VirusTotal] File {file_path.name} is {file_size / (1024 * 1024):.1f}MB (>32MB). Requesting upload URL..."
        )
        status, data, _ = vt_api_request(
            "https://www.virustotal.com/api/v3/files/upload_url",
            api_key,
            method="GET",
            rate_limiter=rate_limiter,
        )
        if status == 200 and data and "data" in data:
            upload_url = str(data["data"])
            print("[VirusTotal] Obtained large-file upload endpoint.")
        else:
            print(
                f"[VirusTotal] Failed to obtain upload URL (HTTP {status}). Falling back to standard endpoint."
            )

    body, content_type = build_multipart_payload("file", file_path)
    status, data, _ = vt_api_request(
        upload_url,
        api_key,
        method="POST",
        data=body,
        content_type=content_type,
        rate_limiter=rate_limiter,
    )

    if status in (200, 201) and data and "data" in data:
        analysis_id = str(data["data"].get("id", ""))
        return True, analysis_id

    print(f"[VirusTotal] Upload failed for {file_path.name} (HTTP {status}): {data}")
    return False, None


def poll_analysis(
    analysis_id: str,
    api_key: str,
    timeout: int,
    rate_limiter: RateLimiter,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Optionally polls /analyses/{analysis_id} until completed or timeout expires."""
    if timeout <= 0:
        return False, None, None

    start = time.time()
    url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
    print(f"[VirusTotal] Polling analysis {analysis_id} (timeout: {timeout}s)...")

    while time.time() - start < timeout:
        status, data, _ = vt_api_request(url, api_key, method="GET", rate_limiter=rate_limiter)
        if status == 200 and data and "data" in data:
            attributes = data["data"].get("attributes", {})
            analysis_status = attributes.get("status")
            if analysis_status == "completed":
                stats = attributes.get("stats", {})
                harmless = stats.get("harmless", 0)
                undetected = stats.get("undetected", 0)
                malicious = stats.get("malicious", 0)
                suspicious = stats.get("suspicious", 0)
                clean = harmless + undetected
                total = clean + malicious + suspicious
                ratio_str = f"{clean}/{total} Clean" if total > 0 else "Clean"
                return True, stats, ratio_str
            print(f"[VirusTotal] Status: {analysis_status}... waiting next cycle.")
    return False, None, None


def set_github_output(name: str, value: str) -> None:
    """Writes key=value output to $GITHUB_OUTPUT."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def append_step_summary(markdown: str) -> None:
    """Appends Markdown content to $GITHUB_STEP_SUMMARY."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def main() -> int:
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Optimized VirusTotal scanner for GitHub Actions.")
    parser.add_argument("files", nargs="+", help="Files to inspect and scan")
    parser.add_argument(
        "--api-key", default=os.environ.get("VT_API_KEY", ""), help="VirusTotal API Key"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("VT_TIMEOUT", "0")),
        help="Polling timeout in seconds after upload (0 for fire-and-forget)",
    )
    parser.add_argument(
        "--request-rate",
        type=float,
        default=float(os.environ.get("VT_REQUEST_RATE", "4")),
        help="API request rate limit in requests/min (default: 4)",
    )
    args = parser.parse_args()

    api_key = args.api_key.strip()
    rate_limiter = RateLimiter(requests_per_minute=args.request_rate)

    results: list[dict[str, Any]] = []
    analysis_outputs: list[str] = []

    print("=" * 60)
    print("[VirusTotal] Scan Optimizer")
    print(f"Target files: {args.files}")
    print(f"API Key present: {'Yes' if api_key else 'No (Dry Run / Hash Permalink Mode)'}")
    print(f"Polling timeout: {args.timeout}s (0 = non-blocking fire-and-forget)")
    print(f"Rate limit: {args.request_rate} req/min")
    print("=" * 60)

    for file_str in args.files:
        file_path = Path(file_str)
        if not file_path.exists():
            print(f"[Warning] File not found: {file_path}")
            continue

        sha256 = compute_sha256(file_path)
        size_mb = file_path.stat().st_size / (1024 * 1024)
        permalink = f"https://www.virustotal.com/gui/file/{sha256}"
        print(f"\nProcessing {file_path.name} ({size_mb:.2f} MB, SHA-256: {sha256})")

        status_text = "Pending"
        ratio_str = ""

        if not api_key:
            status_text = "Generated (No API Key)"
            ratio_str = "N/A"
            print(f"  -> Permalink: {permalink}")
        else:
            # Step 1: Check cache via file-info
            print(f"  -> Checking VirusTotal cache for {sha256[:12]}...")
            cached, stats, ratio = check_file_report(sha256, api_key, rate_limiter)
            if cached and ratio:
                status_text = "Cached"
                ratio_str = ratio
                print(f"  -> Cache HIT! Existing report found: {ratio_str}")
                print(f"  -> Permalink: {permalink}")
            else:
                # Step 2: Upload new file
                print("  -> Cache MISS. Uploading file to VirusTotal...")
                uploaded, analysis_id = upload_file(file_path, api_key, rate_limiter)
                if uploaded and analysis_id:
                    print(f"  -> Upload succeeded! Analysis ID: {analysis_id}")
                    if args.timeout > 0:
                        finished, poll_stats, poll_ratio = poll_analysis(
                            analysis_id, api_key, args.timeout, rate_limiter
                        )
                        if finished and poll_ratio:
                            status_text = "Completed"
                            ratio_str = poll_ratio
                            print(f"  -> Analysis completed: {ratio_str}")
                        else:
                            status_text = "Uploaded (Queued)"
                            ratio_str = "In progress"
                            print("  -> Polling timed out; report will finish asynchronously.")
                    else:
                        status_text = "Uploaded (Queued)"
                        ratio_str = "Queued"
                        print("  -> Fire-and-forget: report will process asynchronously.")
                else:
                    status_text = "Upload Failed"
                    ratio_str = "Error"
                    print("  -> Upload failed; fallback to permalink.")

        results.append(
            {
                "path": str(file_path),
                "name": file_path.name,
                "sha256": sha256,
                "size_mb": round(size_mb, 2),
                "status": status_text,
                "ratio": ratio_str,
                "permalink": permalink,
            }
        )

        if ratio_str and ratio_str not in ("N/A", "Error", "Queued", "In progress"):
            analysis_outputs.append(f"{file_path}={permalink}|{ratio_str}")
        else:
            analysis_outputs.append(f"{file_path}={permalink}")

    # Set GITHUB_OUTPUT for compatibility with subsequent release workflow steps
    vt_output_str = ",".join(analysis_outputs)
    set_github_output("analysis", vt_output_str)

    # Save local JSON report
    dist_dir = Path("dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    report_file = dist_dir / "virustotal_report.json"
    with open(report_file, "w", encoding="utf-8") as rf:
        json.dump(results, rf, indent=2)
    print(f"\n[VirusTotal] Saved summary report to {report_file}")

    # Generate Markdown Summary for GITHUB_STEP_SUMMARY
    summary_md = [
        "### 🛡️ VirusTotal Inspection Results",
        "",
        "| File | SHA-256 | Status | Detection Ratio | Report Link |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        ratio_display = f"**{r['ratio']}**" if "/" in r["ratio"] else r["ratio"]
        summary_md.append(
            f"| `{r['name']}` | `{r['sha256'][:16]}...` | {r['status']} | {ratio_display} | [Inspect Report]({r['permalink']}) |"
        )
    summary_md.append("")

    append_step_summary("\n".join(summary_md))

    print("\n" + "\n".join(summary_md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
