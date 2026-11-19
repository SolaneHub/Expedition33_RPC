"""Cross-platform fast-track pre-commit runner for Expedition33_RPC.

Executes Ruff linting, Ruff formatting checks, and unit tests sequentially.
Terminates immediately on the first non-zero exit code.
"""

from __future__ import annotations

import subprocess
import sys

STEPS: list[tuple[str, list[str]]] = [
    ("Ruff Linting", ["uv", "run", "ruff", "check"]),
    ("Ruff Formatting Check", ["uv", "run", "ruff", "format", "--check"]),
    ("Unit Tests", ["uv", "run", "pytest", "-m", "unit"]),
]


def main() -> int:
    """Run all pre-commit gate checks sequentially."""
    print("=" * 60)
    print("  EXPEDITION 33 RPC - FAST TRACK PRE-COMMIT GATE")
    print("=" * 60)

    for name, command in STEPS:
        cmd_str = " ".join(command)
        print(f"\n[RUNNING] {name} ({cmd_str})...")
        res = subprocess.run(command)
        if res.returncode != 0:
            print("\n" + "=" * 60)
            print(f"  FAST TRACK GATE: FAIL (Failed at '{name}')")
            print("=" * 60)
            return res.returncode

    print("\n" + "=" * 60)
    print("  FAST TRACK GATE: PASS (All checks succeeded)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
