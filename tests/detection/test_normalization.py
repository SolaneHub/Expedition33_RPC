"""Tests for domain string normalization and tower trial resolution."""

from __future__ import annotations

import pytest

from expedition33_rpc.detection.game_data import ENDLESS_TOWER_TRIALS
from expedition33_rpc.detection.normalization import (
    format_checkpoint_tag,
    format_enemy_name,
    format_zone_name,
    normalize_language_code,
    resolve_tower_trial,
)


@pytest.mark.unit
def test_resolve_tower_trial_empty_and_unresolved() -> None:
    assert resolve_tower_trial("") == (None, "")
    assert resolve_tower_trial([]) == (None, "")
    assert resolve_tower_trial(enemies=[]) == (None, "")

    trial, enemy = resolve_tower_trial("Unknown Foe (+3)")
    assert trial is None
    assert enemy == "Unknown Foe (+3)"

    trial_list, enemy_list = resolve_tower_trial(enemies=["Unknown Foe (+3)"])
    assert trial_list is None
    assert enemy_list == "Unknown Foe (+3)"


@pytest.mark.unit
def test_resolve_tower_trial_substring_collision() -> None:
    # A fake or non-existent enemy with a name that embeds a trial boss substring (e.g. "Cleopatra")
    # should NOT match a trial whose variant is "Clea" if exact token equality is required,
    # or ensure "SimonSays" doesn't falsely collide.
    trial, _ = resolve_tower_trial(enemies=["Cleopatra", "SimonSays"])
    assert trial is None


@pytest.mark.unit
def test_resolve_tower_trial_all_trials() -> None:
    for stage, boss, groups in ENDLESS_TOWER_TRIALS:
        names = [min(group, key=len) for group in groups]
        # Structured list in any permutation
        for shift in range(len(names)):
            permuted = names[shift:] + names[:shift]
            t_stage, t_enemy = resolve_tower_trial(enemies=permuted)
            assert t_stage == stage
            assert len(t_enemy) > 0
            if boss:
                assert t_enemy == boss

        # Exact joined string fallback
        summary = ", ".join(names)
        t_stage_s, t_enemy_s = resolve_tower_trial(summary)
        assert t_stage_s == stage
        assert len(t_enemy_s) > 0


@pytest.mark.unit
def test_normalization_basic_helpers() -> None:
    assert normalize_language_code("it-IT") == "it"
    assert normalize_language_code("en_US") == "en-US"
    assert normalize_language_code(None) == "en-US"
    assert format_enemy_name("Duollistes T1") == "Duollistes (Tier 1)"
    assert format_zone_name("") == "Exploring"
    assert format_checkpoint_tag("UnknownCheckpoint") == "Unknown Checkpoint"


@pytest.mark.unit
def test_lazy_loading_game_data_zero_io_on_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that importing and accessing normalization does not eagerly load game_data.json until needed."""
    from expedition33_rpc.detection import game_data, normalization

    # Clear cached game_data in lru_cache if any
    game_data.get_game_data.cache_clear()
    normalization.get_main_menu_displays.cache_clear()
    for attr in game_data.LAZY_ATTRIBUTES:
        game_data.__dict__.pop(attr, None)

    load_called = False
    original_load = game_data.get_game_data.__wrapped__

    def tracking_load():
        nonlocal load_called
        load_called = True
        return original_load()

    monkeypatch.setattr(game_data, "get_game_data", tracking_load)

    # Calling pure helpers that don't need game_data.json
    assert normalization.normalize_language_code("it") == "it"
    assert normalization.strip_accents("Lumière") == "Lumiere"
    assert load_called is False

    # Calling is_main_menu with a translated display name triggers lazy loading
    # e.g. "Hauptmenü" which is not a token and doesn't contain "menu" after strip_accents ("Hauptmenu" has "menu", but let's test a non-"menu" or check get_main_menu_displays directly)
    displays = normalization.get_main_menu_displays()
    assert load_called is True
    assert len(displays) > 0
