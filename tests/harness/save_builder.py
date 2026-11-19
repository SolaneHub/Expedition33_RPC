"""Fluent builder for synthetic Unreal Engine 5 .sav binary files.

Enables expressive and deterministic test cases for save file readers,
checkpoint resolution, and corruption tolerance testing.
"""

from __future__ import annotations

from pathlib import Path


class SaveFileBuilder:
    """Fluent test data builder for UE5 .sav binary structures."""

    def __init__(self) -> None:
        self._empty: bool = False
        self._prefix_padding: int = 100
        self._suffix_padding: int = 100
        self._include_savepoint: bool = True
        self._savepoint_tag_name: bytes = b"LastUsedSavePoint"
        self._level_name: str | None = None
        self._level_property_name: bytes = b"LevelAssetName"
        self._spawnpoint_tag: str | None = None
        self._spawnpoint_property_name: bytes = b"SpawnPointTag"
        self._custom_raw_bytes: bytes | None = None

    def empty(self) -> SaveFileBuilder:
        """Configures builder to emit an empty 0-byte file."""
        self._empty = True
        return self

    def with_header(self, padding_bytes: int = 100) -> SaveFileBuilder:
        """Sets prefix null padding before property structs."""
        self._prefix_padding = max(0, padding_bytes)
        return self

    def with_trailer(self, padding_bytes: int = 100) -> SaveFileBuilder:
        """Sets trailing null padding after property structs."""
        self._suffix_padding = max(0, padding_bytes)
        return self

    def without_savepoint(self) -> SaveFileBuilder:
        """Omits the LastUsedSavePoint marker entirely."""
        self._include_savepoint = False
        return self

    def with_corrupt_savepoint_marker(
        self, corrupt_marker: bytes = b"CorruptedSavePoint"
    ) -> SaveFileBuilder:
        """Replaces LastUsedSavePoint marker with invalid bytes."""
        self._savepoint_tag_name = corrupt_marker
        return self

    def with_level(
        self, level_name: str, property_name: bytes = b"LevelAssetName"
    ) -> SaveFileBuilder:
        """Configures the level asset name property."""
        self._level_name = level_name
        self._level_property_name = property_name
        return self

    def with_savepoint(
        self,
        spawnpoint_tag: str,
        property_name: bytes = b"SpawnPointTag",
    ) -> SaveFileBuilder:
        """Configures the spawn point tag property."""
        self._spawnpoint_tag = spawnpoint_tag
        self._spawnpoint_property_name = property_name
        return self

    def with_raw_bytes(self, raw: bytes) -> SaveFileBuilder:
        """Overrides structured generation with custom raw bytes."""
        self._custom_raw_bytes = raw
        return self

    def build(self) -> bytes:
        """Assembles binary UE5 save file content as bytes."""
        if self._custom_raw_bytes is not None:
            return self._custom_raw_bytes

        if self._empty:
            return b""

        parts: list[bytes] = []

        if self._prefix_padding > 0:
            parts.append(b"\x00" * self._prefix_padding)

        if self._include_savepoint:
            parts.append(
                self._savepoint_tag_name + b"\x00\x0f\x00\x00\x00StructProperty\x00\x02\x00\x00\x00"
            )

        if self._level_name is not None:
            parts.append(
                self._level_property_name
                + b"\x00\r\x00\x00\x00NameProperty\x00\x00\x00\x00\x00"
                + self._level_name.encode("latin1")
                + b"\x00"
            )

        if self._spawnpoint_tag is not None:
            parts.append(
                self._spawnpoint_property_name
                + b"\x00"
                + self._spawnpoint_tag.encode("latin1")
                + b"\x00"
            )

        if self._suffix_padding > 0:
            parts.append(b"\x00" * self._suffix_padding)

        return b"".join(parts)

    def write_to(self, path: Path | str) -> Path:
        """Builds and writes bytes directly to target file path."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.build())
        return target
