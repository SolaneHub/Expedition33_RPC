#!/usr/bin/env python3
"""Standalone CLI developer tool to simulate game telemetry for Expedition 33 Discord RPC.

Writes mock status JSON directly to %TEMP%\\expedition33_status.json to test
Discord Rich Presence and System Tray UI without launching the game.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


def get_default_telemetry_path() -> Path:
    """Resolves default telemetry file path in Windows temp directory."""
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    return Path(temp_dir) / "expedition33_status.json"


def write_telemetry(
    file_path: Path,
    zone: str = "Level_Main_OldLumiere",
    in_combat: bool = False,
    enemy_name: str = "",
    floor: int | None = None,
    checkpoint: str = "Entrance",
    enemies: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically writes telemetry payload matching UE4SS Lua bridge IPC schema."""
    resolved_enemies: list[str] = (
        enemies
        if (enemies is not None and in_combat)
        else (
            [e.strip() for e in enemy_name.split(",") if e.strip()]
            if (enemy_name and in_combat)
            else []
        )
    )
    payload: dict[str, Any] = {
        "timestamp": time.time(),
        "zone": zone,
        "in_combat": in_combat,
        "enemy_name": enemy_name if in_combat else "",
        "enemies": resolved_enemies,
        "floor": floor,
        "checkpoint": checkpoint,
    }

    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(file_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate UE4SS Bridge telemetry for Expedition 33 Discord RPC."
    )
    parser.add_argument(
        "--zone",
        type=str,
        default="Level_Main_OldLumiere",
        help="Map level or zone identifier (default: Level_Main_OldLumiere)",
    )
    parser.add_argument(
        "--combat",
        action="store_true",
        help="Flag indicating active combat encounter",
    )
    parser.add_argument(
        "--enemy",
        type=str,
        default="Duollistes",
        help="Enemy or boss name during combat (default: Duollistes)",
    )
    parser.add_argument(
        "--enemies",
        nargs="*",
        default=None,
        help="List of enemy names in active combat encounter (e.g. --enemies 'Alpha Francois' 'Duollistes')",
    )
    parser.add_argument(
        "--floor",
        type=int,
        default=None,
        help="Endless Tower floor/stage number (default: None)",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default="Entrance",
        help="Spawn point or checkpoint name (default: Entrance)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Target telemetry JSON file path (default: %%TEMP%%\\expedition33_status.json)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously refresh telemetry timestamp in a loop",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Refresh interval in seconds when --loop is active (default: 1.0)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove telemetry file and exit",
    )

    args = parser.parse_args()
    target_path = args.path if args.path is not None else get_default_telemetry_path()

    if args.clean:
        if target_path.exists():
            target_path.unlink()
            print(f"[SimulateTelemetry] Removed telemetry file: {target_path}")
        else:
            print(f"[SimulateTelemetry] Telemetry file does not exist: {target_path}")
        return

    enemy = args.enemy if args.combat else ""
    enemies = args.enemies if args.combat else None

    if args.loop:
        print(f"[SimulateTelemetry] Refreshing telemetry every {args.interval}s at: {target_path}")
        print("Press Ctrl+C to terminate simulation.")
        try:
            while True:
                payload = write_telemetry(
                    file_path=target_path,
                    zone=args.zone,
                    in_combat=args.combat,
                    enemy_name=enemy,
                    floor=args.floor,
                    checkpoint=args.checkpoint,
                    enemies=enemies,
                )
                ts = time.strftime("%H:%M:%S", time.localtime(payload["timestamp"]))
                print(
                    f"[{ts}] zone={payload['zone']} combat={payload['in_combat']} "
                    f"enemy={payload['enemy_name']} checkpoint={payload['checkpoint']}"
                )
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[SimulateTelemetry] Simulation stopped.")
    else:
        payload = write_telemetry(
            file_path=target_path,
            zone=args.zone,
            in_combat=args.combat,
            enemy_name=enemy,
            floor=args.floor,
            checkpoint=args.checkpoint,
            enemies=enemies,
        )
        print(f"[SimulateTelemetry] Written telemetry to: {target_path}")
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
