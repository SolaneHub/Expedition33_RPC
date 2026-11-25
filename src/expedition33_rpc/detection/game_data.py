from __future__ import annotations

import functools
import json
import os
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

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


@functools.lru_cache(maxsize=1)
def get_game_data() -> dict[str, Any]:
    """Returns the global game data catalog, loaded on demand with caching."""
    return _load_game_data()


DEFAULT_MAIN_MENU_TOKENS: list[str] = [
    "bootstrap",
    "gamebootstrap",
    "level_mainmenu",
    "map_game_bootstrap",
    "map_gamebootstrap",
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
    "wbp_mm_newgame",
    "wbp_mm_newgame_c",
    "wbp_mm_saveslot",
    "wbp_mm_saveslot_c",
    "wbp_mm_settings",
    "wbp_mm_settings_c",
    "wbp_mm_titlescreen",
    "wbp_mm_titlescreen_c",
    "wbp_newgame",
    "wbp_newgame_c",
    "wbp_settings",
    "wbp_settings_c",
    "wbp_settings_options",
    "wbp_settings_options_c",
    "wbp_splashscreen_epilepsy",
    "wbp_splashscreen_epilepsy_c",
    "wbp_splashscreen_savewarning",
    "wbp_splashscreen_savewarning_c",
    "wbp_splashscreens_logos",
    "wbp_splashscreens_logos_c",
]

DEFAULT_TARGET_PROCESS_NAMES: tuple[str, ...] = (
    "sandfall-win64-shipping.exe",
    "sandfall-wingdk-shipping.exe",
)


def get_target_process_names() -> tuple[str, ...]:
    """Returns the list of target game process names from game_data.json or defaults."""
    data = get_game_data()
    custom = data.get("target_process_names")
    if isinstance(custom, list) and custom:
        custom_list = cast(list[object], custom)
        names = tuple(str(p).strip().lower() for p in custom_list if str(p).strip())
        if names:
            return names
    return DEFAULT_TARGET_PROCESS_NAMES


def get_main_menu_tokens() -> frozenset[str]:
    """Returns the set of main menu tokens from game_data.json or defaults."""
    data = get_game_data()
    custom = data.get("main_menu_tokens")
    if isinstance(custom, list) and custom:
        custom_list = cast(list[object], custom)
        tokens = frozenset(str(tok).strip().lower() for tok in custom_list if str(tok).strip())
        if tokens:
            return tokens
    return frozenset(DEFAULT_MAIN_MENU_TOKENS)


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


def _freeze_nested_str_map(
    raw: dict[str, dict[str, str]],
) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType({k: MappingProxyType(dict(v)) for k, v in raw.items()})


@dataclass(frozen=True, slots=True)
class _GameDataSnapshot:
    zone_name_overrides_by_lang: Mapping[str, Mapping[str, str]]
    checkpoint_names_by_lang: Mapping[str, Mapping[str, str]]
    tower_stages_by_lang: Mapping[str, Mapping[str, str]]
    localized_presentation: Mapping[str, Mapping[str, str]]
    contextual_checkpoints: tuple[Mapping[str, Any], ...]
    endless_tower_trials: tuple[TrialDefinition, ...]


@functools.cache
def _get_snapshot() -> _GameDataSnapshot:
    data = get_game_data()
    return _GameDataSnapshot(
        zone_name_overrides_by_lang=_freeze_nested_str_map(
            data.get("zone_name_overrides_by_lang", {})
        ),
        checkpoint_names_by_lang=_freeze_nested_str_map(data.get("checkpoint_names_by_lang", {})),
        tower_stages_by_lang=_freeze_nested_str_map(data.get("tower_stages_by_lang", {})),
        localized_presentation=_freeze_nested_str_map(data.get("localized_presentation", {})),
        contextual_checkpoints=tuple(
            MappingProxyType(dict(item)) for item in data.get("contextual_checkpoints", [])
        ),
        endless_tower_trials=tuple(
            _build_endless_tower_trials(data.get("endless_tower_trials", []))
        ),
    )


_orig_game_data_cache_clear = get_game_data.cache_clear


def _clear_game_data_caches() -> None:
    _orig_game_data_cache_clear()
    _get_snapshot.cache_clear()


get_game_data.cache_clear = _clear_game_data_caches


def get_zone_name_overrides_by_lang() -> Mapping[str, Mapping[str, str]]:
    """Returns zone name overrides mapping by language code, cached and immutable."""
    return _get_snapshot().zone_name_overrides_by_lang


