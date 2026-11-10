"""Unit tests for AppOrchestrator coordination of telemetry, presence, updates, and OS state."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.harness import DiscordPipeSimulator
from tests.harness.game_session import GameSessionSimulator

from expedition33_rpc.core.orchestrator import (
    AppOrchestrator,
    BridgeInstallerProtocol,
    StartupProtocol,
    UpdaterProtocol,
)
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import BridgeStateProvider, GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import DiscordIPCClient, DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState


class FakeBridgeInstaller(BridgeInstallerProtocol):
    """Protocol-compliant fake bridge installer for deterministic unit tests."""

    def __init__(
        self,
        installed: bool = False,
        game_win64_dir: str | None = "/mock/game/win64",
        install_success: bool = True,
        install_msg: str = "Success",
        raise_on_install: Exception | None = None,
    ):
        self.installed = installed
        self.game_win64_dir = game_win64_dir
        self.install_success = install_success
        self.install_msg = install_msg
        self.raise_on_install = raise_on_install
        self.install_call_count = 0

    def find_game_win64_directory(
        self,
        target_process_names: Any = None,
        known_win64_dir: Path | str | None = None,
        known_exe_path: Path | str | None = None,
    ) -> str | None:
        del target_process_names, known_win64_dir, known_exe_path
        return self.game_win64_dir

    def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
        del win64_dir
        return self.installed

    def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        del win64_dir
        self.install_call_count += 1
        if self.raise_on_install:
            raise self.raise_on_install
        if self.install_success:
            self.installed = True
        return self.install_success, self.install_msg

    def uninstall_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
        del win64_dir
        self.installed = False
        return True, "Uninstalled"


class FakeStartupService(StartupProtocol):
    """Protocol-compliant fake Windows startup service for deterministic unit tests."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.synced = False

    def is_startup_enabled(self) -> bool:
        return self.enabled

    def set_startup_enabled(self, enable: bool) -> bool:
        self.enabled = enable
        return True

    def sync_startup_path(self) -> None:
        self.synced = True

    def toggle_startup(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled


@pytest.mark.unit
def test_orchestrator_initialization_defaults(tmp_path: Path) -> None:
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    settings = SettingsService(custom_path=tmp_path / "settings.json")
    detector = GameDetector(bridge_provider=None)

    orchestrator = AppOrchestrator(
        detector=detector,
        rpc_manager=rpc,
        settings_service=settings,
        auto_install_bridge=False,
        sync_startup=False,
    )
    assert orchestrator.running is False
    assert isinstance(orchestrator.current_state, GameState)
    assert orchestrator.current_state.is_running is False


@pytest.mark.unit
def test_orchestrator_sync_startup_on_init() -> None:
    fake_startup = FakeStartupService(enabled=False)
    orchestrator = AppOrchestrator(
        startup_service=fake_startup,
        sync_startup=True,
    )
    assert orchestrator.sync_startup is True
    assert fake_startup.synced is True


@pytest.mark.unit
def test_orchestrator_step_update_coordinates_subsystems(tmp_path: Path) -> None:
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="123456", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    assert rpc.connect() is True
    pipe.outgoing_bytes.clear()

    settings = SettingsService(custom_path=tmp_path / "settings.json")
    state_changed_events: list[tuple[GameState, bool]] = []

    with GameSessionSimulator(base_dir=tmp_path) as session:
        session.start_game(pid=1234).enter_zone("Level_Main_OldLumiere")
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc,
            settings_service=settings,
            on_state_change=lambda st, sp: state_changed_events.append((st, sp)),
            auto_install_bridge=False,
            sync_startup=False,
        )

        result = orchestrator.step_update()

        assert result is not None
        assert result.is_running is True
        assert result.zone_name == "Old Lumière"

        # Assert frame emitted on mock Discord channel
        frame = pipe.pop_last_frame_payload()
        assert frame is not None
        assert frame["cmd"] == "SET_ACTIVITY"
        assert frame["args"]["pid"] == 1234
        assert "Old Lumière" in frame["args"]["activity"]["state"]
        assert frame["args"]["activity"]["details"] == "Exploring"

        # Assert external subscriber notification
        assert len(state_changed_events) == 1
        assert state_changed_events[0][0].zone_name == "Old Lumière"
        assert state_changed_events[0][1] is False


@pytest.mark.unit
def test_orchestrator_subscribe_state_change_and_unsubscribe(tmp_path: Path) -> None:
    settings = SettingsService(custom_path=tmp_path / "settings.json")
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)

    with GameSessionSimulator(base_dir=tmp_path) as session:
        session.start_game(pid=5555).enter_zone("Level_Main_OldLumiere")
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        received_events: list[tuple[GameState, bool]] = []

        def callback(state: GameState, anti_spoiler: bool) -> None:
            received_events.append((state, anti_spoiler))

        unsubscribe = orchestrator.subscribe_state_change(callback)

        # 1. First step: callback receives state
        result = orchestrator.step_update()
        assert result is not None
        assert len(received_events) == 1
        assert received_events[0][0].process_pid == 5555

        # 2. Unsubscribe: callback should not be invoked on subsequent steps
        unsubscribe()
        orchestrator.step_update()
        assert len(received_events) == 1


