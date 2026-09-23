import ctypes
import os
import sys

_MUTEX_HANDLE = None


def is_already_running() -> bool:
    """Checks if another instance of Expedition 33 RPC is already running on Windows."""
    global _MUTEX_HANDLE
    mutex_name = "Global\\Expedition33_Discord_RPC_Mutex"
    kernel32 = ctypes.windll.kernel32
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, mutex_name)
    last_error = kernel32.GetLastError()
    # ERROR_ALREADY_EXISTS = 183
    return last_error == 183


def get_base_dir() -> str:
    """Gets directory where the executable or script is located."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    """Application entry point."""
    if sys.platform == "win32" and is_already_running():
        sys.exit(0)

    base_dir = get_base_dir()

    from expedition33_rpc.tray_app import ExpeditionTrayApp

    app = ExpeditionTrayApp(base_dir)
    app.run()


if __name__ == "__main__":
    main()
