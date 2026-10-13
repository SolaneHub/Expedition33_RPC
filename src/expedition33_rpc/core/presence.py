"""Immutable Rich Presence transfer payload DTO."""

from __future__ import annotations

from dataclasses import dataclass


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
