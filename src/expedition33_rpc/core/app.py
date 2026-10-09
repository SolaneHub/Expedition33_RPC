import ctypes
import os
import sys

_MUTEX_HANDLE = None


def is_already_running() -> bool:
    """Checks if another instance of Expedition 33 RPC is already running on Windows."""
    if sys.platform != "win32":
        return False
    global _MUTEX_HANDLE
    mutex_name = "Local\\Expedition33_Discord_RPC_Mutex"
    kernel32 = ctypes.windll.kernel32
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, mutex_name)
    last_error = kernel32.GetLastError()
    # ERROR_ALREADY_EXISTS = 183, ERROR_ACCESS_DENIED = 5
    return last_error in (183, 5)


def get_base_dir() -> str:
    """Gets directory where the executable or script package is located."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    """Application entry point."""
    if "--smoke-test" in sys.argv:
        from expedition33_rpc.core.resources import get_resource_path
        from expedition33_rpc.detection.detector import GameDetector

        assets = (get_resource_path("icon.png"), get_resource_path("bridge.zip"))
        if not all(os.path.isfile(a) for a in assets):
            sys.exit(1)
        GameDetector()
        sys.exit(0)

    if sys.platform == "win32" and is_already_running():
        sys.exit(0)

    from expedition33_rpc.core.orchestrator import AppOrchestrator
    from expedition33_rpc.core.settings import SettingsService
    from expedition33_rpc.ui.tray_app import ExpeditionTrayApp

    settings_service = SettingsService()
    orchestrator = AppOrchestrator(
        auto_install_bridge=True,
        sync_startup=True,
        settings_service=settings_service,
    )

    base_dir = get_base_dir()
    app = ExpeditionTrayApp(
        script_dir=base_dir,
        orchestrator=orchestrator,
    )
    app.run()


if __name__ == "__main__":
    main()
