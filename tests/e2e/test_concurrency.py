"""Concurrency and thread-safety tests for DiscordIPCClient, SettingsService, and TrayApp."""

from __future__ import annotations

import concurrent.futures
import json
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
    settings_service = SettingsService(path=settings_file)

    num_workers = 6
    ops_per_worker = 15
    barrier = threading.Barrier(num_workers)
    errors: list[Exception] = []
    results: list[bool] = []
    results_lock = threading.Lock()

    def worker_task(worker_id: int):
        try:
            barrier.wait()
            for i in range(ops_per_worker):
                if i % 2 == 0:
                    res = isinstance(settings_service.toggle_anti_spoiler(), bool)
                else:
                    res = settings_service.set_anti_spoiler_enabled(worker_id % 2 == 0)
                with results_lock:
                    results.append(res)
                # Verify read consistency
                _val = settings_service.is_anti_spoiler_enabled()
        except Exception as e:
            errors.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task, i) for i in range(num_workers)]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    assert errors == []
    assert all(r is True for r in results)
    # Ensure file on disk matches in-memory value
    in_memory_anti_spoiler = settings_service.is_anti_spoiler_enabled()
    disk_data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert disk_data.get("anti_spoiler") == in_memory_anti_spoiler
    settings_service.load()
    assert settings_service.is_anti_spoiler_enabled() == in_memory_anti_spoiler


def test_concurrent_telemetry_ticks_and_ui_toggles(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    settings_service = SettingsService(path=settings_file)

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
        while not stop_event.is_set() and tick_count < 15:
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
        while not stop_event.is_set() and clicks < 15:
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


def test_concurrent_step_update_and_stop_bridge_install_thread_race() -> None:
    """High-contention barrier race between step_update(auto_install_bridge=True) and stop()."""
    from tests.harness import FakeBridgeInstaller, FakeProcess

    class SlowInstaller(FakeBridgeInstaller):
        def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            del win64_dir
            self.install_call_count += 1
            self.installed = True
            return True, "Installed"

    def _run_iteration(iteration: int) -> None:
        procs = [
            FakeProcess(
                pid=10_000 + iteration,
                name="sandfall-win64-shipping.exe",
                is_running=True,
                exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
            )
        ]
        detector = GameDetector(bridge_provider=None, process_scanner=lambda: procs)
        pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
        rpc = DiscordRPCManager(client=DiscordIPCClient(client_id="123456789", transport=pipe))
        installer = SlowInstaller(installed=False)
        orchestrator = AppOrchestrator(
            detector=detector,
            rpc_manager=rpc,
            bridge_installer=installer,
            auto_install_bridge=True,
            sync_startup=False,
        )

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def _step() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.step_update()
            except BaseException as exc:
                errors.append(exc)

        def _stop() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.stop()
            except BaseException as exc:
                errors.append(exc)

        t_step = threading.Thread(target=_step)
        t_stop = threading.Thread(target=_stop)
        t_step.start()
        t_stop.start()
        t_step.join(timeout=5.0)
        t_stop.join(timeout=5.0)

        assert errors == [], f"Iteration {iteration} raised errors: {errors}"
        orchestrator.stop()
        assert orchestrator._bridge_install_thread is None

    initial_threads = {t for t in threading.enumerate() if t.is_alive()}

    for i in range(30):
        _run_iteration(i)

    # Verify zero orphaned BridgeAutoInstallerThread instances remain
    remaining = [
        t
        for t in threading.enumerate()
        if t.is_alive() and t not in initial_threads and "BridgeAutoInstallerThread" in t.name
    ]
    assert remaining == []


def test_concurrent_bridge_mutations_and_probes_no_stale_overwrite(tmp_path: Path) -> None:
    """High-contention barrier race across step_update, toggle_bridge, install_bridge_to, and stop."""
    import time

    from tests.harness import FakeBridgeInstaller, FakeProcess

    class YieldingInstaller(FakeBridgeInstaller):
        def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
            del win64_dir
            val = self.installed
            time.sleep(0.002)
            return val

        def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            del win64_dir
            time.sleep(0.002)
            self.installed = True
            return True, "Installed"

        def uninstall_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            del win64_dir
            time.sleep(0.002)
            self.installed = False
            return True, "Uninstalled"

    def _run_iteration(iteration: int) -> None:
        procs = [
            FakeProcess(
                pid=20_000 + iteration,
                name="sandfall-win64-shipping.exe",
                is_running=True,
                exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
            )
        ]
        detector = GameDetector(bridge_provider=None, process_scanner=lambda: procs)
        pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
        rpc = DiscordRPCManager(client=DiscordIPCClient(client_id="123456789", transport=pipe))
        installer = YieldingInstaller(installed=(iteration % 2 == 0))
        orchestrator = AppOrchestrator(
            detector=detector,
            rpc_manager=rpc,
            bridge_installer=installer,
            auto_install_bridge=False,
            sync_startup=False,
        )
        if installer.installed:
            orchestrator.install_bridge_to(tmp_path)

        barrier = threading.Barrier(4)
        errors: list[BaseException] = []

        def _step() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.step_update()
            except BaseException as exc:
                errors.append(exc)

        def _toggle() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.toggle_bridge()
            except BaseException as exc:
                errors.append(exc)

        def _install_to() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.install_bridge_to(tmp_path)
            except BaseException as exc:
                errors.append(exc)

        def _stop() -> None:
            try:
                barrier.wait(timeout=2.0)
                orchestrator.stop()
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=_step),
            threading.Thread(target=_toggle),
            threading.Thread(target=_install_to),
            threading.Thread(target=_stop),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Iteration {iteration} raised errors: {errors}"
        assert orchestrator.is_bridge_installed() == installer.installed, (
            f"Iteration {iteration} desync: orch={orchestrator.is_bridge_installed()} "
            f"installer={installer.installed}"
        )

    for i in range(25):
        _run_iteration(i)


