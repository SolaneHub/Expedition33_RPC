import json
import os
from typing import Any

from expedition33_rpc.core.resources import get_resource_path


def _load_game_data() -> dict[str, Any]:
    path = get_resource_path("game_data.json")
    if not os.path.isfile(path):
        candidate = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "game_data.json")
        )
        if os.path.isfile(candidate):
            path = candidate
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_DATA = _load_game_data()

TARGET_PROCESS_NAME: str = str(_DATA.get("target_process_name", "")).strip().lower()

MAIN_MENU_TOKENS: frozenset[str] = frozenset(
    _DATA.get("main_menu_tokens")
    or [
        "mainmenu",
        "main_menu",
        "main menu",
        "bootstrap",
        "map_game_bootstrap",
        "map game bootstrap",
        "map_mainmenu",
        "title",
        "titlescreen",
        "frontend",
        "entry",
    ]
)

ZONE_NAME_OVERRIDES_EN: dict[str, str] = _DATA.get("zone_name_overrides_en", {})
ZONE_NAME_OVERRIDES_IT: dict[str, str] = _DATA.get("zone_name_overrides_it", {})
CHECKPOINT_NAMES_EN: dict[str, str] = _DATA.get("checkpoint_names_en", {})
CHECKPOINT_NAMES_IT: dict[str, str] = _DATA.get("checkpoint_names_it", {})
CONTEXTUAL_CHECKPOINTS: list[dict[str, Any]] = _DATA.get("contextual_checkpoints", [])

type TowerTrial = tuple[int, int] | str
type TrialDefinition = tuple[TowerTrial, str | None, list[list[str]]]

ENDLESS_TOWER_TRIALS: list[TrialDefinition] = [
    (
        (int(item[0][0]), int(item[0][1])) if isinstance(item[0], list) else str(item[0]),
        item[1],
        item[2],
    )
    for item in _DATA.get("endless_tower_trials", [])
]

type SemanticAlias = dict[str, list[str]]
SEMANTIC_ZONE_ALIASES: list[SemanticAlias] = _DATA.get("semantic_zone_aliases") or [
    {"cp_tokens": ["paintress", "monolith"], "zone_tokens": ["monolith"]},
    {"cp_tokens": ["flyinghouse", "manor"], "zone_tokens": ["manor"]},
    {"cp_tokens": ["esquie", "francois"], "zone_tokens": ["esquie", "nest", "nido"]},
    {"cp_tokens": ["chromazone", "chroma"], "zone_tokens": ["sunless", "senza sole", "chroma"]},
    {"cp_tokens": ["yellowforest", "yellow"], "zone_tokens": ["yellow", "giallo", "harvest"]},
    {"cp_tokens": ["reacher"], "zone_tokens": ["reacher", "scalatore"]},
    {"cp_tokens": ["seacliff"], "zone_tokens": ["stone wave", "onda di pietra", "seacliff"]},
    {"cp_tokens": ["goblu"], "zone_tokens": ["goblu", "flying waters", "acque volanti"]},
]

SAVE_READER_IGNORED_ZONE_WORDS: frozenset[str] = frozenset(
    {"the", "il", "la", "inside", "peak", "main", "zone", "camp", "area"}
)

SAVE_READER_IGNORED_CP_WORDS: frozenset[str] = frozenset(
    {"climb", "interior", "exterior", "intro", "savepoint", "entry", "field"}
)

__all__ = [
    "TARGET_PROCESS_NAME",
    "MAIN_MENU_TOKENS",
    "ZONE_NAME_OVERRIDES_EN",
    "ZONE_NAME_OVERRIDES_IT",
    "CHECKPOINT_NAMES_EN",
    "CHECKPOINT_NAMES_IT",
    "CONTEXTUAL_CHECKPOINTS",
    "ENDLESS_TOWER_TRIALS",
    "SEMANTIC_ZONE_ALIASES",
    "SAVE_READER_IGNORED_ZONE_WORDS",
    "SAVE_READER_IGNORED_CP_WORDS",
    "TowerTrial",
    "TrialDefinition",
]