@pytest.mark.unit
def test_orchestrator_step_update_error_resilience() -> None:
    class FailingProvider(BridgeStateProvider):
        def read_game_data(
            self, min_valid_timestamp: float | None = None, lang: str = "en"
        ) -> None:
            del min_valid_timestamp, lang
            raise RuntimeError("Telemetry failure")

    class FakeProc:
        pid = 1111

        def is_running(self) -> bool:
            return True

        def name(self) -> str:
            return "sandfall-win64-shipping.exe"

        def exe(self) -> str | None:
            return None

        def create_time(self) -> float:
            return 1000.0

    detector = GameDetector(bridge_provider=FailingProvider(), process_scanner=lambda: [FakeProc()])
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)

    orchestrator = AppOrchestrator(
        detector=detector,
        rpc_manager=rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    result = orchestrator.step_update()
    assert result is None


@pytest.mark.unit
def test_orchestrator_lifecycle_start_stop() -> None:
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    assert rpc.connect() is True
    assert rpc.is_connected is True

    mock_updater = MagicMock(spec=AppUpdater)
    orchestrator = AppOrchestrator(
        detector=GameDetector(bridge_provider=None),
        rpc_manager=rpc,
        updater=mock_updater,
        auto_install_bridge=False,
        sync_startup=False,
        polling_interval=0.01,
    )

    orchestrator.start()
    assert orchestrator.running is True
    assert orchestrator.worker_thread is not None
    mock_updater.check_in_background.assert_called_once()

    # Starting again is idempotent
    orchestrator.start()

    orchestrator.stop()
    assert orchestrator.running is False
    if orchestrator.worker_thread is not None:
        orchestrator.worker_thread.join(timeout=1.0)
        assert not orchestrator.worker_thread.is_alive()
    assert rpc.is_connected is False


@pytest.mark.unit
def test_orchestrator_auto_install_bridge_on_process_detection() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=1234,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
    )
    # Bridge is not installed prior to game detection event
    assert fake_installer.installed is False
    assert orchestrator.is_bridge_installed() is False

    # Process detection event triggers auto installation
    orchestrator.step_update()
    deadline = time.monotonic() + 1.0
    while not orchestrator.is_bridge_installed() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True
    orchestrator.stop()


@pytest.mark.unit
def test_orchestrator_event_driven_bridge_check_eliminates_parasitic_io() -> None:
    """Verifies that bridge check runs on initial process detection and NOT on subsequent ticks (no parasitic I/O)."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=4242,
        start_time=1000.0,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
    )

    # Tick 1: First time PID 4242 detected -> triggers check and auto installation
    orchestrator.step_update()
    deadline = time.monotonic() + 1.0
    while not orchestrator.is_bridge_installed() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True
    assert fake_installer.install_call_count == 1

    # Ticks 2..10: Same PID 4242 is running -> cached state in-memory without probing
    fake_installer.installed = False
    for _ in range(9):
        st = orchestrator.step_update()
        assert st is not None
        assert st.is_running is True

    assert orchestrator.is_bridge_installed() is True
    assert fake_installer.install_call_count == 1
    orchestrator.stop()


@pytest.mark.unit
def test_orchestrator_event_driven_bridge_check_triggers_on_process_restart() -> None:
    """Verifies that bridge check re-triggers when game process stops and restarts, or when PID/start_time changes."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=True)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. Process 1001 detected
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=1001, start_time=500.0
    )
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is True

    # 2. Same process running -> cached in-memory without disk probe
    fake_installer.installed = False
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is True

    # 3. Game closes
    mock_detector.get_game_state.return_value = GameState(is_running=False)
    orchestrator.step_update()

    # 4. Game restarts with new PID 2002 -> re-checks observable status
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=2002, process_create_time=600.0, start_time=600.0
    )
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is False

    # 5. Fast restart: PID reused but process_create_time changed without intermediate stopped tick -> re-checks
    fake_installer.installed = True
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=2002, process_create_time=700.0, start_time=700.0
    )
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_eliminates_parasitic_io_on_gameplay_timer_transitions() -> None:
    """Anti-regression test: verifies that gameplay zone/combat transitions changing state.start_time

    do NOT re-trigger bridge installation or filesystem checks. Bridge check runs exactly once per process.
    """
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=False, install_success=True)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
    )

    with patch.object(
        orchestrator,
        "check_and_auto_install_bridge",
        wraps=orchestrator.check_and_auto_install_bridge,
    ) as spy_auto_install:
        # 1. Game launches: PID=4242, process_create_time=1000.0, start_time=1000.0 (exploration)
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=4242,
            process_create_time=1000.0,
            start_time=1000.0,
            zone_name="Ancient Sanctuary",
            in_combat=False,
            win64_dir=Path("/mock/game/win64"),
        )
        orchestrator.step_update()
        deadline = time.monotonic() + 1.0
        while spy_auto_install.call_count == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert spy_auto_install.call_count == 1

        # 2. Zone transition: start_time resets to 1050.0, PID and process_create_time unchanged
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=4242,
            process_create_time=1000.0,
            start_time=1050.0,
            zone_name="Crimson Forest",
            in_combat=False,
            win64_dir=Path("/mock/game/win64"),
        )
        orchestrator.step_update()
        # MUST remain 1 (no parasitic I/O)
        assert spy_auto_install.call_count == 1

        # 3. Enter combat: start_time resets to 1080.0
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=4242,
            process_create_time=1000.0,
            start_time=1080.0,
            zone_name="Crimson Forest",
            in_combat=True,
            enemy_name="Duollistes",
            win64_dir=Path("/mock/game/win64"),
        )
        orchestrator.step_update()
        assert spy_auto_install.call_count == 1

        # 4. Exit combat: start_time adjusted to 1110.0
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=4242,
            process_create_time=1000.0,
            start_time=1110.0,
            zone_name="Crimson Forest",
            in_combat=False,
            win64_dir=Path("/mock/game/win64"),
        )
        orchestrator.step_update()
        assert spy_auto_install.call_count == 1


