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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.harness.game_session import (
    SCENARIOS,
    create_telemetry_payload,
)


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
    tower_trial: Any | None = None,
) -> dict[str, Any]:
    """Atomically writes telemetry payload matching UE4SS Lua bridge IPC schema."""
    payload = create_telemetry_payload(
        zone=zone,
        in_combat=in_combat,
        enemy_name=enemy_name,
        enemies=enemies,
        tower_trial=tower_trial,
        checkpoint=checkpoint,
        floor=floor,
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(file_path)
    return payload


def play_scenario(
    scenario_name: str,
    file_path: Path,
    interval: float = 1.0,
    speed: float = 1.0,
    loop: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
    print_fn: Callable[[str], None] = print,
) -> None:
    """Plays back a dynamic telemetry storyboard scenario through sequential timed stages."""
    if sleep_fn is None:
        sleep_fn = time.sleep

    if scenario_name not in SCENARIOS:
        valid = ", ".join(SCENARIOS.keys())
        raise ValueError(f"Unknown scenario '{scenario_name}'. Available scenarios: {valid}")

    steps = SCENARIOS[scenario_name]
    speed = max(0.001, speed)
    print_fn(f"[SimulateTelemetry] Starting scenario '{scenario_name}' ({len(steps)} steps)...")
    if loop:
        print_fn("[SimulateTelemetry] Running in continuous loop mode. Press Ctrl+C to terminate.")

    try:
        while True:
            for idx, step in enumerate(steps, start=1):
                scaled_duration = step.duration / speed
                step_elapsed = 0.0

                print_fn(
                    f"[SimulateTelemetry] Step {idx}/{len(steps)}: {step.description} "
                    f"(duration: {step.duration:.1f}s)"
                )

                while True:
                    payload = write_telemetry(
                        file_path=file_path,
                        zone=step.zone,
                        in_combat=step.in_combat,
                        enemy_name=step.enemy_name,
                        enemies=step.enemies,
                        floor=step.floor,
                        checkpoint=step.checkpoint,
                        tower_trial=step.tower_trial,
                    )
                    ts = time.strftime("%H:%M:%S", time.localtime(payload["timestamp"]))
                    trial_str = (
                        f" trial={payload['tower_trial']}"
                        if payload.get("tower_trial") is not None
                        else ""
                    )
                    print_fn(
                        f"[{ts}] zone={payload['zone']} combat={payload['in_combat']} "
                        f"enemy={payload['enemy_name']} checkpoint={payload['checkpoint']}{trial_str}"
                    )
                    time_to_sleep = min(interval / speed, scaled_duration - step_elapsed)
                    if time_to_sleep <= 0:
                        break
                    sleep_fn(time_to_sleep)
                    step_elapsed += time_to_sleep
                    if step_elapsed >= scaled_duration:
                        break

            if not loop:
                print_fn(f"[SimulateTelemetry] Scenario '{scenario_name}' completed.")
                break
    except KeyboardInterrupt:
        print_fn("\n[SimulateTelemetry] Scenario playback stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simulate UE4SS Bridge telemetry for Expedition 33 Discord RPC."
    )
    parser.add_argument(
        "--scenario",
        type=str,
        choices=list(SCENARIOS.keys()),
        default=None,
        help="Predefined timed storyboard scenario to simulate (e.g. boss_fight, tower_climb)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier for --scenario (default: 1.0)",
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
        help="Refresh interval in seconds when --loop or --scenario is active (default: 1.0)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List all available predefined telemetry storyboard scenarios and exit",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove telemetry file and exit",
    )

    args = parser.parse_args()
    target_path = args.path if args.path is not None else get_default_telemetry_path()

    if args.list_scenarios:
        print("Available Predefined Storyboard Scenarios:")
        for name, steps in SCENARIOS.items():
            total_duration = sum(s.duration for s in steps)
            print(f"  - {name} ({len(steps)} steps, ~{total_duration:.1f}s)")
            for i, step in enumerate(steps, 1):
                print(f"      Step {i}: {step.description} [{step.zone}]")
        return

    if args.clean:
        if target_path.exists():
            target_path.unlink()
            print(f"[SimulateTelemetry] Removed telemetry file: {target_path}")
        else:
            print(f"[SimulateTelemetry] Telemetry file does not exist: {target_path}")
        return

    if args.scenario:
        play_scenario(
            scenario_name=args.scenario,
            file_path=target_path,
            interval=args.interval,
            speed=args.speed,
            loop=args.loop,
        )
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
