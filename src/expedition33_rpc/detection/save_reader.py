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

type SemanticAlias = dict[str, frozenset[str]]

SEMANTIC_ZONE_ALIASES: list[SemanticAlias] = [
    {
        "cp_tokens": frozenset({"paintress", "monolith"}),
        "zone_tokens": frozenset({"monolith"}),
    },
    {
        "cp_tokens": frozenset({"flyinghouse", "manor"}),
        "zone_tokens": frozenset({"manor"}),
    },
    {
        "cp_tokens": frozenset({"esquie", "francois"}),
        "zone_tokens": frozenset({"esquie", "nest", "nido"}),
    },
    {
        "cp_tokens": frozenset({"chromazone", "chroma"}),
        "zone_tokens": frozenset({"sunless", "senza sole", "chroma"}),
    },
    {
        "cp_tokens": frozenset({"yellowforest", "yellow"}),
        "zone_tokens": frozenset({"yellow", "giallo", "harvest"}),
    },
    {
        "cp_tokens": frozenset({"reacher"}),
        "zone_tokens": frozenset({"reacher", "scalatore"}),
    },
    {
        "cp_tokens": frozenset({"seacliff"}),
        "zone_tokens": frozenset({"stone wave", "onda di pietra", "seacliff"}),
    },
    {
        "cp_tokens": frozenset({"goblu"}),
        "zone_tokens": frozenset({"goblu", "flying waters", "acque volanti"}),
    },
]

SAVE_READER_IGNORED_ZONE_WORDS: frozenset[str] = frozenset(
    {"the", "il", "la", "inside", "peak", "main", "zone", "camp", "area"}
)

SAVE_READER_IGNORED_CP_WORDS: frozenset[str] = frozenset(
    {"climb", "interior", "exterior", "intro", "savepoint", "entry", "field"}
)

_RE_LEVEL_ASSET: re.Pattern[bytes] = re.compile(
    rb"LevelAssetName.*?NameProperty[^\x00]*\x00.*?([A-Za-z0-9_]{3,60})\x00",
    re.DOTALL,
)
_RE_SPAWN_POINT: re.Pattern[bytes] = re.compile(rb"(Level\.SpawnPoint\.[A-Za-z0-9_\.]+)\x00")
_RE_CLEAN_PREFIXES: re.Pattern[str] = re.compile(
    r"level_|sidelevel_|smalllevel_|levelmain_|_main|_v\d+|spawnpoint"
)
_RE_NON_ALPHANUMERIC: re.Pattern[str] = re.compile(r"[^a-z0-9]")


class SaveFileReader:
    """Encapsulates binary reading and parsing of Unreal Engine .sav files for Expedition 33."""

    def __init__(self, base_save_dir: str | Path | None = None) -> None:
        self.base_save_dir = str(
            base_save_dir if base_save_dir is not None else resolve_user_data_path()
        )
        self._checkpoint_cache: dict[str, tuple[float, int, tuple[str | None, str | None]]] = {}
        self._latest_dir_cache: tuple[float, str | None] | None = None
        self._dir_sav_cache: dict[str, tuple[float, list[Path]]] = {}

    def reset(self) -> None:
        """Clears all cached checkpoint metadata, directory mtimes, and paths."""
        self._checkpoint_cache.clear()
        self._latest_dir_cache = None
        self._dir_sav_cache.clear()

    def get_latest_save_dir(self) -> str | None:
        """Locates the latest active player profile save directory."""
        base_path = Path(self.base_save_dir)
        try:
            current_mtime = base_path.stat().st_mtime
        except OSError:
            return None

        if not base_path.is_dir():
            return None

        if self._latest_dir_cache is not None and self._latest_dir_cache[0] == current_mtime:
            return self._latest_dir_cache[1]

        try:
            subdirs = [p for p in base_path.iterdir() if p.is_dir() and p.name != "Backup"]
            if not subdirs:
                resolved_dir = str(base_path)
                self._latest_dir_cache = (current_mtime, resolved_dir)
                return resolved_dir

            def _mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0.0

            latest = max(subdirs, key=_mtime)
            resolved_dir = str(latest)
            self._latest_dir_cache = (current_mtime, resolved_dir)
            return resolved_dir
        except Exception:
            return None

    def read_checkpoint_from_save(self, save_dir: str) -> tuple[str | None, str | None]:
        """Extracts (level_name, spawn_point_tag) from the latest EXPEDITION_*.sav file."""
        try:
            save_dir_path = Path(save_dir)
            try:
                dir_mtime = save_dir_path.stat().st_mtime
            except OSError:
                return None, None

            cached_entry = self._dir_sav_cache.get(save_dir)
            if cached_entry is not None and cached_entry[0] == dir_mtime:
                candidates = cached_entry[1]
            else:
                candidates = list(save_dir_path.glob("EXPEDITION_*.sav"))
                self._dir_sav_cache[save_dir] = (dir_mtime, candidates)

            if not candidates:
                return None, None

            def _mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0.0

            latest = max(candidates, key=_mtime)
            sav_path = str(latest)

            try:
                st = latest.stat()
            except OSError:
                return None, None

            if not os.path.isfile(sav_path):
                return None, None

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

                endpos = min(idx + 4096, mm.size())
                lvl_m = _RE_LEVEL_ASSET.search(mm, idx, endpos)
                tag_m = _RE_SPAWN_POINT.search(mm, idx, endpos)
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
        full_cp = _RE_CLEAN_PREFIXES.sub(" ", full_cp)
        full_cp = _RE_NON_ALPHANUMERIC.sub(" ", full_cp)

        # 1. Semantic zone aliases
        for alias in SEMANTIC_ZONE_ALIASES:
            cp_tokens = alias["cp_tokens"]
            zone_tokens = alias["zone_tokens"]
            if any(t in full_cp for t in cp_tokens) and any(t in zone_all for t in zone_tokens):
                return True

        # 2. Match zone words inside cp identifier
        clean_zone_words = set(_RE_NON_ALPHANUMERIC.sub(" ", zone_all).split())
        for w in clean_zone_words:
            if len(w) >= 3 and w not in SAVE_READER_IGNORED_ZONE_WORDS and w in full_cp:
                return True

        # 3. Match cp tokens inside zone name
        cp_words = set(full_cp.split())
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
