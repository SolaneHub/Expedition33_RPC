import pytest

from expedition33_rpc.ui.presentation import (
    DISCORD_MAX_FIELD_LENGTH,
    truncate_presence_field,
)

pytestmark = pytest.mark.unit


def test_truncate_presence_field_utf8_bytes() -> None:
    # 1. Short and long ASCII strings
    short_ascii = "Hello, Expedition 33!"
    assert truncate_presence_field(short_ascii) == short_ascii
    assert len(truncate_presence_field(short_ascii).encode("utf-8")) <= 128

    exact_128_ascii = "A" * DISCORD_MAX_FIELD_LENGTH
    res_exact = truncate_presence_field(exact_128_ascii)
    assert res_exact == exact_128_ascii
    assert len(res_exact.encode("utf-8")) == 128

    long_ascii = "B" * 300
    res_long = truncate_presence_field(long_ascii)
    assert res_long == "B" * 128
    assert len(res_long.encode("utf-8")) == 128

    # 2. Multibyte strings where character count < 128 but UTF-8 byte count > 128
    # Chinese (3 bytes per character)
    # 50 chars * 3 bytes = 150 bytes (> 128 bytes, but < 128 chars)
    chinese_text = "你好世界，远征33号正在激战中！" * 3  # 16 * 3 = 48 chars, 48 * 3 = 144 bytes
    assert len(chinese_text) < 128
    assert len(chinese_text.encode("utf-8")) > 128
    res_chinese = truncate_presence_field(chinese_text)
    assert len(res_chinese.encode("utf-8")) <= 128
    # Check that decoding didn't produce replacement characters or broken sequences
    assert (
        res_chinese.encode("utf-8")
        == chinese_text.encode("utf-8")[: len(res_chinese.encode("utf-8"))]
    )

    # Cyrillic (2 bytes per character)
    # 70 chars * 2 bytes = 140 bytes (> 128 bytes, but < 128 chars)
    cyrillic_text = "Привет мир! Экспедиция 33 исследует неизведанное пространство." * 2
    assert len(cyrillic_text) < 128
    assert len(cyrillic_text.encode("utf-8")) > 128
    res_cyrillic = truncate_presence_field(cyrillic_text)
    assert len(res_cyrillic.encode("utf-8")) <= 128
    assert (
        res_cyrillic.encode("utf-8")
        == cyrillic_text.encode("utf-8")[: len(res_cyrillic.encode("utf-8"))]
    )

    # Emojis (4 bytes per emoji)
    # 35 emojis = 35 chars, 35 * 4 = 140 bytes
    emoji_text = "⚔️🛡️✨🔥" * 10  # Note: ⚔️ is ⚔ (3 bytes) + FE0F (3 bytes) = 6 bytes
    assert len(emoji_text) < 128
    assert len(emoji_text.encode("utf-8")) > 128
    res_emoji = truncate_presence_field(emoji_text)
    assert len(res_emoji.encode("utf-8")) <= 128

    # Mixed text (ASCII + Cyrillic + Chinese + Emojis)
    mixed_text = "Combat: 战斗 [Level 45] Привет мир! ⚔️ " * 5
    assert len(mixed_text.encode("utf-8")) > 128
    res_mixed = truncate_presence_field(mixed_text)
    assert len(res_mixed.encode("utf-8")) <= 128

    # Boundary edge case: splitting a 3-byte Chinese char at byte 127/128
    # 42 Chinese chars = 126 bytes. 43 chars = 129 bytes.
    # At max_bytes=128, exactly 42 characters should fit (126 bytes).
    # The 43rd character's first 2 bytes must be cleanly dropped by errors="ignore".
    c43 = "你" * 43
    res_c43 = truncate_presence_field(c43, max_bytes=128)
    assert res_c43 == "你" * 42
    assert len(res_c43.encode("utf-8")) == 126
    assert len(res_c43.encode("utf-8")) <= 128

    # Verify custom max_bytes
    assert truncate_presence_field("你好", max_bytes=4) == "你"
    assert len(truncate_presence_field("你好", max_bytes=4).encode("utf-8")) <= 4
