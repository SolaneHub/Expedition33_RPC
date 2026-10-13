"""Domain-level string normalization and game state value formatting.

Pure domain functions independent of Discord IPC and UI presentation layers.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterator, Mapping
from typing import Any

from expedition33_rpc.detection.game_data import (
    ALL_SUPPORTED_LANGUAGES,
    CHECKPOINT_NAMES_BY_LANG,
    CONTEXTUAL_CHECKPOINTS,
    ENDLESS_TOWER_TRIALS,
    LOCALIZED_PRESENTATION,
    MAIN_MENU_TOKENS,
    ZONE_NAME_OVERRIDES_BY_LANG,
    TowerTrial,
)


def _normalize_alphanumeric_key(text: str) -> str:
    """Strips all non-alphanumeric characters and converts to lowercase for O(1) key indexing."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_language_code(lang: str | None) -> str:
    """Normalizes raw language codes (e.g. 'it-IT', 'fr_FR', 'zh-CN') to canonical game language codes."""
    if not lang:
        return "en-US"
    c = lang.strip().lower().replace("_", "-")
    match c:
        case "en" | "en-us" | "en-gb":
            return "en-US"
        case "it" | "it-it":
            return "it"
        case "fr" | "fr-fr" | "fr-ca":
            return "fr-FR"
        case "de" | "de-de" | "de-at" | "de-ch":
            return "de"
        case "es-419" | "es-mx" | "es-ar" | "es-co" | "es-cl" | "es-latam":
            return "es-419"
        case "es" | "es-es":
            return "es"
        case "pt-br" | "pt":
            return "pt-BR"
        case "ja" | "ja-jp":
            return "ja"
        case "ko" | "ko-kr":
            return "ko"
        case "zh-hans" | "zh-cn" | "zh-sg" | "zh":
            return "zh-Hans"
        case "zh-hant" | "zh-tw" | "zh-hk":
            return "zh-Hant"
        case "ru" | "ru-ru":
            return "ru"
        case "pl" | "pl-pl":
            return "pl"
        case "ar" | "ar-sa" | "ar-ae" | "ar-eg":
            return "ar"
        case "cs" | "cs-cz":
            return "cs"
        case "tr" | "tr-tr":
            return "tr"
        case "uk" | "uk-ua":
            return "uk"
        case "th" | "th-th":
            return "th"
        case "vi" | "vi-vn":
            return "vi"
        case "id" | "id-id":
            return "id"
        case _:
            prefix = c.split("-")[0]
            for canon in ALL_SUPPORTED_LANGUAGES:
                if canon.lower().startswith(prefix):
                    return canon
            return "en-US"


@functools.lru_cache(maxsize=32)
def get_checkpoint_hash_map(lang: str) -> dict[str, str]:
    """Computes normalized checkpoint hash maps on demand with caching."""
    table = CHECKPOINT_NAMES_BY_LANG.get(lang)
    if table is None:
        return {}
    return {_normalize_alphanumeric_key(k): v for k, v in table.items()}


# Backward-compatible hash map lookup mapping
class _CheckpointHashMapLookup(Mapping[str, dict[str, str]]):
    def __getitem__(self, lang: str) -> dict[str, str]:
        res = get_checkpoint_hash_map(lang)
        if not res and lang not in CHECKPOINT_NAMES_BY_LANG:
            raise KeyError(lang)
        return res

    def __iter__(self) -> Iterator[str]:
        return iter(CHECKPOINT_NAMES_BY_LANG)

    def __len__(self) -> int:
        return len(CHECKPOINT_NAMES_BY_LANG)

    def __contains__(self, key: object) -> bool:
        return key in CHECKPOINT_NAMES_BY_LANG

    def get(self, key: str, default: Any = None) -> Any:
        res = get_checkpoint_hash_map(key)
        return res if res else default


CHECKPOINT_HASH_MAPS_BY_LANG: Mapping[str, dict[str, str]] = _CheckpointHashMapLookup()


def strip_accents(text: str) -> str:
    """Removes diacritics/accents from text for consistent cross-matching (e.g. 'Sirene' -> 'Sirene')."""
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def is_main_menu(raw_zone: str | None, zone_display: str | None = None) -> bool:
    """Returns True if the zone identifier or display string indicates a main menu or title screen."""
    if not raw_zone and not zone_display:
        return False
    raw_lower = (raw_zone or "").lower().strip()
    display_lower = (zone_display or "").lower().strip()
    if raw_lower in MAIN_MENU_TOKENS:
        return True
    norm_display = strip_accents(display_lower)
    if "menu" in raw_lower or "menu" in norm_display:
        return True
    return any(
        table.get("mainmenu", "").lower() == display_lower
        for table in ZONE_NAME_OVERRIDES_BY_LANG.values()
    )


def is_menu_zone(
    raw_zone_or_state: Any = None,
    zone_name: str | None = None,
    *,
    raw_zone: str | None = None,
) -> bool:
    """Detects if raw_zone, zone_name, or a GameState indicates a main menu or title screen."""
    target = raw_zone if raw_zone is not None else raw_zone_or_state
    if hasattr(target, "raw_zone"):
        return is_main_menu(getattr(target, "raw_zone", None), getattr(target, "zone_name", None))
    return is_main_menu(target, zone_name)


