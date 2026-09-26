import os
import sys
import winreg
import zipfile

import psutil

TARGET_EXE_NAMES = {
    "sandfall-win64-shipping.exe",
    "expedition33_steam.exe",
    "expedition33.exe",
    "sandfall.exe",
}


def get_resource_path(filename: str) -> str:
    """Resolves resource path across development and PyInstaller frozen runtime."""
    if getattr(sys, "frozen", False):
        base_meipass = getattr(sys, "_MEIPASS", None)
        if base_meipass:
            bundled_pkg = os.path.join(base_meipass, "expedition33_rpc", "assets", filename)
            if os.path.exists(bundled_pkg):
                return bundled_pkg
            flat = os.path.join(base_meipass, filename)
            if os.path.exists(flat):
                return flat

        exe_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(exe_dir, filename)
        if os.path.exists(candidate):
            return candidate

    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(module_dir, "assets", filename)
    if os.path.exists(candidate):
        return candidate
    candidate_parent = os.path.join(module_dir, "..", "assets", filename)
    if os.path.exists(candidate_parent):
        return candidate_parent

    return filename


def find_game_win64_directory() -> str | None:
    """Locates Clair Obscur: Expedition 33 Win64 directory via active processes or Steam libraries."""
    # 1. Check running processes
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = proc.info.get("name")
            if name and name.lower() in TARGET_EXE_NAMES:
                exe_path = proc.info.get("exe")
                if exe_path and os.path.exists(exe_path):
                    target_dir = os.path.dirname(os.path.abspath(exe_path))
                    if os.path.basename(target_dir).lower() == "win64":
                        return target_dir
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 2. Check Steam Registry and Library Folders
    steam_roots = []
    for hkey, subkey in [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]:
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "SteamPath")
                if val:
                    steam_roots.append(os.path.normpath(val))
        except Exception:
            pass

    libraries = list(steam_roots)
    for root in steam_roots:
        vdf_path = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf_path):
            try:
                with open(vdf_path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if "path" in line.lower():
                            parts = line.split('"')
                            if len(parts) >= 4 and parts[3]:
                                libraries.append(os.path.normpath(parts[3]))
            except Exception:
                pass

    # Add standard root drives as fallback
    for drive in ["C", "D", "E", "F", "G"]:
        libraries.append(f"{drive}:\\SteamLibrary")
        libraries.append(f"{drive}:\\Program Files (x86)\\Steam")
        libraries.append(f"{drive}:\\Program Files\\Steam")

    checked_dirs = set()
    for lib in libraries:
        if not lib or lib in checked_dirs:
            continue
        checked_dirs.add(lib)

        win64_candidate = os.path.join(
            lib,
            "steamapps",
            "common",
            "Expedition 33",
            "Sandfall",
            "Binaries",
            "Win64",
        )
        exe_file = os.path.join(win64_candidate, "SandFall-Win64-Shipping.exe")
        if os.path.exists(exe_file):
            return win64_candidate

    return None


def is_bridge_installed(win64_dir: str | None = None) -> bool:
    """Checks whether the UE4SS combat bridge files are present in the game directory."""
    target_dir = win64_dir or find_game_win64_directory()
    if not target_dir or not os.path.isdir(target_dir):
        return False

    dwmapi = os.path.join(target_dir, "dwmapi.dll")
    lua_script = os.path.join(target_dir, "ue4ss", "Mods", "Expedition33RPC", "scripts", "main.lua")
    return os.path.exists(dwmapi) and os.path.exists(lua_script)


def install_bridge(win64_dir: str | None = None) -> tuple[bool, str]:
    """Extracts and configures the embedded UE4SS real-time combat bridge into the game directory."""
    target_dir = win64_dir or find_game_win64_directory()
    if not target_dir or not os.path.isdir(target_dir):
        return False, "Game directory not found. Please launch the game once to detect it."

    zip_file = get_resource_path("bridge.zip")
    if not os.path.exists(zip_file):
        return False, f"Bridge archive file missing: {zip_file}"

    try:
        with zipfile.ZipFile(zip_file, "r") as zf:
            zf.extractall(target_dir)
        return True, "Combat bridge installed successfully!"
    except Exception as e:
        return False, f"Error during bridge installation: {e}"


def uninstall_bridge(win64_dir: str | None = None) -> tuple[bool, str]:
    """Safely removes the bridge DLL and mod script from the game directory."""
    target_dir = win64_dir or find_game_win64_directory()
    if not target_dir or not os.path.isdir(target_dir):
        return False, "Game directory not found."

    try:
        dwmapi = os.path.join(target_dir, "dwmapi.dll")
        if os.path.exists(dwmapi):
            os.remove(dwmapi)

        mod_dir = os.path.join(target_dir, "ue4ss", "Mods", "Expedition33RPC")
        if os.path.exists(mod_dir):
            import shutil

            shutil.rmtree(mod_dir, ignore_errors=True)

        return True, "Bridge uninstalled successfully."
    except Exception as e:
        return False, f"Error during uninstallation: {e}"
