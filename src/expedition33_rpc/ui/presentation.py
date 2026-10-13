"""Unified presentation formatting and localization logic for Expedition 33 RPC.

Consolidates user-facing presentation formatting for Discord Rich Presence
wire protocol (details, state, limits) and Win32 system tray tooltips / menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from expedition33_rpc.detection.detector import GameState

from expedition33_rpc.detection.game_data import TOWER_STAGES_BY_LANG
from expedition33_rpc.detection.normalization import (
    is_continent_zone,
    is_menu_zone,
    normalize_language_code,
)

DISCORD_MAX_FIELD_LENGTH = 128

LOCALIZED_PRESENTATION: dict[str, dict[str, str]] = {
    "en-US": {
        "in_menu": "In Main Menu",
        "title_screen": "Title Screen",
        "in_combat": "In Combat",
        "fighting": "Fighting: {enemy}",
        "exploring": "Exploring",
        "traveling": "Traveling",
        "hidden_location": "Hidden Location",
        "floor": "Floor {floor}",
        "stage_trial": "Stage {stage}, Trial {trial}",
    },
    "it": {
        "in_menu": "Nel menu principale",
        "title_screen": "Schermata dei titoli",
        "in_combat": "In combattimento",
        "fighting": "In combattimento con: {enemy}",
        "exploring": "In esplorazione",
        "traveling": "In viaggio",
        "hidden_location": "Posizione riservata",
        "floor": "Piano {floor}",
        "stage_trial": "Fase {stage}, Prova {trial}",
    },
    "fr-FR": {
        "in_menu": "Dans le menu principal",
        "title_screen": "Écran titre",
        "in_combat": "En combat",
        "fighting": "Combat contre : {enemy}",
        "exploring": "En exploration",
        "traveling": "En voyage",
        "hidden_location": "Lieu masqué",
        "floor": "Étage {floor}",
        "stage_trial": "Niveau {stage}, Épreuve {trial}",
    },
    "de": {
        "in_menu": "Im Hauptmenü",
        "title_screen": "Titelbildschirm",
        "in_combat": "Im Kampf",
        "fighting": "Kämpft gegen: {enemy}",
        "exploring": "Auf Erkundung",
        "traveling": "Auf Reisen",
        "hidden_location": "Verborgener Ort",
        "floor": "Ebene {floor}",
        "stage_trial": "Phase {stage}, {trial}. Prüfung",
    },
    "es": {
        "in_menu": "En el menú principal",
        "title_screen": "Pantalla de título",
        "in_combat": "En combate",
        "fighting": "Luchando contra: {enemy}",
        "exploring": "Explorando",
        "traveling": "De viaje",
        "hidden_location": "Ubicación oculta",
        "floor": "Piso {floor}",
        "stage_trial": "Fase {stage}, Prueba {trial}",
    },
    "es-419": {
        "in_menu": "En el menú principal",
        "title_screen": "Pantalla de título",
        "in_combat": "En combate",
        "fighting": "Luchando contra: {enemy}",
        "exploring": "Explorando",
        "traveling": "De viaje",
        "hidden_location": "Ubicación oculta",
        "floor": "Piso {floor}",
        "stage_trial": "Fase {stage}, Prueba {trial}",
    },
    "pt-BR": {
        "in_menu": "No Menu Principal",
        "title_screen": "Tela Inicial",
        "in_combat": "Em Combate",
        "fighting": "Lutando contra: {enemy}",
        "exploring": "Explorando",
        "traveling": "Viajando",
        "hidden_location": "Local Oculto",
        "floor": "Andar {floor}",
        "stage_trial": "{stage}ª Fase, Desafio {trial}",
    },
    "ja": {
        "in_menu": "メインメニュー",
        "title_screen": "タイトル画面",
        "in_combat": "戦闘中",
        "fighting": "戦闘中: {enemy}",
        "exploring": "探索中",
        "traveling": "移動中",
        "hidden_location": "非公開の場所",
        "floor": "{floor}階",
        "stage_trial": "ステージ{stage}、試練{trial}",
    },
    "ko": {
        "in_menu": "메인 메뉴",
        "title_screen": "타이틀 화면",
        "in_combat": "전투 중",
        "fighting": "전투 중: {enemy}",
        "exploring": "탐험 중",
        "traveling": "이동 중",
        "hidden_location": "비공개 위치",
        "floor": "{floor}층",
        "stage_trial": "스테이지 {stage}, 시험 {trial}",
    },
    "zh-Hans": {
        "in_menu": "主菜单",
        "title_screen": "标题界面",
        "in_combat": "战斗中",
        "fighting": "战斗中: {enemy}",
        "exploring": "探索中",
        "traveling": "旅行中",
        "hidden_location": "隐藏地点",
        "floor": "第{floor}层",
        "stage_trial": "第{stage}层，试炼{trial}",
    },
    "zh-Hant": {
        "in_menu": "主選單",
        "title_screen": "標題畫面",
        "in_combat": "戰鬥中",
        "fighting": "戰鬥中: {enemy}",
        "exploring": "探索中",
        "traveling": "旅行中",
        "hidden_location": "隱藏地點",
        "floor": "第{floor}層",
        "stage_trial": "試煉{stage}，第{trial}關",
    },
    "ru": {
        "in_menu": "В главном меню",
        "title_screen": "Титульный экран",
        "in_combat": "В бою",
        "fighting": "Сражение: {enemy}",
        "exploring": "Исследование",
        "traveling": "В пути",
        "hidden_location": "Скрытая локация",
        "floor": "Этаж {floor}",
        "stage_trial": "Этап {stage}, Испытание {trial}",
    },
    "pl": {
        "in_menu": "W menu głównym",
        "title_screen": "Ekran tytułowy",
        "in_combat": "W walce",
        "fighting": "Walka: {enemy}",
        "exploring": "Eksploracja",
        "traveling": "W podróży",
        "hidden_location": "Ukryta lokacja",
        "floor": "Piętro {floor}",
        "stage_trial": "Etap {stage}, Próba {trial}",
    },
    "ar": {
        "in_menu": "في القائمة الرئيسية",
        "title_screen": "الشاشة الرئيسية",
        "in_combat": "في معركة",
        "fighting": "قتال: {enemy}",
        "exploring": "استكشاف",
        "traveling": "في ترحال",
        "hidden_location": "موقع مخفي",
        "floor": "الطابق {floor}",
        "stage_trial": "المرحلة {stage}، الاختبار {trial}",
    },
    "cs": {
        "in_menu": "V hlavní nabídce",
        "title_screen": "Úvodní obrazovka",
        "in_combat": "V boji",
        "fighting": "Bojuje s: {enemy}",
        "exploring": "Průzkum",
        "traveling": "Na cestách",
        "hidden_location": "Skrytá lokace",
        "floor": "Patro {floor}",
        "stage_trial": "{stage}. fáze, {trial}. zkouška",
    },
    "tr": {
        "in_menu": "Ana Menüde",
        "title_screen": "Ana Ekran",
        "in_combat": "Savaşta",
        "fighting": "Savaşıyor: {enemy}",
        "exploring": "Keşifte",
        "traveling": "Seyahatte",
        "hidden_location": "Gizli Konum",
        "floor": "Kat {floor}",
        "stage_trial": "{stage}. Aşama, {trial}. Sınama",
    },
    "uk": {
        "in_menu": "У головному меню",
        "title_screen": "Титульний екран",
        "in_combat": "У бою",
        "fighting": "Бій: {enemy}",
        "exploring": "Дослідження",
        "traveling": "У дорозі",
        "hidden_location": "Прихована локація",
        "floor": "Поверх {floor}",
        "stage_trial": "Етап {stage}, Випробування {trial}",
    },
    "th": {
        "in_menu": "อยู่ในเมนูหลัก",
        "title_screen": "หน้าไตเติลเกม",
        "in_combat": "อยู่ในการต่อสู้",
        "fighting": "ต่อสู้: {enemy}",
        "exploring": "กำลังสำรวจ",
        "traveling": "กำลังเดินทาง",
        "hidden_location": "สถานที่ลับ",
        "floor": "ชั้นที่ {floor}",
        "stage_trial": "ด่านที่ {stage} บททดสอบที่ {trial}",
    },
    "vi": {
        "in_menu": "Trong Menu Chính",
        "title_screen": "Màn Hình Tiêu Đề",
        "in_combat": "Đang Giao Chiến",
        "fighting": "Đang chiến đấu: {enemy}",
        "exploring": "Đang Khám Phá",
        "traveling": "Đang Di Chuyển",
        "hidden_location": "Địa Điểm Ẩn",
        "floor": "Tầng {floor}",
        "stage_trial": "Màn {stage}, Thử Thách {trial}",
    },
    "id": {
        "in_menu": "Di Menu Utama",
        "title_screen": "Layar Judul",
        "in_combat": "Dalam Pertarungan",
        "fighting": "Bertarung: {enemy}",
        "exploring": "Menjelajah",
        "traveling": "Bepergian",
        "hidden_location": "Lokasi Tersembunyi",
        "floor": "Lantai {floor}",
        "stage_trial": "Tahap {stage}, Ujian {trial}",
    },
}


def get_presentation_strings(lang: str) -> dict[str, str]:
    """Retrieves presentation formatting strings for the specified language with fallback."""
    canon = normalize_language_code(lang)
    return LOCALIZED_PRESENTATION.get(canon, LOCALIZED_PRESENTATION["en-US"])


def truncate_presence_field(text: str, max_length: int = DISCORD_MAX_FIELD_LENGTH) -> str:
    """Enforces Discord IPC string limits (max 128 characters for details and state).

    If text exceeds max_length, it is deterministically clamped to the boundary.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length]


