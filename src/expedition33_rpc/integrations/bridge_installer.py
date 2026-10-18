from __future__ import annotations

import contextlib
import os
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path

import psutil

from expedition33_rpc.core.platform import winreg, winreg_read_value
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.game_data import TARGET_PROCESS_NAMES


def find_game_win64_directory(
    target_process_names: Iterable[str] | str | None = None,
    known_win64_dir: Path | str | None = None,
    known_exe_path: Path | str | None = None,
) -> str | None:
    """Locates Clair Obscur: Expedition 33 Win64 directory via active processes or Steam libraries."""
    if known_win64_dir and os.path.isdir(known_win64_dir):
        return os.path.normpath(str(known_win64_dir))
    if known_exe_path and os.path.exists(known_exe_path):
        candidate = (
            os.path.dirname(os.path.normpath(str(known_exe_path)))
            if os.path.isfile(known_exe_path)
            else os.path.normpath(str(known_exe_path))
        )
        if os.path.isdir(candidate):
            return candidate
    if (
        target_process_names
        and isinstance(target_process_names, str)
        and os.path.isdir(target_process_names)
    ):
        return os.path.normpath(target_process_names)

    target_names: set[str] = set()
    if target_process_names is not None:
        if isinstance(target_process_names, str):
            target_names.add(target_process_names.strip().lower())
        else:
            target_names.update(n.strip().lower() for n in target_process_names if n.strip())
    else:
        target_names.update(TARGET_PROCESS_NAMES)

    # 1. Check running processes
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = proc.info.get("name")
            if name and name.lower() in target_names:
                exe_path = proc.info.get("exe")
                if exe_path and os.path.exists(exe_path):
                    target_dir = os.path.dirname(os.path.abspath(exe_path))
                    if os.path.basename(target_dir).lower() in ("win64", "wingdk"):
                        return target_dir
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 2. Check Steam Registry and Library Folders
    steam_roots = []
    if winreg is not None:
        for hkey, subkey in [
            (getattr(winreg, "HKEY_CURRENT_USER", None), r"Software\Valve\Steam"),
            (getattr(winreg, "HKEY_LOCAL_MACHINE", None), r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (getattr(winreg, "HKEY_LOCAL_MACHINE", None), r"SOFTWARE\Valve\Steam"),
        ]:
            val = winreg_read_value(hkey, subkey, "SteamPath", winreg_module=winreg)
            if val:
                steam_roots.append(os.path.normpath(val))

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
    drives: list[str] = []
    try:
        for part in psutil.disk_partitions():
            mount = part.mountpoint.rstrip("\\/")
            if mount and mount not in drives:
                drives.append(mount)
    except Exception:
        pass
    if not drives:
        drives = ["C:"]

    for drive in drives:
        libraries.append(f"{drive}\\SteamLibrary")
        libraries.append(f"{drive}\\Program Files (x86)\\Steam")
        libraries.append(f"{drive}\\Program Files\\Steam")

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
        if os.path.isdir(win64_candidate):
            try:
                for entry in os.listdir(win64_candidate):
                    if entry.lower() in target_names:
                        return win64_candidate
            except OSError:
                pass

    # 3. Check Xbox PC Game Pass and Epic Games standard installation directories
    for drive in drives:
        platform_candidates = [
            os.path.join(
                f"{drive}\\",
                "XboxGames",
                "Clair Obscur Expedition 33",
                "Content",
                "Sandfall",
                "Binaries",
                "WinGDK",
            ),
            os.path.join(
                f"{drive}\\",
                "XboxGames",
                "Clair Obscur Expedition 33",
                "Content",
                "Sandfall",
                "Binaries",
                "Win64",
            ),
            os.path.join(
                f"{drive}\\",
                "XboxGames",
                "Expedition 33",
                "Content",
                "Sandfall",
                "Binaries",
                "WinGDK",
            ),
            os.path.join(
                f"{drive}\\",
                "XboxGames",
                "Expedition 33",
                "Content",
                "Sandfall",
                "Binaries",
                "Win64",
            ),
            os.path.join(
                f"{drive}\\",
                "Program Files",
                "Epic Games",
                "Expedition 33",
                "Sandfall",
                "Binaries",
                "Win64",
            ),
            os.path.join(
                f"{drive}\\",
                "Program Files (x86)",
                "Epic Games",
                "Expedition 33",
                "Sandfall",
                "Binaries",
                "Win64",
            ),
            os.path.join(
                f"{drive}\\", "Epic Games", "Expedition 33", "Sandfall", "Binaries", "Win64"
            ),
        ]
        for candidate in platform_candidates:
            if os.path.isdir(candidate):
                try:
                    for entry in os.listdir(candidate):
                        if entry.lower() in target_names:
                            return candidate
                except OSError:
                    pass

    return None


def _update_mods_txt_for_install(mods_txt_path: str) -> None:
    """Non-destructively ensures Expedition33RPC : 1 is configured in mods.txt, preserving other mods."""
    target_mod = "Expedition33RPC"
    if os.path.exists(mods_txt_path):
        try:
            with open(mods_txt_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            found = False
            new_lines = []
            for line in lines:
                parts = line.split(":", 1)
                if parts and parts[0].strip().lower() == target_mod.lower():
                    new_lines.append(f"{target_mod} : 1\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines.append("\n")
                new_lines.append(f"{target_mod} : 1\n")

            with open(mods_txt_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return
        except Exception:
            pass

    os.makedirs(os.path.dirname(mods_txt_path), exist_ok=True)
    with open(mods_txt_path, "w", encoding="utf-8") as f:
        f.write(f"{target_mod} : 1\n")


def _update_mods_txt_for_uninstall(mods_txt_path: str) -> bool:
    """Removes Expedition33RPC from mods.txt and returns True if other active mods remain."""
    target_mod = "Expedition33RPC"
    other_mods_active = False
    if not os.path.exists(mods_txt_path):
        return False
    try:
        with open(mods_txt_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            parts = line.split(":", 1)
            name = parts[0].strip()
            if name.lower() == target_mod.lower():
                continue  # Remove our mod entry
            if len(parts) > 1 and parts[1].strip() == "1":
                other_mods_active = True
            new_lines.append(line)

        with open(mods_txt_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass
    return other_mods_active


def _resolve_target_dir(win64_dir: Path | str | None = None) -> str | None:
    if win64_dir:
        norm = os.path.normpath(str(win64_dir))
        if os.path.isfile(norm):
            return os.path.dirname(norm)
        if os.path.isdir(norm):
            return norm
    return find_game_win64_directory(known_win64_dir=win64_dir)


def is_bridge_installed(win64_dir: Path | str | None = None) -> bool:
    """Checks whether the UE4SS combat bridge files are present in the game directory."""
    target_dir = _resolve_target_dir(win64_dir)
    if not target_dir or not os.path.isdir(target_dir):
        return False

    dwmapi = os.path.join(target_dir, "dwmapi.dll")
    lua_script = os.path.join(target_dir, "ue4ss", "Mods", "Expedition33RPC", "scripts", "main.lua")
    return os.path.exists(dwmapi) and os.path.exists(lua_script)


def install_bridge(win64_dir: Path | str | None = None) -> tuple[bool, str]:
    """Surgically extracts and configures the embedded UE4SS bridge without overwriting third-party mods."""
    target_dir = _resolve_target_dir(win64_dir)
    if not target_dir or not os.path.isdir(target_dir):
        return False, "Game directory not found. Please launch the game once to detect it."

    zip_file = get_resource_path("bridge.zip")
    if not os.path.exists(zip_file):
        return False, f"Bridge archive file missing: {zip_file}"

    try:
        target_root = Path(target_dir).resolve()
        with zipfile.ZipFile(zip_file, "r") as zf:
            for member in zf.infolist():
                dest = (target_root / member.filename).resolve()
                if not dest.is_relative_to(target_root):
                    raise ValueError(f"Zip slip traversal attempt detected: {member.filename}")
                if member.is_dir():
                    continue
                norm_member = member.filename.replace("\\", "/").lower()
                if norm_member.endswith("ue4ss-settings.ini") and dest.exists():
                    continue
                if norm_member.endswith("mods.txt"):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(member) as source, open(dest, "wb") as target:
                        shutil.copyfileobj(source, target)
                except PermissionError as pe:
                    raise PermissionError(
                        f"Failed to write '{dest.name}': file is locked or access is denied. "
                        "Please close the game if it is running."
                    ) from pe

        # Non-destructively register our mod in mods.txt
        mods_txt = os.path.join(target_dir, "ue4ss", "Mods", "mods.txt")
        _update_mods_txt_for_install(mods_txt)

        return True, "Combat bridge installed successfully!"
    except Exception as e:
        return False, f"Error during bridge installation: {e}"


def uninstall_bridge(win64_dir: Path | str | None = None) -> tuple[bool, str]:
    """Surgically removes the bridge mod while preserving UE4SS and other active third-party mods."""
    target_dir = _resolve_target_dir(win64_dir)
    if not target_dir or not os.path.isdir(target_dir):
        return False, "Game directory not found."

    try:
        mods_txt = os.path.join(target_dir, "ue4ss", "Mods", "mods.txt")
        other_mods_exist = _update_mods_txt_for_uninstall(mods_txt)

        mod_dir = os.path.join(target_dir, "ue4ss", "Mods", "Expedition33RPC")
        if os.path.exists(mod_dir):
            shutil.rmtree(mod_dir, ignore_errors=True)

        # Only remove injection proxy DLL if no other active mods depend on UE4SS
        if not other_mods_exist:
            dwmapi = os.path.join(target_dir, "dwmapi.dll")
            if os.path.exists(dwmapi):
                with contextlib.suppress(OSError):
                    os.remove(dwmapi)

        return True, "Bridge uninstalled successfully."
    except Exception as e:
        return False, f"Error during uninstallation: {e}"


__all__ = [
    "find_game_win64_directory",
    "is_bridge_installed",
    "install_bridge",
    "uninstall_bridge",
]
