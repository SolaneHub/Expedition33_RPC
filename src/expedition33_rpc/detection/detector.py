import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, override

import psutil

from expedition33_rpc.detection.game_data import (
    TARGET_PROCESS_NAMES,
    format_checkpoint_tag,
    format_enemy_name,
    format_zone_name,
    resolve_tower_trial,
    strip_accents,
)
from expedition33_rpc.detection.save_reader import SaveFileReader
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker

type TowerTrial = tuple[int, int] | str
type RawGameData = dict[str, Any]


@dataclass
class GameState:
    is_running: bool = False
    process_pid: int | None = None
    start_time: float | None = None
    raw_zone: str = ""
    zone_name: str = "Exploring"
    in_combat: bool = False
    enemy_name: str = ""
    game_language: str = "en"
    tower_floor: int | None = None
    tower_stage_trial: TowerTrial | None = None
    checkpoint_name: str = ""


class GameStateProvider(ABC):
    """Abstract polymorphic provider interface for extracting real-time game telemetry."""

    @abstractmethod
    def read_game_data(self, proc: psutil.Process, lang: str) -> RawGameData | None:
        """Returns raw game state fields or None if data source is unavailable/stale."""
        pass


class BridgeStateProvider(GameStateProvider):
    """Reads real-time in-game telemetry provided by the UE4SS Lua bridge mod via IPC JSON."""

    def __init__(self):
        self.paths = [
            os.path.expandvars(r"%TEMP%\expedition33_status.json"),
            os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\rpc_status.json"),
        ]

    def read_bridge_status(self) -> dict | None:
        for p in self.paths:
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    @override
    def read_game_data(self, proc: psutil.Process, lang: str) -> RawGameData | None:
        del lang
        bridge = self.read_bridge_status()
        if not bridge:
            return None

        # Validate timestamp freshness against process creation time
        bridge_ts = bridge.get("timestamp")
        if bridge_ts:
            try:
                proc_create = proc.create_time()
                if bridge_ts < (proc_create - 10):
                    return None
            except Exception:
                pass

        raw_zone = bridge.get("zone", "")
        if (
            raw_zone.lower().strip()
            in (
                "map_game_bootstrap",
                "map game bootstrap",
                "bootstrap",
                "mainmenu",
                "main menu",
                "map_mainmenu",
                "frontend",
                "title",
                "entry",
            )
            or "bootstrap" in raw_zone.lower()
            or "mainmenu" in raw_zone.lower()
        ):
            raw_zone = "MainMenu"

        enemy_name = bridge.get("enemy_name", "")
        if enemy_name:
            enemy_name = format_enemy_name(enemy_name)

        checkpoint = bridge.get("checkpoint", "")
        if raw_zone == "MainMenu" or any(
            c in raw_zone.lower() for c in ("continent", "continente", "worldmap")
        ):
            checkpoint = ""

        return {
            "raw_zone": raw_zone,
            "in_combat": bridge.get("in_combat", False),
            "enemy_name": enemy_name,
            "tower_floor": bridge.get("floor") or bridge.get("tower_floor"),
            "checkpoint": checkpoint,
        }


