"""Unified presentation formatting and localization logic for Expedition 33 RPC.

Consolidates user-facing presentation formatting for Discord Rich Presence
wire protocol (details, state, limits) and Win32 system tray tooltips / menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

from expedition33_rpc.detection.normalization import (
    format_location_name,
    is_menu_zone,
)

DISCORD_MAX_FIELD_LENGTH = 128


def truncate_presence_field(text: str, max_length: int = DISCORD_MAX_FIELD_LENGTH) -> str:
    """Enforces Discord IPC string limits (max 128 characters for details and state).

    If text exceeds max_length, it is deterministically clamped to the boundary.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length]


def format_presence(game_state: GameState, anti_spoiler: bool = False) -> tuple[str, str]:
    """Generates details and state strings for Discord Rich Presence wire protocol."""
    is_it = game_state.game_language.startswith("it")

    if is_menu_zone(game_state):
        details = "Nel menu principale" if is_it else "In Main Menu"
        state = "Schermata dei titoli" if is_it else "Title Screen"
        return truncate_presence_field(details), truncate_presence_field(state)

    if game_state.in_combat:
        if anti_spoiler or not game_state.enemy_name:
            details = "In combattimento" if is_it else "In Combat"
        else:
            details = (
                f"In combattimento con: {game_state.enemy_name}"
                if is_it
                else f"Fighting: {game_state.enemy_name}"
            )
        state = (
            ("Posizione riservata" if is_it else "Hidden Location")
            if anti_spoiler
            else format_location_name(game_state)
        )
        return truncate_presence_field(details), truncate_presence_field(state)

    details = "In esplorazione" if is_it else "Exploring"
    state = (
        ("Posizione riservata" if is_it else "Hidden Location")
        if anti_spoiler
        else format_location_name(game_state)
    )
    return truncate_presence_field(details), truncate_presence_field(state)


def format_tray_title(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the system tray icon tooltip (pystray.Icon.title)."""
    if not game_state.is_running:
        return "Expedition 33 RPC (Waiting for game...)"

    is_it = game_state.game_language.startswith("it")
    if is_menu_zone(game_state):
        return "Expedition 33: Nel menu principale" if is_it else "Expedition 33: In Main Menu"

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
        is_it = game_state.game_language.startswith("it")
        return f"Location: {'Nel menu principale' if is_it else 'In Main Menu'}"
    if anti_spoiler:
        return "Location: [Hidden - Anti-Spoiler]"
    loc = format_location_name(game_state)
    return f"Location: {loc}"


def format_tray_combat_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Status / Combat line for the system tray menu."""
    if not game_state.is_running:
        return "Status: --"
    if is_menu_zone(game_state):
        is_it = game_state.game_language.startswith("it")
        return "Status: Nel menu principale" if is_it else "Status: Main Menu"
    if game_state.in_combat:
        if not anti_spoiler and game_state.enemy_name:
            return f"Combat: Fighting {game_state.enemy_name}"
        return "Status: In Combat"
    return "Status: Exploring"


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "truncate_presence_field",
    "format_presence",
    "format_tray_title",
    "format_tray_zone_status",
    "format_tray_combat_status",
]
