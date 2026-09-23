import winreg

SETTINGS_KEY = r"Software\Expedition33_RPC"
ANTI_SPOILER_VAL = "AntiSpoiler"

# In-memory fallback if registry access is restricted
_fallback_anti_spoiler: bool = False


def is_anti_spoiler_enabled() -> bool:
    """Checks if Anti-Spoiler mode is enabled in the Windows Registry or in-memory fallback."""
    global _fallback_anti_spoiler
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, ANTI_SPOILER_VAL)
            return bool(val)
    except Exception:
        return _fallback_anti_spoiler


def set_anti_spoiler_enabled(enabled: bool) -> bool:
    """Saves the Anti-Spoiler setting to the Windows Registry and in-memory fallback."""
    global _fallback_anti_spoiler
    _fallback_anti_spoiler = enabled
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as key:
            winreg.SetValueEx(key, ANTI_SPOILER_VAL, 0, winreg.REG_DWORD, 1 if enabled else 0)
        return True
    except Exception as e:
        print(f"[Settings] Error saving anti-spoiler setting: {e}")
        return False


def toggle_anti_spoiler() -> bool:
    """Toggles Anti-Spoiler mode and returns the new state."""
    new_val = not is_anti_spoiler_enabled()
    set_anti_spoiler_enabled(new_val)
    return new_val
