"""Unit tests for ExpeditionTrayApp menu creation and interactive action dispatch."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.harness.clock_harness import DualClockHarness
from tests.harness.discord_pipe import DiscordPipeSimulator
from tests.harness.fake_services import (
    FakeBridgeInstaller,
    FakeStartupService,
    FakeUpdater,
)
from tests.harness.tray_harness import HeadlessTrayHarness

from expedition33_rpc.core.orchestrator import (
    AppOrchestrator,
)
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations.discord_rpc import DiscordIPCClient, DiscordRPCManager
from expedition33_rpc.integrations.updater import UpdateState
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp


@pytest.fixture
def tray_fixture(tmp_path: Path):
    settings_service = SettingsService(tmp_path / "settings.json")
    fake_updater = FakeUpdater(state=UpdateState.IDLE)
    fake_bridge = FakeBridgeInstaller(installed=False)
    fake_startup = FakeStartupService(enabled=False)
    pipe_sim = DiscordPipeSimulator()
    ipc_client = DiscordIPCClient(client_id="1234567890")
    ipc_client.transport = pipe_sim
    rpc_manager = DiscordRPCManager(client=ipc_client)

    orchestrator = AppOrchestrator(
        settings_service=settings_service,
        detector=GameDetector(bridge_provider=None),
        rpc_manager=rpc_manager,
        updater=fake_updater,
        bridge_installer=fake_bridge,
        startup_service=fake_startup,
        auto_install_bridge=False,
        sync_startup=False,
    )
    orchestrator.current_state = GameState(
        is_running=True,
        process_pid=4242,
        zone_name="Ancient Sanctuary",
        in_combat=False,
    )

    selected_folder: list[str | None] = ["C:/CustomGame/Win64"]
    app = ExpeditionTrayApp(
        orchestrator=orchestrator,
        folder_picker=lambda: selected_folder[0],
    )
    mock_icon = MagicMock()
    app.icon = mock_icon

    menu = app.create_menu()
    harness = HeadlessTrayHarness(menu=menu, mock_icon=mock_icon)
    return app, orchestrator, harness, mock_icon, selected_folder


@pytest.mark.unit
def test_tray_menu_structure_inspection(tray_fixture) -> None:
    _app, orchestrator, harness, _icon, _selected_folder = tray_fixture

    labels = harness.get_labels()
    assert any("Clair Obscur: Expedition 33 RPC" in lbl for lbl in labels)
    assert any("Game: Running (PID: 4242)" in lbl for lbl in labels)
    assert any("Location: Ancient Sanctuary" in lbl for lbl in labels)
    assert any("Status: Exploring" in lbl for lbl in labels)
    assert any("Discord:" in lbl for lbl in labels)
    assert any("Anti-Spoiler Mode" in lbl for lbl in labels)
    assert any("Combat Bridge" in lbl for lbl in labels)
    assert any("Start with Windows" in lbl for lbl in labels)
    assert any(orchestrator.updater.get_status_text() in lbl for lbl in labels)
    assert any("Exit" in lbl for lbl in labels)


@pytest.mark.unit
def test_tray_menu_action_toggle_anti_spoiler(
    tray_fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    _app, orchestrator, harness, icon, _selected_folder = tray_fixture
    assert orchestrator.settings_service.is_anti_spoiler_enabled() is False

    harness.invoke("Anti-Spoiler Mode")
    assert orchestrator.settings_service.is_anti_spoiler_enabled() is True
    icon.update_menu.assert_called()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.unit
def test_tray_menu_action_toggle_bridge(tray_fixture) -> None:
    app, orchestrator, harness, icon, _selected_folder = tray_fixture
    assert orchestrator.is_bridge_installed() is False

    harness.invoke("Combat Bridge")
    app.action_exit()
    assert orchestrator.is_bridge_installed() is True
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_toggle_startup(tray_fixture) -> None:
    _app, orchestrator, harness, icon, _selected_folder = tray_fixture
    assert orchestrator.is_startup_enabled() is False

    harness.invoke("Start with Windows")
    assert orchestrator.is_startup_enabled() is True
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_update_click(tray_fixture) -> None:
    _app, orchestrator, harness, _icon, _selected_folder = tray_fixture
    fake_updater = orchestrator.updater
    assert isinstance(fake_updater, FakeUpdater)

    harness.invoke(fake_updater.get_status_text())
    assert fake_updater.state in (UpdateState.IDLE, UpdateState.CHECKING, UpdateState.UP_TO_DATE)


@pytest.mark.unit
def test_tray_menu_action_exit(tray_fixture) -> None:
    _app, orchestrator, harness, icon, _selected_folder = tray_fixture

    harness.invoke("Exit")
    assert orchestrator.running is False
    icon.stop.assert_called_once()


@pytest.mark.unit
def test_tray_menu_action_select_game_folder(tray_fixture) -> None:
    app, orchestrator, harness, icon, selected_folder = tray_fixture
    selected_folder[0] = "C:/CustomGame/Win64"

    harness.invoke("Select Game Folder...")
    app.action_exit()
    assert orchestrator.is_bridge_installed() is True
    icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_menu_action_select_game_folder_cancelled(tray_fixture) -> None:
    _app, orchestrator, harness, _icon, selected_folder = tray_fixture
    selected_folder[0] = None

    harness.invoke("Select Game Folder...")
    assert orchestrator.is_bridge_installed() is False


@pytest.mark.unit
def test_prompt_folder_selection_lifecycle(tray_fixture) -> None:
    """Verifies that selecting a game folder invokes the bridge installer with the chosen path."""
    app, orchestrator, harness, icon, selected_folder = tray_fixture
    selected_folder[0] = "D:/Custom/Win64"

    harness.invoke("Select Game Folder...")
    app.action_exit()
    assert orchestrator.is_bridge_installed() is True
    icon.notify.assert_called_once()
    icon.update_menu.assert_called()


@pytest.mark.unit
@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Win32 native folder dialog requires Windows ctypes.windll",
)
def test_prompt_folder_selection_cancelled_or_closed_x(tmp_path: Path) -> None:
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)

    # Test ctypes Shell32 cancelled selection returns None
    with patch("ctypes.windll.shell32.SHBrowseForFolderW", return_value=0):
        selected = app.prompt_folder_selection()
        assert selected is None

    # Test ctypes Shell32 successful selection
    with (
        patch("ctypes.windll.shell32.SHBrowseForFolderW", return_value=1234),
        patch(
            "ctypes.windll.shell32.SHGetPathFromIDListW",
            side_effect=lambda _pidl, buf: buf.__setattr__("value", "C:\\Games\\Expedition33"),
        ),
        patch("ctypes.windll.ole32.CoTaskMemFree"),
    ):
        selected = app.prompt_folder_selection()
        assert selected == "C:\\Games\\Expedition33"


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="Tests non-Windows fallback")
def test_prompt_folder_selection_non_windows(tmp_path: Path) -> None:
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    assert app.prompt_folder_selection() is None


@pytest.mark.unit
def test_tray_menu_actions_responsiveness_benchmark(tmp_path: Path) -> None:
    """Verifies O(1) structural invariants: 0 disk I/O during get_labels() and non-blocking toggle_bridge."""
    settings_path = tmp_path / "settings.json"
    settings_service = SettingsService(settings_path)

    class CountingBridgeInstaller(FakeBridgeInstaller):
        def __init__(self) -> None:
            super().__init__(installed=False)
            self.is_installed_calls = 0

        def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
            self.is_installed_calls += 1
            return super().is_bridge_installed(win64_dir)

    bridge_installer = CountingBridgeInstaller()
    startup_service = FakeStartupService(enabled=False)

    real_orchestrator = AppOrchestrator(
        settings_service=settings_service,
        detector=GameDetector(bridge_provider=None),
        bridge_installer=bridge_installer,
        startup_service=startup_service,
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )

    app = ExpeditionTrayApp(orchestrator=real_orchestrator)
    mock_icon = MagicMock()
    app.icon = mock_icon

    menu = app.create_menu()
    harness = HeadlessTrayHarness(menu=menu, mock_icon=mock_icon)
    bridge_installer.is_installed_calls = 0

    # 1. Menu dynamic label evaluation must be O(1) in-memory without disk scans
    labels = harness.get_labels()
    assert len(labels) > 0
    assert bridge_installer.is_installed_calls == 0

    # 2. Anti-Spoiler toggle action
    harness.invoke("Anti-Spoiler Mode")
    assert real_orchestrator.settings_service.is_anti_spoiler_enabled() is True

    # 3. Combat Bridge toggle action starts non-blocking async worker
    harness.invoke("Combat Bridge")
    # 4. Exit action joins the background toggle worker and stops orchestrator
    harness.invoke("Exit")
    assert bridge_installer.install_call_count == 1
    assert real_orchestrator.running is False


@pytest.mark.unit
def test_tray_app_folder_picker_di_selected_and_cancelled(tmp_path: Path) -> None:
    """Verifies zero-cost folder_picker DI for both valid selection and None cancel without mocks."""
    picked_dir = tmp_path / "Expedition33" / "Win64"
    picked_dir.mkdir(parents=True)

    # 1. Valid folder selection
    installer = FakeBridgeInstaller(installed=False)
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings_select.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=installer,
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    mock_icon = MagicMock()
    app = ExpeditionTrayApp(orchestrator=orchestrator, folder_picker=lambda: str(picked_dir))
    app.icon = mock_icon
    harness = HeadlessTrayHarness(menu=app.create_menu(), mock_icon=mock_icon)

    harness.invoke("Select Game Folder...")
    # Wait deterministically for TrayInstallBridgeWorker via action_exit()
    app.action_exit()

    assert installer.install_call_count == 1
    assert orchestrator.is_bridge_installed() is True
    mock_icon.notify.assert_called_once()
    assert "installed successfully" in mock_icon.notify.call_args[0][0]

    # 2. Cancelled selection (returns None)
    installer_cancel = FakeBridgeInstaller(installed=False)
    orchestrator_cancel = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings_cancel.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=installer_cancel,
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app_cancel = ExpeditionTrayApp(orchestrator=orchestrator_cancel, folder_picker=lambda: None)
    app_cancel.icon = MagicMock()
    harness_cancel = HeadlessTrayHarness(menu=app_cancel.create_menu(), mock_icon=app_cancel.icon)

    harness_cancel.invoke("Select Game Folder...")
    app_cancel.action_exit()

    assert installer_cancel.install_call_count == 0
    assert orchestrator_cancel.is_bridge_installed() is False


@pytest.mark.unit
def test_tray_app_action_exit_cumulative_monotonic_deadline_deterministic(tmp_path: Path) -> None:
    """Verifies action_exit() enforces a single cumulative 1.0s monotonic deadline across workers."""
    clock = DualClockHarness(initial_monotonic=500.0)
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
        monotonic_provider=clock.monotonic_clock,
        epoch_provider=clock.epoch_clock,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = MagicMock()

    recorded_timeouts: list[float | None] = []

    class _HangingWorker:
        def __init__(self, advance_by: float) -> None:
            self.advance_by = advance_by

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            recorded_timeouts.append(timeout)
            clock.advance(self.advance_by)

    workers: list[Any] = [
        _HangingWorker(0.45),
        _HangingWorker(0.45),
        _HangingWorker(0.45),
        _HangingWorker(0.45),
    ]
    with app._tray_workers_lock:
        app._tray_workers.extend(workers)

    app.action_exit()

    assert len(recorded_timeouts) == 4
    assert recorded_timeouts[0] == pytest.approx(1.0)
    assert recorded_timeouts[1] == pytest.approx(0.55)
    assert recorded_timeouts[2] == pytest.approx(0.10)
    assert recorded_timeouts[3] == pytest.approx(0.0)


@pytest.mark.integration
def test_tray_app_action_exit_cumulative_deadline_real_threads(tmp_path: Path) -> None:
    """Verifies action_exit() bounds total join wait for 3 blocked threads to ~1.0s (not 3*0.5s)."""
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = MagicMock()

    release_event = threading.Event()
    started_count = 0
    started_cond = threading.Condition()

    def _blocked_worker() -> None:
        nonlocal started_count
        with started_cond:
            started_count += 1
            started_cond.notify_all()
        release_event.wait(timeout=5.0)

    threads = [threading.Thread(target=_blocked_worker, daemon=True) for _ in range(3)]
    try:
        for t in threads:
            t.start()
        with started_cond:
            assert started_cond.wait_for(lambda: started_count == 3, timeout=2.0)

        with app._tray_workers_lock:
            app._tray_workers.extend(threads)

        t0 = time.monotonic()
        app.action_exit()
        elapsed = time.monotonic() - t0

        assert 0.90 <= elapsed < 1.35, f"Expected cumulative ~1.0s deadline, got {elapsed:.3f}s"
    finally:
        release_event.set()
        for t in threads:
            t.join(timeout=2.0)


@pytest.mark.unit
def test_tray_app_folder_picker_exception_returns_none_and_skips_install(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Raising folder_picker must log a warning, return None, and skip bridge installation."""
    installer = FakeBridgeInstaller(installed=False)
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=installer,
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )

    def _exploding_picker() -> str | None:
        raise RuntimeError("Tkinter/Shell32 dialog crashed")

    mock_icon = MagicMock()
    app = ExpeditionTrayApp(orchestrator=orchestrator, folder_picker=_exploding_picker)
    app.icon = mock_icon
    harness = HeadlessTrayHarness(menu=app.create_menu(), mock_icon=mock_icon)

    with caplog.at_level(logging.WARNING, logger="expedition33_rpc.ui.tray_app"):
        assert app.prompt_folder_selection() is None
        assert "Folder picker failed" in caplog.text

        harness.invoke("Select Game Folder...")
        app.action_exit()

    assert installer.install_call_count == 0
    assert orchestrator.is_bridge_installed() is False
    mock_icon.notify.assert_not_called()


