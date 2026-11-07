#!/usr/bin/env python3
"""Static SSOT game_data integrity validator for Clair Obscur: Expedition 33 RPC.

Validates that:
a) All 20 supported languages in ALL_SUPPORTED_LANGUAGES are present in localized_presentation
   with all required presentation keys (in_menu, title_screen, exploring, in_combat,
   fighting, hidden_location, traveling, floor, stage_trial).
b) All language dictionaries in zone_name_overrides_by_lang and checkpoint_names_by_lang
   are present, non-empty, and contain non-empty key/value mappings.
c) All 33 stage trials in endless_tower_trials adhere strictly to the schema:
   [[stage, trial], boss_name, [[variants]]].
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from expedition33_rpc.detection.game_data import ALL_SUPPORTED_LANGUAGES

REQUIRED_PRESENTATION_KEYS: frozenset[str] = frozenset(
    {
        "in_menu",
        "title_screen",
        "exploring",
        "in_combat",
        "fighting",
        "hidden_location",
        "traveling",
        "floor",
        "stage_trial",
        "starting",
        "loading",
        "initial_screen",
        "main_menu",
        "loading_save",
        "in_settings",
        "new_game",
    }
)

EXPECTED_STAGE_TRIALS_COUNT: int = 33


def resolve_game_data_path() -> Path:
    """Finds the absolute path to game_data.json in assets."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    candidate = repo_root / "src" / "expedition33_rpc" / "assets" / "game_data.json"
    if candidate.is_file():
        return candidate

    # Fallback to resources module resolution if available
    try:
        from expedition33_rpc.core.resources import get_resource_path

        resolved = Path(get_resource_path("game_data.json"))
        if resolved.is_file():
            return resolved
    except Exception:
        pass

    raise FileNotFoundError(f"Cannot locate game_data.json at candidate: {candidate}")


def validate_localized_presentation(data: dict[str, Any], errors: list[str]) -> None:
    """Validates that all supported languages have complete presentation strings."""
    presentation = data.get("localized_presentation")
    if not isinstance(presentation, dict):
        errors.append("Missing or invalid 'localized_presentation' dictionary")
        return

    for lang in ALL_SUPPORTED_LANGUAGES:
        if lang not in presentation:
            errors.append(f"Language '{lang}' is missing from 'localized_presentation'")
            continue

        lang_dict = presentation[lang]
        if not isinstance(lang_dict, dict):
            errors.append(f"Presentation mapping for language '{lang}' is not a dict")
            continue

        missing_keys = REQUIRED_PRESENTATION_KEYS - set(lang_dict.keys())
        if missing_keys:
            errors.append(
                f"Language '{lang}' in 'localized_presentation' is missing required keys: {sorted(missing_keys)}"
            )

        for key in REQUIRED_PRESENTATION_KEYS:
            if key in lang_dict:
                val = lang_dict[key]
                if not isinstance(val, str) or not val.strip():
                    errors.append(
                        f"Language '{lang}' has empty or non-string presentation value for key '{key}'"
                    )


def validate_overrides_by_lang(data: dict[str, Any], field_name: str, errors: list[str]) -> None:
    """Validates that language override dictionaries are present and contain valid mappings."""
    mapping = data.get(field_name)
    if not isinstance(mapping, dict):
        errors.append(f"Missing or invalid '{field_name}' dictionary")
        return

    if not mapping:
        errors.append(f"'{field_name}' dictionary is empty")
        return

    for lang, submap in mapping.items():
        if not isinstance(submap, dict):
            errors.append(f"'{field_name}' entry for language '{lang}' is not a dict")
            continue

        if not submap:
            errors.append(f"'{field_name}' entry for language '{lang}' is empty")
            continue

        for k, v in submap.items():
            if not isinstance(k, str) or not k.strip():
                errors.append(f"'{field_name}' has empty key in language '{lang}'")
            if not isinstance(v, str) or not v.strip():
                errors.append(f"'{field_name}' has empty value for key '{k}' in language '{lang}'")