def format_location_name(game_state: GameState) -> str:
    """Formats the zone name including trial, floor, or checkpoint details."""
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    zone_display = game_state.zone_name or strings["traveling"]

    if game_state.tower_stage_trial:
        match game_state.tower_stage_trial:
            case (stg, trl) if isinstance(stg, int) and isinstance(trl, int):
                trial_key = f"ST_BattleTowerStages_Stage_{stg:02d}_Trial_{trl:02d}"
                lang_trials = TOWER_STAGES_BY_LANG.get(canon, {})
                if canon in ("it", "en-US") or trial_key not in lang_trials:
                    trial_label = strings["stage_trial"].format(stage=stg, trial=trl)
                else:
                    trial_label = lang_trials[trial_key]
            case other:
                trial_label = str(other)
        return f"{zone_display} ({trial_label})"

    if game_state.tower_floor:
        floor = game_state.tower_floor
        floor_label = strings["floor"].format(floor=floor)
        floor_word = strings["floor"].replace("{floor}", "").strip().lower()
        if floor_word not in zone_display.lower() and "floor" not in zone_display.lower():
            return f"{zone_display} ({floor_label})"
        return zone_display

    if game_state.checkpoint_name and not is_continent_zone(game_state):
        return f"{zone_display} ({game_state.checkpoint_name})"

    return zone_display


