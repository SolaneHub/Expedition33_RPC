"""Concurrency and thread-safety tests for DiscordIPCClient, SettingsService, and TrayApp."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tests.harness import DiscordPipeSimulator

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import (
    OP_FRAME,
    DiscordIPCClient,
    DiscordRPCManager,
)
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# DiscordIPCClient Concurrency Tests
# ---------------------------------------------------------------------------


def test_concurrent_set_activity_and_disconnect() -> None:
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="123456789", transport=pipe)
    assert client.connect() is True
    pipe.outgoing_bytes.clear()

    errors: list[Exception] = []
    num_threads = 8
    iterations_per_thread = 25
    barrier = threading.Barrier(num_threads)

    def worker(thread_idx: int):
        try:
            barrier.wait()
            for i in range(iterations_per_thread):
                if thread_idx % 2 == 0:
                    client.set_activity(
                        pid=1000 + i,
                        state=f"State_{thread_idx}_{i}",
                        details=f"Details_{thread_idx}_{i}",
                    )
                else:
                    client.clear_activity(pid=1000 + i)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == [], f"Encountered concurrency errors: {errors}"

    # Verify wire-level frame integrity
    frames = pipe.drain_all_frames()
    assert len(frames) > 0
    for op, payload in frames:
        assert op == OP_FRAME
        assert payload.get("cmd") == "SET_ACTIVITY"
        assert "args" in payload
        assert "pid" in payload["args"]


# ---------------------------------------------------------------------------
# TrayApp and Settings Concurrency Tests
# ---------------------------------------------------------------------------


def test_concurrent_settings_mutations(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_service = SettingsService(custom_path=settings_file)

    num_workers = 6
    ops_per_worker = 30
    barrier = threading.Barrier(num_workers)
    errors: list[Exception] = []

    def worker_task(worker_id: int):
        try:
            barrier.wait()
            for i in range(ops_per_worker):
                if i % 2 == 0:
                    settings_service.toggle_anti_spoiler()
                else:
                    settings_service.set_anti_spoiler_enabled(worker_id % 2 == 0)
                # Verify read consistency
                _val = settings_service.is_anti_spoiler_enabled()
        except Exception as e:
            errors.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task, i) for i in range(num_workers)]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    assert errors == []
    # Ensure file on disk remains valid JSON
    final_settings = settings_service.load_settings()
    assert isinstance(final_settings.anti_spoiler, bool)


def test_concurrent_telemetry_ticks_and_ui_toggles(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_service = SettingsService(custom_path=settings_file)

    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    ipc_client = DiscordIPCClient(client_id="123456789", transport=pipe)
    real_rpc = DiscordRPCManager(client=ipc_client)
    assert real_rpc.connect() is True
    pipe.outgoing_bytes.clear()

    mock_detector = MagicMock(spec=GameDetector)
    mock_icon = MagicMock()

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=real_rpc,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=settings_service,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = mock_icon

    stop_event = threading.Event()
    errors: list[Exception] = []

    # Background worker performing step_update ticks
    def telemetry_worker():
        tick_count = 0
        while not stop_event.is_set() and tick_count < 50:
            try:
                mock_detector.get_game_state.return_value = GameState.create(
                    is_running=True,
                    zone_name=f"Zone_{tick_count % 3}",
                    in_combat=(tick_count % 2 == 0),
                )
                app.orchestrator.step_update()
                tick_count += 1
            except Exception as e:
                errors.append(e)

    # Foreground UI thread performing user clicks and reading state
    def ui_user_thread():
        clicks = 0
        while not stop_event.is_set() and clicks < 50:
            try:
                settings_service.toggle_anti_spoiler()
                curr = app.orchestrator.current_state
                _zone = curr.zone_name
                # Also simulate user toggling anti-spoiler via tray action
                app.action_toggle_anti_spoiler()
                clicks += 1
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=telemetry_worker)
    t2 = threading.Thread(target=ui_user_thread)
    t1.start()
    t2.start()

    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    stop_event.set()

    assert errors == [], f"Concurrency errors during step_update: {errors}"

    # Verify wire-level frame integrity from concurrent RPC updates
    frames = pipe.drain_all_frames()
    assert len(frames) > 0
    for op, payload in frames:
        assert op == OP_FRAME
        assert payload.get("cmd") == "SET_ACTIVITY"
