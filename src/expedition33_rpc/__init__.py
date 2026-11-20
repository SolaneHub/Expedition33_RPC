"""Clair Obscur: Expedition 33 - Discord Rich Presence package."""

from expedition33_rpc.core.app import main
from expedition33_rpc.detection.detector import GameDetector, GameState

__version__ = "2.3.7"

__all__ = ["GameDetector", "GameState", "__version__", "main"]