def format_presence(game_state: GameState, anti_spoiler: bool = False) -> tuple[str, str]:
    """Generates details and state strings for Discord Rich Presence wire protocol."""
    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)

    if is_menu_zone(game_state):
        details = strings["in_menu"]
        state = strings["title_screen"]
        return truncate_presence_field(details), truncate_presence_field(state)

    if game_state.in_combat:
        if anti_spoiler or not game_state.enemy_name:
            details = strings["in_combat"]
        else:
            details = strings["fighting"].format(enemy=game_state.enemy_name)
        state = strings["hidden_location"] if anti_spoiler else format_location_name(game_state)
        return truncate_presence_field(details), truncate_presence_field(state)

    details = strings["exploring"]
    state = strings["hidden_location"] if anti_spoiler else format_location_name(game_state)
    return truncate_presence_field(details), truncate_presence_field(state)


def format_tray_title(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the system tray icon tooltip (pystray.Icon.title)."""
    if not game_state.is_running:
        return "Expedition 33 RPC (Waiting for game...)"

    canon = normalize_language_code(game_state.game_language)
    strings = get_presentation_strings(canon)
    if is_menu_zone(game_state):
        return f"Expedition 33: {strings['in_menu']}"

    if anti_spoiler:
        mode = "In Combat" if game_state.in_combat else "Exploring"
        return f"Expedition 33: [Protected] ({mode})"

    if game_state.in_combat and game_state.enemy_name:
        mode = f"Fighting: {game_state.enemy_name}"
    else:
        mode = "In Combat" if game_state.in_combat else "Exploring"

    loc = format_location_name(game_state)
    return f"Expedition 33: {loc} ({mode})"


def format_tray_zone_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Location line for the system tray menu."""
    if not game_state.is_running:
        return "Location: --"
    if is_menu_zone(game_state):
        canon = normalize_language_code(game_state.game_language)
        strings = get_presentation_strings(canon)
        return f"Location: {strings['in_menu']}"
    if anti_spoiler:
        return "Location: [Hidden - Anti-Spoiler]"
    loc = format_location_name(game_state)
    return f"Location: {loc}"


def format_tray_combat_status(game_state: GameState, anti_spoiler: bool = False) -> str:
    """Formats the Status / Combat line for the system tray menu."""
    if not game_state.is_running:
        return "Status: --"
    if is_menu_zone(game_state):
        canon = normalize_language_code(game_state.game_language)
        if canon == "it":
            return "Status: Nel menu principale"
        elif canon == "en-US":
            return "Status: Main Menu"
        else:
            strings = get_presentation_strings(canon)
            return f"Status: {strings['in_menu']}"
    if game_state.in_combat:
        if not anti_spoiler and game_state.enemy_name:
            return f"Combat: Fighting {game_state.enemy_name}"
        return "Status: In Combat"
    return "Status: Exploring"


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "LOCALIZED_PRESENTATION",
    "get_presentation_strings",
    "truncate_presence_field",
    "format_presence",
    "format_location_name",
    "is_menu_zone",
    "is_continent_zone",
    "format_tray_title",
    "format_tray_zone_status",
    "format_tray_combat_status",
]
