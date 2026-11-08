"""Unified presentation formatting and localization logic for Expedition 33 RPC.

Consolidates user-facing presentation formatting for Discord Rich Presence
wire protocol (details, state, limits) and Win32 system tray tooltips / menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

import expedition33_rpc.detection.game_data as game_data
from expedition33_rpc.core.presence import (
    DISCORD_MAX_FIELD_LENGTH,
    PresencePayload,
    truncate_presence_field,
)
from expedition33_rpc.detection.normalization import (
    is_continent_zone,
    is_menu_zone,
    normalize_language_code,
    resolve_menu_substate,
)

WIN32_MAX_TRAY_TITLE_LENGTH: int = 127


def get_presentation_strings(lang: str) -> dict[str, str]:
    """Retrieves presentation formatting strings for the specified language with fallback."""
    canon = normalize_language_code(lang)
    return game_data.LOCALIZED_PRESENTATION.get(canon, game_data.LOCALIZED_PRESENTATION["en-US"])


def format_location_name(game_state: GameState) -> str:
    """Formats the zone name including trial, floor, or checkpoint details."""
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    zone_display = game_state.zone_name or strings["traveling"]

    if game_state.tower_stage_trial:
        match game_state.tower_stage_trial:
            case (stg, trl) if isinstance(stg, int) and isinstance(trl, int):
                trial_key = f"ST_BattleTowerStages_Stage_{stg:02d}_Trial_{trl:02d}"
                lang_trials = game_data.TOWER_STAGES_BY_LANG.get(canon, {})
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

    if game_state.is_starting:
        details = strings.get("starting", "Starting...")
        state = strings.get("loading", "Loading...")
        return truncate_presence_field(details), truncate_presence_field(state)

    if is_menu_zone(game_state):
        substate = resolve_menu_substate(game_state)
        details = strings["in_menu"]
        state = strings.get(substate, strings["title_screen"])
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


def build_presence_payload(game_state: GameState, anti_spoiler: bool = False) -> PresencePayload:
    """Constructs an immutable PresencePayload DTO for Discord Rich Presence."""
    details, state = format_presence(game_state, anti_spoiler=anti_spoiler)
    start_timestamp = int(game_state.start_time) if game_state.start_time else None
    return PresencePayload(
        details=details,
        state=state,
        start_timestamp=start_timestamp,
        large_image="logo",
        large_text="Clair Obscur: Expedition 33",
    )


def format_tray_title(game_state: GameState | None, anti_spoiler: bool = False) -> str:
    """Formats the system tray icon tooltip (pystray.Icon.title)."""
    if game_state is None or not game_state.is_running:
        title = "Expedition 33 RPC (Waiting for game...)"
    elif game_state.is_starting:
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        title = f"Expedition 33: {strings.get('starting', 'Starting...')}"
    elif is_menu_zone(game_state):
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        substate = resolve_menu_substate(game_state)
        if substate == "main_menu":
            title = f"Expedition 33: {strings['in_menu']}"
        else:
            sub_text = strings.get(substate, "")
            if sub_text:
                title = f"Expedition 33: {strings['in_menu']} ({sub_text})"
            else:
                title = f"Expedition 33: {strings['in_menu']}"
    elif anti_spoiler:
        mode = "In Combat" if game_state.in_combat else "Exploring"
        title = f"Expedition 33: [Protected] ({mode})"
    else:
        if game_state.in_combat and game_state.enemy_name:
            mode = f"Fighting: {game_state.enemy_name}"
        else:
            mode = "In Combat" if game_state.in_combat else "Exploring"

        loc = format_location_name(game_state)
        title = f"Expedition 33: {loc} ({mode})"

    if len(title) > WIN32_MAX_TRAY_TITLE_LENGTH:
        return title[: WIN32_MAX_TRAY_TITLE_LENGTH - 3] + "..."
    return title


def format_tray_zone_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Location line for the system tray menu."""
    if not game_state.is_running:
        return "Location: --"
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    if game_state.is_starting:
        return f"Location: {strings.get('starting', 'Starting...')}"
    if is_menu_zone(game_state):
        return f"Location: {strings['in_menu']}"
    if anti_spoiler:
        return "Location: [Hidden - Anti-Spoiler]"
    loc = format_location_name(game_state)
    return f"Location: {loc}"


def format_tray_combat_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Status / Combat line for the system tray menu."""
    if not game_state.is_running:
        return "Status: --"
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    if game_state.is_starting:
        return f"Status: {strings.get('loading', 'Loading...')}"
    if is_menu_zone(game_state):
        substate = resolve_menu_substate(game_state)
        sub_text = strings.get(substate, strings["main_menu"])
        return f"Status: {sub_text}"
    if game_state.in_combat:
        if not anti_spoiler and game_state.enemy_name:
            return f"Combat: Fighting {game_state.enemy_name}"
        return "Status: In Combat"
    return "Status: Exploring"


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "WIN32_MAX_TRAY_TITLE_LENGTH",
    "get_presentation_strings",
    "truncate_presence_field",
    "format_presence",
    "build_presence_payload",
    "format_location_name",
    "is_menu_zone",
    "is_continent_zone",
    "format_tray_title",
    "format_tray_zone_status",
    "format_tray_combat_status",
]
