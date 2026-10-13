"""Game detection, timer state machine, and domain data."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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


def __getattr__(name: str) -> Any:
    match name:
        case "GameState" | "GameDetector" | "BridgeStateProvider":
            import expedition33_rpc.detection.detector as d

            return getattr(d, name)
        case "TARGET_PROCESS_NAMES" | "ENDLESS_TOWER_TRIALS":
            import expedition33_rpc.detection.game_data as gd

            return getattr(gd, name)
        case (
            "format_checkpoint_tag"
            | "format_enemy_name"
            | "format_zone_name"
            | "resolve_tower_trial"
            | "strip_accents"
        ):
            import expedition33_rpc.detection.normalization as nm

            return getattr(nm, name)
        case "ZoneTimerTracker":
            from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

            return ZoneTimerTracker
        case _:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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


def __dir__() -> list[str]:
    return sorted(__all__)