@pytest.mark.unit
def test_orchestrator_step_update_respects_cooldown_before_bridge_check() -> None:
    """Verifies that bridge check is NOT attempted on every tick when cooldown is active."""
    current_time = 1000.0

    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=1234,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    fake_installer = FakeBridgeInstaller(
        installed=False, install_success=False, install_msg="Failed install"
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
        time_provider=lambda: current_time,
    )

    # First attempt fails at t = 1000.0, backoff cooldown activated
    orchestrator.step_update()
    deadline = time.monotonic() + 1.0
    while fake_installer.install_call_count < 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert orchestrator.is_bridge_installed() is False
    assert fake_installer.install_call_count == 1

    # Second tick with new process at t = 1010.0 (within cooldown 30.0s)
    current_time = 1010.0
    fake_installer.install_success = True
    fake_installer.install_msg = "Installed"
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=5678,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    orchestrator.step_update()
    time.sleep(0.05)
    # Throttled by cooldown - install is NOT re-attempted, call count remains 1
    assert orchestrator.is_bridge_installed() is False
    assert fake_installer.install_call_count == 1

    # Third tick after cooldown expires at t = 1035.0 (35s > 30s)
    current_time = 1035.0
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=9999,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    orchestrator.step_update()
    deadline = time.monotonic() + 1.0
    while fake_installer.install_call_count < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    # Now allowed - installation succeeds and status reflects True
    assert orchestrator.is_bridge_installed() is True
    assert fake_installer.install_call_count == 2
    orchestrator.stop()


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_deterministic_cooldown() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    fake_installer = FakeBridgeInstaller(
        installed=False,
        install_success=False,
        install_msg="Permission denied: access denied to Program Files",
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. First attempt fails at t = 1000.0
    res1 = orchestrator.check_and_auto_install_bridge(now=1000.0)
    assert res1 is False
    assert fake_installer.installed is False
    assert orchestrator.is_bridge_installed() is False
    assert fake_installer.install_call_count == 1

    # 2. Immediate next attempt at t = 1002.0 (2 seconds later)
    # Should be throttled by deterministic cooldown (30s)
    res2 = orchestrator.check_and_auto_install_bridge(now=1002.0)
    assert res2 is False
    assert fake_installer.install_call_count == 1

    # 3. Intermediate attempt at t = 1025.0 (still within cooldown window)
    res_mid = orchestrator.check_and_auto_install_bridge(now=1025.0)
    assert res_mid is False
    assert fake_installer.install_call_count == 1

    # 4. Attempt after cooldown expires at t = 1035.0
    fake_installer.install_success = True
    fake_installer.install_msg = "Installed successfully"
    res4 = orchestrator.check_and_auto_install_bridge(now=1035.0)
    assert res4 is True
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True
    assert fake_installer.install_call_count == 2


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_early_boot_and_preinstalled() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    fake_installer = FakeBridgeInstaller(
        installed=True,
        install_success=True,
        install_msg="Installed",
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. Early monotonic boot timestamp (now=0.5) must NOT be throttled by initial cooldown
    res = orchestrator.check_and_auto_install_bridge(now=0.5)
    assert res is True
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True

    # 2. toggle_bridge uninstalls bridge and is immediately re-togglable without throttling
    toggle_res = orchestrator.toggle_bridge()
    assert toggle_res is False
    assert fake_installer.installed is False
    assert orchestrator.is_bridge_installed() is False

    fake_installer.install_success = True
    toggle_res2 = orchestrator.toggle_bridge()
    assert toggle_res2 is True
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_os_status_queries_and_toggles(tmp_path: Path) -> None:
    settings = SettingsService(custom_path=tmp_path / "settings.json")
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)

    fake_installer = FakeBridgeInstaller(installed=False)
    fake_startup = FakeStartupService(enabled=True)

    orchestrator = AppOrchestrator(
        settings_service=settings,
        rpc_manager=rpc,
        bridge_installer=fake_installer,
        startup_service=fake_startup,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. Bridge
    assert orchestrator.is_bridge_installed() is False
    res1 = orchestrator.toggle_bridge()
    assert res1 is True
    assert fake_installer.installed is True
    assert orchestrator.is_bridge_installed() is True

    res2 = orchestrator.toggle_bridge()
    assert res2 is False
    assert fake_installer.installed is False
    assert orchestrator.is_bridge_installed() is False

    # 2. Startup
    assert orchestrator.is_startup_enabled() is True
    res_startup = orchestrator.toggle_startup()
    assert res_startup is False
    assert fake_startup.enabled is False
    assert orchestrator.is_startup_enabled() is False

    # 3. Anti-Spoiler persisted to disk and invalidating presence
    assert orchestrator.is_anti_spoiler_enabled() is False
    res_anti_spoiler = orchestrator.toggle_anti_spoiler()
    assert res_anti_spoiler is True
    assert orchestrator.is_anti_spoiler_enabled() is True
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["anti_spoiler"] is True
    assert rpc.last_update_state is None  # Fingerprint invalidated

    res_off = orchestrator.toggle_anti_spoiler()
    assert res_off is False
    assert orchestrator.is_anti_spoiler_enabled() is False
    saved_off = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved_off["anti_spoiler"] is False


@pytest.mark.unit
def test_orchestrator_session_simulator_telemetry_flow(tmp_path: Path) -> None:
    """Verifies observable telemetry state propagation and wire-level presence frames using GameSessionSimulator."""
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="test_flow", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    assert rpc.connect() is True
    pipe.outgoing_bytes.clear()

    settings = SettingsService(custom_path=tmp_path / "settings.json")

    with GameSessionSimulator(base_dir=tmp_path) as session:
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        observed_states: list[GameState] = []
        orchestrator.on_state_change = lambda st, _spoiler: observed_states.append(st)

        # 1. Game not running
        st1 = orchestrator.step_update()
        assert st1 is not None and st1.is_running is False
        assert len(observed_states) == 1
        assert observed_states[-1].is_running is False
        pipe.outgoing_bytes.clear()

        # 2. Launch game and explore Old Lumiere
        session.start_game(pid=8888).enter_zone("Level_Main_OldLumiere", checkpoint="Entrance")
        st2 = orchestrator.step_update()
        assert st2 is not None and st2.is_running is True
        assert st2.zone_name == "Old Lumière"
        assert st2.checkpoint_name == "Entrance"
        assert len(observed_states) == 2

        frame_explore = pipe.pop_last_frame_payload()
        assert frame_explore is not None
        assert frame_explore["cmd"] == "SET_ACTIVITY"
        assert frame_explore["args"]["pid"] == 8888
        assert frame_explore["args"]["activity"]["details"] == "Exploring"
        assert "Old Lumière" in frame_explore["args"]["activity"]["state"]

        # 3. Trigger combat
        session.trigger_combat("Duollistes")
        st3 = orchestrator.step_update()
        assert st3 is not None and st3.in_combat is True
        assert st3.enemy_name == "Duollistes"
        assert len(observed_states) == 3

        frame_combat = pipe.pop_last_frame_payload()
        assert frame_combat is not None
        assert frame_combat["args"]["activity"]["details"] == "Fighting: Duollistes"

        # 4. Leave combat
        session.leave_combat()
        st4 = orchestrator.step_update()
        assert st4 is not None and st4.in_combat is False

        frame_peace = pipe.pop_last_frame_payload()
        assert frame_peace is not None
        assert frame_peace["args"]["activity"]["details"] == "Exploring"

        # 5. Stop game
        session.stop_game()
        st5 = orchestrator.step_update()
        assert st5 is not None and st5.is_running is False

        frame_stopped = pipe.pop_last_frame_payload()
        assert frame_stopped is not None
        assert frame_stopped["args"]["activity"] is None


@pytest.mark.unit
def test_orchestrator_update_notification_callback() -> None:
    update_notifications: list[UpdateInfo] = []

    def on_update(info: UpdateInfo) -> None:
        update_notifications.append(info)

    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        on_update_available=on_update,
        auto_install_bridge=False,
        sync_startup=False,
    )

    sample_info = UpdateInfo(
        tag_name="v1.7.0",
        version_tuple=(1, 7, 0),
        html_url="https://github.com/...",
    )

    orchestrator.on_update_check_complete(sample_info)
    assert len(update_notifications) == 1
    assert update_notifications[0].tag_name == "v1.7.0"

    # None update does not invoke callback
    orchestrator.on_update_check_complete(None)
    assert len(update_notifications) == 1


@pytest.mark.unit
def test_orchestrator_callbacks_dispatch(tmp_path: Path) -> None:
    """Verifies that direct callbacks are invoked upon state change and update events."""
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="test_sub", transport=pipe)
    rpc = DiscordRPCManager(client=client)

    with GameSessionSimulator(base_dir=tmp_path) as session:
        session.start_game().enter_zone("Level_Main_OldLumiere")
        orchestrator = AppOrchestrator(
            detector=session.detector,
            rpc_manager=rpc,
            auto_install_bridge=False,
            sync_startup=False,
        )

        state_calls: list[tuple[GameState, bool]] = []
        update_calls: list[UpdateInfo] = []

        orchestrator.on_state_change = lambda st, sp: state_calls.append((st, sp))
        orchestrator.on_update_available = lambda info: update_calls.append(info)

        st = orchestrator.step_update()
        assert st is not None
        assert len(state_calls) == 1
        assert state_calls[0][0].zone_name == "Old Lumière"

        sample_info = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="")
        orchestrator.on_update_check_complete(sample_info)
        assert len(update_calls) == 1
        assert update_calls[0].tag_name == "v2.0.0"


