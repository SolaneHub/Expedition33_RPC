"""Smoke test routine for compiled executable and CI verification."""

from __future__ import annotations

import os
import sys


def run_smoke_test() -> None:
    """Executes a smoke test validating essential imports, assets, and core initialization."""
    import tkinter

    import PIL
    import pystray

    from expedition33_rpc.core.orchestrator import AppOrchestrator
    from expedition33_rpc.core.resources import get_resource_path
    from expedition33_rpc.core.settings import SettingsService
    from expedition33_rpc.detection.detector import GameDetector
    from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

    assets = (get_resource_path("icon.png"), get_resource_path("bridge.zip"))
    if not all(os.path.isfile(a) for a in assets):
        sys.exit(1)

    detector = GameDetector()
    _ = detector.get_game_state()

    settings = SettingsService()
    _ = settings.is_anti_spoiler_enabled()

    orchestrator = AppOrchestrator(
        detector=detector,
        settings_service=settings,
        auto_install_bridge=False,
        sync_startup=False,
    )

    _ = pystray.__name__
    _ = PIL.__name__
    _ = tkinter.__name__
    tray_app = ExpeditionTrayApp(orchestrator=orchestrator)
    _icon = tray_app.get_icon_image()
    if _icon is None:
        sys.exit(1)
    sys.exit(0)
