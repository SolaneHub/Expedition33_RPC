import sys

from expedition33_rpc.core.platform import is_already_running, release_single_instance_lock


def main() -> None:
    """Application entry point."""
    if "--smoke-test" in sys.argv:
        from expedition33_rpc.core.smoke import run_smoke_test

        run_smoke_test()

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