def test_orchestrator_chaos_harness_multi_cycle_no_orphaned_threads() -> None:
    """Runs multi-cycle chaos simulation across orchestrator, tray, clocks, and Discord pipe."""
    from tests.harness.orchestrator_chaos_harness import OrchestratorChaosHarness

    initial_threads = {t for t in threading.enumerate() if t.is_alive()}
    with OrchestratorChaosHarness() as chaos:
        chaos.run_chaos_cycles(cycles=50, seed=33)
        chaos.assert_no_orphaned_threads()
    chaos.assert_no_orphaned_threads(initial_threads=initial_threads)

    with OrchestratorChaosHarness() as chaos_auto:
        chaos_auto.orchestrator.auto_install_bridge = True
        chaos_auto.run_chaos_cycles(cycles=20, seed=99)
        chaos_auto.assert_no_orphaned_threads()
    chaos_auto.assert_no_orphaned_threads(initial_threads=initial_threads)


def test_orchestrator_chaos_harness_tray_updater_bridge_rpc_no_orphaned_threads(
    tmp_path: Path,
) -> None:
    """Runs full chaos simulation combining tray actions, folder_picker DI, updater, bridge, and RPC."""
    from tests.harness.orchestrator_chaos_harness import OrchestratorChaosHarness

    from expedition33_rpc.integrations.updater import UpdateInfo, UpdateState

    picked_folder = tmp_path / "CustomGameWin64"
    picked_folder.mkdir()

    initial_threads = {t for t in threading.enumerate() if t.is_alive()}
    with OrchestratorChaosHarness() as chaos:
        tray_with_picker = ExpeditionTrayApp(
            orchestrator=chaos.orchestrator,
            folder_picker=lambda: str(picked_folder),
        )
        tray_with_picker.icon = MagicMock()
        chaos.orchestrator.auto_install_bridge = True

        chaos.run_chaos_cycles(cycles=25, seed=77)

        # Interleave tray UI actions, updater state transitions, and RPC cycles
        chaos.session.start_game(pid=9001).enter_zone("Level_Main_OldLumiere")
        chaos.orchestrator.step_update()
        tray_with_picker.action_toggle_anti_spoiler()
        tray_with_picker.action_toggle_bridge()
        tray_with_picker.action_select_game_folder()

        chaos.updater.state = UpdateState.AVAILABLE
        chaos.updater.available_update = UpdateInfo(
            tag_name="v9.9.9",
            version_tuple=(9, 9, 9),
            html_url="https://github.com/SolaneHub/Expedition33_RPC/releases/tag/v9.9.9",
        )
        chaos.orchestrator.on_update_check_complete(chaos.updater.available_update)
        tray_with_picker.action_update_click()
        assert chaos.updater.open_release_page_called is True

        chaos.updater.state = UpdateState.UP_TO_DATE
        chaos.orchestrator.step_update()

        tray_with_picker.action_exit()
        chaos.assert_no_orphaned_threads()
    chaos.assert_no_orphaned_threads(initial_threads=initial_threads)