@pytest.mark.unit
def test_orchestrator_facade_methods(tmp_path: Path) -> None:
    """Verifies that AppOrchestrator exposes Demeter-compliant facade queries and actions."""
    pipe = DiscordPipeSimulator(auto_respond_set_activity=True)
    client = DiscordIPCClient(client_id="facade_test", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    assert rpc.connect() is True

    settings = SettingsService(custom_path=tmp_path / "settings.json")
    settings.set_anti_spoiler_enabled(True)

    mock_updater = MagicMock(spec=AppUpdater)
    mock_updater.get_status_text.return_value = "Update: Available (v2.0.0)"
    mock_updater.state = UpdateState.AVAILABLE

    orchestrator = AppOrchestrator(
        detector=GameDetector(bridge_provider=None),
        rpc_manager=rpc,
        settings_service=settings,
        updater=mock_updater,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. State queries
    assert orchestrator.is_rpc_connected() is True
    assert orchestrator.is_anti_spoiler_enabled() is True
    assert orchestrator.get_updater_status_text() == "Update: Available (v2.0.0)"
    assert orchestrator.is_update_available() is True

    # 2. Update action when AVAILABLE
    orchestrator.trigger_update_action()
    mock_updater.open_release_page.assert_called_once()
    mock_updater.check_in_background.assert_not_called()

    # 3. Update action when UP_TO_DATE
    mock_updater.open_release_page.reset_mock()
    mock_updater.state = UpdateState.UP_TO_DATE
    assert orchestrator.is_update_available() is False
    orchestrator.trigger_update_action()
    mock_updater.open_release_page.assert_not_called()
    mock_updater.check_in_background.assert_called_once_with(
        delay_seconds=0.0, on_complete=orchestrator.on_update_check_complete
    )


@pytest.mark.unit
def test_orchestrator_install_bridge_to_success(tmp_path: Path) -> None:
    """Verifies that install_bridge_to updates internal state on successful installation."""
    target_folder = tmp_path / "game_win64"
    target_folder.mkdir()

    fake_installer = FakeBridgeInstaller(
        installed=False, install_success=True, install_msg=f"Installed to {target_folder}"
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # Test with Path
    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is True
    assert "Installed to" in msg
    assert orchestrator.is_bridge_installed() is True

    # Test with string path as well
    success_str, msg_str = orchestrator.install_bridge_to(str(target_folder))
    assert success_str is True
    assert "Installed to" in msg_str


@pytest.mark.unit
def test_orchestrator_install_bridge_to_failure(tmp_path: Path) -> None:
    """Verifies that install_bridge_to leaves bridge flags False when installation fails."""
    target_folder = tmp_path / "game_win64"

    fake_installer = FakeBridgeInstaller(
        installed=False, install_success=False, install_msg="Permission denied"
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is False
    assert msg == "Permission denied"
    assert orchestrator.is_bridge_installed() is False


@pytest.mark.unit
def test_orchestrator_install_bridge_to_exception(tmp_path: Path) -> None:
    """Verifies that install_bridge_to catches unexpected installer exceptions cleanly without raising."""
    target_folder = tmp_path / "game_win64"

    fake_installer = FakeBridgeInstaller(
        installed=False, raise_on_install=OSError("Access is denied or disk is full")
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is False
    assert "Access is denied or disk is full" in msg
    assert orchestrator.is_bridge_installed() is False


@pytest.mark.unit
def test_orchestrator_update_available_callback() -> None:
    """Verifies that on_update_available callback receives update notifications."""
    received_updates: list[UpdateInfo] = []

    def callback(info: UpdateInfo) -> None:
        received_updates.append(info)

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        on_update_available=callback,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # Calling with None should be a safe no-op
    orchestrator.on_update_check_complete(None)
    assert len(received_updates) == 0

    update_v1 = UpdateInfo(tag_name="v1.0.0", version_tuple=(1, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v1)

    assert len(received_updates) == 1
    assert received_updates[0].tag_name == "v1.0.0"

    # Unsetting callback stops notifications
    orchestrator.on_update_available = None

    update_v2 = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v2)

    assert len(received_updates) == 1


@pytest.mark.unit
def test_orchestrator_update_available_error_resilience() -> None:
    """Verifies unhandled exceptions in on_update_available callback are handled safely."""
    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )

    def failing_cb(info: UpdateInfo) -> None:
        del info
        raise RuntimeError("Subscriber explosion")

    orchestrator.on_update_available = failing_cb

    update_v1 = UpdateInfo(tag_name="v1.0.0", version_tuple=(1, 0, 0), html_url="https://...")
    # Does not raise even if callback fails
    orchestrator.on_update_check_complete(update_v1)


@pytest.mark.unit
def test_orchestrator_subscribe_update_available() -> None:
    """Verifies that subscribe_update_available registers listeners and unsubscribe works."""
    received_updates: list[UpdateInfo] = []
    subscriber_updates: list[UpdateInfo] = []

    def legacy_cb(info: UpdateInfo) -> None:
        received_updates.append(info)

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        on_update_available=legacy_cb,
        auto_install_bridge=False,
        sync_startup=False,
    )

    def sub_cb(info: UpdateInfo) -> None:
        subscriber_updates.append(info)

    def failing_sub(info: UpdateInfo) -> None:
        del info
        raise RuntimeError("Failing sub")

    unsub = orchestrator.subscribe_update_available(sub_cb)
    orchestrator.subscribe_update_available(failing_sub)

    update_v1 = UpdateInfo(tag_name="v1.0.0", version_tuple=(1, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v1)

    assert len(received_updates) == 1
    assert len(subscriber_updates) == 1
    assert subscriber_updates[0] == update_v1

    # Unsubscribe sub_cb
    unsub()
    update_v2 = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v2)

    assert len(received_updates) == 2
    assert len(subscriber_updates) == 1


@pytest.mark.unit
def test_orchestrator_state_change_callback_error_resilience() -> None:
    """Verifies that an unhandled exception in on_state_change callback does not crash step_update."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(is_running=False)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    def exploding_callback(state: GameState, anti_spoiler: bool) -> None:
        del state, anti_spoiler
        raise RuntimeError("Callback crashed")

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        on_state_change=exploding_callback,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # step_update must handle the callback exception gracefully and return the valid state
    st = orchestrator.step_update()
    assert st is not None
    assert st.is_running is False


@pytest.mark.unit
def test_orchestrator_status_snapshot() -> None:
    """Verifies get_status_snapshot black-box inspection of subsystem states."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(is_running=False)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    mock_rpc.is_connected = True

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    snapshot = orchestrator.get_status_snapshot()
    assert isinstance(snapshot, dict)
    assert snapshot["running"] is False
    assert snapshot["rpc_connected"] is True
    assert snapshot["anti_spoiler"] is False
    assert isinstance(snapshot["game_state"], GameState)
    assert "bridge_installed" in snapshot
    assert "startup_enabled" in snapshot
    assert "update_available" in snapshot
    assert "updater_status" in snapshot


@pytest.mark.unit
def test_orchestrator_run_loop_adaptive_idle_backoff() -> None:
    """Verifies that orchestrator uses idle_polling_interval when game is idle and polling_interval when running."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    # 1. Idle state: game is not running
    mock_detector.get_game_state.return_value = GameState.create(is_running=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        polling_interval=2.0,
        idle_polling_interval=7.0,
        auto_install_bridge=False,
        sync_startup=False,
    )

    orchestrator.step_update()
    assert orchestrator.current_polling_interval == 7.0

    # 2. Active state: game is running with PID
    mock_detector.get_game_state.return_value = GameState.create(is_running=True, process_pid=9999)
    orchestrator.step_update()
    assert orchestrator.current_polling_interval == 2.0


@pytest.mark.unit
def test_orchestrator_async_bridge_install_spawns_daemon_thread_and_prevents_concurrency() -> None:
    """Verifies that auto-install runs asynchronously in a daemon thread and does not spawn concurrent threads."""
    started_event = threading.Event()
    continue_event = threading.Event()

    class BlockingInstaller(FakeBridgeInstaller):
        def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            del win64_dir
            self.install_call_count += 1
            started_event.set()
            continue_event.wait(timeout=2.0)
            self.installed = True
            return True, "Installed asynchronously"

    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    installer = BlockingInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=installer,
        auto_install_bridge=True,
        sync_startup=False,
    )

    # 1. Trigger process detection: must return immediately without blocking
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=5555,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    start_time = time.perf_counter()
    res = orchestrator.step_update()
    step_duration = time.perf_counter() - start_time

    assert res is not None
    assert step_duration < 0.1
    assert started_event.wait(timeout=1.0) is True

    # 2. Re-trigger process detection while installation is still in progress:
    # should NOT spawn an additional thread or invoke install_bridge again
    orchestrator.step_update()
    assert installer.install_call_count == 1

    # 3. Release blocking installer and stop orchestrator cleanly
    continue_event.set()
    orchestrator.stop()

    assert orchestrator.is_bridge_installed() is True
    assert installer.install_call_count == 1


@pytest.mark.unit
def test_orchestrator_async_bridge_install_catches_exception_safely() -> None:
    """Verifies that an unexpected exception in check_and_auto_install_bridge does not crash the process."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
    )

    with patch.object(
        orchestrator,
        "check_and_auto_install_bridge",
        side_effect=RuntimeError("Simulated disk failure"),
    ):
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=7777,
            win64_dir=Path("/mock/game/win64"),
        )
        res = orchestrator.step_update()
        assert res is not None
        orchestrator.stop()
        assert orchestrator.is_bridge_installed() is False


@pytest.mark.unit
def test_orchestrator_stop_waits_for_bridge_install_thread() -> None:
    """Verifies that orchestrator.stop() waits for the active bridge install worker thread to finish."""
    thread_finished = False

    def slow_install(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal thread_finished
        time.sleep(0.05)
        thread_finished = True
        return True

    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    fake_installer = FakeBridgeInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        bridge_installer=fake_installer,
        auto_install_bridge=True,
        sync_startup=False,
    )

    with patch.object(orchestrator, "check_and_auto_install_bridge", side_effect=slow_install):
        mock_detector.get_game_state.return_value = GameState.create(
            is_running=True,
            process_pid=8888,
            win64_dir=Path("/mock/game/win64"),
        )
        orchestrator.step_update()
        assert thread_finished is False

        orchestrator.stop()
        assert thread_finished is True


@pytest.mark.unit
def test_orchestrator_step_with_real_detector(tmp_path: Path) -> None:
    """Verifies that orchestrator functions end-to-end with a real GameDetector instance."""
    real_detector = GameDetector(
        bridge_provider=None,
        process_scanner=lambda: [],
        save_reader=None,
    )
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)
    settings = SettingsService(custom_path=tmp_path / "settings.json")
    fake_installer = FakeBridgeInstaller(installed=False)

    orchestrator = AppOrchestrator(
        detector=real_detector,
        rpc_manager=rpc,
        settings_service=settings,
        bridge_installer=fake_installer,
        auto_install_bridge=False,
        sync_startup=False,
    )

    state = orchestrator.step_update()
    assert state is not None
    assert isinstance(state, GameState)
    assert state.is_running is False
    assert orchestrator.current_state == state