class SaveFileStateProvider(GameStateProvider):
    """Fallback provider that extracts zone and checkpoint locations from Unreal Engine .sav files."""

    def __init__(self, save_reader: SaveFileReader):
        self.save_reader = save_reader

    @override
    def read_game_data(self, proc: psutil.Process, lang: str) -> RawGameData | None:
        save_dir = self.save_reader.get_latest_save_dir()
        if not save_dir:
            return None

        # Check if process just started and the save file predates the process launch.
        # If game started less than 40s ago and save file is older, player is in startup / Main Menu.
        try:
            proc_start = proc.create_time()
            container = os.path.join(save_dir, "SavesContainer.sav")
            if os.path.exists(container):
                save_mtime = os.path.getmtime(container)
                if (time.time() - proc_start < 40.0) and (save_mtime < proc_start):
                    return {
                        "raw_zone": "MainMenu",
                        "in_combat": False,
                        "enemy_name": "",
                        "tower_floor": None,
                        "checkpoint": "",
                    }
        except Exception:
            pass

        raw_zone = self.save_reader.read_zone_from_saves(save_dir) or ""
        checkpoint_name = ""
        if raw_zone:
            zone_display = format_zone_name(raw_zone, lang)
            is_continent = any(
                k in raw_zone.lower() or k in zone_display.lower()
                for k in ("continent", "continente", "worldmap")
            )
            is_menu = raw_zone == "MainMenu" or any(
                k in raw_zone.lower() or k in zone_display.lower() for k in ("menu", "bootstrap")
            )
            if not is_continent and not is_menu:
                cp_level, cp_tag = self.save_reader.read_checkpoint_from_save(save_dir)
                if cp_tag and self.save_reader.is_checkpoint_for_zone(
                    cp_level or "", cp_tag, raw_zone, zone_display
                ):
                    checkpoint_name = format_checkpoint_tag(
                        cp_tag, lang=lang, zone=raw_zone or zone_display
                    )

        return {
            "raw_zone": raw_zone,
            "in_combat": False,
            "enemy_name": "",
            "tower_floor": None,
            "checkpoint": checkpoint_name,
        }


