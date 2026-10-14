from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import psutil

from expedition33_rpc.core.platform import read_file_shared_text as _read_file_shared_text
from expedition33_rpc.detection.compat_paths import (
    get_game_user_settings_path,
    get_telemetry_file_path,
    get_telemetry_file_paths,
)
from expedition33_rpc.detection.game_data import TARGET_PROCESS_NAMES
from expedition33_rpc.detection.normalization import (
    format_checkpoint_tag,
    format_enemy_name,
    format_zone_name,
    is_continent_zone,
    is_menu_zone,
    resolve_tower_trial,
)
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

type TowerTrial = tuple[int, int] | str
type RawGameData = dict[str, Any]


@runtime_checkable
class ProcessLike(Protocol):
    """Static protocol decoupling process enumeration from concrete psutil instances."""

    @property
    def pid(self) -> int: ...

    def name(self) -> str: ...

    def exe(self) -> str | None: ...

    def create_time(self) -> float: ...

    def is_running(self) -> bool: ...


@dataclass(frozen=True)
class GameProcessInfo:
    """Immutable DTO holding process-level executable and filesystem locations."""

    pid: int | None = None
    exe_path: str | None = None
    win64_dir: Path | None = None
    process_create_time: float | None = None


@dataclass(frozen=True)
class GameState:
    """Immutable GameState DTO / Value Object representing normalized game presence."""

    is_running: bool = False
    process_pid: int | None = None
    process_create_time: float | None = None
    start_time: float | None = None
    game_language: str = "en"
    zone_name: str = "Exploring"
    raw_zone: str = ""
    in_combat: bool = False
    enemy_name: str = ""
    checkpoint_name: str = ""
    raw_checkpoint: str = ""
    tower_floor: int | None = None
    tower_stage_trial: TowerTrial | None = None
    process_info: GameProcessInfo | None = None

    @property
    def exe_path(self) -> str | None:
        """Convenience property accessing the game executable path from process_info."""
        return self.process_info.exe_path if self.process_info else None

    @property
    def win64_dir(self) -> Path | None:
        """Convenience property accessing the game win64 directory from process_info."""
        return self.process_info.win64_dir if self.process_info else None

    @classmethod
    def create(
        cls,
        *,
        is_running: bool = True,
        process_pid: int | None = None,
        process_create_time: float | None = None,
        start_time: float | None = None,
        game_language: str = "en",
        raw_zone: str = "",
        in_combat: bool = False,
        enemy_name: str = "",
        enemies: list[str] | None = None,
        raw_checkpoint: str = "",
        tower_floor: int | None = None,
        tower_stage_trial: TowerTrial | None = None,
        zone_name: str | None = None,
        checkpoint_name: str | None = None,
        process_info: GameProcessInfo | None = None,
        exe_path: str | None = None,
        win64_dir: Path | None = None,
    ) -> GameState:
        """Constructs an immutable GameState value object from raw telemetry inputs."""
        # 1. Zone name
        if zone_name is not None:
            resolved_zone = zone_name
        else:
            resolved_zone = format_zone_name(raw_zone, game_language)

        # 2. Enemy name & tower trial
        final_enemy = ""
        trial_info: TowerTrial | None = tower_stage_trial

        effective_enemy = enemy_name or (", ".join(enemies) if enemies else "")
        if effective_enemy or enemies:
            final_enemy = format_enemy_name(effective_enemy)

        # 3. Checkpoint name
        if checkpoint_name is not None:
            resolved_cp = checkpoint_name
        else:
            resolved_cp = ""
            is_menu = is_menu_zone(raw_zone, resolved_zone)
            is_continent = is_continent_zone(raw_zone, resolved_zone)
            if not is_menu and not is_continent and raw_checkpoint:
                resolved_cp = format_checkpoint_tag(
                    raw_checkpoint,
                    zone=raw_zone or resolved_zone,
                    lang=game_language,
                )

        # 4. Process info resolution
        effective_process_info = process_info
        effective_create_time = (
            process_create_time
            if process_create_time is not None
            else (effective_process_info.process_create_time if effective_process_info else None)
        )
        if (
            effective_process_info is None
            and is_running
            and (
                process_pid is not None
                or exe_path is not None
                or win64_dir is not None
                or process_create_time is not None
            )
        ):
            effective_process_info = GameProcessInfo(
                pid=process_pid,
                exe_path=exe_path,
                win64_dir=win64_dir,
                process_create_time=effective_create_time,
            )

        return cls(
            is_running=is_running,
            process_pid=process_pid,
            process_create_time=effective_create_time,
            start_time=start_time,
            game_language=game_language,
            zone_name=resolved_zone,
            raw_zone=raw_zone,
            in_combat=in_combat,
            enemy_name=final_enemy,
            checkpoint_name=resolved_cp,
            raw_checkpoint=raw_checkpoint,
            tower_floor=tower_floor,
            tower_stage_trial=trial_info,
            process_info=effective_process_info,
        )


