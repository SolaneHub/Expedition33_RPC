"""Pure-Python deterministic adversarial/property fuzzing generators."""

from __future__ import annotations

import json
import random
import struct
from typing import Any

from expedition33_rpc.detection.game_data import ALL_SUPPORTED_LANGUAGES


def generate_adversarial_discord_frames(count: int, seed: int) -> list[bytes]:
    """Generates adversarial Discord IPC binary frames (<II header + payload)."""
    rng = random.Random(seed)
    frames: list[bytes] = []
    for i in range(count):
        mode = i % 5
        if mode == 0:
            # Truncated <II header (fewer than 8 bytes)
            length = rng.randint(0, 7)
            frames.append(rng.randbytes(length))
        elif mode == 1:
            # Huge length in header with empty/short payload
            op = rng.choice([0, 1, 2, 3, 4])
            huge_len = rng.choice([0xFFFFFFFF, 2_000_000, 0x7FFFFFFF])
            frames.append(struct.pack("<II", op, huge_len) + rng.randbytes(rng.randint(0, 16)))
        elif mode == 2:
            # Out-of-range opcode with valid JSON
            op = rng.choice([99, 255, 0xFFFF, 0xDEAD])
            payload = json.dumps({"cmd": "DISPATCH"}).encode("utf-8")
            frames.append(struct.pack("<II", op, len(payload)) + payload)
        elif mode == 3:
            # Broken UTF-8 payload
            bad_utf8 = b"\xff\xfe\xfd\x80\xc3\x28" + rng.randbytes(8)
            frames.append(struct.pack("<II", 1, len(bad_utf8)) + bad_utf8)
        else:
            # Non-dict JSON payload
            non_dict = rng.choice(["[1, 2, 3]", '"string"', "12345", "null", "true"]).encode(
                "utf-8"
            )
            frames.append(struct.pack("<II", 1, len(non_dict)) + non_dict)
    return frames


def generate_adversarial_bridge_payloads(count: int, seed: int) -> list[dict[str, Any]]:
    """Generates adversarial bridge telemetry JSON dicts with hostile field types."""
    rng = random.Random(seed)
    cjk_long = "ルミエール・永遠の塔・" * 20  # > 256 bytes UTF-8
    arabic_long = "البرج الأبدي " * 25
    emoji_long = "⚔️🛡️🔥💀" * 30

    hostile_templates: list[dict[str, Any]] = [
        {"floor": True, "zone": "Level_EndlessTower", "in_combat": True},
        {"tower_trial": ["bad", None], "zone": "Level_EndlessTower"},
        {"enemies": "not_a_list", "enemy_name": 123, "in_combat": "yes"},
        {"raw_zone": 12345, "zone": None, "checkpoint": ["list"]},
        {"timestamp": "NaN", "zone": cjk_long, "checkpoint": arabic_long},
        {"zone": emoji_long, "enemy_name": cjk_long, "enemies": [1, None, emoji_long]},
    ]

    payloads: list[dict[str, Any]] = []
    for i in range(count):
        base = dict(hostile_templates[i % len(hostile_templates)])
        if rng.random() < 0.5:
            base["extra_junk"] = rng.randint(-999999, 999999)
        payloads.append(base)
    return payloads


def generate_mutated_sav_blobs(count: int, seed: int) -> list[bytes]:
    """Generates mutated UE5 .sav binary blobs for SaveFileReader resilience testing."""
    rng = random.Random(seed)
    valid_base = (
        b"\x00" * 64
        + b"LastUsedSavePoint\x00\x0f\x00\x00\x00StructProperty\x00\x02\x00\x00\x00"
        + b"LevelAssetName\x00\r\x00\x00\x00NameProperty\x00\x00\x00\x00\x00Level_Side_VersosDraft\x00"
        + b"SpawnPointTag\x00Level.SpawnPoint.VersosDraft.CandyLand\x00"
        + b"\x00" * 64
    )
    blobs: list[bytes] = []
    for i in range(count):
        mode = i % 4
        if mode == 0:
            # Truncated at random offset
            cut = rng.randint(0, len(valid_base) - 1)
            blobs.append(valid_base[:cut])
        elif mode == 1:
            # Null-byte injection
            pos = rng.randint(0, len(valid_base) - 1)
            blobs.append(valid_base[:pos] + (b"\x00" * 32) + valid_base[pos:])
        elif mode == 2:
            # Broken LastUsedSavePoint marker
            blobs.append(valid_base.replace(b"LastUsedSavePoint", b"LastUsed\x00\xffPoint"))
        else:
            # Pure random bytes
            blobs.append(rng.randbytes(rng.randint(16, 512)))
    return blobs


def generate_multilingual_presence_inputs(seed: int) -> list[dict[str, Any]]:
    """Generates extreme zone/enemy/checkpoint inputs across all 20 supported languages."""
    rng = random.Random(seed)
    extreme_strings = [
        "漢" * 60,  # 180 UTF-8 bytes, 60 chars
        "🔥⚔️🛡️" * 25,  # 4-byte emoji
        "القلعة المنسية في نهاية العالم " * 5,
        "A" * 200,
    ]
    inputs: list[dict[str, Any]] = []
    for lang in ALL_SUPPORTED_LANGUAGES:
        inputs.append(
            {
                "language": lang,
                "zone": rng.choice(extreme_strings),
                "enemy": rng.choice(extreme_strings),
                "checkpoint": rng.choice(extreme_strings),
            }
        )
    return inputs


__all__ = [
    "generate_adversarial_bridge_payloads",
    "generate_adversarial_discord_frames",
    "generate_multilingual_presence_inputs",
    "generate_mutated_sav_blobs",
]
