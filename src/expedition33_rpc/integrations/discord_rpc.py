import os
import time

from pypresence.presence import Presence

from expedition33_rpc.detection.detector import GameState

EMBEDDED_CLIENT_ID = "1552405358503272468"


class DiscordRPCManager:
    def __init__(self) -> None:
        self.client_id: str = EMBEDDED_CLIENT_ID
        self.rpc: Presence | None = None
        self.is_connected: bool = False
        self.last_update_state: str | None = None
        self.last_retry_time: float = 0

    def connect(self) -> bool:
        if self.is_connected:
            return True

        now = time.time()
        if now - self.last_retry_time < 5.0:
            return False
        self.last_retry_time = now

        try:
            self.rpc = Presence(self.client_id)
            self.rpc.connect()
            self.is_connected = True
            print(f"[DiscordRPC] Connected with Client ID: {self.client_id}")
            return True
        except Exception:
            self.is_connected = False
            self.rpc = None
            return False

    def disconnect(self) -> None:
        if self.rpc:
            try:
                self.rpc.clear()
                self.rpc.close()
            except Exception:
                pass
        self.rpc = None
        self.is_connected = False

    def reconnect(self) -> None:
        self.disconnect()
        self.connect()

    def update(self, game_state: GameState, anti_spoiler: bool = False) -> None:
        if not self.is_connected and not self.connect():
            return

        if not game_state.is_running:
            if self.last_update_state != "idle" and self.rpc:
                try:
                    self.rpc.clear()
                    self.last_update_state = "idle"
                except Exception:
                    self.is_connected = False
            return

        is_it = game_state.game_language.startswith("it")
        is_menu = (
            game_state.raw_zone.lower().strip() in ("mainmenu", "bootstrap", "map_game_bootstrap")
            or "menu" in game_state.zone_name.lower()
        )
        is_continent = (
            "continent" in game_state.zone_name.lower()
            or "continente" in game_state.zone_name.lower()
            or "worldmap" in game_state.raw_zone.lower()
        )

        if is_menu:
            details_text = "Nel menu principale" if is_it else "In Main Menu"
            state_text = "Schermata dei titoli" if is_it else "Title Screen"
        elif game_state.in_combat:
            if anti_spoiler or not game_state.enemy_name:
                details_text = "In combattimento" if is_it else "In Combat"
            else:
                details_text = (
                    f"In combattimento con: {game_state.enemy_name}"
                    if is_it
                    else f"Fighting: {game_state.enemy_name}"
                )
            if anti_spoiler:
                state_text = "Posizione riservata" if is_it else "Hidden Location"
            else:
                zone_display = game_state.zone_name or ("In viaggio" if is_it else "Traveling")
                if game_state.tower_stage_trial:
                    match game_state.tower_stage_trial:
                        case (stg, trl):
                            trial_label = (
                                f"Fase {stg}, Prova {trl}" if is_it else f"Stage {stg}, Trial {trl}"
                            )
                        case other:
                            trial_label = str(other)
                    zone_display = f"{zone_display} ({trial_label})"

                elif game_state.tower_floor:
                    floor_label = (
                        f"Piano {game_state.tower_floor}"
                        if is_it
                        else f"Floor {game_state.tower_floor}"
                    )
                    if "piano" not in zone_display.lower() and "floor" not in zone_display.lower():
                        zone_display = f"{zone_display} ({floor_label})"
                elif game_state.checkpoint_name and not is_continent:
                    zone_display = f"{zone_display} ({game_state.checkpoint_name})"
                state_text = zone_display
        else:
            details_text = "In esplorazione" if is_it else "Exploring"
            if anti_spoiler:
                state_text = "Posizione riservata" if is_it else "Hidden Location"
            else:
                zone_display = game_state.zone_name or ("In viaggio" if is_it else "Traveling")
                if game_state.tower_stage_trial:
                    match game_state.tower_stage_trial:
                        case (stg, trl):
                            trial_label = (
                                f"Fase {stg}, Prova {trl}" if is_it else f"Stage {stg}, Trial {trl}"
                            )
                        case other:
                            trial_label = str(other)
                    zone_display = f"{zone_display} ({trial_label})"
                elif game_state.tower_floor:
                    floor_label = (
                        f"Piano {game_state.tower_floor}"
                        if is_it
                        else f"Floor {game_state.tower_floor}"
                    )
                    if "piano" not in zone_display.lower() and "floor" not in zone_display.lower():
                        zone_display = f"{zone_display} ({floor_label})"
                elif game_state.checkpoint_name and not is_continent:
                    zone_display = f"{zone_display} ({game_state.checkpoint_name})"
                state_text = zone_display

        start_timestamp = int(game_state.start_time) if game_state.start_time else int(time.time())
        target_pid = (
            game_state.process_pid
            if (game_state.process_pid and game_state.process_pid > 0)
            else os.getpid()
        )

        # State fingerprint to avoid unnecessary updates
        fingerprint = f"{details_text}|{state_text}|{start_timestamp}|{target_pid}"
        if fingerprint == self.last_update_state:
            return

        if self.rpc:
            try:
                self.rpc.update(
                    pid=target_pid,
                    state=state_text,
                    details=details_text,
                    start=start_timestamp,
                    large_image="logo",
                    large_text="Clair Obscur: Expedition 33",
                )
                self.last_update_state = fingerprint
                print(f"[DiscordRPC] Status updated: {details_text} - {state_text}")
            except Exception as e:
                print(f"[DiscordRPC] RPC update error: {e}")
                self.is_connected = False
                self.rpc = None
