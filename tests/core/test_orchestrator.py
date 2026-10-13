"""Unit tests for AppOrchestrator coordination of telemetry, presence, updates, and OS state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.harness import DiscordPipeSimulator
from tests.harness.game_session import GameSessionSimulator

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import BridgeStateProvider, GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import DiscordIPCClient, DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState


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
def test_orchestrator_auto_install_bridge_on_process_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=1234,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    bridge_state = {"installed": False}
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_):
        bridge_state["installed"] = True
        return True, "Success"

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=True,
        sync_startup=False,
    )
    # Bridge is not installed prior to game detection event
    assert orchestrator.bridge_auto_installed is False
    assert bridge_state["installed"] is False
    assert orchestrator.is_bridge_installed() is False

    # Process detection event triggers auto installation
    orchestrator.step_update()
    assert orchestrator.bridge_auto_installed is True
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_event_driven_bridge_check_eliminates_parasitic_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    bridge_state = {"installed": False}
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_):
        bridge_state["installed"] = True
        return True, "Success"

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=True,
        sync_startup=False,
    )

    # Tick 1: First time PID 4242 detected -> triggers check and auto installation
    orchestrator.step_update()
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True

    # Ticks 2..10: Same PID 4242 is running -> cached state in-memory without probing
    bridge_state["installed"] = False
    for _ in range(9):
        st = orchestrator.step_update()
        assert st is not None
        assert st.is_running is True

    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_event_driven_bridge_check_triggers_on_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that bridge check re-triggers when game process stops and restarts, or when PID/start_time changes."""
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    bridge_state = {"installed": True}
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
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
    bridge_state["installed"] = False
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is True

    # 3. Game closes
    mock_detector.get_game_state.return_value = GameState(is_running=False)
    orchestrator.step_update()

    # 4. Game restarts with new PID 2002 -> re-checks observable status
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=2002, start_time=600.0
    )
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is False

    # 5. Fast restart: PID reused but start_time changed without intermediate stopped tick -> re-checks
    bridge_state["installed"] = True
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, process_pid=2002, start_time=700.0
    )
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_step_update_respects_cooldown_before_bridge_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that bridge check is NOT attempted on every tick when backoff cooldown is active."""
    current_time = 1000.0

    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=1234,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    bridge_state: dict[str, Any] = {
        "installed": False,
        "install_result": (False, "Failed install"),
    }
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_: Any) -> tuple[bool, str]:
        success, msg = bridge_state["install_result"]
        if success:
            bridge_state["installed"] = True
        return success, msg

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=True,
        sync_startup=False,
        time_provider=lambda: current_time,
    )

    # First attempt fails at t = 1000.0, backoff cooldown activated
    orchestrator.step_update()
    assert orchestrator.is_bridge_installed() is False

    # Second tick with new process at t = 1010.0 (within cooldown 60.0s)
    # If the installer were improperly invoked, it would succeed now:
    current_time = 1010.0
    bridge_state["install_result"] = (True, "Installed")
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=5678,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    orchestrator.step_update()
    # Throttled by cooldown - install is NOT re-attempted, status remains False
    assert orchestrator.is_bridge_installed() is False

    # Third tick after cooldown expires at t = 1070.0
    current_time = 1070.0
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True,
        process_pid=9999,
        win64_dir=Path("/mock/game/win64"),
        exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
    )
    orchestrator.step_update()
    # Now allowed - installation succeeds and status reflects True
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_backoff_and_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    bridge_state: dict[str, Any] = {
        "installed": False,
        "install_result": (False, "Permission denied: access denied to Program Files"),
    }
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_: Any) -> tuple[bool, str]:
        success, msg = bridge_state["install_result"]
        if success:
            bridge_state["installed"] = True
        return success, msg

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. First attempt fails at t = 1000.0
    res1 = orchestrator.check_and_auto_install_bridge(now=1000.0)
    assert res1 is False
    assert orchestrator.bridge_auto_installed is False
    assert bridge_state["installed"] is False
    assert orchestrator.is_bridge_installed() is False

    # 2. Immediate next attempt at t = 1002.0 (2 seconds later, polling tick)
    # Should be throttled by cooldown and NOT attempt re-extracting
    res2 = orchestrator.check_and_auto_install_bridge(now=1002.0)
    assert res2 is False
    assert orchestrator.bridge_auto_installed is False
    assert bridge_state["installed"] is False

    # 3. Intermediate attempt at t = 1050.0 (still within first backoff window)
    res_mid = orchestrator.check_and_auto_install_bridge(now=1050.0)
    assert res_mid is False

    # 4. Next attempt after first cooldown expires at t = 1065.0
    # Fails again, cooldown doubles
    res3 = orchestrator.check_and_auto_install_bridge(now=1065.0)
    assert res3 is False
    assert orchestrator.bridge_auto_installed is False

    # 5. Intermediate attempt at t = 1120.0 (within doubled cooldown window)
    res_doubled_mid = orchestrator.check_and_auto_install_bridge(now=1120.0)
    assert res_doubled_mid is False

    # 6. Now simulate permission resolved at t = 1190.0 (past doubled cooldown)
    bridge_state["install_result"] = (True, "Installed successfully")
    res4 = orchestrator.check_and_auto_install_bridge(now=1190.0)
    assert res4 is True
    assert orchestrator.bridge_auto_installed is True
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_early_boot_and_preinstalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    bridge_state: dict[str, Any] = {
        "installed": True,
        "install_result": (True, "Installed"),
    }
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
        lambda **_: "/mock/game/win64",
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_: Any) -> tuple[bool, str]:
        success, msg = bridge_state["install_result"]
        if success:
            bridge_state["installed"] = True
        return success, msg

    def fake_uninstall(*_: Any) -> tuple[bool, str]:
        bridge_state["installed"] = False
        return True, "Uninstalled"

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.uninstall_bridge",
        fake_uninstall,
    )

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. Early monotonic boot timestamp (now=0.5) must NOT be throttled by initial cooldown
    res = orchestrator.check_and_auto_install_bridge(now=0.5)
    assert res is True
    assert orchestrator.bridge_auto_installed is True
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True

    # 2. toggle_bridge uninstalls bridge and is immediately re-togglable without throttling
    toggle_res = orchestrator.toggle_bridge()
    assert toggle_res is False
    assert orchestrator.bridge_auto_installed is False
    assert bridge_state["installed"] is False
    assert orchestrator.is_bridge_installed() is False

    bridge_state["install_result"] = (True, "Installed")
    toggle_res2 = orchestrator.toggle_bridge()
    assert toggle_res2 is True
    assert orchestrator.bridge_auto_installed is True
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True


@pytest.mark.unit
def test_orchestrator_os_status_queries_and_toggles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SettingsService(custom_path=tmp_path / "settings.json")
    pipe = DiscordPipeSimulator()
    client = DiscordIPCClient(client_id="test", transport=pipe)
    rpc = DiscordRPCManager(client=client)

    bridge_state = {"installed": False}
    startup_state = {"enabled": True}

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
        lambda *_: bridge_state["installed"],
    )

    def fake_install(*_: Any) -> tuple[bool, str]:
        bridge_state["installed"] = True
        return True, "Installed"

    def fake_uninstall(*_: Any) -> tuple[bool, str]:
        bridge_state["installed"] = False
        return True, "Uninstalled"

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        fake_install,
    )
    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.uninstall_bridge",
        fake_uninstall,
    )

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.startup.is_startup_enabled",
        lambda: startup_state["enabled"],
    )

    def fake_toggle_startup() -> bool:
        startup_state["enabled"] = not startup_state["enabled"]
        return startup_state["enabled"]

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.startup.toggle_startup",
        fake_toggle_startup,
    )

    orchestrator = AppOrchestrator(
        settings_service=settings,
        rpc_manager=rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    # 1. Bridge
    assert orchestrator.is_bridge_installed() is False
    res1 = orchestrator.toggle_bridge()
    assert res1 is True
    assert bridge_state["installed"] is True
    assert orchestrator.is_bridge_installed() is True

    res2 = orchestrator.toggle_bridge()
    assert res2 is False
    assert bridge_state["installed"] is False
    assert orchestrator.is_bridge_installed() is False

    # 2. Startup
    assert orchestrator.is_startup_enabled() is True
    res_startup = orchestrator.toggle_startup()
    assert res_startup is False
    assert startup_state["enabled"] is False
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
def test_orchestrator_install_bridge_to_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verifies that install_bridge_to sets internal state and cooldown on successful installation."""
    target_folder = tmp_path / "game_win64"
    target_folder.mkdir()

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        lambda folder: (True, f"Installed to {folder}"),
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )
    # Simulate elevated cooldown from previous backoff
    orchestrator.bridge_install_cooldown = orchestrator.bridge_install_max_cooldown

    # Test with Path
    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is True
    assert "Installed to" in msg
    assert orchestrator.bridge_auto_installed is True
    assert orchestrator._bridge_installed is True
    assert orchestrator.is_bridge_installed() is True
    assert orchestrator.bridge_install_cooldown == orchestrator.bridge_install_min_cooldown

    # Test with string path as well
    success_str, msg_str = orchestrator.install_bridge_to(str(target_folder))
    assert success_str is True
    assert "Installed to" in msg_str


