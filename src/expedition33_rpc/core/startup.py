import contextlib
import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

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
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            if not val:
                return False
            raw = val.strip()
            if raw.startswith('"'):
                parts = raw.split('"')
                clean_path = parts[1] if len(parts) > 1 else raw.strip('"')
            else:
                clean_path = raw.split()[0] if " " in raw else raw
            return os.path.exists(clean_path)
    except Exception:
        return False


def set_startup_enabled(enable: bool) -> bool:
    """Enables or disables automatic startup with Windows."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_current_executable_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                with contextlib.suppress(FileNotFoundError, OSError):
                    winreg.DeleteValue(key, APP_NAME)
        return True
    except Exception as e:
        print(f"[Startup] Error setting startup: {e}")
        return False


def sync_startup_path() -> None:
    """If startup is enabled, ensures the registered path matches the current location of the executable."""
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
    except Exception:
        return

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
