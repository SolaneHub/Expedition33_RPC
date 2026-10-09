"""Semantic fluent builder for Unreal Engine synthetic .sav binary test fixtures."""

from __future__ import annotations

import os
from pathlib import Path


class SaveFixtureBuilder:
    """Fluent API builder that generates synthetic UE .sav binary structures.

    Replaces opaque hex literals in test files with self-documenting,
    composable methods.
    """

    def __init__(self, header: bytes | None = None):
        self._header: bytes = (
            header if header is not None else b"GVAS\x03\x00\x00\x00HeaderData\x00"
        )
        self._parts: list[bytes] = []

    @classmethod
    def container(cls) -> SaveFixtureBuilder:
        """Convenience factory for creating SavesContainer.sav fixtures."""
        return cls(header=b"\x05\x00\x00\x00HeaderData\x00")

    @classmethod
    def expedition_slot(cls) -> SaveFixtureBuilder:
        """Convenience factory for creating EXPEDITION_*.sav fixtures."""
        return cls(header=b"GVAS\x02\x00\x00\x00SlotData\x00")

    def with_header(self, header_bytes: bytes) -> SaveFixtureBuilder:
        self._header = header_bytes
        return self

    def with_last_map(self, zone_name: str, slot_suffix: str = "Current_01") -> SaveFixtureBuilder:
        """Appends a valid Unreal Engine LastMap StrProperty."""
        prop_tag = f"LastMap_{slot_suffix}\x00".encode("latin1")
        str_prop = b"\x0c\x00\x00\x00StrProperty\x00\x1f\x00\x00\x00\x00\x00\x00\x00"
        val = f"{zone_name}\x00".encode("latin1")
        self._parts.append(prop_tag + str_prop + val)
        return self

    def with_corrupt_last_map(self, invalid_tag: str = "InvalidPropertyTag") -> SaveFixtureBuilder:
        """Appends a corrupt LastMap without StrProperty."""
        self._parts.append(f"LastMap_Current_01\x00{invalid_tag}\x00".encode("latin1"))
        return self

    def with_fallback_level(self, level_name: str) -> SaveFixtureBuilder:
        """Appends a level token matchable by fallback regex (Level_*, SideLevel_*, SmallLevel_*)."""
        self._parts.append(f"\x00{level_name}\x00".encode("latin1"))
        return self

    def with_world_map(self) -> SaveFixtureBuilder:
        """Appends a WorldMap token."""
        self._parts.append(b"\x00WorldMap\x00")
        return self

    def with_savepoint(self, level_name: str, spawn_point_tag: str) -> SaveFixtureBuilder:
        """Appends a synthetic LastUsedSavePoint StructProperty block containing LevelAssetName and SpawnPointTag."""
        block = (
            b"LastUsedSavePoint\x00StructProperty\x00\x00\x00"
            b"LevelAssetName\x00NameProperty\x00\x00\x00\x00"
            + f"{level_name}\x00".encode("latin1")
            + b"SpawnPointTag\x00"
            + f"{spawn_point_tag}\x00".encode("latin1")
            + b"EndOfBlockData"
        )
        self._parts.append(block)
        return self

    def with_raw_bytes(self, data: bytes) -> SaveFixtureBuilder:
        """Appends arbitrary raw bytes."""
        self._parts.append(data)
        return self

    def build(self) -> bytes:
        """Constructs and returns the complete binary payload."""
        return self._header + b"".join(self._parts)

    def write_to_file(self, target_path: Path | str, mtime: float | None = None) -> Path:
        """Writes the binary payload to target file and optionally sets modification timestamp."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.build())
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def write_saves_container(self, directory: Path | str, mtime: float | None = None) -> Path:
        """Convenience method to write SavesContainer.sav inside the specified directory."""
        return self.write_to_file(Path(directory) / "SavesContainer.sav", mtime=mtime)

    def write_expedition_slot(
        self, directory: Path | str, slot: int = 0, mtime: float | None = None
    ) -> Path:
        """Convenience method to write EXPEDITION_<slot>.sav inside the specified directory."""
        return self.write_to_file(Path(directory) / f"EXPEDITION_{slot}.sav", mtime=mtime)
