import os
import sys
from pathlib import Path

from expedition33_rpc.core.platform import (
    winreg,
    winreg_delete_value,
    winreg_read_value,
    winreg_set_value,
)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Expedition33_DiscordRPC"


def get_current_executable_command() -> str:
    """Returns the formatted command to execute this application on startup."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    root_main = Path(__file__).resolve().parents[3] / "main.py"
    if root_main.exists():
        # On non-frozen Windows, prefer pythonw.exe if available to avoid opening a console window
        py_exe = sys.executable
        pyw_candidate = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
        target_py = pyw_candidate if os.path.exists(pyw_candidate) else py_exe
        return f'"{target_py}" "{root_main}"'
    return f'"{sys.executable}"'


def is_startup_enabled() -> bool:
    """Checks if the application is registered to run on Windows startup and the target binary exists."""
    if winreg is None:
        return False
    val = winreg_read_value(
        getattr(winreg, "HKEY_CURRENT_USER", None), RUN_KEY, APP_NAME, winreg_module=winreg
    )
    if not val:
        return False
    raw = val.strip()
    if raw.startswith('"'):
        parts = raw.split('"')
        clean_path = parts[1] if len(parts) > 1 else raw.strip('"')
    else:
        clean_path = raw.split()[0] if " " in raw else raw
    return os.path.exists(clean_path)


def set_startup_enabled(enable: bool) -> bool:
    """Enables or disables automatic startup with Windows."""
    if winreg is None:
        return False
    hkey = getattr(winreg, "HKEY_CURRENT_USER", None)
    if enable:
        cmd = get_current_executable_command()
        return winreg_set_value(hkey, RUN_KEY, APP_NAME, cmd, winreg_module=winreg)
    else:
        return winreg_delete_value(hkey, RUN_KEY, APP_NAME, winreg_module=winreg)


def sync_startup_path() -> None:
    """If startup is enabled, ensures the registered path matches the current location of the executable."""
    if winreg is None:
        return
    val = winreg_read_value(
        getattr(winreg, "HKEY_CURRENT_USER", None), RUN_KEY, APP_NAME, winreg_module=winreg
    )

    if val:
        current_cmd = get_current_executable_command()
        if val.strip() != current_cmd.strip():
            set_startup_enabled(True)
            print(f"[Startup] Synced startup path to: {current_cmd}")


def toggle_startup() -> bool:
    """Toggles the current Windows startup state and returns new state."""
    new_state = not is_startup_enabled()
    set_startup_enabled(new_state)
    return new_state


__all__ = [
    "RUN_KEY",
    "APP_NAME",
    "get_current_executable_command",
    "is_startup_enabled",
    "set_startup_enabled",
    "sync_startup_path",
    "toggle_startup",
]