def get_checkpoint_names_by_lang() -> Mapping[str, Mapping[str, str]]:
    """Returns checkpoint names mapping by language code, cached and immutable."""
    return _get_snapshot().checkpoint_names_by_lang


def get_tower_stages_by_lang() -> Mapping[str, Mapping[str, str]]:
    """Returns tower stage names mapping by language code, cached and immutable."""
    return _get_snapshot().tower_stages_by_lang


def get_localized_presentation() -> Mapping[str, Mapping[str, str]]:
    """Returns localized presentation strings mapping by language code, cached and immutable."""
    return _get_snapshot().localized_presentation


def get_contextual_checkpoints() -> tuple[Mapping[str, Any], ...]:
    """Returns contextual checkpoint matchers tuple, cached and immutable."""
    return _get_snapshot().contextual_checkpoints


def get_endless_tower_trials() -> tuple[TrialDefinition, ...]:
    """Returns parsed endless tower trials definitions tuple, cached and immutable."""
    return _get_snapshot().endless_tower_trials


LAZY_ATTRIBUTES = frozenset(
    {
        "TARGET_PROCESS_NAMES",
        "MAIN_MENU_TOKENS",
        "ZONE_NAME_OVERRIDES_BY_LANG",
        "CHECKPOINT_NAMES_BY_LANG",
        "TOWER_STAGES_BY_LANG",
        "LOCALIZED_PRESENTATION",
        "CONTEXTUAL_CHECKPOINTS",
        "ENDLESS_TOWER_TRIALS",
    }
)


class _GameDataModule(types.ModuleType):
    """Module proxy exposing lazy, typed properties for heavy JSON catalogs."""

    @property
    def TARGET_PROCESS_NAMES(self) -> tuple[str, ...]:
        return get_target_process_names()

    @property
    def MAIN_MENU_TOKENS(self) -> frozenset[str]:
        return get_main_menu_tokens()

    @property
    def ZONE_NAME_OVERRIDES_BY_LANG(self) -> Mapping[str, Mapping[str, str]]:
        return get_zone_name_overrides_by_lang()

    @property
    def CHECKPOINT_NAMES_BY_LANG(self) -> Mapping[str, Mapping[str, str]]:
        return get_checkpoint_names_by_lang()

    @property
    def TOWER_STAGES_BY_LANG(self) -> Mapping[str, Mapping[str, str]]:
        return get_tower_stages_by_lang()

    @property
    def LOCALIZED_PRESENTATION(self) -> Mapping[str, Mapping[str, str]]:
        return get_localized_presentation()

    @property
    def CONTEXTUAL_CHECKPOINTS(self) -> tuple[Mapping[str, Any], ...]:
        return get_contextual_checkpoints()

    @property
    def ENDLESS_TOWER_TRIALS(self) -> tuple[TrialDefinition, ...]:
        return get_endless_tower_trials()

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(__all__))


TARGET_PROCESS_NAMES: tuple[str, ...]
MAIN_MENU_TOKENS: frozenset[str]
ZONE_NAME_OVERRIDES_BY_LANG: dict[str, dict[str, str]]
CHECKPOINT_NAMES_BY_LANG: dict[str, dict[str, str]]
TOWER_STAGES_BY_LANG: dict[str, dict[str, str]]
LOCALIZED_PRESENTATION: dict[str, dict[str, str]]
CONTEXTUAL_CHECKPOINTS: list[dict[str, Any]]
ENDLESS_TOWER_TRIALS: list[TrialDefinition]

_current_mod = sys.modules[__name__]
_current_mod.__class__ = _GameDataModule


__all__ = [
    "ALL_SUPPORTED_LANGUAGES",
    "CONTEXTUAL_CHECKPOINTS",
    "CHECKPOINT_NAMES_BY_LANG",
    "DEFAULT_MAIN_MENU_TOKENS",
    "DEFAULT_TARGET_PROCESS_NAMES",
    "ENDLESS_TOWER_TRIALS",
    "LAZY_ATTRIBUTES",
    "LOCALIZED_PRESENTATION",
    "MAIN_MENU_TOKENS",
    "TARGET_PROCESS_NAMES",
    "TOWER_STAGES_BY_LANG",
    "TowerTrial",
    "TrialDefinition",
    "ZONE_NAME_OVERRIDES_BY_LANG",
    "get_game_data",
    "get_main_menu_tokens",
    "get_target_process_names",
]