@pytest.mark.unit
def test_orchestrator_callbacks_slot_decoupling_prevents_stale_and_duplicate_invocation() -> None:
    """Verifies that direct callbacks are isolated from subscribers, preventing stale or duplicate invocations."""
    calls_a: list[GameState] = []
    calls_b: list[GameState] = []

    def callback_a(state: GameState, _spoiler: bool) -> None:
        calls_a.append(state)

    def callback_b(state: GameState, _spoiler: bool) -> None:
        calls_b.append(state)

    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(is_running=False)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    # 1. Initialize with callback_a: direct slot must not leak into _state_subscribers
    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        on_state_change=callback_a,
        auto_install_bridge=False,
        sync_startup=False,
    )

    assert orchestrator.on_state_change is callback_a
    assert len(orchestrator._state_subscribers) == 0

    orchestrator.step_update()
    assert len(calls_a) == 1
    assert len(calls_b) == 0

    # 2. Reassigning on_state_change: callback_a is not stale-invoked
    orchestrator.on_state_change = callback_b
    orchestrator.step_update()
    assert len(calls_a) == 1
    assert len(calls_b) == 1

    # 3. Clearing on_state_change: neither callback invoked
    orchestrator.on_state_change = None
    orchestrator.step_update()
    assert len(calls_a) == 1
    assert len(calls_b) == 1

    # 4. Duplicate prevention for state subscribers when registered both ways
    calls_sub: list[GameState] = []

    def callback_sub(state: GameState, _spoiler: bool) -> None:
        calls_sub.append(state)

    orchestrator.subscribe_state_change(callback_sub)
    orchestrator.on_state_change = callback_sub

    orchestrator.step_update()
    assert len(calls_sub) == 1

    # 5. Duplicate prevention for update check subscribers when registered both ways
    update_calls: list[UpdateInfo] = []

    def update_listener(info: UpdateInfo) -> None:
        update_calls.append(info)

    orchestrator.subscribe_update_available(update_listener)
    orchestrator.on_update_available = update_listener

    sample_info = UpdateInfo(tag_name="v3.0.0", version_tuple=(3, 0, 0), html_url="")
    orchestrator.on_update_check_complete(sample_info)
    assert len(update_calls) == 1


