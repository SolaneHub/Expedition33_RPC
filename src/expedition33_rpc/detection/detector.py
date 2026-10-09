from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, override, runtime_checkable

import psutil

from expedition33_rpc.detection.game_data import TARGET_PROCESS_NAME
from expedition33_rpc.detection.normalization import (
    format_checkpoint_tag,
    format_enemy_name,
    format_zone_name,
    is_main_menu,
    resolve_tower_trial,
    strip_accents,
)
from expedition33_rpc.detection.save_reader import SaveFileReader
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

type TowerTrial = tuple[int, int] | str
type RawGameData = dict[str, Any]


@runtime_checkable
class ProcessLike(Protocol):
    """Static protocol decoupling process enumeration from concrete psutil instances."""

    @property
    def pid(self) -> int: ...

    def name(self) -> str: ...

    def create_time(self) -> float: ...

    def is_running(self) -> bool: ...


@dataclass(frozen=True)
class GameState:
    """Immutable GameState DTO / Value Object representing normalized game presence."""

    is_running: bool = False
    process_pid: int | None = None
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

    @classmethod
    def create(
        cls,
        *,
        is_running: bool = True,
        process_pid: int | None = None,
        start_time: float | None = None,
        game_language: str = "en",
        raw_zone: str = "",
        in_combat: bool = False,
        enemy_name: str = "",
        enemies: list[str] | None = None,
        raw_checkpoint: str = "",
        tower_floor: int | None = None,
        tower_stage_trial: TowerTrial | None = None,
        current_tower_trial: TowerTrial | None = None,
        zone_name: str | None = None,
        checkpoint_name: str | None = None,
    ) -> GameState:
        """Constructs an immutable GameState value object from raw telemetry inputs."""
        # 1. Zone name
        if zone_name is not None:
            resolved_zone = zone_name
        elif not raw_zone:
            resolved_zone = "In esplorazione" if game_language.startswith("it") else "Exploring"
        else:
            resolved_zone = format_zone_name(raw_zone, game_language)

        # 2. Enemy name & tower trial
        is_tower = any(k in (raw_zone or resolved_zone).lower() for k in ("torre", "tower", "clea"))
        final_enemy = ""
        trial_info = tower_stage_trial if tower_stage_trial is not None else current_tower_trial

        effective_enemy = enemy_name or (", ".join(enemies) if enemies else "")
        if effective_enemy or enemies:
            if is_tower:
                if tower_stage_trial is not None:
                    trial_info = tower_stage_trial
                    final_enemy = format_enemy_name(effective_enemy)
                else:
                    t_info, clean_enemy = resolve_tower_trial(effective_enemy, enemies=enemies)
                    if t_info and not trial_info:
                        trial_info = t_info
                    final_enemy = clean_enemy if clean_enemy else format_enemy_name(effective_enemy)
            else:
                final_enemy = format_enemy_name(effective_enemy)

        # 3. Checkpoint name
        if checkpoint_name is not None:
            resolved_cp = checkpoint_name
        else:
            resolved_cp = ""
            is_menu = is_main_menu(raw_zone, resolved_zone)
            is_continent = (
                "worldmap" in raw_zone.lower()
                or raw_zone.lower().strip() in ("main", "the continent", "il continente")
                or "continent" in raw_zone.lower()
                or "continente" in raw_zone.lower()
            )
            if not is_menu and not is_continent and raw_checkpoint:
                resolved_cp = format_checkpoint_tag(
                    raw_checkpoint,
                    zone=raw_zone or resolved_zone,
                    lang=game_language,
                )

        return cls(
            is_running=is_running,
            process_pid=process_pid,
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
        )

    def matches(self, other: GameState | None) -> bool:
        """Returns True if the user-facing game status is functionally identical."""
        if not other:
            return False
        return (
            self.is_running == other.is_running
            and self.zone_name == other.zone_name
            and self.in_combat == other.in_combat
            and self.enemy_name == other.enemy_name
            and self.checkpoint_name == other.checkpoint_name
            and self.tower_floor == other.tower_floor
            and self.tower_stage_trial == other.tower_stage_trial
        )


