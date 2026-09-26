import os
import re

from expedition33_rpc.detection.game_data import strip_accents


class SaveFileReader:
    """Encapsulates binary reading and parsing of Unreal Engine .sav files for Expedition 33."""

    def __init__(self, base_save_dir: str | None = None):
        self.base_save_dir = base_save_dir or os.path.expandvars(
            r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames"
        )

    def get_latest_save_dir(self) -> str | None:
        if not os.path.isdir(self.base_save_dir):
            return None
        try:
            subdirs = [
                os.path.join(self.base_save_dir, d)
                for d in os.listdir(self.base_save_dir)
                if os.path.isdir(os.path.join(self.base_save_dir, d))
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
                print(f"[SaveFileReader] Save read error: {e}")
        return None

    def read_checkpoint_from_save(self, save_dir: str) -> tuple[str | None, str | None]:
        sav_path = os.path.join(save_dir, "EXPEDITION_0.sav")
        if not os.path.exists(sav_path):
            return None, None
        try:
            with open(sav_path, "rb") as f:
                data = f.read()
            idx = data.find(b"LastUsedSavePoint")
            if idx == -1:
                return None, None
            block = data[idx : idx + 800]
            lvl_m = re.search(
                rb"LevelAssetName[^\x00]*\x00.*?(Level_[A-Za-z0-9_]+|SideLevel_[A-Za-z0-9_]+|SmallLevel_[A-Za-z0-9_]+)\x00",
                block,
            )
            level_name = lvl_m.group(1).decode("latin1") if lvl_m else None
            tag_m = re.search(rb"(Level\.SpawnPoint\.[A-Za-z0-9_\.]+)\x00", block)
            tag_name = tag_m.group(1).decode("latin1") if tag_m else None
            return level_name, tag_name
        except Exception:
            return None, None

    def is_checkpoint_for_zone(
        self, level_name: str, cp_tag: str, raw_zone: str, zone_display: str
    ) -> bool:
        if not level_name and not cp_tag:
            return False

        raw_clean = strip_accents(raw_zone).lower()
        disp_clean = strip_accents(zone_display).lower()
        zone_all = f"{raw_clean} {disp_clean}"

        lvl_clean = strip_accents(level_name or "").lower()
        tag_clean = (
            strip_accents(cp_tag or "").lower().replace("level.spawnpoint.", "").replace(".", " ")
        )

        full_cp = f"{lvl_clean} {tag_clean}"
        full_cp = re.sub(r"level_|sidelevel_|smalllevel_|_main|_v\d+|spawnpoint", " ", full_cp)
        full_cp = re.sub(r"[^a-z0-9]", " ", full_cp)

        # 1. Known semantic zone aliases
        if ("paintress" in full_cp or "monolith" in full_cp) and "monolith" in zone_all:
            return True
        if ("flyinghouse" in full_cp or "manor" in full_cp) and "manor" in zone_all:
            return True
        if "worldmap" in full_cp and (
            "continent" in zone_all or "continente" in zone_all or "worldmap" in zone_all
        ):
            return True

        # 2. Match zone words inside cp identifier
        clean_zone_words = re.sub(r"[^a-z0-9]", " ", zone_all).split()
        for w in clean_zone_words:
            if (
                len(w) >= 3
                and w not in ("the", "il", "la", "inside", "peak", "main", "zone")
                and w in full_cp
            ):
                return True

        # 3. Match cp tokens inside zone name
        cp_words = full_cp.split()
        for w in cp_words:
            if (
                len(w) >= 4
                and w
                not in ("climb", "interior", "exterior", "intro", "savepoint", "entry", "field")
                and w in zone_all
            ):
                return True

        return False
