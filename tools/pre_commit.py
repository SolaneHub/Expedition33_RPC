"""Cross-platform fast-track pre-commit runner for Expedition33_RPC.

Executes Ruff linting, Ruff formatting checks, Pyright type checking, and unit tests
sequentially with fail-fast semantics.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

STEPS: list[tuple[str, list[str], dict[str, str] | None]] = [
    ("Ruff Linting", ["uv", "run", "ruff", "check"], None),
    ("Ruff Formatting Check", ["uv", "run", "ruff", "format", "--check"], None),
    ("Pyright Type Check", ["uv", "run", "pyright"], None),
    ("Unit Tests", ["uv", "run", "pytest", "-m", "unit"], {"PYSTRAY_BACKEND": "dummy"}),
]


def main() -> int:
    """Run all pre-commit gate checks sequentially."""
    print("=" * 60)
    print("  EXPEDITION 33 RPC - FAST TRACK PRE-COMMIT GATE")
    print("=" * 60)

    total_start = time.monotonic()

    for name, command, extra_env in STEPS:
        cmd_str = " ".join(command)
        print(f"\n[RUNNING] {name} ({cmd_str})...")
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        step_start = time.monotonic()
        res = subprocess.run(command, env=env)
        step_elapsed = time.monotonic() - step_start
        print(f"[TIMING] {name}: {step_elapsed:.2f}s")

        if res.returncode != 0:
            total_elapsed = time.monotonic() - total_start
            print("\n" + "=" * 60)
            print(f"  FAST TRACK GATE: FAIL (Failed at '{name}' after {total_elapsed:.2f}s)")
            print("=" * 60)
            return res.returncode

    total_elapsed = time.monotonic() - total_start
    print("\n" + "=" * 60)
    print(f"  FAST TRACK GATE: PASS (All checks succeeded in {total_elapsed:.2f}s)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
