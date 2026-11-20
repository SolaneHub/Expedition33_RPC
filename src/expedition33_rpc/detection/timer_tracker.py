import time


class ZoneTimerTracker:
    """Encapsulates the state machine for zone exploration and combat timers.

    Handles freezing exploration time during battles and resetting timers on zone/trial changes.

    Clock decoupling strategy:
        - ``now`` (epoch): Anchors outbound Discord start timestamps. Subject to NTP jumps.
        - ``now_monotonic``: Measures elapsed durations (paused intervals). Immune to NTP jumps.
        - ``zone_paused_duration`` is accumulated from monotonic deltas, then applied as an
          epoch offset to ``zone_start_time`` to produce the final outbound timestamp.
    """

    def __init__(self) -> None:
        self.current_zone_id: str | None = None
        self.zone_start_time: float | None = None
        self.zone_paused_duration: float = 0.0
        self.combat_start_time: float | None = None
        self._combat_start_monotonic: float | None = None
        self.in_combat_prev: bool = False
        self.last_tower_trial: tuple[int, int] | str | None = None

    def reset(self) -> None:
        """Resets all timing states when game process stops."""
        self.current_zone_id = None
        self.zone_start_time = None
        self.zone_paused_duration = 0.0
        self.combat_start_time = None
        self._combat_start_monotonic = None
        self.in_combat_prev = False
        self.last_tower_trial = None

    def update(
        self,
        zone_key: str,
        in_combat: bool,
        is_tower: bool = False,
        current_tower_trial: tuple[int, int] | str | None = None,
        now: float | None = None,
        now_monotonic: float | None = None,
    ) -> float:
        """Updates internal timers and returns the effective epoch start timestamp for Discord RPC.

        Args:
            zone_key: Current zone identifier.
            in_combat: Whether the player is currently in combat.
            is_tower: Whether the zone is an Endless Tower stage.
            current_tower_trial: Active tower trial identifier, if any.
            now: Epoch wall-clock time for outbound Discord timestamps.
            now_monotonic: Monotonic time for computing elapsed durations (NTP-immune).
        """
        if now is None:
            now = time.time()
        if now_monotonic is None:
            now_monotonic = now

        if self.current_zone_id != zone_key:
            # Zone changed: reset zone timer from 0 for the new zone
            self.current_zone_id = zone_key
            self.zone_start_time = now
            self.zone_paused_duration = 0.0
            self.last_tower_trial = current_tower_trial
            if in_combat:
                self.combat_start_time = now
                self._combat_start_monotonic = now_monotonic
                self.in_combat_prev = True
            else:
                self.combat_start_time = None
                self._combat_start_monotonic = None
                self.in_combat_prev = False
        else:
            # Same zone
            if not self.in_combat_prev and in_combat:
                # Entered combat: start combat timer from 0
                self.combat_start_time = now
                self._combat_start_monotonic = now_monotonic
                self.in_combat_prev = True
                self.last_tower_trial = current_tower_trial
            elif self.in_combat_prev and in_combat:
                # Still in combat. Check if tower trial chained directly without an exploration break
                if is_tower and current_tower_trial != self.last_tower_trial:
                    if self._combat_start_monotonic is not None:
                        self.zone_paused_duration += max(
                            0.0, now_monotonic - self._combat_start_monotonic
                        )
                    self.combat_start_time = now
                    self._combat_start_monotonic = now_monotonic
                    self.last_tower_trial = current_tower_trial
            elif self.in_combat_prev and not in_combat:
                # Exited combat: freeze/pause zone timer during combat and resume exploration timer
                if self._combat_start_monotonic is not None:
                    self.zone_paused_duration += max(
                        0.0, now_monotonic - self._combat_start_monotonic
                    )
                self.combat_start_time = None
                self._combat_start_monotonic = None
                self.in_combat_prev = False
                self.last_tower_trial = None

        if in_combat:
            return self.combat_start_time or now
        if self.zone_start_time is None:
            self.zone_start_time = now
        return min(self.zone_start_time + self.zone_paused_duration, now)