class GameDetector:
    """Orchestrates game process detection, telemetry providers, and zone timing."""

    def __init__(self, base_save_dir: str | None = None):
        self.cached_pid: int | None = None
        self.game_start_time: float | None = None
        self.last_zone: str = "Exploring"
        self.last_raw_zone: str = ""
        self.current_tower_trial: tuple[int, int] | str | None = None

        # Components
        self.save_reader = SaveFileReader(base_save_dir)
        self.bridge_provider = BridgeStateProvider()
        self.save_provider = SaveFileStateProvider(self.save_reader)
        self.timer_tracker = ZoneTimerTracker()

        # Polymorphic providers pipeline (Priority: Bridge Mod IPC -> Save File Parser)
        self.providers: list[GameStateProvider] = [
            self.bridge_provider,
            self.save_provider,
        ]

    def get_game_language(self) -> str:
        ini_path = os.path.expandvars(
            r"%LOCALAPPDATA%\Sandfall\Saved\Config\Windows\GameUserSettings.ini"
        )
        if os.path.exists(ini_path):
            try:
                with open(ini_path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("Language="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
                            if val:
                                return val
            except Exception:
                pass
        return "en"

    def find_game_process(self) -> psutil.Process | None:
        if self.cached_pid is not None:
            try:
                proc = psutil.Process(self.cached_pid)
                if proc.is_running() and proc.name().lower() in TARGET_PROCESS_NAMES:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            self.cached_pid = None

        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = proc.info["name"]
                if name and name.lower() in TARGET_PROCESS_NAMES:
                    self.cached_pid = proc.info["pid"]
                    if not self.game_start_time:
                        self.game_start_time = proc.info.get("create_time", time.time())
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def get_game_state(self) -> GameState:
        proc = self.find_game_process()
        lang = self.get_game_language()

        if not proc:
            self.cached_pid = None
            self.game_start_time = None
            self.current_tower_trial = None
            self.last_zone = "Exploring"
            self.last_raw_zone = ""
            self.timer_tracker.reset()
            return GameState(is_running=False, game_language=lang)

        raw_zone = ""
        in_combat = False
        enemy_name = ""
        tower_floor = None
        checkpoint_name = ""

        # Query telemetry providers in priority order
        for provider in self.providers:
            data = provider.read_game_data(proc, lang)
            if not data:
                continue

            if not raw_zone and data.get("raw_zone"):
                raw_zone = data["raw_zone"]
            if data.get("in_combat"):
                in_combat = True
            if not enemy_name and data.get("enemy_name"):
                enemy_name = format_enemy_name(data["enemy_name"])
            if tower_floor is None and data.get("tower_floor") is not None:
                tower_floor = data["tower_floor"]
            if not checkpoint_name and data.get("checkpoint"):
                checkpoint_name = data["checkpoint"]

            # If provider explicitly reports MainMenu, do not fall back to save reader
            if raw_zone == "MainMenu":
                checkpoint_name = ""
                in_combat = False
                break

            if raw_zone and in_combat:
                break

        is_menu = (
            raw_zone.lower().strip() in ("mainmenu", "bootstrap", "map_game_bootstrap")
            or "menu" in raw_zone.lower()
        )
        is_continent = (
            "worldmap" in raw_zone.lower()
            or raw_zone.lower().strip() in ("main", "the continent", "il continente")
            or "continent" in raw_zone.lower()
            or "continente" in raw_zone.lower()
        )

        # Checkpoint resolution via save parser if bridge did not supply one
        if is_menu or is_continent:
            checkpoint_name = ""
        elif not checkpoint_name and raw_zone:
            save_dir = self.save_reader.get_latest_save_dir()
            if save_dir:
                cp_lvl, cp_tag = self.save_reader.read_checkpoint_from_save(save_dir)
                zone_disp = format_zone_name(raw_zone, lang)
                if cp_tag and self.save_reader.is_checkpoint_for_zone(
                    cp_lvl or "", cp_tag, raw_zone, zone_disp
                ):
                    checkpoint_name = format_checkpoint_tag(
                        cp_tag, lang=lang, zone=raw_zone or zone_disp
                    )

        zone_display = self.last_zone
        if raw_zone:
            zone_display = format_zone_name(raw_zone, lang)
            self.last_zone = zone_display
            self.last_raw_zone = raw_zone

        # Absolute guarantee: no checkpoint for Continent or Main Menu
        if (
            "continent" in zone_display.lower()
            or "continente" in zone_display.lower()
            or "menu" in zone_display.lower()
            or is_continent
            or is_menu
        ):
            checkpoint_name = ""
        elif checkpoint_name:
            checkpoint_name = format_checkpoint_tag(
                checkpoint_name, lang=lang, zone=raw_zone or zone_display
            )

        # Track Endless Tower stage and trial
        is_tower = any(
            k in zone_display.lower() or k in raw_zone.lower() for k in ["torre", "tower", "clea"]
        )
        if is_tower and in_combat and enemy_name:
            trial_info, clean_enemy = resolve_tower_trial(enemy_name)
            if trial_info:
                self.current_tower_trial = trial_info
                enemy_name = clean_enemy
        elif not in_combat:
            self.current_tower_trial = None

        # Determine zone key and update state timing machine
        zone_key = (
            zone_display.strip()
            if zone_display.strip() not in ("", "Exploring", "In esplorazione")
            else (raw_zone.strip() or "Exploring")
        )
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

        return GameState(
            is_running=True,
            process_pid=proc.pid,
            start_time=effective_start,
            raw_zone=raw_zone,
            zone_name=zone_display,
            in_combat=in_combat,
            enemy_name=enemy_name,
            game_language=lang,
            tower_floor=tower_floor,
            tower_stage_trial=self.current_tower_trial,
            checkpoint_name=checkpoint_name,
        )

    def format_zone_name(self, raw_name: str, lang: str = "en") -> str:
        return format_zone_name(raw_name, lang)

    def format_enemy_name(self, enemy_name: str) -> str:
        return format_enemy_name(enemy_name)

    def resolve_tower_trial(self, enemy_name: str) -> tuple[tuple[int, int] | str | None, str]:
        return resolve_tower_trial(enemy_name)

    def read_bridge_status(self) -> dict | None:
        return self.bridge_provider.read_bridge_status()

    def get_latest_save_dir(self) -> str | None:
        return self.save_reader.get_latest_save_dir()

    def read_zone_from_saves(self, save_dir: str) -> str | None:
        return self.save_reader.read_zone_from_saves(save_dir)

    def read_checkpoint_from_save(self, save_dir: str) -> tuple[str | None, str | None]:
        return self.save_reader.read_checkpoint_from_save(save_dir)

    def is_checkpoint_for_zone(
        self, level_name: str, cp_tag: str, raw_zone: str, zone_display: str
    ) -> bool:
        return self.save_reader.is_checkpoint_for_zone(level_name, cp_tag, raw_zone, zone_display)


__all__ = [
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
    "TARGET_PROCESS_NAMES",
]
