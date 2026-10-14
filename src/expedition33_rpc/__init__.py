"""Clair Obscur: Expedition 33 - Discord Rich Presence package."""

from typing import TYPE_CHECKING, Any

__version__ = "2.0.1"

if TYPE_CHECKING:
    from expedition33_rpc.core.app import main
    from expedition33_rpc.detection.detector import GameDetector, GameState


def __getattr__(name: str) -> Any:
    if name == "main":
        from expedition33_rpc.core.app import main

        return main
    if name in ("GameDetector", "GameState"):
        from expedition33_rpc.detection.detector import GameDetector, GameState

        return GameDetector if name == "GameDetector" else GameState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main", "GameDetector", "GameState", "__version__"]


def __dir__() -> list[str]:
    return sorted(__all__)
