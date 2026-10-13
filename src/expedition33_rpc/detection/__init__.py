"""Game detection, timer state machine, and domain data."""

from expedition33_rpc.detection.detector import (
    BridgeStateProvider,
    GameDetector,
    GameState,
)
from expedition33_rpc.detection.game_data import (
    ENDLESS_TOWER_TRIALS,
    TARGET_PROCESS_NAMES,
)
from expedition33_rpc.detection.normalization import (
    format_checkpoint_tag,
    format_enemy_name,
    format_zone_name,
    resolve_tower_trial,
    strip_accents,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

__all__ = [
    "GameState",
    "GameDetector",
    "BridgeStateProvider",
    "ZoneTimerTracker",
    "format_checkpoint_tag",
    "format_enemy_name",
    "format_zone_name",
    "resolve_tower_trial",
    "strip_accents",
    "TARGET_PROCESS_NAMES",
    "ENDLESS_TOWER_TRIALS",
]
