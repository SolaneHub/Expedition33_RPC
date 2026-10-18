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