# ---------------------------------------------------------------------------
# Stress & Lifecycle Callback Decoupling Tests
# ---------------------------------------------------------------------------


def _create_test_orchestrator(
    on_state_change: Callable[[GameState, bool], None] | None = None,
    on_update_available: Callable[[UpdateInfo], None] | None = None,
) -> tuple[AppOrchestrator, MagicMock]:
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=1234, zone_name="Lumiere"
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        on_state_change=on_state_change,
        on_update_available=on_update_available,
        auto_install_bridge=False,
        sync_startup=False,
    )
    return orchestrator, mock_detector


@pytest.mark.unit
def test_orchestrator_on_state_change_cleared_to_none_prevents_invocation() -> None:
    """Verifies that setting orchestrator.on_state_change = None completely suppresses callback invocations."""
    calls: list[GameState] = []

    def callback(state: GameState, _spoiler: bool) -> None:
        calls.append(state)

    orchestrator, _ = _create_test_orchestrator(on_state_change=callback)

    # Initial tick: callback invoked once
    orchestrator.step_update()
    assert len(calls) == 1

    # Setting on_state_change to None
    orchestrator.on_state_change = None

    # Subsequent ticks: no invocation occurs
    for _ in range(5):
        orchestrator.step_update()
    assert len(calls) == 1


