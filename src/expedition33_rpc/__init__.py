"""Clair Obscur: Expedition 33 - Discord Rich Presence package."""

from expedition33_rpc.core.app import main
from expedition33_rpc.detection.detector import GameDetector, GameState

__version__ = "1.6.0"

__all__ = ["main", "GameDetector", "GameState", "__version__"]
