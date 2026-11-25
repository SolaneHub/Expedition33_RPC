"""Unified presentation formatting and localization logic for Expedition 33 RPC.

Consolidates user-facing presentation formatting for Discord Rich Presence
wire protocol (details, state, limits) and Win32 system tray tooltips / menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

from expedition33_rpc.core.presence import (
    format_location_name,
    get_presentation_strings,
)
from expedition33_rpc.detection.normalization import (
    is_main_menu,
    normalize_language_code,
    resolve_menu_substate,
)

WIN32_MAX_TRAY_TITLE_LENGTH: int = 127


def format_tray_title(game_state: GameState | None, anti_spoiler: bool = False) -> str:
    """Formats the system tray icon tooltip (pystray.Icon.title)."""
    if game_state is None or not game_state.is_running:
        title = "Expedition 33 RPC (Waiting for game...)"
    elif game_state.is_starting:
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        title = f"Expedition 33: {strings.get('starting', 'Starting...')}"
    elif is_main_menu(game_state.raw_zone, game_state.zone_name):
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        substate = resolve_menu_substate(
            game_state.raw_zone, game_state.zone_name, is_starting=game_state.is_starting
        )
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
    if is_main_menu(game_state.raw_zone, game_state.zone_name):
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
    if is_main_menu(game_state.raw_zone, game_state.zone_name):
        substate = resolve_menu_substate(
            game_state.raw_zone, game_state.zone_name, is_starting=game_state.is_starting
        )
        sub_text = strings.get(substate, strings["main_menu"])
        return f"Status: {sub_text}"
    if game_state.in_combat:
        if not anti_spoiler and game_state.enemy_name:
            return f"Combat: Fighting {game_state.enemy_name}"
        return "Status: In Combat"
    return "Status: Exploring"


__all__ = [
    "WIN32_MAX_TRAY_TITLE_LENGTH",
    "format_tray_title",
    "format_tray_zone_status",
    "format_tray_combat_status",
]