def is_continent_zone(
    raw_zone_or_state: Any = None,
    zone_name: str | None = None,
    *,
    raw_zone: str | None = None,
) -> bool:
    """Detects if current location strings or a GameState represent the world map / continent."""
    target = raw_zone if raw_zone is not None else raw_zone_or_state
    if hasattr(target, "raw_zone"):
        raw = (getattr(target, "raw_zone", "") or "").lower()
        zone = (getattr(target, "zone_name", None) or "").lower()
    else:
        raw = (target or "").lower()
        zone = (zone_name or "").lower()
    return "continent" in zone or "continente" in zone or "worldmap" in raw


def format_enemy_name(enemy_name: str) -> str:
    """Formats and normalizes enemy names, converting 'Chromatic' to in-game official 'Alpha' and tier formatting."""
    if not enemy_name:
        return ""
    if "UObject:" in enemy_name or "0x" in enemy_name:
        return ""

    formatted = enemy_name
    # Format T1 / T2 / T3 suffix as (Tier 1) / (Tier 2) / (Tier 3)
    formatted = re.sub(r"\bT(\d+)\b", r"(Tier \1)", formatted)

    # In-game chromatic variants are officially called 'Alpha'
    formatted = re.sub(r"\bChromatic\b", "Alpha", formatted, flags=re.IGNORECASE)
    formatted = re.sub(r"\bCromatic[oaie]\b", "Alpha", formatted, flags=re.IGNORECASE)

    return formatted.strip()


def resolve_tower_trial(
    enemy_name: str | list[str] = "",
    *,
    enemies: list[str] | None = None,
) -> tuple[TowerTrial | None, str]:
    """Determines the (stage, trial) in Endless Tower and the clean boss/enemy name.

    Operates deterministically on structured enemy lists or exact names, with
    transparent fallback to single enemy string when structured data is absent.
    """
    structured: list[str] = []
    single_name = ""

    if isinstance(enemy_name, (list, tuple)):
        structured = [str(x) for x in enemy_name if x]
        single_name = ", ".join(structured)
    elif isinstance(enemy_name, str):
        single_name = enemy_name
        if enemies:
            structured = [str(x) for x in enemies if x]
        if not single_name and structured:
            single_name = ", ".join(structured)

    if not single_name and not structured:
        return None, ""

    normalized_single = format_enemy_name(single_name) if single_name else ""

    # 1. Primary path: Match against structured enemy names if available
    if structured:
        cleaned_list = [
            re.sub(r"\(Tier \d+\)", "", format_enemy_name(e), flags=re.IGNORECASE).strip().lower()
            for e in structured
        ]
        for stage_info, boss_name, enemy_groups in ENDLESS_TOWER_TRIALS:
            if all(
                any(any(variant.lower() in e for e in cleaned_list) for variant in group)
                for group in enemy_groups
            ):
                final_enemy = boss_name if boss_name else normalized_single
                return stage_info, final_enemy

    # 2. Fallback path: Match against exact single/summary string
    if normalized_single:
        cleaned_str = re.sub(r"\(Tier \d+\)", "", normalized_single, flags=re.IGNORECASE)
        cleaned_str = re.sub(r"\bT\d+\b", "", cleaned_str, flags=re.IGNORECASE).lower()

        for stage_info, boss_name, enemy_groups in ENDLESS_TOWER_TRIALS:
            if all(
                any(variant.lower() in cleaned_str for variant in group) for group in enemy_groups
            ):
                final_enemy = boss_name if boss_name else normalized_single
                return stage_info, final_enemy

    return None, normalized_single


