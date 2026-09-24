import os
import re
import time
from dataclasses import dataclass

import psutil

TARGET_PROCESS_NAMES = {
    "sandfall-win64-shipping.exe",
    "expedition33_steam.exe",
    "expedition33.exe",
    "sandfall.exe",
}


@dataclass
class GameState:
    is_running: bool = False
    process_pid: int | None = None
    start_time: float | None = None
    raw_zone: str = ""
    zone_name: str = "In esplorazione"
    in_combat: bool = False
    enemy_name: str = ""
    game_language: str = "it"


class GameDetector:
    def __init__(self):
        self.cached_pid: int | None = None
        self.game_start_time: float | None = None
        self.last_zone: str = "In esplorazione"

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
                            return line.split("=", 1)[1].lower().strip()
            except Exception:
                pass
        return "it"

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

    def get_latest_save_dir(self) -> str | None:
        base = os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames")
        if not os.path.isdir(base):
            return None
        try:
            subdirs = [
                os.path.join(base, d)
                for d in os.listdir(base)
                if os.path.isdir(os.path.join(base, d))
            ]
            if not subdirs:
                return None
            subdirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return subdirs[0]
        except Exception:
            return None

    def read_zone_from_saves(self, save_dir: str) -> str | None:
        container = os.path.join(save_dir, "SavesContainer.sav")
        if os.path.exists(container):
            try:
                with open(container, "rb") as f:
                    data = f.read()
                    m = re.search(
                        b"LastMap_[A-Za-z0-9_]+\\x00\\x0c\\x00\\x00\\x00StrProperty.*?([A-Za-z0-9_]{3,40})\\x00",
                        data,
                        re.DOTALL,
                    )
                    if m:
                        return m.group(1).decode("latin1")
                    matches = re.findall(
                        b"(Level_[A-Za-z0-9_]+|SideLevel_[A-Za-z0-9_]+|SmallLevel_[A-Za-z0-9_]+|WorldMap)",
                        data,
                    )
                    if matches:
                        return matches[-1].decode("latin1")
            except Exception as e:
                print(f"[Detector] Save read error: {e}")
        return None

    def read_bridge_status(self) -> dict | None:
        paths = [
            os.path.expandvars(r"%TEMP%\expedition33_status.json"),
            os.path.expandvars(r"%LOCALAPPDATA%\Sandfall\rpc_status.json"),
        ]
        for p in paths:
            if os.path.exists(p):
                try:
                    import json

                    with open(p, encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    def format_zone_name(self, raw_name: str, lang: str = "it") -> str:
        if not raw_name:
            return "In esplorazione"

        menu_names = {
            "Main Menu",
            "MainMenu",
            "Map Game Bootstrap",
            "Map_Game_Bootstrap",
            "Bootstrap",
        }
        if raw_name in menu_names:
            return "Menu Principale" if lang.startswith("it") else "Main Menu"

        cleaned = raw_name
        for prefix in [
            "Level_Side_",
            "Level_Small_",
            "Level_Main_",
            "Level_WorldMap_",
            "Level_",
            "SideLevel_",
            "SmallLevel_",
            "MainLevel_",
            "SubLevel_",
        ]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
                break

        cleaned = re.sub(r"_V\d+$", "", cleaned)
        cleaned = re.sub(r"_C$", "", cleaned)
        cleaned = re.sub(r"_\d+$", "", cleaned)
        cleaned = cleaned.replace("_", " ")

        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
        spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
        return spaced.strip()

    def get_game_state(self) -> GameState:
        proc = self.find_game_process()
        lang = self.get_game_language()

        if not proc:
            self.game_start_time = None
            return GameState(is_running=False, game_language=lang)

        raw_zone = ""
        in_combat = False
        enemy_name = ""

        bridge = self.read_bridge_status()
        if bridge:
            raw_zone = bridge.get("zone", "")
            in_combat = bridge.get("in_combat", False)
            enemy_name = bridge.get("enemy_name", "")
            if enemy_name and ("UObject:" in enemy_name or "0x" in enemy_name):
                enemy_name = ""

        if not raw_zone:
            save_dir = self.get_latest_save_dir()
            if save_dir:
                found_zone = self.read_zone_from_saves(save_dir)
                if found_zone:
                    raw_zone = found_zone
                    self.last_zone = self.format_zone_name(raw_zone, lang)

        zone_display = self.last_zone
        if raw_zone:
            zone_display = self.format_zone_name(raw_zone, lang)
            self.last_zone = zone_display

        return GameState(
            is_running=True,
            process_pid=proc.pid,
            start_time=self.game_start_time or time.time(),
            raw_zone=raw_zone,
            zone_name=zone_display,
            in_combat=in_combat,
            enemy_name=enemy_name,
            game_language=lang,
        )