@runtime_checkable
class BridgeProviderProtocol(Protocol):
    """Protocol for bridge telemetry providers."""

    def read_bridge_status(self) -> RawGameData | None: ...

    def read_game_data(
        self, min_valid_timestamp: float | None = None, lang: str = "en"
    ) -> RawGameData | None: ...

    def reset(self) -> None: ...


class BridgeStateProvider:
    """Reads real-time in-game telemetry provided by the UE4SS Lua bridge mod via IPC JSON."""

    def __init__(
        self,
        paths: list[str] | None = None,
        grace_period: float = 2.5,
        time_provider: Callable[[], float] = time.time,
    ):
        if paths is not None:
            self.paths = list(paths)
        else:
            self.paths = get_telemetry_file_paths()
        self.grace_period = grace_period
        self.time_provider = time_provider
        self._last_valid_data: RawGameData | None = None
        self._last_valid_time: float = 0.0

    def reset(self) -> None:
        self._last_valid_data = None
        self._last_valid_time = 0.0

    def read_bridge_status(self) -> dict[str, Any] | None:
        for p in self.paths:
            if not os.path.exists(p):
                continue
            for attempt in range(6):
                try:
                    content = _read_file_shared_text(p).strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            return data
                    elif attempt < 5:
                        time.sleep(0.001 * (attempt + 1))
                except (PermissionError, json.JSONDecodeError, OSError):
                    if attempt < 5:
                        time.sleep(0.001 * (attempt + 1))
                    continue
                except Exception:
                    break
        return None

    def read_game_data(
        self, min_valid_timestamp: float | None = None, lang: str = "en"
    ) -> RawGameData | None:
        del lang
        bridge = self.read_bridge_status()
        if bridge:
            bridge_ts = bridge.get("timestamp")
            is_fresh = True
            now = self.time_provider()
            if bridge_ts is not None:
                try:
                    ts_val = float(bridge_ts)
                    if abs(now - ts_val) > 5.0 or (
                        min_valid_timestamp is not None and ts_val < (min_valid_timestamp - 10)
                    ):
                        is_fresh = False
                except Exception:
                    is_fresh = False

            if is_fresh:
                raw_zone = (
                    bridge.get("raw_zone")
                    if bridge.get("raw_zone") is not None
                    else bridge.get("zone")
                )
                raw_zone_str = str(raw_zone) if raw_zone is not None else ""

                raw_enemy = bridge.get("enemy_name")
                enemy_str = str(raw_enemy) if (isinstance(raw_enemy, str) and raw_enemy) else ""

                raw_checkpoint = bridge.get("checkpoint")
                checkpoint_str = str(raw_checkpoint) if raw_checkpoint is not None else ""

                raw_floor = (
                    bridge.get("floor")
                    if bridge.get("floor") is not None
                    else bridge.get("tower_floor")
                )
                tower_floor = raw_floor if isinstance(raw_floor, int) else None

                raw_enemies = bridge.get("enemies")
                enemies_list: list[str] = (
                    [str(e) for e in raw_enemies if e] if isinstance(raw_enemies, list) else []
                )

                raw_trial = bridge.get("tower_trial")
                tower_trial: TowerTrial | None = None
                if isinstance(raw_trial, list) and len(raw_trial) == 2:
                    tower_trial = (int(raw_trial[0]), int(raw_trial[1]))
                elif isinstance(raw_trial, str) and raw_trial:
                    tower_trial = raw_trial

                data: RawGameData = {
                    "raw_zone": raw_zone_str,
                    "in_combat": bool(bridge.get("in_combat", False)),
                    "enemy_name": enemy_str,
                    "enemies": enemies_list,
                    "tower_floor": tower_floor,
                    "tower_trial": tower_trial,
                    "checkpoint": checkpoint_str,
                }
                self._last_valid_data = data
                self._last_valid_time = self.time_provider()
                return data
            else:
                self._last_valid_data = None
                return None

        # Transient glitch grace period encapsulated inside bridge provider
        if (
            self._last_valid_data is not None
            and (self.time_provider() - self._last_valid_time) < self.grace_period
        ):
            return self._last_valid_data

        return None


