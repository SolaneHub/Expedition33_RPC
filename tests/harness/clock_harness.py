"""Deterministic dual-clock test harness for Expedition33_RPC testing.

Provides fully decoupled, synchronized-yet-independent monotonic and epoch
clock primitives to test polling loops, join deadlines, telemetry freshness,
and immunity against NTP clock jumps.
"""

from __future__ import annotations

import threading


class DualClockHarness:
    """Manages synchronized yet independent deterministic clocks.

    Monotonic clock:
        Controls internal intervals, polling loops, retry cooldowns, and
        thread join deadlines. Strictly non-decreasing (advances monotonically).

    Epoch clock:
        Controls wall-clock timestamps (time.time()), e.g. Discord start_time
        generation, telemetry timestamp verification (TTL 5.0s freshness).
        Can jump forward or backward (NTP sync / user adjustments).
    """

    def __init__(
        self, initial_monotonic: float = 1000.0, initial_epoch: float = 1_700_000_000.0
    ) -> None:
        self._lock = threading.Lock()
        self._monotonic = float(initial_monotonic)
        self._epoch = float(initial_epoch)

    @property
    def monotonic(self) -> float:
        """Returns the current monotonic time."""
        with self._lock:
            return self._monotonic

    @property
    def epoch(self) -> float:
        """Returns the current epoch wall-clock time."""
        with self._lock:
            return self._epoch

    def monotonic_clock(self) -> float:
        """Callable matching time.monotonic signature."""
        with self._lock:
            return self._monotonic

    def epoch_clock(self) -> float:
        """Callable matching time.time signature."""
        with self._lock:
            return self._epoch

    def advance(self, seconds: float) -> None:
        """Advances both monotonic and epoch clocks simultaneously by `seconds`.

        Raises ValueError if `seconds` is negative, since monotonic time can never regress.
        """
        if seconds < 0:
            raise ValueError(f"Cannot advance monotonic clock by negative duration: {seconds}")
        with self._lock:
            self._monotonic += seconds
            self._epoch += seconds

    def simulate_ntp_jump(self, delta_seconds: float) -> None:
        """Simulates an abrupt wall-clock jump (positive or negative) without affecting monotonic time.

        This validates that internal engine timers, polling backoffs, and cooldowns
        rely strictly on monotonic time and remain impervious to NTP synchronization
        adjustments or manual OS clock changes.
        """
        with self._lock:
            self._epoch += delta_seconds
