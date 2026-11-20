"""Single Source of Truth for Steam, Proton, and Wine path and prefix resolution."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from expedition33_rpc.core.platform import winreg as platform_winreg
from expedition33_rpc.core.platform import winreg_read_value
from expedition33_rpc.detection.game_data import TARGET_PROCESS_NAMES

DEFAULT_STEAM_APP_ID: str = "1903340"
DEFAULT_APP_ID: str = "1903340"

STANDARD_LINUX_STEAM_ROOTS: tuple[str, ...] = (
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
)

STEAM_REGISTRY_SUBKEYS: tuple[tuple[str, str], ...] = (
    ("HKEY_CURRENT_USER", r"Software\Valve\Steam"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Valve\Steam"),
)


class SteamCompatResolver:
    """Pure, testable single-source-of-truth resolver for Steam, Proton, Wine prefixes, and library folders."""

    DEFAULT_APP_ID: str = DEFAULT_APP_ID
    DEFAULT_STEAM_APP_ID: str = DEFAULT_STEAM_APP_ID

    def __init__(
        self,
        app_id: str = DEFAULT_APP_ID,
        *,
        is_windows: bool | None = None,
        home_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
        winreg_module: Any | None = None,
    ) -> None:
        self.app_id = app_id
        self._is_windows: bool = (
            is_windows if is_windows is not None else (sys.platform == "win32" or os.name == "nt")
        )
        self._home_dir: Path = home_dir if home_dir is not None else Path.home()
        self._environ: Mapping[str, str] = environ if environ is not None else os.environ
        self._winreg_module: Any = winreg_module if winreg_module is not None else platform_winreg

    @property
    def is_windows(self) -> bool:
        return self._is_windows

    @property
    def home_dir(self) -> Path:
        return self._home_dir

    def get_steam_roots(self, existing_only: bool = False) -> list[Path]:
        """Resolves root Steam installation paths across Windows registry or Linux/SteamOS roots."""
        roots: list[Path] = []
        if self._winreg_module is not None:
            for hkey_attr, subkey in STEAM_REGISTRY_SUBKEYS:
                hkey = getattr(self._winreg_module, hkey_attr, None)
                if hkey is None:
                    continue
                val = winreg_read_value(
                    hkey, subkey, "SteamPath", winreg_module=self._winreg_module
                )
                if val:
                    p = Path(os.path.normpath(val))
                    if not existing_only or os.path.isdir(p):
                        roots.append(p)

        # Non-Windows / Linux / Steam Deck standard roots
        if not roots and not self._is_windows:
            for rel in STANDARD_LINUX_STEAM_ROOTS:
                p = self._home_dir / rel
                if not existing_only or os.path.isdir(p):
                    roots.append(p)

        # De-duplicate preserving order
        seen: set[str] = set()
        unique: list[Path] = []
        for r in roots:
            norm = os.path.normpath(str(r))
            if norm not in seen:
                seen.add(norm)
                unique.append(Path(norm))
        return unique

    @staticmethod
    def parse_libraryfolders_vdf(vdf_path: Path | str) -> list[Path]:
        """Parses a Valve libraryfolders.vdf file and extracts all configured library paths."""
        libraries: list[Path] = []
        path_obj = Path(vdf_path)
        try:
            if not os.path.isfile(path_obj):
                return libraries
            with open(path_obj, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("//") or stripped.startswith("#"):
                        continue
                    for m in re.finditer(r'"path"\s*"([^"]+)"', stripped, re.IGNORECASE):
                        val = m.group(1).strip()
                        if val:
                            libraries.append(Path(os.path.normpath(val)))
        except OSError:
            pass
        return libraries

    def get_steam_libraries(self, steam_roots: Iterable[Path | str] | None = None) -> list[Path]:
        """Discovers all Steam library folders across all detected Steam roots via libraryfolders.vdf."""
        roots = (
            [Path(r) for r in steam_roots]
            if steam_roots is not None
            else self.get_steam_roots(existing_only=not self._is_windows)
        )
        libraries: list[Path] = list(roots)

        for root in roots:
            vdf_path = root / "steamapps" / "libraryfolders.vdf"
            for lib in self.parse_libraryfolders_vdf(vdf_path):
                libraries.append(lib)

        # De-duplicate preserving order
        seen: set[str] = set()
        unique: list[Path] = []
        for lib in libraries:
            norm = os.path.normpath(str(lib))
            if norm not in seen:
                seen.add(norm)
                unique.append(Path(norm))
        return unique

    def get_proton_prefixes(self) -> list[Path]:
        """Resolves Proton / Wine prefix directories (the 'pfx' folder) ordered by priority:

        1. STEAM_COMPAT_DATA_PATH override -> <val>/pfx
        2. WINEPREFIX override -> <val>
        3. Standard Linux Steam roots -> <root>/steamapps/compatdata/<app_id>/pfx
        """
        prefixes: list[Path] = []

        # 1. STEAM_COMPAT_DATA_PATH
        env_compat = self._environ.get("STEAM_COMPAT_DATA_PATH")
        if env_compat:
            prefixes.append(Path(env_compat) / "pfx")

        # 2. WINEPREFIX
        env_wine = self._environ.get("WINEPREFIX")
        if env_wine:
            prefixes.append(Path(env_wine))

        # 3. Standard Linux Steam roots
        if not self._is_windows:
            for root in self.get_steam_roots(existing_only=False):
                prefixes.append(root / "steamapps" / "compatdata" / self.app_id / "pfx")

        # De-duplicate preserving order
        seen: set[str] = set()
        unique: list[Path] = []
        for p in prefixes:
            norm = os.path.normpath(str(p))
            if norm not in seen:
                seen.add(norm)
                unique.append(Path(norm))
        return unique

    def get_prefix_user_roots(self) -> list[Path]:
        """Returns candidate 'drive_c/users/steamuser' paths for each Proton/Wine prefix."""
        return [pfx / "drive_c" / "users" / "steamuser" for pfx in self.get_proton_prefixes()]

    def resolve_telemetry_candidates(self) -> list[str]:
        """Returns candidate paths for the expedition33_status.json / rpc_status.json telemetry files."""
        if self._is_windows:
            return [
                os.path.expandvars(r"%TEMP%\expedition33_status.json"),
                os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\rpc_status.json"),
            ]

        paths: list[str] = []
        for user_root in self.get_prefix_user_roots():
            paths.append(str(user_root / "Temp" / "expedition33_status.json"))
            paths.append(str(user_root / "AppData" / "Local" / "Sandfall" / "rpc_status.json"))

        paths.append("/tmp/expedition33_status.json")

        seen: set[str] = set()
        unique: list[str] = []
        for p in paths:
            norm = os.path.normpath(p)
            if norm not in seen:
                seen.add(norm)
                unique.append(norm)
        return unique

    def resolve_config_candidates(self) -> list[str]:
        """Returns candidate paths for GameUserSettings.ini."""
        if self._is_windows:
            return [
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Sandfall\Saved\Config\Windows\GameUserSettings.ini"
                ),
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Sandfall\Saved\Config\WindowsNoEditor\GameUserSettings.ini"
                ),
            ]

        paths: list[str] = []
        for user_root in self.get_prefix_user_roots():
            sandfall_saved = user_root / "AppData" / "Local" / "Sandfall" / "Saved" / "Config"
            paths.append(str(sandfall_saved / "Windows" / "GameUserSettings.ini"))
            paths.append(str(sandfall_saved / "WindowsNoEditor" / "GameUserSettings.ini"))

        paths.append(
            str(
                self._home_dir
                / ".config"
                / "Sandfall"
                / "Saved"
                / "Config"
                / "Windows"
                / "GameUserSettings.ini"
            )
        )

        seen: set[str] = set()
        unique: list[str] = []
        for p in paths:
            norm = os.path.normpath(p)
            if norm not in seen:
                seen.add(norm)
                unique.append(norm)
        return unique

    def resolve_save_games_candidates(self) -> list[str]:
        """Returns candidate paths for the SaveGames directory."""
        if self._is_windows:
            return [
                os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames"),
            ]

        paths: list[str] = []
        for user_root in self.get_prefix_user_roots():
            paths.append(str(user_root / "AppData" / "Local" / "Sandfall" / "Saved" / "SaveGames"))

        paths.append(str(self._home_dir / ".config" / "Sandfall" / "Saved" / "SaveGames"))

        seen: set[str] = set()
        unique: list[str] = []
        for p in paths:
            norm = os.path.normpath(p)
            if norm not in seen:
                seen.add(norm)
                unique.append(norm)
        return unique

    def find_game_install_win64_directory(self, target_names: set[str] | None = None) -> str | None:
        """Scans all discovered Steam libraries for the game's Win64 binary directory containing a target binary."""
        targets = (
            target_names
            if target_names is not None
            else {name.lower() for name in TARGET_PROCESS_NAMES}
        )

        libraries = self.get_steam_libraries()
        checked_dirs: set[str] = set()

        for lib in libraries:
            lib_str = os.path.normpath(str(lib))
            if not lib_str or lib_str in checked_dirs:
                continue
            checked_dirs.add(lib_str)

            win64_candidate = os.path.join(
                lib_str,
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
                        if entry.lower() in targets:
                            return win64_candidate
                except OSError:
                    pass

        return None

    @staticmethod
    def get_steam_installation_path() -> Path | None:
        """Returns the first detected active Steam installation root path, if any."""
        roots = SteamCompatResolver().get_steam_roots(existing_only=True)
        for r in roots:
            if os.path.isdir(r):
                return r
        return None

    @staticmethod
    def get_steam_library_folders(steam_path: Path | None = None) -> list[Path]:
        """Discovers all Steam library paths, optionally from a specified Steam root."""
        if steam_path is not None:
            vdf_path = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
            libs = SteamCompatResolver.parse_libraryfolders_vdf(vdf_path)
            all_libs = [Path(steam_path)] + libs
            seen: set[str] = set()
            res: list[Path] = []
            for lib in all_libs:
                norm = os.path.normpath(str(lib))
                if norm not in seen:
                    seen.add(norm)
                    res.append(Path(norm))
            return res
        return SteamCompatResolver().get_steam_libraries()

    @classmethod
    def get_game_installation_directories(
        cls, app_id: str = DEFAULT_APP_ID, folder_name: str = "Expedition 33"
    ) -> list[Path]:
        """Finds game installation directories across all discovered Steam libraries."""
        resolver = cls(app_id=app_id)
        candidates: list[Path] = []
        for lib in resolver.get_steam_libraries():
            candidate = lib / "steamapps" / "common" / folder_name
            if os.path.isdir(candidate):
                candidates.append(candidate)
        return candidates

    @classmethod
    def get_proton_prefix_paths(cls, app_id: str = DEFAULT_APP_ID) -> list[Path]:
        """Resolves Proton / Wine prefix directories for the given app_id."""
        return cls(app_id=app_id).get_proton_prefixes()

    @classmethod
    def get_telemetry_file_candidates(cls, app_id: str = DEFAULT_APP_ID) -> list[str]:
        """Resolves candidate telemetry status files for the given app_id."""
        return cls(app_id=app_id).resolve_telemetry_candidates()


__all__ = [
    "DEFAULT_APP_ID",
    "DEFAULT_STEAM_APP_ID",
    "STANDARD_LINUX_STEAM_ROOTS",
    "STEAM_REGISTRY_SUBKEYS",
    "SteamCompatResolver",
]
