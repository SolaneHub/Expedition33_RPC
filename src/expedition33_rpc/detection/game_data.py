from __future__ import annotations

import json
import os
from typing import Any

from expedition33_rpc.core.resources import get_resource_path

type TowerTrial = tuple[int, int] | str
type TrialDefinition = tuple[TowerTrial, str | None, list[list[str]]]


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


_DATA: dict[str, Any] = _load_game_data()


def get_game_data() -> dict[str, Any]:
    """Returns the global game data catalog loaded at module import."""
    return _DATA


_DEFAULT_MAIN_MENU_TOKENS: list[str] = [
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

_raw_process_names = _DATA.get("target_process_names")
if isinstance(_raw_process_names, list) and _raw_process_names:
    TARGET_PROCESS_NAMES: tuple[str, ...] = tuple(
        str(n).strip().lower() for n in _raw_process_names if str(n).strip()
    )
elif isinstance(_raw_process_names, str) and _raw_process_names.strip():
    TARGET_PROCESS_NAMES = (str(_raw_process_names).strip().lower(),)
else:
    TARGET_PROCESS_NAMES = ("sandfall-win64-shipping.exe", "sandfall-wingdk-shipping.exe")

MAIN_MENU_TOKENS: frozenset[str] = frozenset(
    _DATA.get("main_menu_tokens") or _DEFAULT_MAIN_MENU_TOKENS
)

ZONE_NAME_OVERRIDES_EN: dict[str, str] = dict(_DATA.get("zone_name_overrides_en", {}))
ZONE_NAME_OVERRIDES_IT: dict[str, str] = dict(_DATA.get("zone_name_overrides_it", {}))
CHECKPOINT_NAMES_EN: dict[str, str] = dict(_DATA.get("checkpoint_names_en", {}))
CHECKPOINT_NAMES_IT: dict[str, str] = dict(_DATA.get("checkpoint_names_it", {}))
CONTEXTUAL_CHECKPOINTS: list[dict[str, Any]] = list(_DATA.get("contextual_checkpoints", []))


def _build_endless_tower_trials(raw_trials: list[Any]) -> list[TrialDefinition]:
    return [
        (
            (int(item[0][0]), int(item[0][1])) if isinstance(item[0], list) else str(item[0]),
            item[1],
            item[2],
        )
        for item in raw_trials
    ]


ENDLESS_TOWER_TRIALS: list[TrialDefinition] = _build_endless_tower_trials(
    _DATA.get("endless_tower_trials", [])
)

__all__ = [
    "TARGET_PROCESS_NAMES",
    "MAIN_MENU_TOKENS",
    "ZONE_NAME_OVERRIDES_EN",
    "ZONE_NAME_OVERRIDES_IT",
    "CHECKPOINT_NAMES_EN",
    "CHECKPOINT_NAMES_IT",
    "CONTEXTUAL_CHECKPOINTS",
    "ENDLESS_TOWER_TRIALS",
    "TowerTrial",
    "TrialDefinition",
    "get_game_data",
]
