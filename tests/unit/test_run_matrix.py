"""Unit tests for tools/run_matrix.py."""

from __future__ import annotations

import pytest
from tools.run_matrix import TIER_SLAS, get_steps_for_tier, parse_args


@pytest.mark.unit
def test_parse_args_valid_tiers() -> None:
    for tier in ("fast", "pr", "release", "soak"):
        ns = parse_args(["--tier", tier])
        assert ns.tier == tier


@pytest.mark.unit
def test_parse_args_invalid_tier_exits() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--tier", "unknown"])


@pytest.mark.unit
def test_tier_step_hierarchy_and_commands() -> None:
    fast_steps = get_steps_for_tier("fast")
    pr_steps = get_steps_for_tier("pr")
    release_steps = get_steps_for_tier("release")
    soak_steps = get_steps_for_tier("soak")

    assert len(fast_steps) == 4
    assert pr_steps[: len(fast_steps)] == fast_steps
    assert release_steps[: len(pr_steps)] == pr_steps

    # Verify PYSTRAY_BACKEND=dummy on pytest and smoke-test steps
    for step in release_steps:
        if "pytest" in step.command or "--smoke-test" in step.command:
            assert step.env_overrides == {"PYSTRAY_BACKEND": "dummy"}

    assert any("soak" in step.command for step in soak_steps)
    assert any("tools/verify_save_reader_dormancy.py" in step.command for step in soak_steps)


@pytest.mark.unit
def test_tier_slas_defined() -> None:
    assert TIER_SLAS["fast"] == 2.5
    assert TIER_SLAS["pr"] == 8.0
    assert TIER_SLAS["release"] == 15.0
    assert TIER_SLAS["soak"] is None
