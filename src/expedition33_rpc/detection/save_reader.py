"""Lightweight Unreal Engine 5 .sav binary reader for Expedition 33 checkpoint resolution."""

from __future__ import annotations

import mmap
import os
import re
from pathlib import Path

from expedition33_rpc.detection.compat_paths import resolve_user_data_path
from expedition33_rpc.detection.normalization import (
    format_zone_name,
    is_continent_zone,
    is_menu_zone,
    strip_accents,
)

type SemanticAlias = dict[str, list[str]]

SEMANTIC_ZONE_ALIASES: list[SemanticAlias] = [
    {"cp_tokens": ["paintress", "monolith"], "zone_tokens": ["monolith"]},
    {"cp_tokens": ["flyinghouse", "manor"], "zone_tokens": ["manor"]},
    {"cp_tokens": ["esquie", "francois"], "zone_tokens": ["esquie", "nest", "nido"]},
    {"cp_tokens": ["chromazone", "chroma"], "zone_tokens": ["sunless", "senza sole", "chroma"]},
    {"cp_tokens": ["yellowforest", "yellow"], "zone_tokens": ["yellow", "giallo", "harvest"]},
    {"cp_tokens": ["reacher"], "zone_tokens": ["reacher", "scalatore"]},
    {"cp_tokens": ["seacliff"], "zone_tokens": ["stone wave", "onda di pietra", "seacliff"]},
    {"cp_tokens": ["goblu"], "zone_tokens": ["goblu", "flying waters", "acque volanti"]},
]

SAVE_READER_IGNORED_ZONE_WORDS: frozenset[str] = frozenset(
    {"the", "il", "la", "inside", "peak", "main", "zone", "camp", "area"}
)

SAVE_READER_IGNORED_CP_WORDS: frozenset[str] = frozenset(
    {"climb", "interior", "exterior", "intro", "savepoint", "entry", "field"}
)


class SaveFileReader:
    """Encapsulates binary reading and parsing of Unreal Engine .sav files for Expedition 33."""

    def __init__(self, base_save_dir: str | Path | None = None) -> None:
        self.base_save_dir = str(
            base_save_dir if base_save_dir is not None else resolve_user_data_path()
        )
        self._checkpoint_cache: dict[str, tuple[float, int, tuple[str | None, str | None]]] = {}

    def reset(self) -> None:
        """Clears the cached checkpoint metadata."""
        self._checkpoint_cache.clear()

    def get_latest_save_dir(self) -> str | None:
        """Locates the latest active player profile save directory."""
        base_path = Path(self.base_save_dir)
        if not base_path.is_dir():
            return None
        try:
            subdirs = [p for p in base_path.iterdir() if p.is_dir() and p.name != "Backup"]
            if not subdirs:
                return str(base_path)

            def _mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0.0

            latest = max(subdirs, key=_mtime)
            return str(latest)
        except Exception:
            return None

    def read_checkpoint_from_save(self, save_dir: str) -> tuple[str | None, str | None]:
        """Extracts (level_name, spawn_point_tag) from the latest EXPEDITION_*.sav file."""
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
            if not os.path.isfile(sav_path):
                return None, None

            st = latest.stat()
            cache_key = (st.st_mtime, st.st_size)
            if (
                sav_path in self._checkpoint_cache
                and self._checkpoint_cache[sav_path][:2] == cache_key
            ):
                return self._checkpoint_cache[sav_path][2]

            size = st.st_size
            if size == 0:
                res: tuple[str | None, str | None] = (None, None)
                self._checkpoint_cache[sav_path] = (st.st_mtime, st.st_size, res)
                return res

            with (
                open(sav_path, "rb") as f,
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            ):
                idx = mm.find(b"LastUsedSavePoint")
                if idx == -1:
                    res = (None, None)
                    self._checkpoint_cache[sav_path] = (st.st_mtime, st.st_size, res)
                    return res

                block = mm[idx : min(idx + 4096, mm.size())]
                lvl_m = re.search(
                    rb"LevelAssetName.*?NameProperty[^\x00]*\x00.*?([A-Za-z0-9_]{3,60})\x00",
                    block,
                    re.DOTALL,
                )
                tag_m = re.search(rb"(Level\.SpawnPoint\.[A-Za-z0-9_\.]+)\x00", block)
                lvl = lvl_m.group(1).decode("latin1") if lvl_m else None
                tag = tag_m.group(1).decode("latin1") if tag_m else None

                res = (lvl, tag)
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
        """Determines whether a saved checkpoint corresponds to the current game zone."""
        if not level_name and not cp_tag:
            return False

        if is_menu_zone(raw_zone, zone_display) or is_continent_zone(raw_zone, zone_display):
            return False

        raw_clean = strip_accents(raw_zone).lower()
        disp_clean = strip_accents(zone_display).lower()
        zone_all = f"{raw_clean} {disp_clean}"

        lvl_clean = strip_accents(level_name or "").lower()
        tag_clean = (
            strip_accents(cp_tag or "").lower().removeprefix("level.spawnpoint.").replace(".", " ")
        )

        full_cp = f"{lvl_clean} {tag_clean}"
        full_cp = re.sub(
            r"level_|sidelevel_|smalllevel_|levelmain_|_main|_v\d+|spawnpoint", " ", full_cp
        )
        full_cp = re.sub(r"[^a-z0-9]", " ", full_cp)

        # 1. Semantic zone aliases
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

    def resolve_checkpoint_for_zone(self, raw_zone: str, zone_display: str = "") -> str:
        """Resolves active checkpoint tag for current zone if matching."""
        if not raw_zone:
            return ""
        save_dir = self.get_latest_save_dir()
        if not save_dir:
            return ""
        lvl, tag = self.read_checkpoint_from_save(save_dir)
        if not tag:
            return ""
        effective_disp = zone_display or format_zone_name(raw_zone)
        if self.is_checkpoint_for_zone(lvl, tag, raw_zone, effective_disp):
            return tag
        return ""


__all__ = ["SaveFileReader"]
