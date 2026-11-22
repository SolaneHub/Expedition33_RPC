"""Clair Obscur: Expedition 33 - Discord Rich Presence package."""

from typing import TYPE_CHECKING, Any

from expedition33_rpc._version import __version__
from expedition33_rpc.detection.detector import GameDetector, GameState

if TYPE_CHECKING:
    from expedition33_rpc.core.app import main

__all__ = ["GameDetector", "GameState", "__version__", "main"]


def __getattr__(name: str) -> Any:
    if name == "main":
        from expedition33_rpc.core.app import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))
