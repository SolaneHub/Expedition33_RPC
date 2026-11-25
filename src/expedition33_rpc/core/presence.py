"""Immutable Rich Presence transfer payload DTO and formatting functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

import expedition33_rpc.detection.game_data as game_data
from expedition33_rpc.detection.normalization import (
    is_continent_zone,
    is_main_menu,
    normalize_language_code,
    resolve_menu_substate,
)

DISCORD_MAX_FIELD_LENGTH: int = 128


def truncate_presence_field(text: str, max_bytes: int = DISCORD_MAX_FIELD_LENGTH) -> str:
    """Enforces Discord IPC string limits (max 128 bytes for details and state).

    If text exceeds max_bytes, it is deterministically clamped to the byte boundary
    without splitting multibyte sequences.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


@dataclass(frozen=True, slots=True)
class PresencePayload:
    details: str | None
    state: str | None
    start_timestamp: int | None = None
    large_image: str | None = None
    large_text: str | None = None


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

    if game_state.checkpoint_name and not is_continent_zone(
        game_state.raw_zone, game_state.zone_name
    ):
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

    if is_main_menu(game_state.raw_zone, game_state.zone_name):
        substate = resolve_menu_substate(
            game_state.raw_zone, game_state.zone_name, is_starting=game_state.is_starting
        )
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


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "PresencePayload",
    "build_presence_payload",
    "format_location_name",
    "format_presence",
    "get_presentation_strings",
    "truncate_presence_field",
]