_DEFAULT_BRIDGE: Any = object()


class GameDetector:
    """Orchestrates game process detection, telemetry providers, and zone timing."""

    def __init__(
        self,
        timer_tracker: ZoneTimerTracker | None = None,
        bridge_provider: BridgeProviderProtocol | None | Any = _DEFAULT_BRIDGE,
        process_scanner: Callable[[], Iterable[ProcessLike]] | None = None,
        target_process_names: Iterable[str] | str | None = None,
        game_user_settings_path: Path | str | None = None,
        idle_poll_interval: float = 5.0,
        time_provider: Callable[[], float] | None = None,
    ):
        self.cached_pid: int | None = None
        self.game_start_time: float | None = None
        self.game_exe_path: str | None = None
        self.game_win64_dir: Path | None = None
        self.last_zone: str = "Exploring"
        self.last_raw_zone: str = ""
        self.last_raw_checkpoint: str = ""
        self.current_tower_trial: tuple[int, int] | str | None = None
        self._cached_language: str = "en"
        self._last_ini_mtime: float | None = None
        self._last_ini_path: Path | None = None
        self._game_user_settings_path: Path | None = (
            Path(game_user_settings_path) if game_user_settings_path is not None else None
        )
        self.idle_poll_interval: float = idle_poll_interval
        self.time_provider: Callable[[], float] = (
            time_provider if time_provider is not None else time.monotonic
        )
        self._last_process_scan_time: float = -float("inf")
        resolved_names: list[str] = []
        if target_process_names is not None:
            if isinstance(target_process_names, str):
                resolved_names.append(target_process_names.strip().lower())
            else:
                resolved_names.extend(n.strip().lower() for n in target_process_names if n.strip())
        else:
            resolved_names.extend(TARGET_PROCESS_NAMES)
        self.target_process_names: frozenset[str] = frozenset(resolved_names)

        # Components
        self.timer_tracker = timer_tracker if timer_tracker is not None else ZoneTimerTracker()
        self.process_scanner = process_scanner

        # Telemetry Provider (Bridge IPC)
        self.bridge_provider: BridgeProviderProtocol | None = (
            BridgeStateProvider() if bridge_provider is _DEFAULT_BRIDGE else bridge_provider
        )

    @property
    def exe_path(self) -> str | None:
        """Returns the detected executable path of the running game process."""
        return self.game_exe_path

    @property
    def win64_dir(self) -> Path | None:
        """Returns the detected Win64 directory of the running game process."""
        return self.game_win64_dir

    def _resolve_and_cache_process_paths(self, proc: ProcessLike) -> None:
        if self.game_win64_dir is not None:
            return
        try:
            exe = proc.exe()
            if exe and isinstance(exe, str):
                self.game_exe_path = os.path.normpath(exe)
                candidate = os.path.dirname(self.game_exe_path)
                self.game_win64_dir = Path(candidate)
        except Exception:
            pass

    def find_game_process(
        self, now: float | None = None, force: bool = False
    ) -> ProcessLike | None:
        """Finds game process using cached PID validation or fast name-only process iteration with idle backoff."""
        # 1. Fast path: validate cached PID
        if self.cached_pid is not None:
            if self.process_scanner is not None:
                try:
                    for p in self.process_scanner():
                        if (
                            p.pid == self.cached_pid
                            and p.is_running()
                            and p.name().lower() in self.target_process_names
                        ):
                            self._resolve_and_cache_process_paths(p)
                            return p
                except Exception:
                    pass
            else:
                try:
                    proc = psutil.Process(self.cached_pid)
                    if proc.is_running() and proc.name().lower() in self.target_process_names:
                        self._resolve_and_cache_process_paths(proc)
                        return proc
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    pass
            self.cached_pid = None
            self.game_exe_path = None
            self.game_win64_dir = None

        # 2. Optimized global enumeration with adaptive idle backoff
        current_time = self.time_provider() if now is None else now
        if (
            self.cached_pid is None
            and self.process_scanner is None
            and not force
            and (current_time - self._last_process_scan_time < self.idle_poll_interval)
        ):
            return None

        self._last_process_scan_time = current_time

        try:
            procs = (
                self.process_scanner()
                if self.process_scanner is not None
                else psutil.process_iter(["pid", "name"])
            )
        except Exception:
            return None

        for proc in procs:
            try:
                proc_name = proc.name()
                if proc_name and proc_name.lower() in self.target_process_names:
                    self.cached_pid = proc.pid
                    self._resolve_and_cache_process_paths(proc)
                    if not self.game_start_time:
                        try:
                            self.game_start_time = float(proc.create_time())
                        except Exception:
                            self.game_start_time = time.time()
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                continue
        self.game_exe_path = None
        self.game_win64_dir = None
        return None

    def get_game_language(self, ini_path: Path | str | None = None) -> str:
        """Extracts configured UI language from GameUserSettings.ini with mtime caching."""
        target_ini = ini_path or self._game_user_settings_path or get_game_user_settings_path()
        if target_ini is None:
            target_ini = os.path.expandvars(
                r"%LOCALAPPDATA%\Sandfall\Saved\Config\Windows\GameUserSettings.ini"
            )
        ini_file = Path(target_ini)
        try:
            if ini_file.is_file():
                current_mtime = ini_file.stat().st_mtime
                if self._last_ini_path == ini_file and self._last_ini_mtime == current_mtime:
                    return self._cached_language

                lang = "en"
                with open(ini_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Language="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
                            if val:
                                lang = val
                                break
                self._cached_language = lang
                self._last_ini_mtime = current_mtime
                self._last_ini_path = ini_file
                return lang
        except Exception:
            pass
        return self._cached_language

    def get_game_state(self, now: float | None = None, force: bool = False) -> GameState:
        """Executes a full detection cycle returning an immutable GameState snapshot."""
        proc = (
            self.find_game_process(now, force)
            if (now is not None or force)
            else self.find_game_process()
        )

        if not proc:
            self.cached_pid = None
            self.game_start_time = None
            self.game_exe_path = None
            self.game_win64_dir = None
            self.current_tower_trial = None
            self.last_zone = "Exploring"
            self.last_raw_zone = ""
            self.last_raw_checkpoint = ""
            if self.bridge_provider is not None:
                self.bridge_provider.reset()
            self.timer_tracker.reset()
            return GameState(is_running=False, game_language=self._cached_language)

        lang = self.get_game_language()

        # Extract process creation time safely only for the matched process
        proc_create_time: float | None = None
        try:
            proc_create_time = float(proc.create_time())
        except Exception:
            proc_create_time = None

        # Query configured telemetry provider
        data: RawGameData | None = (
            self.bridge_provider.read_game_data(min_valid_timestamp=proc_create_time, lang=lang)
            if self.bridge_provider is not None
            else None
        )

        raw_zone = ""
        in_combat = False
        raw_enemy = ""
        raw_enemies: list[str] = []
        tower_floor = None
        raw_checkpoint = ""

        if data:
            raw_zone = str(data.get("raw_zone", "") or "")
            in_combat = bool(data.get("in_combat", False))
            raw_enemy = str(data.get("enemy_name", "") or "")
            raw_enemies = data.get("enemies", [])
            tower_floor = data.get("tower_floor")
            raw_checkpoint = str(data.get("checkpoint", "") or "")

            if is_menu_zone(raw_zone):
                raw_checkpoint = ""
                in_combat = False

        is_menu = is_menu_zone(raw_zone)
        is_continent = is_continent_zone(raw_zone)

        # Checkpoint resolution via active telemetry source
        if is_menu or is_continent:
            raw_checkpoint = ""
            self.last_raw_checkpoint = ""
        elif raw_checkpoint:
            self.last_raw_checkpoint = raw_checkpoint
        else:
            if raw_zone and raw_zone == self.last_raw_zone:
                raw_checkpoint = self.last_raw_checkpoint
            else:
                raw_checkpoint = ""
                self.last_raw_checkpoint = ""

        self.last_raw_zone = raw_zone

        # Track Endless Tower stage and trial
        is_tower = any(k in raw_zone.lower() for k in ("torre", "tower", "clea"))
        effective_enemy = raw_enemy
        if is_tower and in_combat:
            bridge_trial = data.get("tower_trial") if data else None
            if bridge_trial:
                self.current_tower_trial = bridge_trial
            elif raw_enemy or raw_enemies:
                trial_info, clean_enemy = resolve_tower_trial(raw_enemy, enemies=raw_enemies)
                self.current_tower_trial = trial_info
                if clean_enemy:
                    effective_enemy = clean_enemy
            else:
                self.current_tower_trial = None
        elif not in_combat:
            self.current_tower_trial = None

        # Determine zone key and update state timing machine
        zone_key = raw_zone.strip() or "Exploring"
        self.last_zone = zone_key
        if zone_key == "Exploring" and self.timer_tracker.current_zone_id not in (
            None,
            "Exploring",
        ):
            zone_key = self.timer_tracker.current_zone_id

        effective_start = self.timer_tracker.update(
            zone_key=zone_key,
            in_combat=in_combat,
            is_tower=is_tower,
            current_tower_trial=self.current_tower_trial,
        )

        proc_info = GameProcessInfo(
            pid=proc.pid,
            exe_path=self.game_exe_path,
            win64_dir=self.game_win64_dir,
            process_create_time=proc_create_time,
        )

        return GameState.create(
            is_running=True,
            process_pid=proc.pid,
            process_create_time=proc_create_time,
            start_time=effective_start,
            game_language=lang,
            raw_zone=raw_zone,
            in_combat=in_combat,
            enemy_name=effective_enemy,
            enemies=raw_enemies,
            raw_checkpoint=raw_checkpoint,
            tower_floor=tower_floor,
            tower_stage_trial=self.current_tower_trial,
            process_info=proc_info,
            exe_path=self.game_exe_path,
            win64_dir=self.game_win64_dir,
        )


__all__ = [
    "ProcessLike",
    "BridgeProviderProtocol",
    "GameProcessInfo",
    "GameState",
    "BridgeStateProvider",
    "GameDetector",
    "TARGET_PROCESS_NAMES",
    "get_telemetry_file_path",
    "get_telemetry_file_paths",
]
