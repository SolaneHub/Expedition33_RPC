"""Concurrency stress tests for BridgeStateProvider IPC JSON reading."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from expedition33_rpc.detection.detector import BridgeStateProvider


@pytest.mark.integration
def test_bridge_ipc_concurrent_writes_and_reads(tmp_path: Path) -> None:
    """Verifies that BridgeStateProvider safely handles concurrent truncations and writes

    via its 6-attempt retry loop without throwing uncaught filesystem or parsing exceptions.
    """
    status_file = tmp_path / "expedition33_status.json"
    valid_payload = {
        "timestamp": time.time(),
        "zone": "Level_Main_OldLumiere",
        "in_combat": True,
        "enemy_name": "Duollistes",
        "floor": None,
        "checkpoint": "Entrance",
    }
    status_file.write_text(json.dumps(valid_payload), encoding="utf-8")

    provider = BridgeStateProvider(paths=[str(status_file)], grace_period=0.5)

    stop_event = threading.Event()
    writer_errors: list[Exception] = []
    reader_errors: list[Exception] = []
    successful_reads = 0

    def writer_loop() -> None:
        try:
            iteration = 0
            while not stop_event.is_set() and iteration < 150:
                iteration += 1
                payload = dict(valid_payload)
                payload["timestamp"] = time.time()
                # 1. Truncate/write partial data to simulate concurrent atomic collisions
                try:
                    with open(status_file, "w", encoding="utf-8") as f:
                        f.write(json.dumps(payload)[:15])  # Malformed / truncated
                except OSError:
                    pass

                time.sleep(0.001)

                # 2. Write complete valid JSON
                try:
                    with open(status_file, "w", encoding="utf-8") as f:
                        f.write(json.dumps(payload))
                except OSError:
                    pass

                time.sleep(0.002)
        except Exception as e:
            writer_errors.append(e)

    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    try:
        start_time = time.monotonic()
        while time.monotonic() - start_time < 1.0:
            try:
                data = provider.read_game_data()
                if data is not None and data.get("raw_zone") == "Level_Main_OldLumiere":
                    successful_reads += 1
            except Exception as e:
                reader_errors.append(e)
            time.sleep(0.003)
    finally:
        stop_event.set()
        writer_thread.join(timeout=2.0)

    # 1. No uncaught exceptions in reader thread
    assert not reader_errors, f"Reader thread encountered unhandled exceptions: {reader_errors}"
    assert not writer_errors, f"Writer thread failed unexpectedly: {writer_errors}"

    # 2. Concurrency retry loop managed to yield valid reads despite contention
    assert successful_reads > 0, "Expected at least one successful read during concurrent execution"

    # 3. Final read after writer stops yields fully valid state
    final_payload = dict(valid_payload)
    final_payload["timestamp"] = time.time()
    status_file.write_text(json.dumps(final_payload), encoding="utf-8")
    final_data = provider.read_game_data()
    assert final_data is not None
    assert final_data["raw_zone"] == "Level_Main_OldLumiere"