class GameStateProvider(ABC):
    """Abstract Strategy interface for querying game presence telemetry."""

    def reset(self) -> None:
        """Resets cached or grace-period state when game terminates."""
        return None

    @abstractmethod
    def read_game_data(
        self, min_valid_timestamp: float | None = None, lang: str = "en"
    ) -> RawGameData | None:
        """Reads raw, un-normalized game telemetry from the provider."""
        pass

    def resolve_raw_checkpoint(self, raw_zone: str) -> str:
        """Resolves raw checkpoint tag for a zone if supported by this provider."""
        del raw_zone
        return ""


class BridgeStateProvider(GameStateProvider):
    """Reads real-time in-game telemetry provided by the UE4SS Lua bridge mod via IPC JSON."""

    def __init__(self, paths: list[str] | None = None, grace_period: float = 2.5):
        if paths is not None:
            self.paths = list(paths)
        else:
            self.paths = [
                os.path.expandvars(r"%TEMP%\expedition33_status.json"),
                os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\rpc_status.json"),
            ]
        self.grace_period = grace_period
        self._last_valid_data: RawGameData | None = None
        self._last_valid_time: float = 0.0

    @override
    def reset(self) -> None:
        self._last_valid_data = None
        self._last_valid_time = 0.0

    def read_bridge_status(self) -> dict[str, Any] | None:
        for p in self.paths:
            if not os.path.exists(p):
                continue
            for attempt in range(6):
                try:
                    with open(p, encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            return data
                    elif attempt < 5:
                        time.sleep(0.005 * (attempt + 1))
                except (PermissionError, json.JSONDecodeError, OSError):
                    if attempt < 5:
                        time.sleep(0.005 * (attempt + 1))
                    continue
                except Exception:
                    break
        return None

    @override
    def read_game_data(
        self, min_valid_timestamp: float | None = None, lang: str = "en"
    ) -> RawGameData | None:
        del lang
        bridge = self.read_bridge_status()
        if bridge:
            bridge_ts = bridge.get("timestamp")
            is_fresh = True
            if bridge_ts is not None and min_valid_timestamp is not None:
                try:
                    ts_val = float(bridge_ts)
                    if ts_val < (min_valid_timestamp - 10):
                        is_fresh = False
                except Exception:
                    is_fresh = False

            if is_fresh:
                raw_zone = (
                    bridge.get("zone") if bridge.get("zone") is not None else bridge.get("raw_zone")
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
                self._last_valid_time = time.time()
                return data

        # Transient glitch grace period encapsulated inside bridge provider
        if (
            self._last_valid_data is not None
            and (time.time() - self._last_valid_time) < self.grace_period
        ):
            return self._last_valid_data

        return None


class SaveFileStateProvider(GameStateProvider):
    """Fallback provider that extracts zone and checkpoint locations from Unreal Engine .sav files.

    Passive fallback contract:
    - Provides non-intrusive disk inspection when active bridge IPC telemetry is inactive.
    - If min_valid_timestamp is provided and save files predate process launch, indicates
      the user is at game startup / Main Menu before loading a save.
    """

    def __init__(self, save_reader: SaveFileReader):
        self.save_reader = save_reader

    @override
    def resolve_raw_checkpoint(self, raw_zone: str) -> str:
        """Finds matching checkpoint tag using the SaveFileReader index."""
        save_dir = self.save_reader.get_latest_save_dir()
        if not save_dir:
            return ""

        cp_lvl, cp_tag = self.save_reader.read_checkpoint_from_save(save_dir)
        zone_disp = format_zone_name(raw_zone)
        if cp_tag and self.save_reader.is_checkpoint_for_zone(
            cp_lvl or "", cp_tag, raw_zone, zone_disp
        ):
            return cp_tag

        return ""

    @override
    def read_game_data(
        self, min_valid_timestamp: float | None = None, lang: str = "en"
    ) -> RawGameData | None:
        del lang
        save_dir = self.save_reader.get_latest_save_dir()
        if not save_dir:
            return None

        # Check if process launched and save file strictly predates process start time
        if min_valid_timestamp is not None:
            try:
                container = os.path.join(save_dir, "SavesContainer.sav")
                if os.path.exists(container):
                    save_mtime = os.path.getmtime(container)
                else:
                    sav_files = list(Path(save_dir).glob("*.sav"))
                    if sav_files:
                        save_mtime = max(p.stat().st_mtime for p in sav_files)
                    else:
                        save_mtime = os.path.getmtime(save_dir)
                if save_mtime < min_valid_timestamp:
                    return {
                        "raw_zone": "MainMenu",
                        "in_combat": False,
                        "enemy_name": "",
                        "enemies": [],
                        "tower_floor": None,
                        "tower_trial": None,
                        "checkpoint": "",
                    }
            except Exception:
                pass

        raw_zone = self.save_reader.read_zone_from_saves(save_dir) or ""
        raw_checkpoint = self.resolve_raw_checkpoint(raw_zone) if raw_zone else ""

        return {
            "raw_zone": raw_zone,
            "in_combat": False,
            "enemy_name": "",
            "enemies": [],
            "tower_floor": None,
            "tower_trial": None,
            "checkpoint": raw_checkpoint,
        }


class GameDetector:
    """Orchestrates game process detection, telemetry providers, and zone timing."""

    def __init__(
        self,
        base_save_dir: str | None = None,
        save_reader: SaveFileReader | None = None,
        timer_tracker: ZoneTimerTracker | None = None,
        providers: list[GameStateProvider] | None = None,
        process_scanner: Callable[[], Iterable[ProcessLike]] | None = None,
        target_process_name: str | None = None,
        game_user_settings_path: Path | str | None = None,
    ):
        self.cached_pid: int | None = None
        self.game_start_time: float | None = None
        self.last_zone: str = "Exploring"
        self.last_raw_zone: str = ""
        self.current_tower_trial: tuple[int, int] | str | None = None
        self._game_user_settings_path: Path | None = (
            Path(game_user_settings_path) if game_user_settings_path is not None else None
        )
        self.target_process_name: str = (
            target_process_name.strip().lower()
            if target_process_name is not None
            else TARGET_PROCESS_NAME
        )

        # Components
        effective_reader = save_reader if save_reader is not None else SaveFileReader(base_save_dir)
        self.timer_tracker = timer_tracker if timer_tracker is not None else ZoneTimerTracker()
        self.process_scanner = process_scanner

        # Polymorphic Telemetry Providers Pipeline (Bridge IPC -> Save File)
        self.providers: list[GameStateProvider] = (
            list(providers)
            if providers is not None
            else [BridgeStateProvider(), SaveFileStateProvider(effective_reader)]
        )

    def find_game_process(self) -> ProcessLike | None:
        """Finds game process using cached PID validation or fast name-only process iteration."""
        # 1. Fast path: validate cached PID
        if self.cached_pid is not None:
            if self.process_scanner is not None:
                try:
                    for p in self.process_scanner():
                        if (
                            p.pid == self.cached_pid
                            and p.is_running()
                            and p.name().lower() == self.target_process_name
                        ):
                            return p
                except Exception:
                    pass
            else:
                try:
                    proc = psutil.Process(self.cached_pid)
                    if proc.is_running() and proc.name().lower() == self.target_process_name:
                        return proc
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    pass
            self.cached_pid = None

        # 2. Optimized global enumeration: request only name and pid, avoid create_time on all processes
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
                if proc_name and proc_name.lower() == self.target_process_name:
                    self.cached_pid = proc.pid
                    if not self.game_start_time:
                        try:
                            self.game_start_time = float(proc.create_time())
                        except Exception:
                            self.game_start_time = time.time()
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                continue
        return None

    def get_game_language(self, ini_path: Path | str | None = None) -> str:
        """Extracts configured UI language from GameUserSettings.ini."""
        target_ini = ini_path or self._game_user_settings_path
        if target_ini is None:
            target_ini = os.path.expandvars(
                r"%LOCALAPPDATA%\Sandfall\Saved\Config\Windows\GameUserSettings.ini"
            )
        ini_file = Path(target_ini)
        if ini_file.is_file():
            try:
                with open(ini_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Language="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
                            if val:
                                return val
            except Exception:
                pass
        return "en"

    def get_game_state(self) -> GameState:
        """Executes a full detection cycle returning an immutable GameState snapshot."""
        proc = self.find_game_process()
        lang = self.get_game_language()

        if not proc:
            self.cached_pid = None
            self.game_start_time = None
            self.current_tower_trial = None
            self.last_zone = "Exploring"
            self.last_raw_zone = ""
            for provider in self.providers:
                provider.reset()
            self.timer_tracker.reset()
            return GameState(is_running=False, game_language=lang)

        # Extract process creation time safely only for the matched process
        proc_create_time: float | None = None
        try:
            proc_create_time = float(proc.create_time())
        except Exception:
            proc_create_time = None

        # Query configured telemetry providers polymorphic pipeline
        data: RawGameData | None = None
        for provider in self.providers:
            data = provider.read_game_data(min_valid_timestamp=proc_create_time, lang=lang)
            if data:
                break

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

            if is_main_menu(raw_zone):
                raw_checkpoint = ""
                in_combat = False

        is_menu = is_main_menu(raw_zone)
        is_continent = (
            "worldmap" in raw_zone.lower()
            or raw_zone.lower().strip() in ("main", "the continent", "il continente")
            or "continent" in raw_zone.lower()
            or "continente" in raw_zone.lower()
        )

        # Checkpoint resolution via providers if not supplied by the active telemetry source
        if is_menu or is_continent:
            raw_checkpoint = ""
        elif not raw_checkpoint and raw_zone:
            for provider in self.providers:
                resolved_cp = provider.resolve_raw_checkpoint(raw_zone)
                if resolved_cp and isinstance(resolved_cp, str):
                    raw_checkpoint = resolved_cp
                    break

        # Track Endless Tower stage and trial
        is_tower = any(k in raw_zone.lower() for k in ("torre", "tower", "clea"))
        if is_tower and in_combat:
            bridge_trial = data.get("tower_trial") if data else None
            if bridge_trial:
                self.current_tower_trial = bridge_trial
            elif raw_enemy or raw_enemies:
                trial_info, _clean_enemy = resolve_tower_trial(raw_enemy, enemies=raw_enemies)
                if trial_info:
                    self.current_tower_trial = trial_info
        elif not in_combat:
            self.current_tower_trial = None

        # Determine zone key and update state timing machine
        zone_key = raw_zone.strip() or "Exploring"
        if zone_key in (
            "Exploring",
            "In esplorazione",
        ) and self.timer_tracker.current_zone_id not in (None, "Exploring", "In esplorazione"):
            zone_key = self.timer_tracker.current_zone_id

        effective_start = self.timer_tracker.update(
            zone_key=zone_key,
            in_combat=in_combat,
            is_tower=is_tower,
            current_tower_trial=self.current_tower_trial,
        )

        return GameState.create(
            is_running=True,
            process_pid=proc.pid,
            start_time=effective_start,
            game_language=lang,
            raw_zone=raw_zone,
            in_combat=in_combat,
            enemy_name=raw_enemy,
            enemies=raw_enemies,
            raw_checkpoint=raw_checkpoint,
            tower_floor=tower_floor,
            current_tower_trial=self.current_tower_trial,
        )


__all__ = [
    "ProcessLike",
    "GameState",
    "GameStateProvider",
    "BridgeStateProvider",
    "SaveFileStateProvider",
    "GameDetector",
    "format_checkpoint_tag",
    "format_enemy_name",
    "format_zone_name",
    "resolve_tower_trial",
    "strip_accents",
    "TARGET_PROCESS_NAME",
]