@pytest.mark.unit
def test_orchestrator_install_bridge_to_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verifies that install_bridge_to leaves bridge flags False when installation fails."""
    target_folder = tmp_path / "game_win64"

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        lambda _folder: (False, "Permission denied"),
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )
    initial_cooldown = 60.0
    orchestrator.bridge_install_cooldown = initial_cooldown

    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is False
    assert msg == "Permission denied"
    assert orchestrator.bridge_auto_installed is False
    assert orchestrator._bridge_installed is False
    assert orchestrator.is_bridge_installed() is False
    assert orchestrator.bridge_install_cooldown == initial_cooldown


@pytest.mark.unit
def test_orchestrator_install_bridge_to_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verifies that install_bridge_to catches unexpected installer exceptions cleanly without raising."""
    target_folder = tmp_path / "game_win64"

    def raise_err(_folder: Any) -> tuple[bool, str]:
        raise OSError("Access is denied or disk is full")

    monkeypatch.setattr(
        "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        raise_err,
    )

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )
    initial_cooldown = 45.0
    orchestrator.bridge_install_cooldown = initial_cooldown

    success, msg = orchestrator.install_bridge_to(target_folder)

    assert success is False
    assert "Access is denied or disk is full" in msg
    assert orchestrator.bridge_auto_installed is False
    assert orchestrator._bridge_installed is False
    assert orchestrator.is_bridge_installed() is False
    assert orchestrator.bridge_install_cooldown == initial_cooldown