@pytest.mark.unit
def test_tray_app_toggle_bridge_worker_exception_still_refreshes_menu(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Worker exception in toggle_bridge must still log error and trigger icon.update_menu()."""

    class ExplodingBridgeInstaller(FakeBridgeInstaller):
        def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            del win64_dir
            raise RuntimeError("Unexpected installer failure")

    installer = ExplodingBridgeInstaller(installed=False)
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=installer,
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    mock_icon = MagicMock()
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = mock_icon
    harness = HeadlessTrayHarness(menu=app.create_menu(), mock_icon=mock_icon)

    with caplog.at_level(logging.ERROR, logger="expedition33_rpc.ui.tray_app"):
        harness.invoke("Combat Bridge")
        app.action_exit()

    assert "Bridge toggle failed" in caplog.text
    mock_icon.update_menu.assert_called()


@pytest.mark.unit
def test_tray_app_automatic_menu_update_on_state_change(tmp_path: Path) -> None:
    """Verifies icon.update_menu() is triggered when bridge_installed or updater.state changes."""
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(installed=False),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(state=UpdateState.IDLE),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    mock_icon = MagicMock()
    app.icon = mock_icon
    harness = HeadlessTrayHarness(menu=app.create_menu(), mock_icon=mock_icon)

    harness.invoke("Combat Bridge")
    app.action_exit()
    assert mock_icon.update_menu.call_count >= 1


@pytest.mark.unit
def test_tray_app_run_initializes_icon_before_orchestrator_start(tmp_path: Path) -> None:
    """Verifies self.icon is initialized before orchestrator.start() is called in run()."""
    orchestrator = AppOrchestrator(
        settings_service=SettingsService(tmp_path / "settings.json"),
        detector=GameDetector(bridge_provider=None),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    icon_ready_at_start = False

    def _check_start() -> None:
        nonlocal icon_ready_at_start
        icon_ready_at_start = app.icon is not None

    with (
        patch.object(orchestrator, "start", side_effect=_check_start),
        patch("pystray.Icon") as mock_icon_cls,
    ):
        app.run()
        assert icon_ready_at_start is True
        mock_icon_cls.return_value.run.assert_called_once()
