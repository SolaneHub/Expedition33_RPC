"""Cross-OS 4-tier verification matrix orchestrator for Expedition33_RPC.

Supports four execution granularities:
- fast:    Ruff lint/format, Pyright, unit tests (SLA < 2.5s)
- pr:      fast + integration tests + bridge zip check (SLA < 8.0s)
- release: pr + ci tests + cross-OS Pyright + Prettier + game_data + smoke test (SLA < 15.0s)
- soak:    soak tests + save reader dormancy verification (no strict SLA)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass

type TierName = str


@dataclass(frozen=True)
class MatrixStep:
    """A single command step in a verification tier."""

    name: str
    command: list[str]
    env_overrides: dict[str, str] | None = None


@dataclass(frozen=True)
class StepResult:
    """Execution result for a single MatrixStep."""

    name: str
    passed: bool
    duration_s: float
    returncode: int


TIER_SLAS: dict[TierName, float | None] = {
    "fast": 2.5,
    "pr": 8.0,
    "release": 15.0,
    "soak": None,
}

_FAST_STEPS: list[MatrixStep] = [
    MatrixStep("Ruff Linting", ["uv", "run", "ruff", "check"]),
    MatrixStep("Ruff Formatting", ["uv", "run", "ruff", "format", "--check"]),
    MatrixStep("Pyright Type Check", ["uv", "run", "pyright"]),
    MatrixStep(
        "Unit Tests",
        ["uv", "run", "pytest", "-m", "unit"],
        env_overrides={"PYSTRAY_BACKEND": "dummy"},
    ),
]

_PR_EXTRA_STEPS: list[MatrixStep] = [
    MatrixStep(
        "Integration Tests",
        ["uv", "run", "pytest", "-m", "integration"],
        env_overrides={"PYSTRAY_BACKEND": "dummy"},
    ),
    MatrixStep(
        "Bridge Zip Check",
        ["uv", "run", "python", "tools/build_bridge_zip.py", "--check"],
    ),
]

_RELEASE_EXTRA_STEPS: list[MatrixStep] = [
    MatrixStep(
        "CI Tests",
        ["uv", "run", "pytest", "-m", "ci"],
        env_overrides={"PYSTRAY_BACKEND": "dummy"},
    ),
    MatrixStep(
        "Pyright (Windows)",
        ["uv", "run", "pyright", "--pythonplatform", "Windows"],
    ),
    MatrixStep(
        "Pyright (Linux)",
        ["uv", "run", "pyright", "--pythonplatform", "Linux"],
    ),
    MatrixStep(
        "Prettier (game_data.json)",
        ["npx", "--yes", "prettier", "--check", "src/expedition33_rpc/assets/game_data.json"],
    ),
    MatrixStep(
        "Verify Game Data",
        ["uv", "run", "python", "tools/verify_game_data.py"],
    ),
    MatrixStep(
        "Smoke Test",
        ["uv", "run", "python", "-m", "expedition33_rpc", "--smoke-test"],
        env_overrides={"PYSTRAY_BACKEND": "dummy"},
    ),
]

_SOAK_STEPS: list[MatrixStep] = [
    MatrixStep(
        "Soak Tests",
        ["uv", "run", "pytest", "-m", "soak"],
        env_overrides={"PYSTRAY_BACKEND": "dummy"},
    ),
    MatrixStep(
        "Save Reader Dormancy",
        ["uv", "run", "python", "tools/verify_save_reader_dormancy.py"],
    ),
]


def get_steps_for_tier(tier: TierName) -> list[MatrixStep]:
    """Return the ordered list of MatrixStep objects for the given tier."""
    match tier:
        case "fast":
            return list(_FAST_STEPS)
        case "pr":
            return [*_FAST_STEPS, *_PR_EXTRA_STEPS]
        case "release":
            return [*_FAST_STEPS, *_PR_EXTRA_STEPS, *_RELEASE_EXTRA_STEPS]
        case "soak":
            return list(_SOAK_STEPS)
        case _:
            raise ValueError(f"Unknown tier: {tier!r}. Expected one of: fast, pr, release, soak.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the verification matrix runner."""
    parser = argparse.ArgumentParser(
        description="Run Expedition33_RPC verification matrix at the specified granularity."
    )
    parser.add_argument(
        "--tier",
        required=True,
        choices=["fast", "pr", "release", "soak"],
        help="Verification tier to execute.",
    )
    return parser.parse_args(argv)


def _print_summary(
    tier: TierName,
    results: list[StepResult],
    total_s: float,
    sla_s: float | None,
) -> None:
    """Print a tabular summary of step outcomes, durations, and SLA status."""
    print("\n" + "=" * 72)
    print(f"  VERIFICATION MATRIX SUMMARY — TIER: {tier.upper()}")
    print("=" * 72)
    print(f"  {'Step':<34} {'Status':<10} {'Duration':>10}")
    print("-" * 72)
    for r in results:
        status = "PASS" if r.passed else f"FAIL({r.returncode})"
        print(f"  {r.name:<34} {status:<10} {r.duration_s:>9.2f}s")
    print("-" * 72)
    sla_note = ""
    if sla_s is not None:
        if total_s > sla_s:
            sla_note = f"  [SLA BREACH: {total_s:.2f}s > {sla_s:.1f}s]"
        else:
            sla_note = f"  [SLA OK: <= {sla_s:.1f}s]"
    print(f"  {'TOTAL':<34} {'':<10} {total_s:>9.2f}s{sla_note}")
    print("=" * 72)


def run_tier(tier: TierName) -> int:
    """Execute all steps for the given tier with fail-fast semantics."""
    steps = get_steps_for_tier(tier)
    sla_s = TIER_SLAS[tier]
    results: list[StepResult] = []
    total_start = time.monotonic()

    print("=" * 72)
    print(f"  EXPEDITION 33 RPC — MATRIX RUNNER (TIER: {tier.upper()})")
    print("=" * 72)

    for step in steps:
        cmd_str = " ".join(step.command)
        print(f"\n[RUNNING] {step.name} ({cmd_str})...")
        env = os.environ.copy()
        if step.env_overrides:
            env.update(step.env_overrides)

        step_start = time.monotonic()
        proc = subprocess.run(step.command, env=env)
        step_elapsed = time.monotonic() - step_start

        passed = proc.returncode == 0
        results.append(
            StepResult(
                name=step.name,
                passed=passed,
                duration_s=step_elapsed,
                returncode=proc.returncode,
            )
        )
        if not passed:
            total_elapsed = time.monotonic() - total_start
            _print_summary(tier, results, total_elapsed, sla_s)
            return proc.returncode

    total_elapsed = time.monotonic() - total_start
    _print_summary(tier, results, total_elapsed, sla_s)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    return run_tier(args.tier)


if __name__ == "__main__":
    sys.exit(main())
