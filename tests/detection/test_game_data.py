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
    en_checkpoints = game_data_json.get("checkpoint_names_en", {})
    it_checkpoints = game_data_json.get("checkpoint_names_it", {})
    assert isinstance(en_checkpoints, dict) and isinstance(it_checkpoints, dict)

    en_keys = set(en_checkpoints.keys())
    it_keys = set(it_checkpoints.keys())
    assert en_keys == it_keys, (
        f"Checkpoint asymmetry: missing IT {en_keys - it_keys}, missing EN {it_keys - en_keys}"
    )
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

    # 4. Semantic zone aliases must be purged
    assert "semantic_zone_aliases" not in game_data_json
    assert "save_reader_ignored_zone_words" not in game_data_json
    assert "save_reader_ignored_cp_words" not in game_data_json

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
    ("Ancient Sanctuary", "GiantBellAlley", "Sanctuary Maze", "Labirinto del Santuario"),
    ("Ancient Sanctuary", "Arena", "Giant Bell Alley", "Vicolo della Grande Campana"),
    # 3. Crimson Forest
    ("Crimson Forest", "Plazza", "Crimson Perch", "Posatoio Cremisi"),
    # 4. Endless Night Sanctuary
    ("Endless Night Sanctuary", "Arena", "Warrior's Route", "Percorso del Guerriero"),
    ("Endless Night Sanctuary", "Totem", "Night Totem", "Totem della Notte"),
    # 5. Esoteric Ruins
    ("Esoteric Ruins", "Cliff Bottom", "Lumiere's Wrecks", "Relitti di Lumière"),
    # 6. Esquie's Nest
    ("Esquie's Nest", "GestralEntry", "Entrance", "Entrata"),
    ("Esquie's Nest", "Francois", "Francois' Cave", "Grotta di François"),
    # 7. Falling Leaves
    ("Falling Leaves", "Crimson Perch", "Resinveil Grove", "Boschetto del Velo di Resina"),
    ("Falling Leaves", "CenterPlazza", "Resinveil Grove", "Boschetto del Velo di Resina"),
    # 8. Forgotten Battlefield
    ("Forgotten Battlefield", "Main Ruins", "Fort Ruins", "Rovine del Forte"),
    ("Forgotten Battlefield", "Battlefield", "Vanguard Point", "Punto di Avanguardia"),
    ("Forgotten Battlefield", "Side Battlefield", "Battlefield", "Campo di Battaglia"),
    ("Forgotten Battlefield", "DuallistArena", "Ancient Bridge", "Ponte Antico"),
    # 9. Frozen Hearts
    ("Frozen Hearts", "Cave Station", "Icebound Terminal", "Capolinea Ghiacciato"),
    ("Frozen Hearts", "Cave Forest", "Iced Heart", "Cuore Ghiacciato"),
    (
        "Frozen Hearts",
        "Train Station",
        "Icebound Train Station",
        "Stazione Ferroviaria Ghiacciata",
    ),
    ("Frozen Hearts", "Frozenlakes", "Glacial Falls", "Cascate Glaciali"),
    # 10. Gestral Village
    ("Gestral Village", "Village Entry", "Entrance", "Entrata"),
    # 11. Inside the Monolith
    ("Inside the Monolith", "Spring Meadows", "Tainted Meadows", "Prati Corrotti"),
    ("Inside the Monolith", "Goblu", "Tainted Waters", "Acque Corrotte"),
    ("Inside the Monolith", "Ancient Sanctuary", "Tainted Sanctuary", "Santuario Corrotto"),
    ("Inside the Monolith", "Sea Cliff", "Tainted Cliffs", "Scogliere Corrotte"),
    (
        "Inside the Monolith",
        "Forgotten Battlefield",
        "Tainted Battlefield",
        "Campo di Battaglia Corrotto",
    ),
    ("Inside the Monolith", "Monoco Mountain", "Tainted Hearts", "Cuori Corrotti"),
    ("Inside the Monolith", "Lumiere", "Tainted Lumiere", "Lumière Corrotta"),
    # 12. Lumiere Act 3
    ("Lumiere", "Dock", "Harbour", "Porto"),
    ("Lumiere", "Big Plazza", "Central Plaza", "Piazza Centrale"),
    ("Lumiere", "Crumbling Buildings", "Shattered Alley", "Vicolo Frantumato"),
    ("Lumiere", "Opera", "Opera House", "Teatro dell'Opera"),
    ("Lumiere", "Manor Gardens", "Lumiere's Gardens", "Giardini di Lumière"),
    (
        "Lumiere",
        "Train Station Ruins",
        "Crooked Tower Walkway",
        "Passerella della Torre Storta",
    ),
    # 13. Monoco's Station
    ("Monoco's Station", "Inside Station", "Monoco's Station", "Stazione di Monoco"),
    # 14. Old Lumiere
    ("Old Lumiere", "Broken Buildings", "Entrance", "Entrata"),
    ("Old Lumiere", "Manor Arena", "Manor Gardens", "Giardini del Maniero"),
    ("Old Lumiere", "Lune Path", "Right Street", "Via Destra"),
    ("Old Lumiere", "Maelle Path", "Left Street", "Via Sinistra"),
    ("Old Lumiere", "Alpha Arena", "Train Station Ruins", "Rovine della Stazione"),
    # 15. Painting Workshop
    ("Painting Workshop", "Broken Lampmaster", "Broken Conception", "Concezione Spezzata"),
    # 16. Renoir's Drafts
    ("Renoir's Drafts", "Golden Tree", "Golden Tree", "Albero Dorato"),
    # 17. Siren's Dress
    ("Siren's Dress", "Inside", "Glissando", "Glissando"),
    # 18. Spring Meadows
    (
        "Spring Meadows",
        "Old Expeditioner Camp",
        "Abandoned Expeditioner Camp",
        "Accampamento Abbandonato",
    ),
    # 19. Stone Wave Cliffs
    ("Stone Wave Cliffs", "Zeppelin Entry", "Entrance", "Entrata"),
    ("Stone Wave Cliffs", "Village", "Old Farm", "Vecchia Fattoria"),
    ("Stone Wave Cliffs", "Caves", "Tide Caverns", "Caverne della Marea"),
    # 20. Stone Wave Cliffs Cave
    ("Stone Wave Cliffs Cave", "Vista", "Entrance", "Entrata"),
    # 21. Sunless Cliffs
    ("Sunless Cliffs", "Cave", "Chroma Portal", "Portale Chroma"),
    # 22. The Canvas
    ("The Canvas", "Broken Conception", "Entrance", "Entrata"),
    # 23. The Reacher
    ("The Reacher", "Mountain Top", "Peak", "Cima"),
    ("The Reacher", "Fog Area", "Foggy Area", "Zona Nebbiosa"),
    # 24. Visages
    ("Visages", "Visages Arena", "Peak", "Picco"),
    ("Visages", "Sadness", "Sadness Vale", "Valle della Tristezza"),
    ("Visages", "Anger", "Anger Vale", "Valle della Rabbia"),
    ("Visages", "Joy", "Joy Vale", "Valle della Gioia"),
    # 25. Yellow Harvest
    ("Yellow Harvest", "Lake", "Harvester's Hollow", "Conca del Mietitore"),
    ("Yellow Harvest", "Arena", "Yellow Spire Wrecks", "Relitti della Guglia Gialla"),
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
    detector = GameDetector(
        bridge_provider=bridge,
    )

    real_proc = psutil.Process(os.getpid())
    detector.find_game_process = lambda: real_proc  # type: ignore
    state = detector.get_game_state()
    assert state.in_combat is True
    assert state.enemy_name != ""