@pytest.mark.unit
def test_orchestrator_unsubscribe_update_available() -> None:
    """Verifies that unsubscribing an update callback prevents it from receiving future notifications."""
    received_updates_1: list[UpdateInfo] = []
    received_updates_2: list[UpdateInfo] = []

    def callback_1(info: UpdateInfo) -> None:
        received_updates_1.append(info)

    def callback_2(info: UpdateInfo) -> None:
        received_updates_2.append(info)

    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )

    orchestrator.subscribe_update_available(callback_1)
    orchestrator.subscribe_update_available(callback_2)

    # Calling with None should be a safe no-op
    orchestrator.on_update_check_complete(None)
    assert len(received_updates_1) == 0
    assert len(received_updates_2) == 0

    update_v1 = UpdateInfo(tag_name="v1.0.0", version_tuple=(1, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v1)

    assert len(received_updates_1) == 1
    assert received_updates_1[0].tag_name == "v1.0.0"
    assert len(received_updates_2) == 1
    assert received_updates_2[0].tag_name == "v1.0.0"

    # Unsubscribe callback_1
    orchestrator.unsubscribe_update_available(callback_1)

    update_v2 = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v2)

    # callback_1 should not receive the subsequent update
    assert len(received_updates_1) == 1
    # callback_2 should receive both updates
    assert len(received_updates_2) == 2
    assert received_updates_2[1].tag_name == "v2.0.0"

    # Unsubscribing a non-registered callback is safe and does not raise
    orchestrator.unsubscribe_update_available(callback_1)


@pytest.mark.unit
def test_orchestrator_update_available_reentrant_and_error_resilience() -> None:
    """Verifies re-entrant unsubscription and error resilience across multiple update listeners."""
    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(spec=DiscordRPCManager),
        auto_install_bridge=False,
        sync_startup=False,
    )

    call_order: list[str] = []

    def self_unsubscribing_cb(info: UpdateInfo) -> None:
        call_order.append(f"unsub_cb:{info.tag_name}")
        orchestrator.unsubscribe_update_available(self_unsubscribing_cb)

    def failing_cb(info: UpdateInfo) -> None:
        call_order.append(f"fail_cb:{info.tag_name}")
        raise RuntimeError("Subscriber explosion")

    def stable_cb(info: UpdateInfo) -> None:
        call_order.append(f"stable_cb:{info.tag_name}")

    orchestrator.subscribe_update_available(self_unsubscribing_cb)
    orchestrator.subscribe_update_available(failing_cb)
    orchestrator.subscribe_update_available(stable_cb)

    update_v1 = UpdateInfo(tag_name="v1.0.0", version_tuple=(1, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v1)

    assert "unsub_cb:v1.0.0" in call_order
    assert "fail_cb:v1.0.0" in call_order
    assert "stable_cb:v1.0.0" in call_order

    call_order.clear()
    update_v2 = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="https://...")
    orchestrator.on_update_check_complete(update_v2)

    # self_unsubscribing_cb should not have been called
    assert "unsub_cb:v2.0.0" not in call_order
    # failing_cb still called
    assert "fail_cb:v2.0.0" in call_order
    # stable_cb still called despite failing_cb raising
    assert "stable_cb:v2.0.0" in call_order


@pytest.mark.unit
def test_orchestrator_unsubscribe_state_change() -> None:
    """Verifies that unsubscribing a state change callback removes it cleanly."""
    received_states: list[GameState] = []

    def state_cb(state: GameState, _spoiler: bool) -> None:
        received_states.append(state)

    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(is_running=False)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    orchestrator.subscribe_state_change(state_cb)
    orchestrator.step_update()
    assert len(received_states) == 1

    orchestrator.unsubscribe_state_change(state_cb)
    orchestrator.step_update()
    assert len(received_states) == 1

    # Unsubscribing again is a no-op and safe
    orchestrator.unsubscribe_state_change(state_cb)
