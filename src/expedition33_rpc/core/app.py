import os
import sys

from expedition33_rpc.core.platform import is_already_running, release_single_instance_lock


def main() -> None:
    """Application entry point."""
    if "--smoke-test" in sys.argv:
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
        assert _icon is not None
        sys.exit(0)

    if is_already_running():
        sys.exit(0)

    try:
        from expedition33_rpc.core.orchestrator import AppOrchestrator
        from expedition33_rpc.core.settings import SettingsService
        from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

        settings_service = SettingsService()
        orchestrator = AppOrchestrator(
            auto_install_bridge=True,
            sync_startup=True,
            settings_service=settings_service,
        )

        app = ExpeditionTrayApp(orchestrator=orchestrator)
        app.run()
    finally:
        release_single_instance_lock()


if __name__ == "__main__":
    main()
