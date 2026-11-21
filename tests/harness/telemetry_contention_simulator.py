"""Harness for testing BridgeStateProvider file contention, locks, and partial writes."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from expedition33_rpc.detection.detector import BridgeStateProvider


class TelemetryContentionSimulator:
    """Simulates file contention, concurrent non-atomic writes, partial streams,

    and transient PermissionError / SharingViolation on telemetry JSON files.
    """

    def __init__(self, target_path: str | Path) -> None:
        self.target_path = Path(target_path)
        self._permission_error_count = 0
        self._sharing_violation_count = 0
        self._active_patch: Any = None

    def simulate_partial_write(self, mode: str = "empty") -> None:
        """Writes partial or corrupted content to simulate non-atomic NTFS writes.

        Modes:
            - 'empty': File is zero-byte / truncated during mid-write.
            - 'truncated_json': File contains incomplete JSON chunk (syntax error).
            - 'broken_utf8': File contains malformed byte sequence interrupting UTF-8 stream.
        """
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        match mode:
            case "empty":
                self.target_path.write_bytes(b"")
            case "truncated_json":
                self.target_path.write_text(
                    '{"raw_zone": "Level_Forest", "in_combat":', encoding="utf-8"
                )
            case "broken_utf8":
                # Valid JSON header followed by incomplete multibyte sequence (0xC3 without continuation)
                self.target_path.write_bytes(b'{"raw_zone": "Forest \xc3')
            case _:
                raise ValueError(f"Unknown partial write mode: '{mode}'")

    @contextlib.contextmanager
    def transient_lock(self, failures: int = 1, error_type: type[Exception] = PermissionError):
        """Simulates transient I/O lock (PermissionError / SharingViolation / OSError)

        for a configurable number of attempts (1..6) before allowing the read to proceed.
        """
        remaining_failures = max(0, failures)

        from expedition33_rpc.detection import detector

        original_fn = detector._read_file_shared_text

        def mock_read(path: str | Path) -> str:
            nonlocal remaining_failures
            if remaining_failures > 0:
                remaining_failures -= 1
                if error_type is PermissionError:
                    raise PermissionError(f"[WinError 32] Sharing violation: {path}")
                elif error_type is OSError:
                    raise OSError(13, f"Sharing violation: {path}")
                else:
                    raise error_type(f"Simulated lock error on {path}")
            return original_fn(path)

        with patch(
            "expedition33_rpc.detection.detector._read_file_shared_text", side_effect=mock_read
        ):
            yield

    def verify_bridge_provider_resilience(
        self,
        provider: BridgeStateProvider,
        expected_valid_data: dict[str, Any] | None = None,
        transient_failures: int = 0,
    ) -> dict[str, Any] | None:
        """Executes read_bridge_status() under simulated lock, verifying clean retry handling."""
        if transient_failures > 0:
            with self.transient_lock(failures=transient_failures):
                result = provider.read_bridge_status()
        else:
            result = provider.read_bridge_status()

        if expected_valid_data is not None:
            assert result == expected_valid_data, f"Expected {expected_valid_data}, got {result}"
        return result