@pytest.mark.unit
def test_orchestrator_on_state_change_repeated_reassignment() -> None:
    """Reassigns on_state_change through multiple distinct callables.

    Guarantees that stale callbacks are NEVER invoked, and only the active callback receives dispatches.
    """
    call_counts: dict[str, int] = {f"cb_{i}": 0 for i in range(10)}

    def make_cb(name: str) -> Callable[[GameState, bool], None]:
        def _cb(state: GameState, _spoiler: bool) -> None:
            del state, _spoiler
            call_counts[name] += 1

        return _cb

    orchestrator, _ = _create_test_orchestrator()

    # Repeatedly assign and execute step_update
    for i in range(10):
        cb_name = f"cb_{i}"
        orchestrator.on_state_change = make_cb(cb_name)

        # Execute 2 ticks per callback
        orchestrator.step_update()
        orchestrator.step_update()

        # Only the current callback should have incremented (by 2)
        assert call_counts[cb_name] == 2
        for other_name, count in call_counts.items():
            if other_name != cb_name:
                assert count == (2 if int(other_name.split("_")[1]) < i else 0)

    # Re-assign back to cb_0
    orchestrator.on_state_change = make_cb("cb_0")
    orchestrator.step_update()
    assert call_counts["cb_0"] == 3
    # Others must not have changed
    for i in range(1, 10):
        assert call_counts[f"cb_{i}"] == 2


