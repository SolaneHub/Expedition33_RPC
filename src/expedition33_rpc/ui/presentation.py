"""Unified presentation formatting and localization logic for Expedition 33 RPC.

Consolidates user-facing presentation formatting for Discord Rich Presence
wire protocol (details, state, limits) and Win32 system tray tooltips / menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

from expedition33_rpc.detection.game_data import LOCALIZED_PRESENTATION, TOWER_STAGES_BY_LANG
from expedition33_rpc.detection.normalization import (
    is_continent_zone,
    is_menu_zone,
    normalize_language_code,
)

DISCORD_MAX_FIELD_LENGTH = 128


def get_presentation_strings(lang: str) -> dict[str, str]:
    """Retrieves presentation formatting strings for the specified language with fallback."""
    canon = normalize_language_code(lang)
    return LOCALIZED_PRESENTATION.get(canon, LOCALIZED_PRESENTATION["en-US"])


def truncate_presence_field(text: str, max_length: int = DISCORD_MAX_FIELD_LENGTH) -> str:
    """Enforces Discord IPC string limits (max 128 characters for details and state).

    If text exceeds max_length, it is deterministically clamped to the boundary.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length]


def format_location_name(game_state: GameState) -> str:
    """Formats the zone name including trial, floor, or checkpoint details."""
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    zone_display = game_state.zone_name or strings["traveling"]

    if game_state.tower_stage_trial:
        match game_state.tower_stage_trial:
            case (stg, trl) if isinstance(stg, int) and isinstance(trl, int):
                trial_key = f"ST_BattleTowerStages_Stage_{stg:02d}_Trial_{trl:02d}"
                lang_trials = TOWER_STAGES_BY_LANG.get(canon, {})
                if canon in ("it", "en-US") or trial_key not in lang_trials:
                    trial_label = strings["stage_trial"].format(stage=stg, trial=trl)
                else:
                    trial_label = lang_trials[trial_key]
            case other:
                trial_label = str(other)
        return f"{zone_display} ({trial_label})"

    if game_state.tower_floor:
        floor = game_state.tower_floor
        floor_label = strings["floor"].format(floor=floor)
        floor_word = strings["floor"].replace("{floor}", "").strip().lower()
        if floor_word not in zone_display.lower() and "floor" not in zone_display.lower():
            return f"{zone_display} ({floor_label})"
        return zone_display

    if game_state.checkpoint_name and not is_continent_zone(game_state):
        return f"{zone_display} ({game_state.checkpoint_name})"

    return zone_display


def format_presence(game_state: GameState, anti_spoiler: bool = False) -> tuple[str, str]:
    """Generates details and state strings for Discord Rich Presence wire protocol."""
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)

    if is_menu_zone(game_state):
        details = strings["in_menu"]
        state = strings["title_screen"]
        return truncate_presence_field(details), truncate_presence_field(state)

    if game_state.in_combat:
        if anti_spoiler or not game_state.enemy_name:
            details = strings["in_combat"]
        else:
            details = strings["fighting"].format(enemy=game_state.enemy_name)
        state = strings["hidden_location"] if anti_spoiler else format_location_name(game_state)
        return truncate_presence_field(details), truncate_presence_field(state)

    details = strings["exploring"]
    state = strings["hidden_location"] if anti_spoiler else format_location_name(game_state)
    return truncate_presence_field(details), truncate_presence_field(state)


def format_tray_title(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the system tray icon tooltip (pystray.Icon.title)."""
    if not game_state.is_running:
        return "Expedition 33 RPC (Waiting for game...)"

    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    if is_menu_zone(game_state):
        return f"Expedition 33: {strings['in_menu']}"

    if anti_spoiler:
        mode = "In Combat" if game_state.in_combat else "Exploring"
        return f"Expedition 33: [Protected] ({mode})"

    if game_state.in_combat and game_state.enemy_name:
        mode = f"Fighting: {game_state.enemy_name}"
    else:
        mode = "In Combat" if game_state.in_combat else "Exploring"

    loc = format_location_name(game_state)
    return f"Expedition 33: {loc} ({mode})"


def format_tray_zone_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Location line for the system tray menu."""
    if not game_state.is_running:
        return "Location: --"
    if is_menu_zone(game_state):
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        return f"Location: {strings['in_menu']}"
    if anti_spoiler:
        return "Location: [Hidden - Anti-Spoiler]"
    loc = format_location_name(game_state)
    return f"Location: {loc}"


def format_tray_combat_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Status / Combat line for the system tray menu."""
    if not game_state.is_running:
        return "Status: --"
    if is_menu_zone(game_state):
        canon = normalize_language_code(game_state.game_language)
        if canon == "it":
            return "Status: Nel menu principale"
        elif canon == "en-US":
            return "Status: Main Menu"
        else:
            strings = get_presentation_strings(canon)
            return f"Status: {strings['in_menu']}"
    if game_state.in_combat:
        if not anti_spoiler and game_state.enemy_name:
            return f"Combat: Fighting {game_state.enemy_name}"
        return "Status: In Combat"
    return "Status: Exploring"


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "LOCALIZED_PRESENTATION",
    "get_presentation_strings",
    "truncate_presence_field",
    "format_presence",
    "format_location_name",
    "is_menu_zone",
    "is_continent_zone",
    "format_tray_title",
    "format_tray_zone_status",
    "format_tray_combat_status",
]
