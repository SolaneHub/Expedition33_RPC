"""CI test validating static game_data.json schema and catalog integrity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.verify_game_data import verify_game_data

pytestmark = pytest.mark.ci


def test_game_data_ssot_integrity() -> None:
    """Verifies that the canonical game_data.json passes all SSOT integrity checks."""
    is_valid, errors = verify_game_data()
    assert is_valid, f"Game data integrity verification failed: {errors}"
    assert len(errors) == 0


def test_verify_game_data_detects_missing_language(tmp_path: Path) -> None:
    """Verifies verify_game_data fails when a required language is missing."""
    invalid_data = {
        "localized_presentation": {
            "en-US": {
                "in_menu": "In Menu",
                "title_screen": "Title Screen",
                "exploring": "Exploring",
                "in_combat": "In Combat",
                "fighting": "Fighting",
                "hidden_location": "Hidden Location",
                "traveling": "Traveling",
                "floor": "Floor",
                "stage_trial": "Stage Trial",
            }
        },
        "zone_name_overrides_by_lang": {"en-US": {"Zone": "Zone"}},
        "checkpoint_names_by_lang": {"en-US": {"CP": "CP"}},
        "endless_tower_trials": [],
    }
    test_file = tmp_path / "game_data_broken.json"
    test_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    is_valid, errors = verify_game_data(test_file)
    assert is_valid is False
    assert any("Language 'it' is missing from 'localized_presentation'" in e for e in errors)


def test_verify_game_data_detects_malformed_trials(tmp_path: Path) -> None:
    """Verifies verify_game_data fails when endless_tower_trials has invalid entries."""
    invalid_data = {
        "localized_presentation": {},
        "zone_name_overrides_by_lang": {},
        "checkpoint_names_by_lang": {},
        "endless_tower_trials": [
            [[1], None, [["Variant"]]],  # Coordinate list length != 2
            [[1, 2], None, []],  # Empty variants
        ],
    }
    test_file = tmp_path / "game_data_trials_broken.json"
    test_file.write_text(json.dumps(invalid_data), encoding="utf-8")

    is_valid, errors = verify_game_data(test_file)
    assert is_valid is False
    assert any("invalid [stage, trial] coordinates" in e for e in errors)
    assert any("must have non-empty variants list" in e for e in errors)
