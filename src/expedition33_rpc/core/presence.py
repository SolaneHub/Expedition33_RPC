"""Immutable Rich Presence transfer payload DTO."""

from __future__ import annotations

from dataclasses import dataclass

DISCORD_MAX_FIELD_LENGTH: int = 128


def truncate_presence_field(text: str, max_bytes: int = DISCORD_MAX_FIELD_LENGTH) -> str:
    """Enforces Discord IPC string limits (max 128 bytes for details and state).

    If text exceeds max_bytes, it is deterministically clamped to the byte boundary
    without splitting multibyte sequences.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


@dataclass(frozen=True, slots=True)
class PresencePayload:
    details: str | None
    state: str | None
    start_timestamp: int | None = None
    large_image: str | None = None
    large_text: str | None = None
    small_image: str | None = None
    small_text: str | None = None
    party_id: str | None = None
    party_size: tuple[int, int] | None = None


__all__ = [
    "DISCORD_MAX_FIELD_LENGTH",
    "PresencePayload",
    "truncate_presence_field",
]
