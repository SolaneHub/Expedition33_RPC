"""Smoke test routine for compiled executable and CI verification."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import PIL
import pystray

from expedition33_rpc.core.orchestrator import AppOrchestrator
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.detection.detector import GameDetector
from expedition33_rpc.ui.tray_app import ExpeditionTrayApp


def run_smoke_test(settings_path: Path | None = None) -> None:
    """Executes a smoke test validating essential imports, assets, and core initialization."""
    icon_png = get_resource_path("icon.png")
    icon_ico = get_resource_path("icon.ico")
    bridge_zip = get_resource_path("bridge.zip")
    game_data_json = get_resource_path("game_data.json")
    assets = (icon_png, icon_ico, bridge_zip, game_data_json)
    if not all(os.path.isfile(a) for a in assets):
        sys.exit(1)

    try:
        parsed_game_data: object = json.loads(Path(game_data_json).read_text(encoding="utf-8"))
        if not isinstance(parsed_game_data, dict) or not parsed_game_data:
            sys.exit(1)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        sys.exit(1)

    try:
        with zipfile.ZipFile(bridge_zip, "r") as zf:
            if "ue4ss/Mods/Expedition33RPC/scripts/main.lua" not in zf.namelist():
                sys.exit(1)
    except (OSError, zipfile.BadZipFile):
        sys.exit(1)

    def _run_with_settings(target_settings_path: Path) -> None:
        detector = GameDetector()
        _ = detector.get_game_state()

        settings = SettingsService(path=target_settings_path)
        _ = settings.is_anti_spoiler_enabled()

        orchestrator = AppOrchestrator(
            detector=detector,
            settings_service=settings,
            auto_install_bridge=False,
            sync_startup=False,
        )

        _ = pystray.__name__
        _ = PIL.__name__
        tray_app = ExpeditionTrayApp(orchestrator=orchestrator)
        _icon = tray_app.get_icon_image()
        if _icon is None:
            sys.exit(1)
        sys.exit(0)

    if settings_path is not None:
        _run_with_settings(settings_path)
    else:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _run_with_settings(Path(tmp_dir) / "settings.json")