def format_zone_name(raw_name: str, lang: str = "en") -> str:
    """Converts internal Unreal Engine map names (e.g. Level_Sirene_Main_V2) to player-friendly titles."""
    canon_lang = normalize_language_code(lang)

    if not raw_name:
        strings = LOCALIZED_PRESENTATION.get(canon_lang, LOCALIZED_PRESENTATION.get("en-US", {}))
        return strings.get("exploring", "Exploring")

    if is_main_menu(raw_name):
        if canon_lang == "it":
            return "Nel menu principale"
        lang_overrides = ZONE_NAME_OVERRIDES_BY_LANG.get(canon_lang) or {}
        if "mainmenu" in lang_overrides:
            return lang_overrides["mainmenu"]
        strings = LOCALIZED_PRESENTATION.get(canon_lang, LOCALIZED_PRESENTATION.get("en-US", {}))
        return strings.get("in_menu", "Main Menu")

    continent_names = {
        "main",
        "worldmap",
        "world_map",
        "worldmap_main",
        "level_worldmap",
        "level_worldmap_main",
        "level_worldmap_main_v2",
    }
    lang_overrides = ZONE_NAME_OVERRIDES_BY_LANG.get(canon_lang) or ZONE_NAME_OVERRIDES_BY_LANG.get(
        "en-US", {}
    )
    if raw_name.lower().strip() in continent_names or "worldmap" in raw_name.lower():
        return lang_overrides.get("worldmap", "The Continent")

    cleaned = raw_name
    for prefix in [
        "Level_Side_",
        "Level_Small_",
        "Level_Main_",
        "Level_WorldMap_",
        "Level_",
        "SideLevel_",
        "SmallLevel_",
        "MainLevel_",
        "SubLevel_",
    ]:
        if cleaned.startswith(prefix):
            cleaned = cleaned.removeprefix(prefix)
            break

    cleaned = re.sub(r"_V\d+$", "", cleaned)
    cleaned = re.sub(r"_C$", "", cleaned)
    cleaned = re.sub(r"_\d+$", "", cleaned)
    cleaned = re.sub(r"_Main$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("_", " ")

    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    normalized = spaced.strip().lower()

    if normalized in ("main", "world map", "worldmap"):
        return lang_overrides.get("worldmap", "The Continent")

    # Check official overrides for active language
    override = lang_overrides.get(normalized) or lang_overrides.get(cleaned.lower().strip())
    if override:
        return override

    # Fallback to English overrides
    if canon_lang != "en-US":
        en_overrides = ZONE_NAME_OVERRIDES_BY_LANG.get("en-US", {})
        en_override = en_overrides.get(normalized) or en_overrides.get(cleaned.lower().strip())
        if en_override:
            return en_override

    return spaced.strip()


def format_checkpoint_tag(
    tag: str,
    *,
    zone: str = "",
    lang: str = "en",
) -> str:
    """Returns the official in-game Expedition Flag name for a given SpawnPoint tag."""
    if not tag:
        return ""

    clean_tag = tag.removeprefix("Level.SpawnPoint.")
    parts = clean_tag.split(".")
    suffix = parts[-1]
    if suffix in ("WorldMap", "Generic", "Dynamic", "Editor", "todelete", "None", "Default"):
        return ""

    canon_lang = normalize_language_code(lang)
    fallback_dict = CHECKPOINT_NAMES_BY_LANG.get("en-US", {})
    name_dict = CHECKPOINT_NAMES_BY_LANG.get(canon_lang) or fallback_dict
    fallback_hash_map = get_checkpoint_hash_map("en-US")
    hash_map = get_checkpoint_hash_map(canon_lang) or fallback_hash_map

    clean_tag_lower = clean_tag.lower()
    suffix_lower = suffix.lower()
    norm_suffix = _normalize_alphanumeric_key(suffix_lower)
    norm_clean = _normalize_alphanumeric_key(clean_tag_lower)

    # 1. Full dotted tag lookup (e.g. AncientSanctuary.RedForest, EsquieNest.Francois)
    if "." in clean_tag:
        res = (
            name_dict.get(clean_tag)
            or fallback_dict.get(clean_tag)
            or hash_map.get(norm_clean)
            or fallback_hash_map.get(norm_clean)
        )
        if res:
            return res

    # 2. Declarative contextual zone matching from game_data.json
    if zone:
        z_norm = strip_accents(zone).lower()
        for rule in CONTEXTUAL_CHECKPOINTS:
            if not any(k in z_norm for k in rule.get("zone_keywords", [])):
                continue
            if "zone_required" in rule and not any(k in z_norm for k in rule["zone_required"]):
                continue
            if "zone_exclude" in rule and any(k in z_norm for k in rule["zone_exclude"]):
                continue
            if "tag_contains" in rule and not any(
                k in clean_tag_lower for k in rule["tag_contains"]
            ):
                continue
            if ("contains" in rule and any(k in norm_suffix for k in rule["contains"])) or (
                "suffixes" in rule and norm_suffix in rule["suffixes"]
            ):
                by_lang = rule.get("by_lang")
                if isinstance(by_lang, dict):
                    if canon_lang in by_lang:
                        return by_lang[canon_lang]
                    if "en-US" in by_lang:
                        return by_lang["en-US"]
                if canon_lang == "it" and "it" in rule:
                    return rule["it"]
                return rule.get("en", "")

    # 3. Direct dictionary lookup by suffix / clean_tag in O(1)
    res = (
        name_dict.get(suffix)
        or fallback_dict.get(suffix)
        or hash_map.get(norm_suffix)
        or fallback_hash_map.get(norm_suffix)
        or hash_map.get(norm_clean)
        or fallback_hash_map.get(norm_clean)
    )
    if res:
        return res

    # 4. Spacing fallback
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", suffix)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced).strip()
    if spaced.lower() in ("entry", "entrance"):
        return name_dict.get("entrance") or fallback_dict.get("entrance", "Entrance")
    return spaced


__all__ = [
    "CHECKPOINT_HASH_MAPS_BY_LANG",
    "get_checkpoint_hash_map",
    "normalize_language_code",
    "strip_accents",
    "is_main_menu",
    "is_menu_zone",
    "is_continent_zone",
    "format_enemy_name",
    "resolve_tower_trial",
    "format_zone_name",
    "format_checkpoint_tag",
]
