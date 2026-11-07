"""Fluent Test Harness for Clair Obscur: Expedition 33 telemetry and session simulation."""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from tests.harness.fake_process import FakeProcess

from expedition33_rpc.detection.detector import (
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker


@dataclass(frozen=True, slots=True)
class StoryboardStep:
    """Represents a single step in a timed telemetry storyboard playback scenario."""

    duration: float
    zone: str
    in_combat: bool = False
    enemy_name: str = ""
    enemies: list[str] | None = None
    floor: int | None = None
    checkpoint: str = "Entrance"
    tower_trial: Any | None = None
    description: str = ""


SCENARIOS: dict[str, list[StoryboardStep]] = {
    "boss_fight": [
        StoryboardStep(
            duration=5.0,
            zone="Level_Main_OldLumiere",
            in_combat=False,
            enemy_name="",
            checkpoint="Entrance",
            description="Exploration in Level_Main_OldLumiere",
        ),
        StoryboardStep(
            duration=10.0,
            zone="Level_Main_OldLumiere",
            in_combat=True,
            enemy_name="Duollistes",
            enemies=["Duollistes"],
            checkpoint="Entrance",
            description="Boss encounter with Duollistes",
        ),
        StoryboardStep(
            duration=5.0,
            zone="Level_Main_OldLumiere",
            in_combat=False,
            enemy_name="",
            checkpoint="Manor Gardens",
            description="Victory and exploration at Manor Gardens",
        ),
    ],
    "tower_climb": [
        StoryboardStep(
            duration=5.0,
            zone="Level_EndlessTower",
            in_combat=True,
            enemy_name="Gault, Luster, Ramasseur",
            enemies=["Gault", "Luster", "Ramasseur"],
            floor=1,
            tower_trial=(1, 1),
            checkpoint="Stage 1, Trial 1",
            description="Endless Tower - Stage 1, Trial 1",
        ),
        StoryboardStep(
            duration=5.0,
            zone="Level_EndlessTower",
            in_combat=True,
            enemy_name="Potier, Steel Chevaliere, Greatsword Cultist",
            enemies=["Potier", "Steel Chevaliere", "Greatsword Cultist"],
            floor=1,
            tower_trial=(1, 2),
            checkpoint="Stage 1, Trial 2",
            description="Endless Tower - Stage 1, Trial 2",
        ),
        StoryboardStep(
            duration=5.0,
            zone="Level_EndlessTower",
            in_combat=True,
            enemy_name="Dualliste, Luster, Troubadour",
            enemies=["Dualliste", "Luster", "Troubadour"],
            floor=1,
            tower_trial=(1, 3),
            checkpoint="Stage 1, Trial 3",
            description="Endless Tower - Stage 1, Trial 3",
        ),
    ],
    "rare_boss": [
        StoryboardStep(
            duration=5.0,
            zone="Level_Main_OldLumiere",
            in_combat=False,
            enemy_name="",
            checkpoint="Manor Gardens",
            description="Exploration near Manor Gardens",
        ),
        StoryboardStep(
            duration=12.0,
            zone="Level_Main_OldLumiere",
            in_combat=True,
            enemy_name="Simon the Divergent Star",
            enemies=["Simon the Divergent Star"],
            checkpoint="Manor Gardens",
            description="Encounter with Super Boss Simon the Divergent Star",
        ),
        StoryboardStep(
            duration=5.0,
            zone="Level_Main_OldLumiere",
            in_combat=False,
            enemy_name="",
            checkpoint="Sanctuary",
            description="Victory over rare boss and rest at Sanctuary",
        ),
    ],
    "multi_enemy": [
        StoryboardStep(
            duration=5.0,
            zone="Level_Sirene_Main_V2",
            in_combat=False,
            enemy_name="",
            checkpoint="Coast Entrance",
            description="Sirene Coastal Exploration",
        ),
        StoryboardStep(
            duration=8.0,
            zone="Level_Sirene_Main_V2",
            in_combat=True,
            enemy_name="Potier, Steel Chevaliere, Greatsword Cultist",
            enemies=["Potier", "Steel Chevaliere", "Greatsword Cultist"],
            checkpoint="Coast Entrance",
            description="Multi-enemy skirmish against 3 cultists",
        ),
        StoryboardStep(
            duration=5.0,
            zone="Level_Sirene_Main_V2",
            in_combat=False,
            enemy_name="",
            checkpoint="Cliffside",
            description="Post-skirmish rest at Cliffside",
        ),
    ],
}


def create_telemetry_payload(
    zone: str = "",
    in_combat: bool = False,
    enemy_name: str = "",
    enemies: list[str] | None = None,
    tower_trial: Any | None = None,
    checkpoint: str = "",
    floor: int | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Builds a standardized bridge status telemetry dictionary."""
    resolved_enemies: list[str] = (
        list(enemies)
        if (enemies is not None and in_combat)
        else (
            [e.strip() for e in enemy_name.split(",") if e.strip()]
            if (enemy_name and in_combat)
            else []
        )
    )
    return {
        "timestamp": time.time() if timestamp is None else timestamp,
        "zone": zone,
        "in_combat": in_combat,
        "enemy_name": enemy_name if in_combat else "",
        "enemies": resolved_enemies,
        "tower_trial": tower_trial,
        "checkpoint": checkpoint,
        "floor": floor,
    }


class GameSessionSimulator:
    """Fluent test harness simulating game lifecycles, zone exploration, and combat telemetry."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        pid: int = 4333,
        process_name: str = "Sandfall-Win64-Shipping.exe",
    ) -> None:
        if base_dir is None:
            self._temp_dir_obj: tempfile.TemporaryDirectory[str] | None = (
                tempfile.TemporaryDirectory()
            )
            self.root_path = Path(self._temp_dir_obj.name)
        else:
            self._temp_dir_obj = None
            self.root_path = Path(base_dir)

        self.pid = pid
        self.process_name = process_name
        self.bridge_path = self.root_path / "expedition33_status.json"

        # Mock process
        self.proc_start_time = time.time()
        self.mock_proc = FakeProcess(
            pid=self.pid,
            name=self.process_name,
            is_running=False,
            create_time=self.proc_start_time,
            exe_path=str(self.root_path / self.process_name),
        )

        self.running_procs: list[Any] = []

        # Current telemetry state
        self.current_zone = ""
        self.current_checkpoint = ""
        self.in_combat = False
        self.current_enemy = ""
        self.current_enemies: list[str] = []
        self.current_floor: int | None = None
        self.current_tower_trial: Any = None

        # Telemetry providers and detector
        self.bridge_provider = BridgeStateProvider(paths=[str(self.bridge_path)])
        self.timer_tracker = ZoneTimerTracker()

        self._detector: GameDetector | None = None

    def start_game(self, pid: int | None = None) -> Self:
        """Simulates launching the game executable."""
        if pid is not None:
            self.pid = pid
            self.mock_proc._pid = pid
        self.mock_proc._is_running = True
        if self.mock_proc not in self.running_procs:
            self.running_procs.append(self.mock_proc)
        return self

    def stop_game(self) -> Self:
        """Simulates closing the game executable."""
        self.mock_proc._is_running = False
        self.running_procs.clear()
        return self

    def enter_zone(self, zone: str, checkpoint: str = "") -> Self:
        """Simulates entering a zone or map area."""
        self.current_zone = zone
        self.current_checkpoint = checkpoint
        self.in_combat = False
        self.current_enemy = ""
        self.current_enemies = []
        self.current_floor = None
        self.current_tower_trial = None
        self._flush_telemetry()
        return self

    def trigger_combat(
        self,
        enemy_name: str,
        floor: int | None = None,
        checkpoint: str | None = None,
        enemies: list[str] | None = None,
        tower_trial: Any | None = None,
    ) -> Self:
        """Simulates engaging an enemy or boss encounter."""
        self.in_combat = True
        self.current_enemy = enemy_name
        self.current_enemies = list(enemies) if enemies is not None else []
        self.current_tower_trial = tower_trial
        if floor is not None:
            self.current_floor = floor
        if checkpoint is not None:
            self.current_checkpoint = checkpoint
        self._flush_telemetry()
        return self

    def leave_combat(self, checkpoint: str | None = None) -> Self:
        """Simulates successfully winning or escaping combat."""
        self.in_combat = False
        self.current_enemy = ""
        self.current_enemies = []
        self.current_tower_trial = None
        if checkpoint is not None:
            self.current_checkpoint = checkpoint
        self._flush_telemetry()
        return self

    def set_checkpoint(self, checkpoint: str) -> Self:
        """Simulates reaching an in-game flag or checkpoint."""
        self.current_checkpoint = checkpoint
        self._flush_telemetry()
        return self

    def apply_storyboard_step(self, step: StoryboardStep) -> Self:
        """Applies a single StoryboardStep state immediately to the game session."""
        self.current_zone = step.zone
        self.current_checkpoint = step.checkpoint
        self.in_combat = step.in_combat
        self.current_enemy = step.enemy_name
        self.current_enemies = list(step.enemies) if step.enemies is not None else []
        self.current_floor = step.floor
        self.current_tower_trial = step.tower_trial
        self._flush_telemetry()
        return self

    def play_storyboard_scenario(
        self,
        scenario_name: str,
        step_index: int | None = None,
    ) -> Self:
        """Applies a scenario storyboard to the session.

        If step_index is provided (0-based), only that step is applied.
        Otherwise, all steps are applied in sequence, leaving the session in the final step's state.
        """
        if scenario_name not in SCENARIOS:
            valid = ", ".join(SCENARIOS.keys())
            raise ValueError(f"Unknown scenario '{scenario_name}'. Available scenarios: {valid}")
        steps = SCENARIOS[scenario_name]
        if step_index is not None:
            if not 0 <= step_index < len(steps):
                raise IndexError(
                    f"step_index {step_index} out of range for scenario '{scenario_name}' (len={len(steps)})"
                )
            return self.apply_storyboard_step(steps[step_index])
        for step in steps:
            self.apply_storyboard_step(step)
        return self

    def _flush_telemetry(self) -> None:
        """Writes current telemetry to the Bridge status JSON file."""
        payload = create_telemetry_payload(
            zone=self.current_zone,
            in_combat=self.in_combat,
            enemy_name=self.current_enemy,
            enemies=self.current_enemies,
            tower_trial=self.current_tower_trial,
            checkpoint=self.current_checkpoint,
            floor=self.current_floor,
        )
        self.bridge_path.write_text(json.dumps(payload), encoding="utf-8")

    def create_detector(self) -> GameDetector:
        """Creates or returns a GameDetector wired to this simulation session."""
        if self._detector is None:
            self._detector = GameDetector(
                timer_tracker=self.timer_tracker,
                bridge_provider=self.bridge_provider,
                process_scanner=lambda: list(self.running_procs),
            )
        return self._detector

    @property
    def detector(self) -> GameDetector:
        return self.create_detector()

    def get_game_state(self) -> GameState:
        """Queries GameDetector for the current state."""
        return self.detector.get_game_state()

    def cleanup(self) -> None:
        """Cleans up temporary resources if managed internally."""
        if self._temp_dir_obj is not None:
            self._temp_dir_obj.cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()
