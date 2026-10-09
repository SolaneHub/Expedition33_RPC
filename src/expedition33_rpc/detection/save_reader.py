import os
import re
from pathlib import Path

from expedition33_rpc.detection.game_data import (
    SAVE_READER_IGNORED_CP_WORDS,
    SAVE_READER_IGNORED_ZONE_WORDS,
    SEMANTIC_ZONE_ALIASES,
)
from expedition33_rpc.detection.normalization import is_main_menu, strip_accents

_STREAMING_NOISE_RE = re.compile(
    r"(_hlod|_stream|_lighting|_light|_audio|_sound|_art|_nav|_vfx|_fx|_cine|_collision|_geo|_lod|_sublevel|_partition)",
    re.IGNORECASE,
)


class SaveFileReader:
    """Encapsulates binary reading and parsing of Unreal Engine .sav files for Expedition 33."""

    def __init__(self, base_save_dir: str | None = None):
        self.base_save_dir = base_save_dir or os.path.expandvars(
            r"%LOCALAPPDATA%\Sandfall\Saved\SaveGames"
        )
        self._zone_cache: dict[str, tuple[float, int, str | None]] = {}
        self._checkpoint_cache: dict[str, tuple[float, int, tuple[str | None, str | None]]] = {}

    def get_latest_save_dir(self) -> str | None:
        base_path = Path(self.base_save_dir)
        if not base_path.is_dir():
            return None
        try:
            subdirs = [p for p in base_path.iterdir() if p.is_dir()]
            if not subdirs:
                return None

            def _mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0.0

            latest = max(subdirs, key=_mtime)
            return str(latest)
        except Exception:
            return None

    def read_zone_from_saves(self, save_dir: str) -> str | None:
        container = os.path.join(save_dir, "SavesContainer.sav")
        if os.path.exists(container):
            try:
                st = os.stat(container)
                cache_key = (st.st_mtime, st.st_size)
                if container in self._zone_cache and self._zone_cache[container][:2] == cache_key:
                    return self._zone_cache[container][2]

                with open(container, "rb") as f:
                    data = f.read()
                    m = re.search(
                        b"LastMap_[A-Za-z0-9_]+\\x00\\x0c\\x00\\x00\\x00StrProperty.*?([A-Za-z0-9_]{3,40})\\x00",
                        data,
                        re.DOTALL,
                    )
                    res: str | None = None
                    if m:
                        res = m.group(1).decode("latin1")
                    else:
                        matches = re.findall(
                            b"(Level_[A-Za-z0-9_]+|SideLevel_[A-Za-z0-9_]+|SmallLevel_[A-Za-z0-9_]+|WorldMap)",
                            data,
                        )
                        if matches:
                            decoded = [tok.decode("latin1") for tok in matches]
                            clean = [c for c in decoded if not _STREAMING_NOISE_RE.search(c)]
                            candidates = clean if clean else decoded
                            if candidates:

                                def _score(name: str) -> int:
                                    lower = name.lower()
                                    if "main" in lower:
                                        return 3
                                    if lower.startswith(
                                        ("level_", "sidelevel_", "smalllevel_", "worldmap")
                                    ):
                                        return 2
                                    return 1

                                best = max(
                                    enumerate(candidates),
                                    key=lambda item: (_score(item[1]), item[0]),
                                )
                                res = best[1]

                    self._zone_cache[container] = (st.st_mtime, st.st_size, res)
                    return res
            except Exception as e:
                print(f"[SaveFileReader] Save read error: {e}")
        return None

    def read_checkpoint_from_save(self, save_dir: str) -> tuple[str | None, str | None]:
        try:
            candidates = sorted(
                Path(save_dir).glob("EXPEDITION_*.sav"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
                reverse=True,
            )
            if not candidates:
                return None, None
            latest = candidates[0]
            sav_path = str(latest)
            st = latest.stat()
            cache_key = (st.st_mtime, st.st_size)
            if (
                sav_path in self._checkpoint_cache
                and self._checkpoint_cache[sav_path][:2] == cache_key
            ):
                return self._checkpoint_cache[sav_path][2]

            with open(sav_path, "rb") as f:
                data = f.read()
            idx = data.find(b"LastUsedSavePoint")
            if idx == -1:
                res: tuple[str | None, str | None] = (None, None)
                self._checkpoint_cache[sav_path] = (st.st_mtime, st.st_size, res)
                return res
            block = data[idx : idx + 800]
            lvl_m = re.search(
                rb"LevelAssetName.*?NameProperty[^\x00]*\x00.*?([A-Za-z0-9_]{3,50})\x00",
                block,
                re.DOTALL,
            )
            level_name = lvl_m.group(1).decode("latin1") if lvl_m else None
            tag_m = re.search(rb"(Level\.SpawnPoint\.[A-Za-z0-9_\.]+)\x00", block)
            tag_name = tag_m.group(1).decode("latin1") if tag_m else None
            res = (level_name, tag_name)
            self._checkpoint_cache[sav_path] = (st.st_mtime, st.st_size, res)
            return res
        except Exception:
            return None, None

    def is_checkpoint_for_zone(
        self,
        level_name: str | None,
        cp_tag: str | None,
        raw_zone: str,
        zone_display: str = "",
    ) -> bool:
        if not level_name and not cp_tag:
            return False

        raw_clean = strip_accents(raw_zone).lower()
        disp_clean = strip_accents(zone_display).lower()
        zone_all = f"{raw_clean} {disp_clean}"

        # Checkpoints are never valid for The Continent or Main Menu
        if is_main_menu(raw_zone, zone_display) or any(
            k in zone_all for k in ("continent", "continente", "worldmap", "world map")
        ):
            return False

        lvl_clean = strip_accents(level_name or "").lower()
        tag_clean = (
            strip_accents(cp_tag or "").lower().removeprefix("level.spawnpoint.").replace(".", " ")
        )

        full_cp = f"{lvl_clean} {tag_clean}"
        full_cp = re.sub(
            r"level_|sidelevel_|smalllevel_|levelmain_|_main|_v\d+|spawnpoint", " ", full_cp
        )
        full_cp = re.sub(r"[^a-z0-9]", " ", full_cp)

        # 1. Semantic zone aliases loaded declaratively from game_data
        for alias in SEMANTIC_ZONE_ALIASES:
            cp_tokens = alias.get("cp_tokens", [])
            zone_tokens = alias.get("zone_tokens", [])
            if any(t in full_cp for t in cp_tokens) and any(t in zone_all for t in zone_tokens):
                return True

        # 2. Match zone words inside cp identifier
        clean_zone_words = re.sub(r"[^a-z0-9]", " ", zone_all).split()
        for w in clean_zone_words:
            if len(w) >= 3 and w not in SAVE_READER_IGNORED_ZONE_WORDS and w in full_cp:
                return True

        # 3. Match cp tokens inside zone name
        cp_words = full_cp.split()
        for w in cp_words:
            if len(w) >= 4 and w not in SAVE_READER_IGNORED_CP_WORDS and w in zone_all:
                return True

        return False
