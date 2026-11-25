"""Tests for presentation formatting, Discord payload limits, and TrayApp."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.harness.fake_process import FakeProcess
from tests.harness.fake_services import (
    FakeBridgeInstaller,
    FakeStartupService,
    FakeUpdater,
)
from tests.harness.tray_harness import HeadlessTrayHarness

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.presence import (
    DISCORD_MAX_FIELD_LENGTH,
    build_presence_payload,
    format_location_name,
    format_presence,
    truncate_presence_field,
)
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector, GameState
from expedition33_rpc.detection.normalization import (
    is_continent_zone,
    is_main_menu,
)
from expedition33_rpc.integrations.updater import UpdateInfo, UpdateState
from expedition33_rpc.ui.presentation import (
    WIN32_MAX_TRAY_TITLE_LENGTH,
    format_tray_combat_status,
    format_tray_title,
    format_tray_zone_status,
)
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Presentation & Normalization Formatting
# ---------------------------------------------------------------------------


def test_is_main_menu() -> None:
    assert is_main_menu("Level_MainMenu") is True
    assert is_main_menu("WBP_MM_MainMenu") is True
    assert is_main_menu("WBP_MM_TitleScreen") is True
    assert is_main_menu(zone_display="Main Menu") is True
    assert is_main_menu(zone_display="Nel menu principale") is True
    assert is_main_menu("Level_Forest", zone_display="Forest") is False


def test_is_continent_zone() -> None:
    assert is_continent_zone(zone_name="Continent") is True
    assert is_continent_zone(zone_name="Continente") is True
    assert is_continent_zone(raw_zone="WorldMap_Sub") is True
    assert is_continent_zone(zone_name="Flying Waters") is False


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
    assert format_tray_title(menu_en) == "Expedition 33: In Main Menu (Title Screen)"

    menu_it = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="it")
    assert format_tray_title(menu_it) == "Expedition 33: Nel menu principale (Schermata dei titoli)"

    main_menu_en = GameState.create(is_running=True, raw_zone="WBP_MM_MainMenu", game_language="en")
    assert format_tray_title(main_menu_en) == "Expedition 33: In Main Menu"

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


def test_format_tray_title_clamping_with_long_strings() -> None:
    # 1. Extremely long enemy name (>200 chars)
    huge_enemy = "ColossalEnemyBossName_" * 15  # 330 chars
    state_long_enemy = GameState.create(
        is_running=True, in_combat=True, enemy_name=huge_enemy, zone_name="Ancient Sanctuary"
    )
    title_enemy = format_tray_title(state_long_enemy)
    assert len(title_enemy) <= WIN32_MAX_TRAY_TITLE_LENGTH
    assert len(title_enemy) == 127
    assert title_enemy.endswith("...")
    expected_enemy_prefix = f"Expedition 33: Ancient Sanctuary (Fighting: {huge_enemy})"[:124]
    assert title_enemy == f"{expected_enemy_prefix}..."

    # 2. Extremely long zone name (>200 chars)
    huge_zone = "ExtremelyLongForgottenAbyssalRuinsRegionName_" * 10  # 450 chars
    state_long_zone = GameState.create(is_running=True, in_combat=False, zone_name=huge_zone)
    title_zone = format_tray_title(state_long_zone)
    assert len(title_zone) <= WIN32_MAX_TRAY_TITLE_LENGTH
    assert len(title_zone) == 127
    assert title_zone.endswith("...")
    expected_zone_prefix = f"Expedition 33: {huge_zone} (Exploring)"[:124]
    assert title_zone == f"{expected_zone_prefix}..."

    # 3. Both zone and enemy extremely long (>200 chars each)
    state_both = GameState.create(
        is_running=True, in_combat=True, zone_name=huge_zone, enemy_name=huge_enemy
    )
    title_both = format_tray_title(state_both)
    assert len(title_both) <= WIN32_MAX_TRAY_TITLE_LENGTH
    assert len(title_both) == 127
    assert title_both.endswith("...")


def test_format_tray_title_exact_boundary_conditions() -> None:
    # Exact 127 characters should not be truncated
    # Prefix: "Expedition 33: " (15) + Suffix: " (Exploring)" (12) = 27 fixed chars
    # Zone: 100 chars -> total 127 chars
    zone_100 = "Z" * 100
    state_127 = GameState.create(is_running=True, in_combat=False, zone_name=zone_100)
    title_127 = format_tray_title(state_127)
    assert len(title_127) == 127
    assert not title_127.endswith("...")
    assert title_127 == f"Expedition 33: {zone_100} (Exploring)"

    # 128 characters (off-by-one boundary) must truncate to 124 chars + "..."
    # Zone: 101 chars -> total 128 chars
    zone_101 = "Z" * 101
    state_128 = GameState.create(is_running=True, in_combat=False, zone_name=zone_101)
    title_128 = format_tray_title(state_128)
    assert len(title_128) == 127
    assert title_128.endswith("...")
    assert title_128 == f"Expedition 33: {zone_101} (Exploring)"[:124] + "..."


def test_format_tray_title_none_state() -> None:
    assert format_tray_title(None) == "Expedition 33 RPC (Waiting for game...)"


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
    assert format_tray_combat_status(menu) == "Status: Title Screen"
    assert format_tray_combat_status(menu, anti_spoiler=True) == "Status: Title Screen"

    menu_it = GameState.create(is_running=True, raw_zone="Level_MainMenu", game_language="it")
    assert format_tray_zone_status(menu_it, anti_spoiler=True) == "Location: Nel menu principale"
    assert format_tray_combat_status(menu_it, anti_spoiler=True) == "Status: Schermata dei titoli"

    menu_main = GameState.create(is_running=True, raw_zone="WBP_MM_MainMenu", game_language="en")
    assert format_tray_combat_status(menu_main) == "Status: Main Menu"

    menu_main_it = GameState.create(is_running=True, raw_zone="WBP_MM_MainMenu", game_language="it")
    assert format_tray_combat_status(menu_main_it) == "Status: Menu principale"

    starting = GameState.create(is_running=True, is_starting=True, game_language="it")
    assert format_tray_zone_status(starting) == "Location: Avvio in corso..."
    assert format_tray_combat_status(starting) == "Status: Caricamento..."


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


def test_truncate_presence_field_utf8_bytes() -> None:
    # 1. Short and long ASCII strings
    short_ascii = "Hello, Expedition 33!"
    assert truncate_presence_field(short_ascii) == short_ascii
    assert len(truncate_presence_field(short_ascii).encode("utf-8")) <= 128

    exact_128_ascii = "A" * DISCORD_MAX_FIELD_LENGTH
    res_exact = truncate_presence_field(exact_128_ascii)
    assert res_exact == exact_128_ascii
    assert len(res_exact.encode("utf-8")) == 128

    long_ascii = "B" * 300
    res_long = truncate_presence_field(long_ascii)
    assert res_long == "B" * 128
    assert len(res_long.encode("utf-8")) == 128

    # 2. Multibyte strings where character count < 128 but UTF-8 byte count > 128
    # Chinese (3 bytes per character)
    # 50 chars * 3 bytes = 150 bytes (> 128 bytes, but < 128 chars)
    chinese_text = "你好世界，远征33号正在激战中！" * 3
    assert len(chinese_text) < 128
    assert len(chinese_text.encode("utf-8")) > 128
    res_chinese = truncate_presence_field(chinese_text)
    assert len(res_chinese.encode("utf-8")) <= 128
    assert (
        res_chinese.encode("utf-8")
        == chinese_text.encode("utf-8")[: len(res_chinese.encode("utf-8"))]
    )

    # Cyrillic (2 bytes per character)
    # 70 chars * 2 bytes = 140 bytes (> 128 bytes, but < 128 chars)
    cyrillic_text = "Привет мир! Экспедиция 33 исследует неизведанное пространство." * 2
    assert len(cyrillic_text) < 128
    assert len(cyrillic_text.encode("utf-8")) > 128
    res_cyrillic = truncate_presence_field(cyrillic_text)
    assert len(res_cyrillic.encode("utf-8")) <= 128
    assert (
        res_cyrillic.encode("utf-8")
        == cyrillic_text.encode("utf-8")[: len(res_cyrillic.encode("utf-8"))]
    )

    # Emojis (4 bytes per emoji)
    # 35 emojis = 35 chars, 35 * 4 = 140 bytes
    emoji_text = "⚔️🛡️✨🔥" * 10
    assert len(emoji_text) < 128
    assert len(emoji_text.encode("utf-8")) > 128
    res_emoji = truncate_presence_field(emoji_text)
    assert len(res_emoji.encode("utf-8")) <= 128

    # Mixed text (ASCII + Cyrillic + Chinese + Emojis)
    mixed_text = "Combat: 战斗 [Level 45] Привет мир! ⚔️ " * 5
    assert len(mixed_text.encode("utf-8")) > 128
    res_mixed = truncate_presence_field(mixed_text)
    assert len(res_mixed.encode("utf-8")) <= 128

    # Boundary edge case: splitting a 3-byte Chinese char at byte 127/128
    # 42 Chinese chars = 126 bytes. 43 chars = 129 bytes.
    # At max_bytes=128, exactly 42 characters should fit (126 bytes).
    # The 43rd character's first 2 bytes must be cleanly dropped by errors="ignore".
    c43 = "你" * 43
    res_c43 = truncate_presence_field(c43, max_bytes=128)
    assert res_c43 == "你" * 42
    assert len(res_c43.encode("utf-8")) == 126
    assert len(res_c43.encode("utf-8")) <= 128

    # Verify custom max_bytes
    assert truncate_presence_field("你好", max_bytes=4) == "你"
    assert len(truncate_presence_field("你好", max_bytes=4).encode("utf-8")) <= 4


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


def test_menu_lifecycle_substates_presentation_en_and_it() -> None:
    """Verifies that each distinct menu substate format matches Discord and Tray expectations."""
    # 1. Starting phase (process running, telemetry pending)
    start_en = GameState.create(is_running=True, is_starting=True, game_language="en")
    assert format_presence(start_en) == ("Starting...", "Loading...")
    assert format_tray_title(start_en) == "Expedition 33: Starting..."
    assert format_tray_zone_status(start_en) == "Location: Starting..."
    assert format_tray_combat_status(start_en) == "Status: Loading..."

    start_it = GameState.create(is_running=True, is_starting=True, game_language="it")
    assert format_presence(start_it) == ("Avvio in corso...", "Caricamento...")
    assert format_tray_title(start_it) == "Expedition 33: Avvio in corso..."
    assert format_tray_zone_status(start_it) == "Location: Avvio in corso..."
    assert format_tray_combat_status(start_it) == "Status: Caricamento..."

    # 2. Bootstrap & Splash phase
    boot_en = GameState.create(is_running=True, raw_zone="Map_GameBootstrap", game_language="en")
    assert format_presence(boot_en) == ("In Main Menu", "Initial Screen")
    assert format_tray_title(boot_en) == "Expedition 33: In Main Menu (Initial Screen)"
    assert format_tray_zone_status(boot_en) == "Location: In Main Menu"
    assert format_tray_combat_status(boot_en) == "Status: Initial Screen"

    boot_it = GameState.create(is_running=True, raw_zone="Map_GameBootstrap", game_language="it")
    assert format_presence(boot_it) == ("Nel menu principale", "Schermata iniziale")
    assert format_tray_title(boot_it) == "Expedition 33: Nel menu principale (Schermata iniziale)"
    assert format_tray_zone_status(boot_it) == "Location: Nel menu principale"
    assert format_tray_combat_status(boot_it) == "Status: Schermata iniziale"

    # 3. Title Screen (Press any key)
    title_en = GameState.create(is_running=True, raw_zone="WBP_MM_TitleScreen", game_language="en")
    assert format_presence(title_en) == ("In Main Menu", "Title Screen")
    assert format_tray_title(title_en) == "Expedition 33: In Main Menu (Title Screen)"
    assert format_tray_combat_status(title_en) == "Status: Title Screen"

    title_it = GameState.create(is_running=True, raw_zone="WBP_MM_TitleScreen", game_language="it")
    assert format_presence(title_it) == ("Nel menu principale", "Schermata dei titoli")
    assert (
        format_tray_title(title_it) == "Expedition 33: Nel menu principale (Schermata dei titoli)"
    )
    assert format_tray_combat_status(title_it) == "Status: Schermata dei titoli"

    # 4. Main Menu (Options: Continue, New Game, Load, Settings)
    main_en = GameState.create(is_running=True, raw_zone="WBP_MM_MainMenu", game_language="en")
    assert format_presence(main_en) == ("In Main Menu", "Main Menu")
    assert format_tray_title(main_en) == "Expedition 33: In Main Menu"
    assert format_tray_combat_status(main_en) == "Status: Main Menu"

    main_it = GameState.create(is_running=True, raw_zone="WBP_MM_MainMenu", game_language="it")
    assert format_presence(main_it) == ("Nel menu principale", "Menu principale")
    assert format_tray_title(main_it) == "Expedition 33: Nel menu principale"
    assert format_tray_combat_status(main_it) == "Status: Menu principale"

    # 5a. Loading Save / Save Slots
    save_en = GameState.create(is_running=True, raw_zone="WBP_MM_LoadScreen", game_language="en")
    assert format_presence(save_en) == ("In Main Menu", "Loading Save")
    assert format_tray_title(save_en) == "Expedition 33: In Main Menu (Loading Save)"
    assert format_tray_combat_status(save_en) == "Status: Loading Save"

    save_it = GameState.create(is_running=True, raw_zone="WBP_MM_LoadScreen", game_language="it")
    assert format_presence(save_it) == ("Nel menu principale", "Caricamento salvataggio")
    assert (
        format_tray_title(save_it) == "Expedition 33: Nel menu principale (Caricamento salvataggio)"
    )
    assert format_tray_combat_status(save_it) == "Status: Caricamento salvataggio"

    # 5b. Settings / Options
    settings_en = GameState.create(is_running=True, raw_zone="WBP_MM_Settings", game_language="en")
    assert format_presence(settings_en) == ("In Main Menu", "In Settings")
    assert format_tray_title(settings_en) == "Expedition 33: In Main Menu (In Settings)"
    assert format_tray_combat_status(settings_en) == "Status: In Settings"

    settings_it = GameState.create(is_running=True, raw_zone="WBP_MM_Settings", game_language="it")
    assert format_presence(settings_it) == ("Nel menu principale", "Nelle impostazioni")
    assert (
        format_tray_title(settings_it) == "Expedition 33: Nel menu principale (Nelle impostazioni)"
    )
    assert format_tray_combat_status(settings_it) == "Status: Nelle impostazioni"

    # 5c. New Game
    newgame_en = GameState.create(is_running=True, raw_zone="WBP_MM_NewGame", game_language="en")
    assert format_presence(newgame_en) == ("In Main Menu", "New Game")
    assert format_tray_title(newgame_en) == "Expedition 33: In Main Menu (New Game)"
    assert format_tray_combat_status(newgame_en) == "Status: New Game"

    newgame_it = GameState.create(is_running=True, raw_zone="WBP_MM_NewGame", game_language="it")
    assert format_presence(newgame_it) == ("Nel menu principale", "Nuova partita")
    assert format_tray_title(newgame_it) == "Expedition 33: Nel menu principale (Nuova partita)"
    assert format_tray_combat_status(newgame_it) == "Status: Nuova partita"


# ---------------------------------------------------------------------------
# Tray App Lifecycle and Step Update
# ---------------------------------------------------------------------------


@pytest.fixture
def tray_test_app(tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    settings_svc = SettingsService(path=settings_file)

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
    mock_rpc.update_presence.assert_called_once_with(expected_payload, pid=9999)
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


def test_tray_app_on_orchestrator_state_change_suppresses_title_exception(
    tray_test_app,
) -> None:
    app, _mock_detector, _mock_rpc, _ = tray_test_app

    class FaultyIcon:
        def __init__(self) -> None:
            self.update_menu = MagicMock()

        @property
        def title(self) -> str:
            return "Current Title"

        @title.setter
        def title(self, value: str) -> None:
            del value
            raise OSError("Win32 UI thread disconnected")

    faulty_icon = FaultyIcon()
    app.icon = faulty_icon

    state = GameState.create(is_running=True, zone_name="Lumiere")
    # Must not raise an exception even when setting self.icon.title raises OSError
    app.on_orchestrator_state_change(state, anti_spoiler=False)
    faulty_icon.update_menu.assert_called_once()


# ---------------------------------------------------------------------------
# Stress & Boundary Tests for Win32 Tooltip Clamping & Tray App Protection
# ---------------------------------------------------------------------------


class CustomTrayException(Exception):
    """Custom exception simulating an unhandled tray UI subsystem error."""


@pytest.mark.parametrize(
    ("target_length", "should_truncate"),
    [
        (124, False),
        (126, False),
        (127, False),
        (128, True),
        (129, True),
        (200, True),
        (1000, True),
    ],
)
def test_format_tray_title_exact_boundaries(target_length: int, should_truncate: bool) -> None:
    """Tests exact target title lengths (124, 126, 127, 128, 129, 200, 1000).

    Verifies output is NEVER > 127 characters and truncates to 124 chars + '...'.
    """
    fixed_overhead = 27
    zone_length = target_length - fixed_overhead
    assert zone_length > 0

    zone_name = "X" * zone_length
    state = GameState.create(is_running=True, in_combat=False, zone_name=zone_name)
    result = format_tray_title(state)

    # Invariant 1: Length is NEVER greater than 127
    assert len(result) <= WIN32_MAX_TRAY_TITLE_LENGTH
    assert len(result) <= 127

    if should_truncate:
        assert len(result) == 127
        assert result.endswith("...")
        untruncated_expected = f"Expedition 33: {zone_name} (Exploring)"
        assert result == untruncated_expected[:124] + "..."
    else:
        assert len(result) == target_length
        assert not result.endswith("...")
        assert result == f"Expedition 33: {zone_name} (Exploring)"


def test_format_tray_title_comprehensive_length_sweep() -> None:
    """Sweeps un-truncated title lengths from 0 to 1500 to guarantee universal clamp invariant."""
    fixed_overhead = 27
    for total_len in range(fixed_overhead + 1, 1500):
        zone_len = total_len - fixed_overhead
        state = GameState.create(is_running=True, in_combat=False, zone_name="A" * zone_len)
        result = format_tray_title(state)

        assert len(result) <= 127
        if total_len > 127:
            assert len(result) == 127
            assert result.endswith("...")
        else:
            assert len(result) == total_len


@pytest.mark.parametrize(
    "unicode_sample",
    [
        # Japanese Kanji & Kana
        "ルミエール・漆黒の深淵・第9999階層",
        # Chinese Simplified & Traditional
        "遠征隊33：光之城與古老神殿的終極對決",
        # Emojis & Pictographs (4-byte UTF-8, SMP)
        "⚔️🛡️🔥🐲💥👑💀🏰🌟🚀✨",
        # Right-to-Left (Hebrew)
        "מבוך חשוך של לומייר - קרב בוס אפי",
        # Right-to-Left (Arabic)
        "رحلة استكشافية 33: قلعة الظلال المفقودة",
        # Combining diacritics / Zalgo
        "Z\u0332\u032a\u0324a\u0300\u0316\u0327l\u0321\u0328\u0334g\u0345\u0360o\u032f\u033d",
        # Surrogate pairs / supplementary characters
        "\U00010000\U0001f600\U0001f47e\U0001f984\U0001fa84",
        # Zero-width joiner sequences (Family emoji)
        "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466",
        # Mixed whitespace, newlines, null bytes, tabs
        "Zone\tWith\nNewlines\x00And\rNulls",
    ],
)
def test_format_tray_title_unicode_stress(unicode_sample: str) -> None:
    """Stress-tests multi-byte, SMP, RTL, and combining Unicode strings of various lengths."""
    for multiplier in (1, 5, 20, 100):
        stretched_zone = unicode_sample * multiplier
        stretched_enemy = ("Boss_" + unicode_sample) * multiplier

        # 1. Exploring state
        state_exploring = GameState.create(
            is_running=True, in_combat=False, zone_name=stretched_zone
        )
        title_exploring = format_tray_title(state_exploring)
        assert len(title_exploring) <= 127
        if len(stretched_zone) > 100:
            assert len(title_exploring) == 127
            assert title_exploring.endswith("...")

        # 2. Combat state
        state_combat = GameState.create(
            is_running=True,
            in_combat=True,
            zone_name=stretched_zone,
            enemy_name=stretched_enemy,
        )
        title_combat = format_tray_title(state_combat)
        assert len(title_combat) <= 127
        if len(stretched_zone) + len(stretched_enemy) > 100:
            assert len(title_combat) == 127
            assert title_combat.endswith("...")


def test_format_tray_title_none_and_empty_edge_cases() -> None:
    """Tests extreme edge cases: None state, empty strings, pure whitespace, stopped state."""
    assert format_tray_title(None) == "Expedition 33 RPC (Waiting for game...)"
    assert (
        format_tray_title(GameState.create(is_running=False))
        == "Expedition 33 RPC (Waiting for game...)"
    )

    empty_state = GameState.create(is_running=True, zone_name="", enemy_name="")
    title_empty = format_tray_title(empty_state)
    assert len(title_empty) <= 127
    assert "Expedition 33:" in title_empty

    whitespace_state = GameState.create(is_running=True, zone_name="   ", enemy_name="   ")
    title_ws = format_tray_title(whitespace_state)
    assert len(title_ws) <= 127


@pytest.mark.parametrize(
    "exception_to_raise",
    [
        OSError("Win32 UI thread disconnected / INVALID_HANDLE"),
        RuntimeError("pystray icon thread has terminated"),
        ValueError("Invalid title parameter"),
        KeyError("Missing internal tray key"),
        TypeError("Title must be a str"),
        CustomTrayException("Simulated custom platform crash"),
    ],
)
def test_tray_app_on_orchestrator_state_change_suppresses_various_exceptions(
    tmp_path: Path, exception_to_raise: Exception
) -> None:
    """Verifies that with contextlib.suppress(Exception): in TrayApp protects

    against diverse exception types (OSError, RuntimeError, custom exceptions)
    without crashing the orchestrator loop or breaking menu updates.
    """
    settings_file = tmp_path / "settings.json"
    settings_svc = SettingsService(path=settings_file)
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock()
    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=settings_svc,
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)

    class FaultyIcon:
        def __init__(self) -> None:
            self.update_menu = MagicMock()

        @property
        def title(self) -> str:
            return "Old Title"

        @title.setter
        def title(self, value: str) -> None:
            del value
            raise exception_to_raise

    faulty_icon = FaultyIcon()
    app.icon = faulty_icon

    state = GameState.create(
        is_running=True,
        process_pid=5555,
        zone_name="Monolith Subterrane",
        in_combat=True,
        enemy_name="Titan",
    )

    # Must complete cleanly without propagating exception
    with contextlib.nullcontext():
        app.on_orchestrator_state_change(state, anti_spoiler=False)

    # Menu update must still succeed
    faulty_icon.update_menu.assert_called_once()


def test_tray_app_handles_none_icon_gracefully(tmp_path: Path) -> None:
    """Verifies that TrayApp handles state change when icon is None without raising."""
    settings_file = tmp_path / "settings.json"
    settings_svc = SettingsService(path=settings_file)
    mock_detector = MagicMock(spec=GameDetector)
    mock_rpc = MagicMock()
    orchestrator = AppOrchestrator(
        detector=mock_detector,
        rpc_manager=mock_rpc,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=settings_svc,
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app.icon = None

    state = GameState.create(is_running=True, zone_name="Lumiere")
    # Must not raise AttributeError
    app.on_orchestrator_state_change(state, anti_spoiler=False)


def test_tray_menu_state_refreshes_on_subsystem_changes_outside_menu_lock(tmp_path: Path) -> None:
    """Verifies menu_state refreshes on bridge/startup/updater changes under identical GameState,
    and that _menu_lock is NEVER held while querying orchestrator subsystems.
    """
    app_ref: list[ExpeditionTrayApp] = []
    lock_held_during_probe: list[bool] = []

    class InspectingBridgeInstaller(FakeBridgeInstaller):
        def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
            if app_ref:
                lock_held_during_probe.append(app_ref[0]._menu_lock.locked())
            return super().is_bridge_installed(win64_dir)

    class InspectingStartupService(FakeStartupService):
        def is_startup_enabled(self) -> bool:
            if app_ref:
                lock_held_during_probe.append(app_ref[0]._menu_lock.locked())
            return super().is_startup_enabled()

    bridge = InspectingBridgeInstaller(installed=False)
    startup = InspectingStartupService(enabled=False)
    updater = FakeUpdater(state=UpdateState.IDLE)
    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(),
        bridge_installer=bridge,
        startup_service=startup,
        updater=updater,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=SettingsService(tmp_path / "settings.json"),
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app_ref.append(app)
    mock_icon = MagicMock()
    app.icon = mock_icon

    same_state = GameState.create(is_running=True, process_pid=1111, zone_name="Lumiere")

    # 1. Initial notification
    app.on_orchestrator_state_change(same_state, anti_spoiler=False)
    assert mock_icon.update_menu.call_count == 1

    # 2. Identical state & subsystems -> no redundant update_menu
    app.on_orchestrator_state_change(same_state, anti_spoiler=False)
    assert mock_icon.update_menu.call_count == 1

    # 3. Bridge installed flips under identical GameState
    orchestrator.toggle_bridge()
    app.on_orchestrator_state_change(same_state, anti_spoiler=False)
    assert mock_icon.update_menu.call_count == 2

    # 4. Startup enabled flips under identical GameState
    orchestrator.toggle_startup()
    app.on_orchestrator_state_change(same_state, anti_spoiler=False)
    assert mock_icon.update_menu.call_count == 3

    # 5. Updater state transitions under identical GameState
    updater.state = UpdateState.AVAILABLE
    app.on_orchestrator_state_change(same_state, anti_spoiler=False)
    assert mock_icon.update_menu.call_count == 4

    assert lock_held_during_probe and all(held is False for held in lock_held_during_probe)


def test_tray_menu_updates_to_installed_on_async_auto_install_completion(tmp_path: Path) -> None:
    """End-to-end async auto-install completion refreshes tray menu label to [Installed]."""
    install_started = threading.Event()
    allow_install = threading.Event()
    install_done = threading.Event()

    class SignalingBridgeInstaller(FakeBridgeInstaller):
        def install_bridge(self, win64_dir: Path | str | None = None) -> tuple[bool, str]:
            install_started.set()
            assert allow_install.wait(timeout=2.0)
            res = super().install_bridge(win64_dir)
            install_done.set()
            return res

    procs = [
        FakeProcess(
            pid=4321,
            name="sandfall-win64-shipping.exe",
            is_running=True,
            exe_path="/mock/game/win64/Sandfall-Win64-Shipping.exe",
        )
    ]
    detector = GameDetector(bridge_provider=None, process_scanner=lambda: procs)
    bridge = SignalingBridgeInstaller(installed=False)
    orchestrator = AppOrchestrator(
        detector=detector,
        rpc_manager=MagicMock(),
        bridge_installer=bridge,
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=True,
        sync_startup=False,
        settings_service=SettingsService(tmp_path / "settings.json"),
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)
    mock_icon = MagicMock()
    app.icon = mock_icon
    harness = HeadlessTrayHarness(menu=app.create_menu(), mock_icon=mock_icon)

    assert "Combat Bridge  [Install Now]" in harness.get_labels()

    try:
        orchestrator.step_update()
        assert install_started.wait(timeout=2.0)
        assert mock_icon.update_menu.call_count == 1
        assert "Combat Bridge  [Install Now]" in harness.get_labels()

        allow_install.set()
        assert install_done.wait(timeout=2.0)

        # Wait briefly for _async_install to emit _notify_state_change after install_bridge returns
        with orchestrator._bridge_lock:
            install_thread = orchestrator._bridge_install_thread
        if install_thread is not None:
            install_thread.join(timeout=2.0)

        assert orchestrator.is_bridge_installed() is True
        assert mock_icon.update_menu.call_count >= 2
        assert "Combat Bridge  [Installed]" in harness.get_labels()
    finally:
        allow_install.set()
        orchestrator.stop()


def test_tray_app_run_initializes_icon_before_orchestrator_start(tmp_path: Path) -> None:
    """Verifies run() constructs self.icon before orchestrator.start() so early events are not lost."""
    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(),
        bridge_installer=FakeBridgeInstaller(),
        startup_service=FakeStartupService(),
        updater=FakeUpdater(),
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=SettingsService(tmp_path / "settings.json"),
    )
    app = ExpeditionTrayApp(orchestrator=orchestrator)

    icon_seen_at_start: list[Any] = []
    early_state = GameState.create(is_running=True, process_pid=777, zone_name="Lumiere")

    def _fake_start() -> None:
        icon_seen_at_start.append(app.icon)
        orchestrator._notify_state_change(early_state, False)

    class _FakeIcon:
        def __init__(self, name: str, icon: Any, title: str, menu: Any) -> None:
            self.name = name
            self.icon = icon
            self.title = title
            self.menu = menu
            self.update_menu = MagicMock()
            self.run_called = False
            self.stop_called = False

        def run(self) -> None:
            self.run_called = True

        def stop(self) -> None:
            self.stop_called = True

    with (
        patch.object(orchestrator, "start", side_effect=_fake_start),
        patch("expedition33_rpc.ui.tray_app.pystray.Icon", _FakeIcon),
    ):
        app.run()

    assert len(icon_seen_at_start) == 1
    assert icon_seen_at_start[0] is not None
    assert app.icon.run_called is True
    assert "Lumiere" in app.icon.title
    assert app._last_menu_state is not None
    app.icon.update_menu.assert_called_once()


def test_tray_menu_state_seq_prevents_stale_overwrite_on_concurrent_callbacks(
    tmp_path: Path,
) -> None:
    """Out-of-order concurrent on_orchestrator_state_change calls must not overwrite newer state."""
    app_ref: list[ExpeditionTrayApp] = []
    lock_held_during_probe: list[bool] = []
    first_probe_entered = threading.Event()
    release_first_probe = threading.Event()
    probe_call_count = 0
    probe_count_lock = threading.Lock()

    class GatedBridgeInstaller(FakeBridgeInstaller):
        def is_bridge_installed(self, win64_dir: Path | str | None = None) -> bool:
            nonlocal probe_call_count
            if app_ref:
                lock_held_during_probe.append(app_ref[0]._menu_lock.locked())
            with probe_count_lock:
                probe_call_count += 1
                is_first = probe_call_count == 1
            if is_first:
                first_probe_entered.set()
                assert release_first_probe.wait(timeout=2.0)
            return super().is_bridge_installed(win64_dir)

    class InspectingStartupService(FakeStartupService):
        def is_startup_enabled(self) -> bool:
            if app_ref:
                lock_held_during_probe.append(app_ref[0]._menu_lock.locked())
            return super().is_startup_enabled()

    bridge = GatedBridgeInstaller(installed=False)
    startup = InspectingStartupService(enabled=False)
    updater = FakeUpdater(state=UpdateState.IDLE)
    orchestrator = AppOrchestrator(
        detector=MagicMock(spec=GameDetector),
        rpc_manager=MagicMock(),
        bridge_installer=bridge,
        startup_service=startup,
        updater=updater,
        auto_install_bridge=False,
        sync_startup=False,
        settings_service=SettingsService(tmp_path / "settings.json"),
    )

    app = ExpeditionTrayApp(orchestrator=orchestrator)
    app_ref.append(app)
    mock_icon = MagicMock()
    app.icon = mock_icon

    old_state = GameState.create(is_running=True, process_pid=1001, zone_name="Lumiere")
    new_state = GameState.create(is_running=True, process_pid=1001, zone_name="Flying Waters")

    thread_a_errors: list[BaseException] = []

    def _run_stale_callback() -> None:
        try:
            app.on_orchestrator_state_change(old_state, anti_spoiler=False)
        except BaseException as exc:  # pragma: no cover - defensive capture
            thread_a_errors.append(exc)

    def _probe_bridge(force_probe: bool = False) -> bool:
        del force_probe
        return bridge.is_bridge_installed(orchestrator.current_state.win64_dir)

    thread_a = threading.Thread(target=_run_stale_callback, daemon=True)
    with patch.object(orchestrator, "is_bridge_installed", side_effect=_probe_bridge):
        try:
            thread_a.start()
            assert first_probe_entered.wait(timeout=2.0)

            # Newer state arrives and commits while Thread A is paused outside _menu_lock
            bridge.installed = True
            app.on_orchestrator_state_change(new_state, anti_spoiler=False)

            assert app._applied_menu_seq == 2
            assert app._last_menu_state is not None
            assert app._last_menu_state[2] == "Flying Waters"
            assert app._last_menu_state[12] is True
            expected_title = format_tray_title(new_state, anti_spoiler=False)
            assert mock_icon.title == expected_title
        finally:
            release_first_probe.set()
            thread_a.join(timeout=2.0)

    assert not thread_a_errors
    assert app._applied_menu_seq == 2
    assert app._last_menu_state is not None
    assert app._last_menu_state[2] == "Flying Waters"
    assert app._last_menu_state[12] is True
    assert mock_icon.title == expected_title
    assert mock_icon.update_menu.call_count == 1
    assert len(lock_held_during_probe) >= 2
    assert all(held is False for held in lock_held_during_probe)