@pytest.mark.unit
def test_orchestrator_same_function_dual_registration_invoked_exactly_once() -> None:
    """Verifies that registering the exact same function both via subscribe_state_change

    and as on_state_change results in exactly ONE invocation per step_update().
    Also verifies unsubscription dynamics and clearing.
    """
    call_history: list[int | None] = []

    def shared_callback(state: GameState, _spoiler: bool) -> None:
        call_history.append(state.process_pid)

    orchestrator, _ = _create_test_orchestrator()

    # Register in both slots
    unsubscribe = orchestrator.subscribe_state_change(shared_callback)
    orchestrator.on_state_change = shared_callback

    assert orchestrator.on_state_change is shared_callback
    assert shared_callback in orchestrator._state_subscribers

    # Tick 1: Must be called exactly once despite being in both slots
    orchestrator.step_update()
    assert len(call_history) == 1

    # Tick 2: Still called exactly once
    orchestrator.step_update()
    assert len(call_history) == 2

    # Unsubscribe from subscriber list: callback remains in direct slot on_state_change
    unsubscribe()
    assert shared_callback not in orchestrator._state_subscribers
    assert orchestrator.on_state_change is shared_callback

    # Tick 3: Should STILL be called via on_state_change slot
    orchestrator.step_update()
    assert len(call_history) == 3

    # Now clear direct slot: callback is completely disabled
    orchestrator.on_state_change = None
    orchestrator.step_update()
    assert len(call_history) == 3


@pytest.mark.unit
def test_orchestrator_update_available_decoupling_and_dual_registration() -> None:
    """Verifies slot decoupling, clearing, reassignment, and duplicate suppression

    for update available listeners (on_update_available and subscribe_update_available).
    """
    calls: list[str] = []

    def listener_a(info: UpdateInfo) -> None:
        calls.append(f"A:{info.tag_name}")

    def listener_b(info: UpdateInfo) -> None:
        calls.append(f"B:{info.tag_name}")

    orchestrator, _ = _create_test_orchestrator(on_update_available=listener_a)
    sample_info = UpdateInfo(tag_name="v3.1.0", version_tuple=(3, 1, 0), html_url="")

    # 1. Initial direct callback
    orchestrator.on_update_check_complete(sample_info)
    assert calls == ["A:v3.1.0"]

    # 2. Reassignment to listener_b
    orchestrator.on_update_available = listener_b
    orchestrator.on_update_check_complete(sample_info)
    assert calls == ["A:v3.1.0", "B:v3.1.0"]

    # 3. Dual registration of listener_b
    unsubscribe = orchestrator.subscribe_update_available(listener_b)
    orchestrator.on_update_check_complete(sample_info)
    # listener_b must only be called ONCE in this tick
    assert calls == ["A:v3.1.0", "B:v3.1.0", "B:v3.1.0"]

    # 4. Unsubscribe and clearing
    unsubscribe()
    orchestrator.on_update_available = None
    orchestrator.on_update_check_complete(sample_info)
    # No new calls
    assert calls == ["A:v3.1.0", "B:v3.1.0", "B:v3.1.0"]


@pytest.mark.unit
def test_orchestrator_subscriber_exception_does_not_break_other_subscribers_or_direct_slot() -> (
    None
):
    """Verifies that an unhandled exception in one subscriber does NOT prevent

    other subscribers or on_state_change from being notified.
    """
    received: list[str] = []

    def crashing_sub(state: GameState, _spoiler: bool) -> None:
        del state, _spoiler
        raise RuntimeError("Subscriber crashed intentionally")

    def healthy_sub(state: GameState, _spoiler: bool) -> None:
        del state, _spoiler
        received.append("healthy_sub")

    def direct_slot(state: GameState, _spoiler: bool) -> None:
        del state, _spoiler
        received.append("direct_slot")

    orchestrator, _ = _create_test_orchestrator(on_state_change=direct_slot)
    orchestrator.subscribe_state_change(crashing_sub)
    orchestrator.subscribe_state_change(healthy_sub)

    # Tick execution should catch crashing_sub exception and still call healthy_sub and direct_slot
    state = orchestrator.step_update()
    assert state is not None
    assert received == ["healthy_sub", "direct_slot"]


@pytest.mark.unit
def test_orchestrator_stop_cancels_updater_and_joins_worker_thread() -> None:
    """Verifies that orchestrator.stop() deterministically cancels updater and joins worker thread."""
    worker_started = threading.Event()
    release_worker = threading.Event()

    class FakeUpdater(UpdaterProtocol):
        def __init__(self) -> None:
            self.state = UpdateState.IDLE
            self.available_update: UpdateInfo | None = None
            self.error_message: str | None = None
            self.cancel_called = False
            self._worker_thread: threading.Thread | None = None

        def cancel(self) -> None:
            self.cancel_called = True
            release_worker.set()

        def join(self, timeout: float | None = None) -> None:
            if self._worker_thread is not None:
                self._worker_thread.join(timeout=timeout)

        def check_in_background(
            self,
            delay_seconds: float = 0.0,
            on_complete: Callable[[UpdateInfo | None], None] | None = None,
        ) -> None:
            del delay_seconds, on_complete

            def _run() -> None:
                worker_started.set()
                release_worker.wait(timeout=2.0)

            t = threading.Thread(target=_run, name="FakeUpdaterWorker", daemon=True)
            self._worker_thread = t
            t.start()

        def open_release_page(self) -> bool:
            return True

        def get_status_text(self) -> str:
            return "Fake Updater Status"

    fake_updater = FakeUpdater()
    fake_updater.check_in_background()
    assert worker_started.wait(timeout=1.0) is True

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        updater=fake_updater,
        auto_install_bridge=False,
        sync_startup=False,
    )
    assert fake_updater._worker_thread is not None
    assert fake_updater._worker_thread.is_alive() is True

    # Call stop() on orchestrator
    orchestrator.stop()

    assert fake_updater.cancel_called is True
    # The worker thread must have been joined cleanly
    assert fake_updater._worker_thread.is_alive() is False
