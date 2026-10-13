"""Tests for presentation formatting, Discord payload limits, and TrayApp."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.integrations.updater import UpdateInfo
from expedition33_rpc.ui.presentation import (
    DISCORD_MAX_FIELD_LENGTH,
    build_presence_payload,
    format_location_name,
    format_presence,
    format_tray_combat_status,
    format_tray_title,
    format_tray_zone_status,
    is_continent_zone,
    is_menu_zone,
    truncate_presence_field,
)
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Presentation & Normalization Formatting
# ---------------------------------------------------------------------------


def test_is_menu_zone() -> None:
    assert is_menu_zone(GameState.create(raw_zone="Level_MainMenu")) is True
    assert is_menu_zone(GameState.create(raw_zone="WBP_MM_MainMenu")) is True
    assert is_menu_zone(GameState.create(raw_zone="WBP_MM_TitleScreen")) is True
    assert is_menu_zone(GameState.create(zone_name="Main Menu")) is True
    assert is_menu_zone(GameState.create(zone_name="Nel menu principale")) is True
    assert is_menu_zone(GameState.create(raw_zone="Level_Forest", zone_name="Forest")) is False


def test_is_continent_zone() -> None:
    assert is_continent_zone(GameState.create(zone_name="Continent")) is True
    assert is_continent_zone(GameState.create(zone_name="Continente")) is True
    assert is_continent_zone(GameState.create(raw_zone="WorldMap_Sub")) is True
    assert is_continent_zone(GameState.create(zone_name="Flying Waters")) is False


def test_format_location_name() -> None:
    st_state = GameState.create(
        zone_name="Endless Tower", tower_stage_trial=(11, 2), game_language="en"
    )
    assert format_location_name(st_state) == "Endless Tower (Stage 11, Trial 2)"

    st_state_it = GameState.create(
        zone_name="Torre Infinita", tower_stage_trial=(11, 2), game_language="it"
    )
    assert format_location_name(st_state_it) == "Torre Infinita (Fase 11, Prova 2)"

    st_str = GameState.create(
        zone_name="Endless Tower", tower_stage_trial="Floor 10", game_language="en"
    )
    assert format_location_name(st_str) == "Endless Tower (Floor 10)"

    cp_state = GameState.create(
        zone_name="Old Lumiere", checkpoint_name="Manor Gardens", game_language="en"
    )
    assert format_location_name(cp_state) == "Old Lumiere (Manor Gardens)"


def test_format_tray_title() -> None:
    assert (
        format_tray_title(GameState.create(is_running=False))
        == "Expedition 33 RPC (Waiting for game...)"
    )

    menu_en = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="en")
    assert format_tray_title(menu_en) == "Expedition 33: In Main Menu"

    menu_it = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="it")
    assert format_tray_title(menu_it) == "Expedition 33: Nel menu principale"

    spoiler_combat = GameState.create(is_running=True, in_combat=True, zone_name="Secret Area")
    assert (
        format_tray_title(spoiler_combat, anti_spoiler=True)
        == "Expedition 33: [Protected] (In Combat)"
    )

    spoiler_explore = GameState.create(is_running=True, in_combat=False, zone_name="Secret Area")
    assert (
        format_tray_title(spoiler_explore, anti_spoiler=True)
        == "Expedition 33: [Protected] (Exploring)"
    )

    combat_enemy = GameState.create(
        is_running=True, in_combat=True, enemy_name="Boss", zone_name="Area"
    )
    assert format_tray_title(combat_enemy) == "Expedition 33: Area (Fighting: Boss)"

    explore = GameState.create(is_running=True, in_combat=False, zone_name="Area")
    assert format_tray_title(explore) == "Expedition 33: Area (Exploring)"


def test_format_tray_zone_and_combat_status() -> None:
    not_running = GameState.create(is_running=False)
    assert format_tray_zone_status(not_running) == "Location: --"
    assert format_tray_combat_status(not_running) == "Status: --"

    running = GameState.create(is_running=True, zone_name="Area", in_combat=True, enemy_name="Boss")
    assert (
        format_tray_zone_status(running, anti_spoiler=True) == "Location: [Hidden - Anti-Spoiler]"
    )
    assert format_tray_combat_status(running, anti_spoiler=True) == "Status: In Combat"
    assert format_tray_combat_status(running, anti_spoiler=False) == "Combat: Fighting Boss"

    menu = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="en")
    assert format_tray_zone_status(menu) == "Location: In Main Menu"
    assert format_tray_zone_status(menu, anti_spoiler=True) == "Location: In Main Menu"
    assert format_tray_combat_status(menu) == "Status: Main Menu"
    assert format_tray_combat_status(menu, anti_spoiler=True) == "Status: Main Menu"

    menu_it = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="it")
    assert format_tray_zone_status(menu_it, anti_spoiler=True) == "Location: Nel menu principale"
    assert format_tray_combat_status(menu_it, anti_spoiler=True) == "Status: Nel menu principale"


# ---------------------------------------------------------------------------
# Discord Field Limits
# ---------------------------------------------------------------------------


def test_truncate_presence_field_boundaries() -> None:
    sample = "In combattimento con: Simon the Divergent Star"
    assert truncate_presence_field(sample) == sample

    exact_128 = "A" * DISCORD_MAX_FIELD_LENGTH
    assert len(truncate_presence_field(exact_128)) == 128

    over_limit = "B" * 300
    result = truncate_presence_field(over_limit)
    assert len(result) == 128
    assert result == "B" * 128


def test_format_presence_boundary_limits() -> None:
    huge_enemy = "HugeBossName_" * 20
    huge_location = "VeryLongCheckpointNameInsideDeepZone_" * 10
    over_state = GameState.create(
        is_running=True,
        in_combat=True,
        enemy_name=huge_enemy,
        zone_name=huge_location,
    )
    det_over, st_over = format_presence(over_state)
    assert len(det_over) <= 128
    assert len(st_over) <= 128


def test_format_presence_across_languages() -> None:
    """Verifies format_presence outputs accurately localized details and state across language families."""
    # French (fr-FR)
    state_fr = GameState.create(
        is_running=True, zone_name="Vieille Lumière", in_combat=False, game_language="fr-FR"
    )
    assert format_presence(state_fr) == ("En exploration", "Vieille Lumière")

    # German (de) Combat with Enemy
    state_de = GameState.create(
        is_running=True,
        zone_name="Alt-Lumière",
        in_combat=True,
        enemy_name="Goblu",
        game_language="de",
    )
    assert format_presence(state_de) == ("Kämpft gegen: Goblu", "Alt-Lumière")

    # Japanese (ja) Main Menu
    state_ja = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="ja")
    assert format_presence(state_ja) == ("メインメニュー", "タイトル画面")

    # Russian (ru) Anti-Spoiler
    state_ru = GameState.create(
        is_running=True, zone_name="Скрытая локация", in_combat=True, game_language="ru"
    )
    assert format_presence(state_ru, anti_spoiler=True) == ("В бою", "Скрытая локация")

    # Simplified Chinese (zh-Hans) Tower Stage & Floor
    state_zh = GameState.create(
        is_running=True,
        zone_name="克莱尔之塔",
        tower_stage_trial=(1, 2),
        game_language="zh-Hans",
    )
    assert format_presence(state_zh) == ("探索中", "克莱尔之塔 (第1层，试炼2)")

    state_zh_floor = GameState.create(
        is_running=True,
        zone_name="无尽之塔",
        tower_floor=7,
        game_language="zh-Hans",
    )
    assert format_presence(state_zh_floor) == ("探索中", "无尽之塔 (第7层)")


# ---------------------------------------------------------------------------
# Tray App Lifecycle and Step Update
# ---------------------------------------------------------------------------


@pytest.fixture
def tray_test_app(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    settings_svc = SettingsService(custom_path=settings_file)

    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock()
    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=settings_svc,
    )
    mock_icon = MagicMock()
    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = mock_icon
    return app, mock_detector, mock_rpc, mock_icon


def test_step_update_reads_state_and_calls_rpc(tray_test_app) -> None:
    app, mock_detector, mock_rpc, mock_icon = tray_test_app
    running_state = GameState.create(
        is_running=True,
        process_pid=9999,
        zone_name="Old Lumiere",
        in_combat=False,
    )
    mock_detector.get_game_state.return_value = running_state

    result = app.orchestrator.step_update()

    mock_detector.get_game_state.assert_called_once()
    assert app.orchestrator.current_state == running_state
    assert result == running_state
    expected_payload = build_presence_payload(running_state, anti_spoiler=False)
    mock_rpc.update.assert_called_once_with(expected_payload, pid=9999)
    mock_icon.update_menu.assert_called_once()
    assert "Old Lumiere" in mock_icon.title


def test_step_update_state_changes_and_menu_caching(tray_test_app) -> None:
    app, mock_detector, _mock_rpc, mock_icon = tray_test_app

    # Tick 1: Exploring Old Lumiere
    state1 = GameState.create(is_running=True, process_pid=1234, zone_name="Old Lumiere")
    mock_detector.get_game_state.return_value = state1
    app.orchestrator.step_update()
    assert "Old Lumiere" in mock_icon.title

    # Tick 2: Same state
    app.orchestrator.step_update()
    assert "Old Lumiere" in mock_icon.title

    # Tick 3: Combat starts
    state2 = GameState.create(
        is_running=True,
        process_pid=1234,
        zone_name="Old Lumiere",
        in_combat=True,
        enemy_name="Duollistes",
    )
    mock_detector.get_game_state.return_value = state2
    app.orchestrator.step_update()
    assert "Duollistes" in mock_icon.title


def test_step_update_graceful_exception_handling(tray_test_app) -> None:
    app, mock_detector, _mock_rpc, mock_icon = tray_test_app
    mock_icon.update_menu.side_effect = RuntimeError("Tray busy")
    mock_detector.get_game_state.return_value = GameState.create(
        is_running=True, zone_name="Lumiere"
    )
    res = app.orchestrator.step_update()
    assert res is not None

    mock_detector.get_game_state.side_effect = Exception("Telemetry fault")
    res2 = app.orchestrator.step_update()
    assert res2 is None


def test_tray_app_chains_injected_orchestrator_callbacks() -> None:
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock()
    mock_icon = MagicMock()
    external_state_calls: list[tuple[GameState, bool]] = []
    external_update_calls: list[UpdateInfo] = []

    def ext_on_change(st: GameState, anti_spoiler: bool) -> None:
        external_state_calls.append((st, anti_spoiler))

    def ext_on_update(info: UpdateInfo) -> None:
        external_update_calls.append(info)

    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        on_state_change=ext_on_change,
        on_update_available=ext_on_update,
        auto_install_bridge=False,
        sync_startup=False,
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = mock_icon

    test_state = GameState.create(is_running=True, zone_name="Lumiere")
    mock_detector.get_game_state.return_value = test_state

    # Trigger tick directly via orchestrator
    orchestrator.step_update()

    # Both tray icon update and external listener were called
    assert len(external_state_calls) == 1
    assert external_state_calls[0][0] == test_state
    mock_icon.update_menu.assert_called_once()

    # Trigger update callback
    info = UpdateInfo(tag_name="v2.0.0", version_tuple=(2, 0, 0), html_url="http://example.com")
    orchestrator.on_update_check_complete(info)
    assert len(external_update_calls) == 1
    assert external_update_calls[0] == info