def validate_endless_tower_trials(data: dict[str, Any], errors: list[str]) -> None:
    """Validates that Endless Tower stage trials conform to [[stage, trial], boss, [[variants]]]."""
    trials = data.get("endless_tower_trials")
    if not isinstance(trials, list):
        errors.append("Missing or invalid 'endless_tower_trials' list")
        return

    stage_trials: list[list[Any]] = []
    super_boss_trials: list[list[Any]] = []

    for idx, item in enumerate(trials):
        if not isinstance(item, list) or len(item) != 3:
            errors.append(f"Trial at index {idx} does not have length 3: {item!r}")
            continue

        target, boss_name, variants = item[0], item[1], item[2]

        if isinstance(target, list):
            stage_trials.append(item)
            if len(target) != 2 or not all(isinstance(coord, int) for coord in target):
                errors.append(
                    f"Trial at index {idx} has invalid [stage, trial] coordinates: {target!r}"
                )
        elif isinstance(target, str):
            super_boss_trials.append(item)
        else:
            errors.append(
                f"Trial at index {idx} has invalid target type: {type(target)!r} ({target!r})"
            )

        if boss_name is not None and not isinstance(boss_name, str):
            errors.append(f"Trial at index {idx} has invalid boss_name type: {type(boss_name)!r}")

        if not isinstance(variants, list) or not variants:
            errors.append(f"Trial at index {idx} must have non-empty variants list: {variants!r}")
        else:
            for v_idx, var_group in enumerate(variants):
                if not isinstance(var_group, list) or not var_group:
                    errors.append(
                        f"Trial at index {idx} variants[{v_idx}] must be a non-empty list of strings"
                    )
                else:
                    for s in var_group:
                        if not isinstance(s, str) or not s.strip():
                            errors.append(
                                f"Trial at index {idx} variants[{v_idx}] contains empty string: {s!r}"
                            )

    if len(stage_trials) != EXPECTED_STAGE_TRIALS_COUNT:
        errors.append(
            f"Expected exactly {EXPECTED_STAGE_TRIALS_COUNT} stage trials, found {len(stage_trials)}"
        )


def verify_game_data(file_path: Path | None = None) -> tuple[bool, list[str]]:
    """Runs all integrity checks on game_data.json and returns (is_valid, errors)."""
    target_path = file_path if file_path is not None else resolve_game_data_path()
    if not target_path.is_file():
        return False, [f"File not found: {target_path}"]

    try:
        content = target_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as e:
        return False, [f"Failed to read or parse JSON from {target_path}: {e}"]

    if not isinstance(data, dict):
        return False, ["Root JSON object must be a dictionary"]

    errors: list[str] = []

    # a) Localized presentation check
    validate_localized_presentation(data, errors)

    # b) Overrides dictionary check
    validate_overrides_by_lang(data, "zone_name_overrides_by_lang", errors)
    validate_overrides_by_lang(data, "checkpoint_names_by_lang", errors)

    # c) Endless tower trials check
    validate_endless_tower_trials(data, errors)

    return len(errors) == 0, errors


def main() -> int:
    """CLI entrypoint returning 0 on success or 1 with error report."""
    target_path: Path | None = None
    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])

    try:
        path = target_path if target_path is not None else resolve_game_data_path()
    except Exception as exc:
        print(f"[ERROR] Failed to resolve game_data.json: {exc}", file=sys.stderr)
        return 1

    print(f"[INFO] Verifying game_data integrity for: {path}")
    is_valid, errors = verify_game_data(path)

    if is_valid:
        print(
            f"[SUCCESS] All game data integrity checks passed for {len(ALL_SUPPORTED_LANGUAGES)} languages."
        )
        return 0

    print(f"[FAIL] Found {len(errors)} game data integrity errors:", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
