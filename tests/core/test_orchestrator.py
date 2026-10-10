"""Unit tests for AppOrchestrator coordination of telemetry, presence, updates, and OS state."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo


@pytest.mark.unit
def test_orchestrator_initialization_defaults() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )
    assert orchestrator.running is False
    assert isinstance(orchestrator.current_state, GameState)
    assert orchestrator.current_state.is_running is False


@pytest.mark.unit
def test_orchestrator_step_update_coordinates_subsystems() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)
    mock_settings = MagicMock(spec=SettingsService)
    mock_settings.is_anti_spoiler_enabled.return_value = False

    expected_state = GameState.create(
        is_running=True,
        process_pid=1234,
        zone_name="Old Lumiere",
        in_combat=False,
    )
    mock_detector.get_game_state.return_value = expected_state

    state_changed_events: list[tuple[GameState, bool]] = []

    def on_change(state: GameState, anti_spoiler: bool) -> None:
        state_changed_events.append((state, anti_spoiler))

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        settings_service=mock_settings,
        on_state_change=on_change,
        auto_install_bridge=False,
        sync_startup=False,
    )

    result = orchestrator.step_update()

    assert result == expected_state
    assert orchestrator.current_state == expected_state
    mock_rpc.update.assert_called_once_with(expected_state, anti_spoiler=False)
    assert len(state_changed_events) == 1
    assert state_changed_events[0] == (expected_state, False)


@pytest.mark.unit
def test_orchestrator_step_update_error_resilience() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.side_effect = RuntimeError("Telemetry failure")
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    result = orchestrator.step_update()
    assert result is None


@pytest.mark.unit
def test_orchestrator_lifecycle_start_stop() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_updater = MagicMock(spec=AppUpdater)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        updater=mock_updater,
        auto_install_bridge=False,
        sync_startup=False,
        polling_interval=0.01,
    )

    with patch.object(orchestrator, "run_loop"):
        orchestrator.start()
        assert orchestrator.running is True
        assert orchestrator.worker_thread is not None
        mock_updater.check_in_background.assert_called_once()

        # Starting again is idempotent
        orchestrator.start()

    orchestrator.stop()
    assert orchestrator.running is False
    mock_rpc.disconnect.assert_called_once()


@pytest.mark.unit
def test_orchestrator_auto_install_bridge_on_init() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    with (
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
            return_value="/mock/game/win64",
        ) as mock_find,
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
            return_value=False,
        ) as mock_installed,
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
            return_value=(True, "Success"),
        ) as mock_install,
    ):
        orchestrator = AppOrchestrator(
            detector=mock_detector,
            rpc_manager=mock_rpc,
            auto_install_bridge=True,
            sync_startup=False,
        )
        assert orchestrator.bridge_auto_installed is True
        mock_find.assert_called_once()
        mock_installed.assert_called_once_with("/mock/game/win64")
        mock_install.assert_called_once_with("/mock/game/win64")


@pytest.mark.unit
def test_orchestrator_periodic_auto_install_during_step_update() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_detector.get_game_state.return_value = GameState.create(is_running=True)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )
    # Enable flag to test periodic check during step_update
    orchestrator.auto_install_bridge = True
    orchestrator.bridge_auto_installed = False

    with (
        patch.object(
            orchestrator, "check_and_auto_install_bridge", return_value=True
        ) as mock_check,
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
            return_value=False,
        ),
    ):
        orchestrator.step_update()
        mock_check.assert_called_once()


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_backoff_and_cooldown() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    with (
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
            return_value="/mock/game/win64",
        ),
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
            return_value=False,
        ),
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
            return_value=(False, "Permission denied: access denied to Program Files"),
        ) as mock_install,
    ):
        # 1. First attempt fails at t = 1000.0
        res1 = orchestrator.check_and_auto_install_bridge(now=1000.0)
        assert res1 is False
        assert mock_install.call_count == 1
        assert orchestrator.bridge_auto_installed is False
        assert orchestrator.bridge_install_cooldown == 60.0

        # 2. Immediate next attempt at t = 1002.0 (2 seconds later, polling tick)
        # Should be throttled by cooldown and NOT attempt re-extracting
        res2 = orchestrator.check_and_auto_install_bridge(now=1002.0)
        assert res2 is False
        assert mock_install.call_count == 1

        # 3. Next attempt after 60s cooldown expires at t = 1065.0
        # Fails again, cooldown doubles to 120.0s
        res3 = orchestrator.check_and_auto_install_bridge(now=1065.0)
        assert res3 is False
        assert mock_install.call_count == 2
        assert orchestrator.bridge_install_cooldown == 120.0

        # 4. Now simulate permission resolved at t = 1190.0 (past 120s cooldown)
        mock_install.return_value = (True, "Installed successfully")
        res4 = orchestrator.check_and_auto_install_bridge(now=1190.0)
        assert res4 is True
        assert mock_install.call_count == 3
        assert orchestrator.bridge_auto_installed is True
        assert orchestrator.bridge_install_cooldown == 30.0


@pytest.mark.unit
def test_orchestrator_bridge_auto_install_early_boot_and_preinstalled() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    with (
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.find_game_win64_directory",
            return_value="/mock/game/win64",
        ),
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
            return_value=True,
        ) as mock_installed,
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
        ) as mock_install,
    ):
        # 1. Early monotonic boot timestamp (now=0.5) must NOT be throttled by initial cooldown
        res = orchestrator.check_and_auto_install_bridge(now=0.5)
        assert res is True
        assert orchestrator.bridge_auto_installed is True
        mock_installed.assert_called_once_with("/mock/game/win64")
        mock_install.assert_not_called()

        # 2. toggle_bridge resets the attempt timestamp and cooldown
        with patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.uninstall_bridge",
            return_value=(True, "OK"),
        ):
            orchestrator.toggle_bridge()
            assert orchestrator.bridge_auto_installed is False
            assert orchestrator.last_bridge_install_attempt == -float("inf")
            assert orchestrator.bridge_install_cooldown == 30.0


@pytest.mark.unit
def test_orchestrator_os_status_queries_and_toggles() -> None:
    mock_settings = MagicMock(spec=SettingsService)
    mock_settings.toggle_anti_spoiler.return_value = True
    mock_rpc = MagicMock(spec=DiscordRPCManager)

    orchestrator = AppOrchestrator(
        settings_service=mock_settings,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
    )

    with (
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.is_bridge_installed",
            side_effect=[False, False, True, True],
        ),
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.install_bridge",
            return_value=(True, "OK"),
        ) as mock_install,
        patch(
            "expedition33_rpc.core.orchestrator.bridge_installer.uninstall_bridge",
            return_value=(True, "OK"),
        ) as mock_uninstall,
        patch(
            "expedition33_rpc.core.orchestrator.startup.is_startup_enabled",
            return_value=True,
        ),
        patch(
            "expedition33_rpc.core.orchestrator.startup.toggle_startup",
            return_value=False,
        ) as mock_toggle_startup,
    ):
        # 1. Bridge
        assert orchestrator.is_bridge_installed() is False
        res1 = orchestrator.toggle_bridge()
        assert res1 is True
        mock_install.assert_called_once()

        assert orchestrator.is_bridge_installed() is True
        res2 = orchestrator.toggle_bridge()
        assert res2 is False
        mock_uninstall.assert_called_once()

        # 2. Startup
        assert orchestrator.is_startup_enabled() is True
        res_startup = orchestrator.toggle_startup()
        assert res_startup is False
        mock_toggle_startup.assert_called_once()

        # 3. Anti-Spoiler
        res_anti_spoiler = orchestrator.toggle_anti_spoiler()
        assert res_anti_spoiler is True
        mock_settings.toggle_anti_spoiler.assert_called_once()
        mock_rpc.invalidate.assert_called_once()
        mock_rpc.update.assert_called_once()


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
