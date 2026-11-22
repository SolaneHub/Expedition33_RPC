import sys

import expedition33_rpc.core.orchestrator as orchestrator_module
import expedition33_rpc.ui.tray_app as tray_app_module
from expedition33_rpc.core.platform import is_already_running, release_single_instance_lock
from expedition33_rpc.core.settings import SettingsService
from expedition33_rpc.core.smoke import run_smoke_test


def main() -> None:
    """Application entry point."""
    if "--smoke-test" in sys.argv:
        run_smoke_test()

    if is_already_running():
        sys.exit(0)

    try:
        settings_service = SettingsService()
        orchestrator = orchestrator_module.AppOrchestrator(
            auto_install_bridge=True,
            sync_startup=True,
            settings_service=settings_service,
        )

        app = tray_app_module.ExpeditionTrayApp(orchestrator=orchestrator)
        app.run()
    finally:
        release_single_instance_lock()