def test_normalization_pure_string_menu_and_continent_detection() -> None:
    # Pure string menu checks
    assert is_menu_zone(raw_zone="MainMenu") is True
    assert is_menu_zone(raw_zone="bootstrap") is True
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
        CHECKPOINT_NAMES_EN,
        CHECKPOINT_NAMES_IT,
        CONTEXTUAL_CHECKPOINTS,
        ENDLESS_TOWER_TRIALS,
        MAIN_MENU_TOKENS,
        TARGET_PROCESS_NAMES,
        ZONE_NAME_OVERRIDES_EN,
        ZONE_NAME_OVERRIDES_IT,
        get_game_data,
    )

    data = get_game_data()
    assert isinstance(data, dict)
    assert isinstance(TARGET_PROCESS_NAMES, tuple)
    assert "sandfall-win64-shipping.exe" in TARGET_PROCESS_NAMES
    assert "sandfall-wingdk-shipping.exe" in TARGET_PROCESS_NAMES
    assert isinstance(MAIN_MENU_TOKENS, frozenset)
    assert isinstance(ZONE_NAME_OVERRIDES_EN, dict)
    assert isinstance(ZONE_NAME_OVERRIDES_IT, dict)
    assert isinstance(CHECKPOINT_NAMES_EN, dict)
    assert isinstance(CHECKPOINT_NAMES_IT, dict)
    assert isinstance(CONTEXTUAL_CHECKPOINTS, list)
    assert isinstance(ENDLESS_TOWER_TRIALS, list)
