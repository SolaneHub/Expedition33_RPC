import contextlib
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Expedition33_DiscordRPC"


def is_startup_enabled() -> bool:
    """Checks if the application is registered to run on Windows startup."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except Exception:
        return False


def set_startup_enabled(enable: bool) -> bool:
    """Enables or disables automatic startup with Windows."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                if getattr(sys, "frozen", False):
                    exe_path = sys.executable
                else:
                    root_main = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "..", "main.py")
                    )
                    exe_path = root_main if os.path.exists(root_main) else sys.executable
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                with contextlib.suppress(FileNotFoundError, OSError):
                    winreg.DeleteValue(key, APP_NAME)
        return True
    except Exception as e:
        print(f"[Startup] Error setting startup: {e}")
        return False


def toggle_startup() -> bool:
    """Toggles the current Windows startup state and returns new state."""
    new_state = not is_startup_enabled()
    set_startup_enabled(new_state)
    return new_state
