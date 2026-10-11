"""Fluent Test Harness for Clair Obscur: Expedition 33 telemetry and session simulation."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock

from expedition33_rpc.detection.detector import (
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker


class GameSessionSimulator:
    """Fluent test harness simulating game lifecycles, zone exploration, and combat telemetry."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        pid: int = 4333,
        process_name: str = "Sandfall-Win64-Shipping.exe",
    ) -> None:
        if base_dir is None:
            self._temp_dir_obj: tempfile.TemporaryDirectory | None = tempfile.TemporaryDirectory()
            self.root_path = Path(self._temp_dir_obj.name)
        else:
            self._temp_dir_obj = None
            self.root_path = Path(base_dir)

        self.pid = pid
        self.process_name = process_name
        self.bridge_path = self.root_path / "expedition33_status.json"

        # Mock process
        self.proc_start_time = time.time()
        self.mock_proc = MagicMock()
        self.mock_proc.pid = self.pid
        self.mock_proc.name.return_value = self.process_name
        self.mock_proc.exe.return_value = str(self.root_path / self.process_name)
        self.mock_proc.create_time.return_value = self.proc_start_time
        self.mock_proc.is_running.return_value = False

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
            self.mock_proc.pid = pid
        self.mock_proc.is_running.return_value = True
        if self.mock_proc not in self.running_procs:
            self.running_procs.append(self.mock_proc)
        return self

    def stop_game(self) -> Self:
        """Simulates closing the game executable."""
        self.mock_proc.is_running.return_value = False
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

    def _flush_telemetry(self) -> None:
        """Writes current telemetry to the Bridge status JSON file."""
        payload = {
            "timestamp": time.time(),
            "zone": self.current_zone,
            "in_combat": self.in_combat,
            "enemy_name": self.current_enemy,
            "enemies": self.current_enemies,
            "tower_trial": self.current_tower_trial,
            "checkpoint": self.current_checkpoint,
            "floor": self.current_floor,
        }
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
