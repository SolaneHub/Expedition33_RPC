"""Unit tests for ExpeditionTrayApp menu creation and interactive action dispatch."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.harness.tray_harness import HeadlessTrayHarness

from expedition33_rpc.core.orchestrator import (
    AppOrchestrator,
    BridgeInstallerProtocol,
    StartupProtocol,
)
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp


@pytest.fixture
def tray_fixture():
    mock_orchestrator = MagicMock(spec=AppOrchestrator)
    mock_orchestrator.current_state = GameState(
        is_running=True,
        process_pid=4242,
        zone_name="Ancient Sanctuary",
        in_combat=False,
    )
    mock_orchestrator.is_anti_spoiler_enabled.return_value = False
    mock_orchestrator.is_rpc_connected.return_value = True
    mock_orchestrator.get_updater_status_text.return_value = "Update: Up to date (v1.6.0)"
    mock_orchestrator.is_update_available.return_value = False
    mock_orchestrator.is_bridge_installed.return_value = False
    mock_orchestrator.is_startup_enabled.return_value = False

    app = ExpeditionTrayApp(orchestrator=mock_orchestrator)
    mock_icon = MagicMock()
    app.icon = mock_icon

    menu = app.create_menu()
    harness = HeadlessTrayHarness(menu=menu, mock_icon=mock_icon)
    return app, mock_orchestrator, harness, mock_icon


@pytest.mark.unit
def test_tray_menu_structure_inspection(tray_fixture) -> None:
    _app, _orchestrator, harness, _icon = tray_fixture

    labels = harness.get_labels()
    assert any("Clair Obscur: Expedition 33 RPC" in lbl for lbl in labels)
    assert any("Game: Running (PID: 4242)" in lbl for lbl in labels)
    assert any("Location: Ancient Sanctuary" in lbl for lbl in labels)
    assert any("Status: Exploring" in lbl for lbl in labels)
    assert any("Discord: Connected" in lbl for lbl in labels)
    assert any("Anti-Spoiler Mode" in lbl for lbl in labels)
    assert any("Combat Bridge" in lbl for lbl in labels)
    assert any("Start with Windows" in lbl for lbl in labels)
    assert any("Update: Up to date" in lbl for lbl in labels)
    assert any("Exit" in lbl for lbl in labels)


@pytest.mark.unit
def test_tray_menu_action_toggle_anti_spoiler(tray_fixture) -> None:
    _app, orchestrator, harness, icon = tray_fixture
    orchestrator.toggle_anti_spoiler.return_value = True

    harness.invoke("Anti-Spoiler Mode")
    orchestrator.toggle_anti_spoiler.assert_called_once()
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_toggle_bridge(tray_fixture) -> None:
    _app, orchestrator, harness, icon = tray_fixture
    orchestrator.toggle_bridge.return_value = True

    harness.invoke("Combat Bridge")
    orchestrator.toggle_bridge.assert_called_once()
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_toggle_startup(tray_fixture) -> None:
    _app, orchestrator, harness, icon = tray_fixture
    orchestrator.toggle_startup.return_value = True

    harness.invoke("Start with Windows")
    orchestrator.toggle_startup.assert_called_once()
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_update_click(tray_fixture) -> None:
    _app, orchestrator, harness, _icon = tray_fixture

    harness.invoke("Update:")
    orchestrator.trigger_update_action.assert_called_once()


@pytest.mark.unit
def test_tray_menu_action_exit(tray_fixture) -> None:
    _app, orchestrator, harness, icon = tray_fixture

    harness.invoke("Exit")
    orchestrator.stop.assert_called_once()
    icon.stop.assert_called_once()


@pytest.mark.unit
def test_tray_menu_action_select_game_folder(tray_fixture) -> None:
    app, orchestrator, harness, icon = tray_fixture
    orchestrator.install_bridge_to.return_value = (True, "Installed")

    with patch.object(app, "_prompt_folder_selection", return_value="C:/CustomGame/Win64"):
        harness.invoke("Select Game Folder...")
        orchestrator.install_bridge_to.assert_called_once_with("C:/CustomGame/Win64")
        icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_actions_responsiveness_benchmark(tmp_path: Path) -> None:
    """Verifies that tray menu rendering and user actions execute within a strict latency budget (<10ms)."""
    settings_path = tmp_path / "settings.json"
    settings_service = SettingsService(settings_path)

    bridge_installer = MagicMock(spec=BridgeInstallerProtocol)
    bridge_installer.install_bridge.return_value = (True, "Installed")
    bridge_installer.uninstall_bridge.return_value = (True, "Uninstalled")
    bridge_installer.is_bridge_installed.return_value = False

    startup_service = MagicMock(spec=StartupProtocol)
    startup_service.is_startup_enabled.return_value = False
    startup_service.toggle_startup.return_value = True

    real_orchestrator = AppOrchestrator(
        settings_service=settings_service,
        detector=GameDetector(bridge_provider=None),
        bridge_installer=bridge_installer,
        startup_service=startup_service,
        auto_install_bridge=False,
        sync_startup=False,
    )

    app = ExpeditionTrayApp(orchestrator=real_orchestrator)
    mock_icon = MagicMock()
    app.icon = mock_icon

    menu = app.create_menu()
    harness = HeadlessTrayHarness(menu=menu, mock_icon=mock_icon)
    bridge_installer.is_bridge_installed.reset_mock()

    # 1. Benchmark menu dynamic label evaluation (must be O(1) in-memory without disk scans)
    t0 = time.perf_counter()
    labels = harness.get_labels()
    menu_eval_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert len(labels) > 0
    assert menu_eval_duration_ms < 10.0, (
        f"Menu evaluation took {menu_eval_duration_ms:.2f}ms (>10ms)"
    )
    assert bridge_installer.is_bridge_installed.call_count == 0

    # 2. Benchmark Anti-Spoiler toggle action
    t0 = time.perf_counter()
    harness.invoke("Anti-Spoiler Mode")
    anti_spoiler_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert anti_spoiler_duration_ms < 10.0, (
        f"Anti-spoiler action took {anti_spoiler_duration_ms:.2f}ms (>10ms)"
    )
    assert real_orchestrator.is_anti_spoiler_enabled() is True

    # 3. Benchmark Combat Bridge toggle action
    t0 = time.perf_counter()
    harness.invoke("Combat Bridge")
    bridge_toggle_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert bridge_toggle_duration_ms < 10.0, (
        f"Bridge toggle action took {bridge_toggle_duration_ms:.2f}ms (>10ms)"
    )
    bridge_installer.install_bridge.assert_called_once()

    # 4. Benchmark Exit action
    t0 = time.perf_counter()
    harness.invoke("Exit")
    exit_duration_ms = (time.perf_counter() - t0) * 1000.0
    assert exit_duration_ms < 10.0, f"Exit action took {exit_duration_ms:.2f}ms (>10ms)"
    assert real_orchestrator.running is False
