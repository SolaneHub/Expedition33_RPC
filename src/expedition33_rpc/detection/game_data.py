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
    "level_mainmenu",
    "wbp_gm_mainmenucontainer",
    "wbp_gm_mainmenucontainer_c",
    "wbp_loadingscreen",
    "wbp_loadingscreen_c",
    "wbp_loadingscreen_expedition33",
    "wbp_loadingscreen_expedition33_c",
    "wbp_mm_backupsaveentry",
    "wbp_mm_backupsaveentry_c",
    "wbp_mm_backupsavesbox",
    "wbp_mm_backupsavesbox_c",
    "wbp_mm_loadscreen",
    "wbp_mm_loadscreen_c",
    "wbp_mm_mainmenu",
    "wbp_mm_mainmenu_c",
    "wbp_mm_saveslot",
    "wbp_mm_saveslot_c",
    "wbp_mm_titlescreen",
    "wbp_mm_titlescreen_c",
    "wbp_splashscreen_epilepsy",
    "wbp_splashscreen_epilepsy_c",
    "wbp_splashscreen_savewarning",
    "wbp_splashscreen_savewarning_c",
    "wbp_splashscreens_logos",
    "wbp_splashscreens_logos_c",
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
ZONE_NAME_OVERRIDES_BY_LANG: dict[str, dict[str, str]] = dict(
    _DATA.get("zone_name_overrides_by_lang", {})
)
CHECKPOINT_NAMES_BY_LANG: dict[str, dict[str, str]] = dict(
    _DATA.get("checkpoint_names_by_lang", {})
)
TOWER_STAGES_BY_LANG: dict[str, dict[str, str]] = dict(_DATA.get("tower_stages_by_lang", {}))
CONTEXTUAL_CHECKPOINTS: list[dict[str, Any]] = list(_DATA.get("contextual_checkpoints", []))

ALL_SUPPORTED_LANGUAGES: tuple[str, ...] = (
    "ar",
    "cs",
    "de",
    "en-US",
    "es-419",
    "es",
    "fr-FR",
    "id",
    "it",
    "ja",
    "ko",
    "pl",
    "pt-BR",
    "ru",
    "th",
    "tr",
    "uk",
    "vi",
    "zh-Hans",
    "zh-Hant",
)


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
    "ALL_SUPPORTED_LANGUAGES",
    "TARGET_PROCESS_NAMES",
    "MAIN_MENU_TOKENS",
    "ZONE_NAME_OVERRIDES_EN",
    "ZONE_NAME_OVERRIDES_IT",
    "ZONE_NAME_OVERRIDES_BY_LANG",
    "CHECKPOINT_NAMES_EN",
    "CHECKPOINT_NAMES_IT",
    "CHECKPOINT_NAMES_BY_LANG",
    "TOWER_STAGES_BY_LANG",
    "CONTEXTUAL_CHECKPOINTS",
    "ENDLESS_TOWER_TRIALS",
    "TowerTrial",
    "TrialDefinition",
    "get_game_data",
]
