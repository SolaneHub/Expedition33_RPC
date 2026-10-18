"""Declarative schema validation and integrity tests for game_data."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import psutil
import pytest

from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.detector import BridgeStateProvider, GameDetector
from expedition33_rpc.detection.game_data import ENDLESS_TOWER_TRIALS
from expedition33_rpc.detection.normalization import (
    format_checkpoint_tag,
    is_continent_zone,
    is_menu_zone,
    resolve_tower_trial,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def game_data_json() -> dict:
    json_path = get_resource_path("game_data.json")
    if not os.path.isfile(json_path):
        candidate = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "expedition33_rpc"
            / "assets"
            / "game_data.json"
        )
        if candidate.is_file():
            json_path = str(candidate)

    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def test_game_data_schema_and_catalog_integrity(game_data_json: dict) -> None:
    """Declarative structural validator verifying complete schema integrity and bilingual symmetry."""
    # 1. Target processes and menu tokens
    procs = game_data_json.get("target_process_names")
    assert isinstance(procs, list) and len(procs) >= 2
    assert all(isinstance(p, str) and p.endswith(".exe") and p == p.lower() for p in procs)
    assert "sandfall-win64-shipping.exe" in procs
    assert "sandfall-wingdk-shipping.exe" in procs
    assert "target_process_name" not in game_data_json

    tokens = game_data_json.get("main_menu_tokens")
    assert isinstance(tokens, list) and len(tokens) > 0
    assert all(isinstance(tok, str) and len(tok) > 0 for tok in tokens)

    # 2. Checkpoint dictionary symmetry
    cp_by_lang_raw = game_data_json.get("checkpoint_names_by_lang", {})
    en_checkpoints = cp_by_lang_raw.get("en-US", {})
    it_checkpoints = cp_by_lang_raw.get("it", {})
    assert isinstance(en_checkpoints, dict) and isinstance(it_checkpoints, dict)

    en_keys = set(en_checkpoints.keys())
    it_keys = set(it_checkpoints.keys())
    assert en_keys == it_keys, (
        f"Checkpoint asymmetry: missing IT {en_keys - it_keys}, missing EN {it_keys - en_keys}"
    )
    assert len(en_keys) >= 300, (
        f"Expected at least 300 canonical checkpoint keys, got {len(en_keys)}"
    )
    assert all(re.sub(r"[^a-z0-9]", "", k.lower()) == k for k in en_keys)
    assert all(re.sub(r"[^a-z0-9]", "", k.lower()) == k for k in it_keys)
    assert all(isinstance(v, str) and len(v.strip()) > 0 for v in en_checkpoints.values())
    assert all(isinstance(v, str) and len(v.strip()) > 0 for v in it_checkpoints.values())

    # 3. Contextual checkpoint rules
    rules = game_data_json.get("contextual_checkpoints", [])
    assert isinstance(rules, list) and len(rules) > 0
    criteria_keys = ("contains", "suffixes", "tag_contains", "zone_required", "zone_exclude")
    for rule in rules:
        assert isinstance(rule, dict)
        assert isinstance(rule.get("en"), str) and len(rule["en"]) > 0
        assert isinstance(rule.get("it"), str) and len(rule["it"]) > 0
        assert isinstance(rule.get("zone_keywords"), list) and len(rule["zone_keywords"]) > 0
        assert any(k in rule for k in criteria_keys)

    # 4. Semantic zone aliases and legacy tables must be purged
    assert "semantic_zone_aliases" not in game_data_json
    assert "save_reader_ignored_zone_words" not in game_data_json
    assert "save_reader_ignored_cp_words" not in game_data_json
    assert "zone_name_overrides_en" not in game_data_json
    assert "zone_name_overrides_it" not in game_data_json
    assert "checkpoint_names_en" not in game_data_json
    assert "checkpoint_names_it" not in game_data_json

    # 4b. Localized presentation strings present in SSOT catalog
    loc_pres = game_data_json.get("localized_presentation", {})
    assert isinstance(loc_pres, dict) and len(loc_pres) >= 20
    assert "en-US" in loc_pres and "it" in loc_pres

    # 5. Endless tower trial definitions
    trials = game_data_json.get("endless_tower_trials", [])
    assert isinstance(trials, list) and len(trials) > 0
    for trial in trials:
        assert isinstance(trial, list) and len(trial) == 3
        stage_info, boss_name, groups = trial
        if isinstance(stage_info, list):
            assert len(stage_info) == 2 and all(isinstance(x, int) and x >= 1 for x in stage_info)
        else:
            assert isinstance(stage_info, str) and len(stage_info) > 0

        if boss_name is not None:
            assert isinstance(boss_name, str) and len(boss_name) > 0

        assert isinstance(groups, list) and len(groups) > 0
        for g in groups:
            assert isinstance(g, list) and len(g) > 0
            for variant in g:
                assert isinstance(variant, str) and len(variant) > 0
                re.compile(re.escape(variant))


CHECKPOINT_CASES = [
    # 1. Abbest Cave
    ("Abbest Cave", "Arena", "Entrance", "Entrata"),
    # 2. Ancient Sanctuary
    ("Ancient Sanctuary", "RedForest", "Entrance", "Entrata"),
    ("Ancient Sanctuary", "GiantBellAlley", "Sanctuary Maze", "Labirinto del santuario"),
    ("Ancient Sanctuary", "Arena", "Giant Bell Alley", "Vicolo della campana gigante"),
    # 3. Crimson Forest
    ("Crimson Forest", "Plazza", "Crimson Perch", "Trespolo cremisi"),
    # 4. Endless Night Sanctuary
    ("Endless Night Sanctuary", "Arena", "Warrior's Route", "Itinerario del guerriero"),
    ("Endless Night Sanctuary", "Totem", "Night Totem", "Totem della notte"),
    # 5. Esoteric Ruins
    ("Esoteric Ruins", "Cliff Bottom", "Lumiere's Wrecks", "Rovine di Lumière"),
    # 6. Esquie's Nest
    ("Esquie's Nest", "GestralEntry", "Entrance", "Entrata"),
    ("Esquie's Nest", "Francois", "Francois' Cave", "Grotta di François"),
    # 7. Falling Leaves
    ("Falling Leaves", "Crimson Perch", "Resinveil Grove", "Boschetto velo di resina"),
    ("Falling Leaves", "CenterPlazza", "Resinveil Grove", "Boschetto velo di resina"),
    # 8. Forgotten Battlefield
    ("Forgotten Battlefield", "Main Ruins", "Fort Ruins", "Rovine della fortezza"),
    ("Forgotten Battlefield", "Battlefield", "Vanguard Point", "Punto dell'avanguardia"),
    ("Forgotten Battlefield", "Side Battlefield", "Battlefield", "Campo di battaglia"),
    ("Forgotten Battlefield", "DuallistArena", "Ancient Bridge", "Ponte antico"),
    # 9. Frozen Hearts
    ("Frozen Hearts", "Cave Station", "Icebound Terminal", "Terminal congelato"),
    ("Frozen Hearts", "Cave Forest", "Iced Heart", "Cuore congelato"),
    ("Frozen Hearts", "Train Station", "Icebound Train Station", "Stazione ferroviaria congelata"),
    ("Frozen Hearts", "Frozenlakes", "Glacial Falls", "Cascate glaciali"),
    # 10. Gestral Village
    ("Gestral Village", "Village Entry", "Entrance", "Entrata"),
    # 11. Inside the Monolith
    ("Inside the Monolith", "Spring Meadows", "Tainted Meadows", "Radure contaminate"),
    ("Inside the Monolith", "Goblu", "Tainted Waters", "Acque contaminate"),
    ("Inside the Monolith", "Ancient Sanctuary", "Tainted Sanctuary", "Santuario contaminato"),
    ("Inside the Monolith", "Sea Cliff", "Tainted Cliffs", "Scogliera contaminata"),
    (
        "Inside the Monolith",
        "Forgotten Battlefield",
        "Tainted Battlefield",
        "Campo di battaglia contaminato",
    ),
    ("Inside the Monolith", "Monoco Mountain", "Tainted Hearts", "Cuorgelati contaminati"),
    ("Inside the Monolith", "Lumiere", "Tainted Lumiere", "Lumière contaminata"),
    # 12. Lumiere Act 3
    ("Lumiere", "Dock", "Harbour", "Porto"),
    ("Lumiere", "Big Plazza", "Central Plaza", "Piazza centrale"),
    ("Lumiere", "Crumbling Buildings", "Shattered Alley", "Vicolo in rovina"),
    ("Lumiere", "Opera", "Opera House", "Teatro dell'Opera"),
    ("Lumiere", "Manor Gardens", "Lumiere's Gardens", "Giardini di Lumière"),
    ("Lumiere", "Train Station Ruins", "Crooked Tower Walkway", "Sentiero della Torre ritorta"),
    # 13. Monoco's Station
    ("Monoco's Station", "Inside Station", "Monoco's Station", "Stazione di Monoco"),
    # 14. Old Lumiere
    ("Old Lumiere", "Broken Buildings", "Entrance", "Entrata"),
    ("Old Lumiere", "Manor Arena", "Manor Gardens", "Giardini della villa"),
    ("Old Lumiere", "Lune Path", "Right Street", "Strada destra"),
    ("Old Lumiere", "Maelle Path", "Left Street", "Strada sinistra"),
    ("Old Lumiere", "Alpha Arena", "Train Station Ruins", "Rovine della stazione ferroviaria"),
    # 15. Painting Workshop
    ("Painting Workshop", "Broken Lampmaster", "Broken Conception", "Concezione spezzata"),
    # 16. Renoir's Drafts
    ("Renoir's Drafts", "Golden Tree", "Golden Tree", "Albero dorato"),
    # 17. Siren's Dress
    ("Siren's Dress", "Inside", "Glissando", "Glissando"),
    # 18. Spring Meadows
    (
        "Spring Meadows",
        "Old Expeditioner Camp",
        "Abandoned Expeditioner Camp",
        "Accampamento abbandonato degli esploratori",
    ),
    # 19. Stone Wave Cliffs
    ("Stone Wave Cliffs", "Zeppelin Entry", "Entrance", "Entrata"),
    ("Stone Wave Cliffs", "Village", "Old Farm", "Vecchia fattoria"),
    ("Stone Wave Cliffs", "Caves", "Tide Caverns", "Grotte della marea"),
    # 20. Stone Wave Cliffs Cave
    ("Stone Wave Cliffs Cave", "Vista", "Entrance", "Entrata"),
    # 21. Sunless Cliffs
    ("Sunless Cliffs", "Cave", "Chroma Portal", "Portale di chroma"),
    # 22. The Canvas
    ("The Canvas", "Broken Conception", "Entrance", "Entrata"),
    # 23. The Reacher
    ("The Reacher", "Mountain Top", "Peak", "Cima"),
    ("The Reacher", "Fog Area", "Foggy Area", "Area nebbiosa"),
    # 24. Visages
    ("Visages", "Visages Arena", "Peak", "Cima"),
    ("Visages", "Sadness", "Sadness Vale", "Valle della tristezza"),
    ("Visages", "Anger", "Anger Vale", "Valle dell'ira"),
    ("Visages", "Joy", "Joy Vale", "Valle della gioia"),
    # 25. Yellow Harvest
    ("Yellow Harvest", "Lake", "Harvester's Hollow", "Fossa del Mietitore"),
    ("Yellow Harvest", "Arena", "Yellow Spire Wrecks", "Relitto dei pinnacoli cerei"),
]


def test_checkpoint_mapping_catalog() -> None:
    """Verifies that all catalog checkpoints format correctly in EN and IT."""
    for zone, tag, expected_en, expected_it in CHECKPOINT_CASES:
        res_en = format_checkpoint_tag(tag, zone=zone, lang="en")
        res_it = format_checkpoint_tag(tag, zone=zone, lang="it")
        assert res_en == expected_en, f"[{zone}] {tag} (EN)"
        assert res_it == expected_it, f"[{zone}] {tag} (IT)"


def test_every_trial_resolves_from_structured_and_exact_names() -> None:
    for stage, boss, groups in ENDLESS_TOWER_TRIALS:
        names = [min(group, key=len) for group in groups]
        # 1. Structured list in any permutation
        for shift in range(len(names)):
            permuted = names[shift:] + names[:shift]
            t_stage, t_enemy = resolve_tower_trial(enemies=permuted)
            assert t_stage == stage
            assert len(t_enemy) > 0
            if boss:
                assert t_enemy == boss
        # 2. Exact joined string fallback
        summary = ", ".join(names)
        t_stage_s, t_enemy_s = resolve_tower_trial(summary)
        assert t_stage_s == stage
        assert len(t_enemy_s) > 0


def test_unresolved_enemy_returns_none() -> None:
    trial, enemy = resolve_tower_trial("Unknown Foe (+3)")
    assert trial is None
    assert enemy == "Unknown Foe (+3)"

    trial_list, enemy_list = resolve_tower_trial(enemies=["Unknown Foe (+3)"])
    assert trial_list is None
    assert enemy_list == "Unknown Foe (+3)"


def test_detector_resolves_structured_bridge_payload_end_to_end(tmp_path: Path) -> None:
    bridge_path = tmp_path / "expedition33_status.json"
    now = time.time()
    bridge_path.write_text(
        json.dumps(
            {
                "timestamp": now,
                "zone": "Endless Tower",
                "in_combat": True,
                "enemy_name": "Alpha Gold Chevaliere, Duollistes",
                "enemies": ["Alpha Gold Chevaliere", "Duollistes"],
                "checkpoint": "",
            }
        ),
        encoding="utf-8",
    )
    bridge = BridgeStateProvider(paths=[str(bridge_path)])
    real_proc = psutil.Process(os.getpid())
    detector = GameDetector(
        bridge_provider=bridge,
        process_scanner=lambda: [real_proc],
        target_process_names=[real_proc.name()],
    )
    state = detector.get_game_state()
    assert state.in_combat is True
    assert state.enemy_name != ""


def test_normalization_pure_string_menu_and_continent_detection() -> None:
    # Pure string menu checks
    assert is_menu_zone(raw_zone="Level_MainMenu") is True
    assert is_menu_zone(raw_zone="WBP_MM_MainMenu") is True
    assert is_menu_zone(raw_zone="WBP_MM_TitleScreen") is True
    assert is_menu_zone(zone_name="Main Menu") is True
    assert is_menu_zone(zone_name="Nel menu principale") is True
    assert is_menu_zone(raw_zone="Level_Forest", zone_name="Forest") is False
    assert is_menu_zone(None, None) is False

    # Pure string continent checks
    assert is_continent_zone(zone_name="The Continent") is True
    assert is_continent_zone(zone_name="Il Continente") is True
    assert is_continent_zone(raw_zone="WorldMap_Main") is True
    assert is_continent_zone(zone_name="Old Lumiere") is False
    assert is_continent_zone(None, None) is False


def test_native_game_data_structures_at_module_load() -> None:
    """Verifies that catalog constants are loaded as native/immutable types at module load."""
    from expedition33_rpc.detection.game_data import (
        CHECKPOINT_NAMES_BY_LANG,
        CONTEXTUAL_CHECKPOINTS,
        ENDLESS_TOWER_TRIALS,
        MAIN_MENU_TOKENS,
        TARGET_PROCESS_NAMES,
        ZONE_NAME_OVERRIDES_BY_LANG,
        get_game_data,
    )

    data = get_game_data()
    assert isinstance(data, dict)
    assert isinstance(TARGET_PROCESS_NAMES, tuple)
    assert "sandfall-win64-shipping.exe" in TARGET_PROCESS_NAMES
    assert "sandfall-wingdk-shipping.exe" in TARGET_PROCESS_NAMES
    assert isinstance(MAIN_MENU_TOKENS, frozenset)
    assert isinstance(ZONE_NAME_OVERRIDES_BY_LANG, dict)
    assert isinstance(CHECKPOINT_NAMES_BY_LANG, dict)
    assert isinstance(CONTEXTUAL_CHECKPOINTS, list)
    assert isinstance(ENDLESS_TOWER_TRIALS, list)

    import expedition33_rpc.detection as detection
    import expedition33_rpc.detection.game_data as gd
    import expedition33_rpc.detection.normalization as norm

    for legacy in (
        "ZONE_NAME_OVERRIDES_EN",
        "ZONE_NAME_OVERRIDES_IT",
        "CHECKPOINT_NAMES_EN",
        "CHECKPOINT_NAMES_IT",
    ):
        assert not hasattr(gd, legacy), f"{legacy} should not be in game_data"
        assert not hasattr(detection, legacy), f"{legacy} should not be in detection"

    for legacy_map in ("CHECKPOINT_HASH_MAP_EN", "CHECKPOINT_HASH_MAP_IT"):
        assert not hasattr(norm, legacy_map), f"{legacy_map} should not be in normalization"


def test_all_20_languages_schema_and_symmetry(game_data_json: dict) -> None:
    """Verifies that all 20 official languages are populated with strict key symmetry."""
    from expedition33_rpc.detection.game_data import (
        ALL_SUPPORTED_LANGUAGES,
        CHECKPOINT_NAMES_BY_LANG,
        TOWER_STAGES_BY_LANG,
        ZONE_NAME_OVERRIDES_BY_LANG,
    )

    assert len(ALL_SUPPORTED_LANGUAGES) == 20

    zone_by_lang = game_data_json.get("zone_name_overrides_by_lang", {})
    cp_by_lang = game_data_json.get("checkpoint_names_by_lang", {})
    stages_by_lang = game_data_json.get("tower_stages_by_lang", {})

    assert isinstance(zone_by_lang, dict)
    assert isinstance(cp_by_lang, dict)
    assert isinstance(stages_by_lang, dict)

    master_cp_keys = set(cp_by_lang["en-US"].keys())

    for lang in ALL_SUPPORTED_LANGUAGES:
        # 1. Zone overrides exist and have non-empty values
        assert lang in zone_by_lang, f"Missing zone overrides for language {lang}"
        assert len(zone_by_lang[lang]) >= 200, f"Insufficient zone overrides for language {lang}"
        assert all(isinstance(v, str) and len(v) > 0 for v in zone_by_lang[lang].values())

        # 2. Checkpoints maintain 100% key symmetry across all 20 languages
        assert lang in cp_by_lang, f"Missing checkpoints for language {lang}"
        lang_keys = set(cp_by_lang[lang].keys())
        assert lang_keys == master_cp_keys, (
            f"Checkpoint asymmetry in {lang}: missing {master_cp_keys - lang_keys}, extra {lang_keys - master_cp_keys}"
        )
        assert all(re.sub(r"[^a-z0-9]", "", k.lower()) == k for k in lang_keys)
        assert all(isinstance(v, str) and len(v) > 0 for v in cp_by_lang[lang].values())

        # 3. Tower stages exist with all 33 trials
        assert lang in stages_by_lang, f"Missing tower stages for language {lang}"
        assert len(stages_by_lang[lang]) == 33, (
            f"Expected 33 tower stages for {lang}, got {len(stages_by_lang[lang])}"
        )

    # Also verify runtime module constants
    assert len(ZONE_NAME_OVERRIDES_BY_LANG) == 20
    assert len(CHECKPOINT_NAMES_BY_LANG) == 20
    assert len(TOWER_STAGES_BY_LANG) == 20


def test_normalize_language_code() -> None:
    """Verifies that all language formats map to canonical Unreal Engine language tags."""
    from expedition33_rpc.detection.normalization import normalize_language_code

    assert normalize_language_code("en") == "en-US"
    assert normalize_language_code("en-US") == "en-US"
    assert normalize_language_code("it") == "it"
    assert normalize_language_code("it-IT") == "it"
    assert normalize_language_code("fr") == "fr-FR"
    assert normalize_language_code("fr-FR") == "fr-FR"
    assert normalize_language_code("de") == "de"
    assert normalize_language_code("de-DE") == "de"
    assert normalize_language_code("es") == "es"
    assert normalize_language_code("es-ES") == "es"
    assert normalize_language_code("es-419") == "es-419"
    assert normalize_language_code("es-MX") == "es-419"
    assert normalize_language_code("pt-BR") == "pt-BR"
    assert normalize_language_code("pt") == "pt-BR"
    assert normalize_language_code("ja") == "ja"
    assert normalize_language_code("ko") == "ko"
    assert normalize_language_code("zh-Hans") == "zh-Hans"
    assert normalize_language_code("zh-CN") == "zh-Hans"
    assert normalize_language_code("zh-Hant") == "zh-Hant"
    assert normalize_language_code("zh-TW") == "zh-Hant"
    assert normalize_language_code("ru") == "ru"
    assert normalize_language_code("pl") == "pl"
    assert normalize_language_code("ar") == "ar"
    assert normalize_language_code("cs") == "cs"
    assert normalize_language_code("tr") == "tr"
    assert normalize_language_code("uk") == "uk"
    assert normalize_language_code("th") == "th"
    assert normalize_language_code("vi") == "vi"
    assert normalize_language_code("id") == "id"
    # Fallback to English
    assert normalize_language_code("") == "en-US"
    assert normalize_language_code("unknown_lang") == "en-US"


def test_multi_language_zone_and_checkpoint_formatting() -> None:
    """Verifies that format_zone_name and format_checkpoint_tag output real in-game names across languages."""
    from expedition33_rpc.detection.normalization import (
        format_checkpoint_tag,
        format_zone_name,
        is_main_menu,
    )

    # 1. Zone formatting for Old Lumière across distinct language families
    assert format_zone_name("Level_OldLumiere_Main", lang="en-US") == "Old Lumière"
    assert format_zone_name("Level_OldLumiere_Main", lang="it") == "Vecchia Lumière"
    assert format_zone_name("Level_OldLumiere_Main", lang="fr") == "Vieille Lumière"
    assert format_zone_name("Level_OldLumiere_Main", lang="de") == "Alt-Lumière"
    assert format_zone_name("Level_OldLumiere_Main", lang="es") == "Vieja Lumière"
    assert format_zone_name("Level_OldLumiere_Main", lang="ja") == "旧ルミエール"
    assert format_zone_name("Level_OldLumiere_Main", lang="zh-CN") == "卢明旧城"
    assert format_zone_name("Level_OldLumiere_Main", lang="zh-TW") == "盧明舊城"
    assert format_zone_name("Level_OldLumiere_Main", lang="ru") == "Старый Люмьер"
    assert format_zone_name("Level_OldLumiere_Main", lang="ar") == "لوميير القديمة"

    # 2. The Continent across languages
    assert format_zone_name("Level_WorldMap", lang="en-US") == "The Continent"
    assert format_zone_name("Level_WorldMap", lang="it") == "Il continente"
    assert format_zone_name("Level_WorldMap", lang="fr") == "Continent"
    assert format_zone_name("Level_WorldMap", lang="de") == "Der Kontinent"
    assert format_zone_name("Level_WorldMap", lang="ja") == "大陸"
    assert format_zone_name("Level_WorldMap", lang="zh-Hans") == "大陆"
    assert format_zone_name("Level_WorldMap", lang="ar") == "القارة"

    # 2b. Main menu across languages
    assert format_zone_name("Level_MainMenu", lang="en-US") == "Main Menu"
    assert format_zone_name("Level_MainMenu", lang="it") == "Menu principale"
    assert format_zone_name("Level_MainMenu", lang="fr") == "Menu principal"
    assert format_zone_name("Level_MainMenu", lang="de") == "Hauptmenü"
    assert format_zone_name("Level_MainMenu", lang="ja") == "メインメニュー"

    # 3. Checkpoint formatting across languages
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="en") == "François' Cave"
    )
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="it")
        == "Grotta di François"
    )
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="fr")
        == "Grotte de François"
    )
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="de")
        == "François' Höhle"
    )
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="ja")
        == "フランソワの洞窟"
    )
    assert (
        format_checkpoint_tag("Level.SpawnPoint.EsquieNest.Francois", lang="zh-CN")
        == "弗朗索瓦的洞穴"
    )

    # 4. Multilingual main menu recognition from display strings
    assert is_main_menu(None, "Hauptmenü") is True
    assert is_main_menu(None, "Menu principal") is True
    assert is_main_menu(None, "Nel menu principale") is True
    assert is_main_menu(None, "Main Menu") is True

    # 5. Generic entrance tag spacing fallback across languages
    assert format_checkpoint_tag("Level.SpawnPoint.Generic.Entry", lang="en-US") == "Entrance"
    assert format_checkpoint_tag("Level.SpawnPoint.Generic.Entry", lang="it") == "Entrata"
    assert format_checkpoint_tag("Level.SpawnPoint.Generic.Entry", lang="fr") == "Entrée"
    assert format_checkpoint_tag("Level.SpawnPoint.Generic.Entry", lang="de") == "Eingang"


def test_target_process_names_and_main_menu_tokens_ssot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that get_target_process_names and get_main_menu_tokens source directly from catalog with fallbacks."""
    from expedition33_rpc.detection import game_data

    # 1. Normal state: values match JSON catalog
    procs = game_data.get_target_process_names()
    assert isinstance(procs, tuple)
    assert procs == game_data.TARGET_PROCESS_NAMES
    assert "sandfall-win64-shipping.exe" in procs

    tokens = game_data.get_main_menu_tokens()
    assert isinstance(tokens, frozenset)
    assert tokens == game_data.MAIN_MENU_TOKENS
    assert "level_mainmenu" in tokens

    # 2. Dynamic customization from catalog dict
    custom_data = {
        "target_process_names": ["CustomGame.exe", "  ANOTHER_GAME.EXE  "],
        "main_menu_tokens": ["token_one", "TOKEN_TWO"],
    }
    monkeypatch.setattr(game_data, "get_game_data", lambda: custom_data)
    assert game_data.get_target_process_names() == ("customgame.exe", "another_game.exe")
    assert game_data.get_main_menu_tokens() == frozenset({"token_one", "token_two"})

    # 3. Fallback when keys are missing or empty
    empty_data: dict[str, list[str]] = {}
    monkeypatch.setattr(game_data, "get_game_data", lambda: empty_data)
    fallback_procs = game_data.get_target_process_names()
    fallback_tokens = game_data.get_main_menu_tokens()
    assert fallback_procs == game_data._DEFAULT_TARGET_PROCESS_NAMES
    assert fallback_tokens == frozenset(game_data._DEFAULT_MAIN_MENU_TOKENS)
