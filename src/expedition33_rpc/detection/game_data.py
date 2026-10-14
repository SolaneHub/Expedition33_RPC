from __future__ import annotations

import functools
import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    ZONE_NAME_OVERRIDES_BY_LANG: dict[str, dict[str, str]]
    CHECKPOINT_NAMES_BY_LANG: dict[str, dict[str, str]]
    TOWER_STAGES_BY_LANG: dict[str, dict[str, str]]
    LOCALIZED_PRESENTATION: dict[str, dict[str, str]]
    CONTEXTUAL_CHECKPOINTS: list[dict[str, Any]]
    ENDLESS_TOWER_TRIALS: list[TrialDefinition]

type TowerTrial = tuple[int, int] | str
type TrialDefinition = tuple[TowerTrial, str | None, list[list[str]]]


def _load_game_data() -> dict[str, Any]:
    from expedition33_rpc.core.resources import get_resource_path

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


@functools.lru_cache(maxsize=1)
def get_game_data() -> dict[str, Any]:
    """Returns the global game data catalog, loaded on demand with caching."""
    return _load_game_data()


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

TARGET_PROCESS_NAMES: tuple[str, ...] = (
    "sandfall-win64-shipping.exe",
    "sandfall-wingdk-shipping.exe",
)

MAIN_MENU_TOKENS: frozenset[str] = frozenset(_DEFAULT_MAIN_MENU_TOKENS)

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


_LAZY_ATTRIBUTES = frozenset(
    {
        "ZONE_NAME_OVERRIDES_BY_LANG",
        "CHECKPOINT_NAMES_BY_LANG",
        "TOWER_STAGES_BY_LANG",
        "LOCALIZED_PRESENTATION",
        "CONTEXTUAL_CHECKPOINTS",
        "ENDLESS_TOWER_TRIALS",
    }
)


def __getattr__(name: str) -> Any:
    """Lazily loads heavy localized game data catalogs only upon access."""
    if name not in _LAZY_ATTRIBUTES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    data = get_game_data()
    match name:
        case "ZONE_NAME_OVERRIDES_BY_LANG":
            val = dict(data.get("zone_name_overrides_by_lang", {}))
        case "CHECKPOINT_NAMES_BY_LANG":
            val = dict(data.get("checkpoint_names_by_lang", {}))
        case "TOWER_STAGES_BY_LANG":
            val = dict(data.get("tower_stages_by_lang", {}))
        case "LOCALIZED_PRESENTATION":
            val = dict(data.get("localized_presentation", {}))
        case "CONTEXTUAL_CHECKPOINTS":
            val = list(data.get("contextual_checkpoints", []))
        case "ENDLESS_TOWER_TRIALS":
            val = _build_endless_tower_trials(data.get("endless_tower_trials", []))
        case _:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = val
    return val


__all__ = [
    "ALL_SUPPORTED_LANGUAGES",
    "CONTEXTUAL_CHECKPOINTS",
    "CHECKPOINT_NAMES_BY_LANG",
    "ENDLESS_TOWER_TRIALS",
    "LOCALIZED_PRESENTATION",
    "MAIN_MENU_TOKENS",
    "TARGET_PROCESS_NAMES",
    "TOWER_STAGES_BY_LANG",
    "TowerTrial",
    "TrialDefinition",
    "ZONE_NAME_OVERRIDES_BY_LANG",
    "get_game_data",
]
