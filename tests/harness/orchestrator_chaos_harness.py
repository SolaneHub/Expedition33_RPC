"""Chaos and soak test harness orchestrating multi-threaded lifecycle stress testing."""

from __future__ import annotations

import contextlib
import random
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from tests.harness.clock_harness import DualClockHarness
from tests.harness.discord_transport_mock import MockDiscordServer
from tests.harness.fake_services import (
    FakeBridgeInstaller,
    FakeStartupService,
    FakeUpdater,
)
from tests.harness.game_session import GameSessionSimulator
from tests.harness.tray_harness import HeadlessTrayHarness

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.integrations.discord_rpc import DiscordIPCClient, DiscordRPCManager
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp


class OrchestratorChaosHarness:
    """Composite chaos harness orchestrating:

    AppOrchestrator + MockDiscordServer + HeadlessTrayHarness + DualClockHarness + GameSessionSimulator.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        pipe_path: str | None = None,
    ) -> None:
        if base_dir is None:
            self._temp_dir_obj: tempfile.TemporaryDirectory[str] | None = (
                tempfile.TemporaryDirectory()
            )
            self.root_path = Path(self._temp_dir_obj.name)
        else:
            self._temp_dir_obj = None
            self.root_path = Path(base_dir)

        # Clocks
        self.clock = DualClockHarness(initial_monotonic=1000.0, initial_epoch=1_700_000_000.0)

        # Game session simulation
        self.session = GameSessionSimulator(base_dir=self.root_path)

        # Mock Discord Server
        self.server = MockDiscordServer(pipe_path=pipe_path)
        self.server.start()

        # IPC & RPC Manager
        self.ipc_client = DiscordIPCClient(
            client_id="1234567890", custom_pipe_path=self.server.pipe_path
        )
        self.rpc_manager = DiscordRPCManager(
            client=self.ipc_client,
            monotonic_provider=self.clock.monotonic_clock,
            epoch_provider=self.clock.epoch_clock,
        )

        # Settings & Fake services
        self.settings = SettingsService(path=self.root_path / "chaos_settings.json")
        self.updater = FakeUpdater()
        self.bridge_installer = FakeBridgeInstaller()
        self.startup_service = FakeStartupService()

        # Orchestrator
        self.orchestrator = AppOrchestrator(
            detector=self.session.detector,
            rpc_manager=self.rpc_manager,
            updater=self.updater,
            settings_service=self.settings,
            bridge_installer=self.bridge_installer,
            startup_service=self.startup_service,
            auto_install_bridge=False,
            sync_startup=False,
            polling_interval=0.01,
            idle_polling_interval=0.02,
            monotonic_provider=self.clock.monotonic_clock,
            epoch_provider=self.clock.epoch_clock,
        )

        # Headless Tray App
        self.tray_app = ExpeditionTrayApp(orchestrator=self.orchestrator)
        mock_icon = getattr(self.tray_app, "icon", None)
        self.tray_harness = HeadlessTrayHarness(
            menu=self.tray_app.create_menu(),
            mock_icon=mock_icon,
        )

    def run_chaos_cycles(self, cycles: int = 50) -> None:
        """Runs rapid chaos cycles executing random interleaved events:

        - Rapid orchestrator start() / stop()
        - Game process termination (FakeProcess.terminate())
        - Discord pipe closure / server reconnect
        - Simulated clock jumps (advance or NTP jitter)
        - Tray menu interaction
        """
        for cycle in range(cycles):
            action = cycle % 5

            if action == 0:
                # Rapid start/stop
                self.orchestrator.start()
                time.sleep(0.005)
                self.orchestrator.stop()
            elif action == 1:
                # Process crash simulation
                self.orchestrator.start()
                self.session.start_game(pid=5000 + cycle).enter_zone("Level_Forest")
                time.sleep(0.005)
                # Terminate game process unexpectedly
                self.session.mock_proc.terminate()
                self.orchestrator.step_update()
                self.orchestrator.stop()
            elif action == 2:
                # Sudden closure of Discord named pipe / socket
                self.orchestrator.start()
                with contextlib.suppress(Exception):
                    self.ipc_client.close()
                time.sleep(0.005)
                self.orchestrator.stop()
            elif action == 3:
                # Simulated clock jumps
                self.clock.advance(float(random.randint(1, 100)))
                self.clock.simulate_ntp_jump(float(random.choice([-100, 100])))
                self.orchestrator.start()
                self.session.start_game(pid=6000 + cycle).trigger_combat("Duollistes")
                self.orchestrator.step_update()
                self.orchestrator.stop()
            else:
                # Tray interaction under active session
                self.orchestrator.start()
                self.session.start_game(pid=7000 + cycle).enter_zone("Level_Main_OldLumiere")
                self.orchestrator.step_update()
                # Inspect tray labels
                _ = self.tray_harness.get_labels()
                self.orchestrator.stop()

    def assert_no_orphaned_threads(
        self, initial_threads: set[threading.Thread] | None = None
    ) -> None:
        """Asserts that no background threads spawned by this harness or orchestrator remain active."""
        if self.orchestrator.running:
            self.orchestrator.stop()

        # Wait up to 3.0 seconds for worker threads to terminate
        deadline = time.monotonic() + 3.0
        new_active: list[threading.Thread] = []
        while time.monotonic() < deadline:
            active_threads = [
                t
                for t in threading.enumerate()
                if t.is_alive() and t is not threading.current_thread()
            ]
            if initial_threads is not None:
                new_active = [t for t in active_threads if t not in initial_threads]
            else:
                target_thread_names = (
                    "OrchestratorWorkerThread",
                    "BridgeAutoInstallerThread",
                    "TrayToggleBridgeWorker",
                    "TrayInstallBridgeWorker",
                    "AppUpdaterWorkerThread",
                )
                new_active = [
                    t
                    for t in active_threads
                    if any(target in t.name for target in target_thread_names)
                ]
            if not new_active:
                return
            time.sleep(0.02)

        remaining_names = [t.name for t in new_active]
        raise AssertionError(
            f"Orphaned threads detected after orchestrator.stop(): {remaining_names}"
        )

    def close(self) -> None:
        """Tears down all chaos harness resources cleanly."""
        with contextlib.suppress(Exception):
            self.orchestrator.stop()
        with contextlib.suppress(Exception):
            self.server.stop()
        with contextlib.suppress(Exception):
            self.session.cleanup()
        if self._temp_dir_obj is not None:
            with contextlib.suppress(Exception):
                self._temp_dir_obj.cleanup()

    def __enter__(self) -> OrchestratorChaosHarness:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
