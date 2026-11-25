from __future__ import annotations

import os
import shutil
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from expedition33_rpc.core.platform import winreg
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.game_data import TARGET_PROCESS_NAMES
from expedition33_rpc.detection.steam_resolver import SteamCompatResolver

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import ProcessLike


def _find_win64_from_running_processes(
    target_names: set[str],
    process_scanner: Callable[[], Iterable[Any]] | None = None,
) -> str | None:
    """Scans running processes via process_scanner or psutil to locate the game's Win64 / WinGDK directory."""
    try:
        procs = (
            process_scanner()
            if process_scanner is not None
            else psutil.process_iter(["name", "exe"])
        )
    except Exception:
        return None

    for proc in procs:
        try:
            name: str | None = proc.name() if callable(getattr(proc, "name", None)) else None
            exe_path: str | None = proc.exe() if callable(getattr(proc, "exe", None)) else None

            if name and name.lower() in target_names and exe_path and os.path.exists(exe_path):
                target_dir = os.path.dirname(os.path.abspath(exe_path))
                if os.path.basename(target_dir).lower() in ("win64", "wingdk"):
                    return target_dir
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            continue
    return None


def find_game_win64_directory(
    target_process_names: Iterable[str] | str | None = None,
    known_win64_dir: Path | str | None = None,
    known_exe_path: Path | str | None = None,
    *,
    process_scanner: Callable[[], Iterable[ProcessLike]] | None = None,
    steam_resolver: SteamCompatResolver | None = None,
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

    target_names: set[str] = set()
    if target_process_names is not None:
        if isinstance(target_process_names, str):
            target_names.add(target_process_names.strip().lower())
        else:
            target_names.update(n.strip().lower() for n in target_process_names if n.strip())
    else:
        target_names.update(TARGET_PROCESS_NAMES)

    # 1. Check running processes via ProcessLike / process_scanner protocol
    proc_dir = _find_win64_from_running_processes(target_names, process_scanner=process_scanner)
    if proc_dir:
        return proc_dir

    # 2. Check Steam Registry and Library Folders via unified SteamCompatResolver
    resolver = steam_resolver or SteamCompatResolver(winreg_module=winreg)
    return resolver.find_game_install_win64_directory(target_names)


def _update_mods_txt_for_install(mods_txt_path: str) -> None:
    """Non-destructively ensures Expedition33RPC : 1 is configured in mods.txt, preserving other mods."""
    target_mod = "Expedition33RPC"
    if os.path.exists(mods_txt_path):
        try:
            with open(mods_txt_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            found = False
            new_lines: list[str] = []
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


def _has_other_active_mods(mods_txt_path: str) -> bool:
    """Returns True if mods.txt contains active mods other than Expedition33RPC."""
    target_mod = "Expedition33RPC"
    if not os.path.exists(mods_txt_path):
        return False
    try:
        with open(mods_txt_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split(":", 1)
                name = parts[0].strip()
                if name.lower() == target_mod.lower():
                    continue
                if len(parts) > 1 and parts[1].strip() == "1":
                    return True
    except Exception:
        pass
    return False


def _update_mods_txt_for_uninstall(mods_txt_path: str) -> bool:
    """Removes Expedition33RPC from mods.txt and returns True if other active mods remain."""
    target_mod = "Expedition33RPC"
    other_mods_active = False
    if not os.path.exists(mods_txt_path):
        return False
    try:
        with open(mods_txt_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        new_lines: list[str] = []
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
        mod_dir = os.path.join(target_dir, "ue4ss", "Mods", "Expedition33RPC")
        if os.path.exists(mod_dir):
            try:
                shutil.rmtree(mod_dir)
            except (PermissionError, OSError) as exc:
                return (
                    False,
                    f"Failed to remove '{mod_dir}': {exc}. Please close the game if it is running.",
                )

        if os.path.exists(mod_dir):
            return (
                False,
                f"Failed to remove '{mod_dir}': target still exists on disk. "
                "Please close the game if it is running.",
            )

        mods_txt = os.path.join(target_dir, "ue4ss", "Mods", "mods.txt")
        other_mods_exist = _has_other_active_mods(mods_txt)

        # Only remove injection proxy DLL if no other active mods depend on UE4SS
        dwmapi = os.path.join(target_dir, "dwmapi.dll")
        if not other_mods_exist and os.path.exists(dwmapi):
            try:
                os.remove(dwmapi)
            except (PermissionError, OSError) as exc:
                return (
                    False,
                    f"Failed to remove '{dwmapi}': {exc}. Please close the game if it is running.",
                )

        if not other_mods_exist and os.path.exists(dwmapi):
            return (
                False,
                f"Failed to remove '{dwmapi}': target still exists on disk. "
                "Please close the game if it is running.",
            )

        _update_mods_txt_for_uninstall(mods_txt)
        return True, "Bridge uninstalled successfully."
    except Exception as e:
        return False, f"Error during uninstallation: {e}"


__all__ = [
    "find_game_win64_directory",
    "is_bridge_installed",
    "install_bridge",
    "uninstall_bridge",
]
