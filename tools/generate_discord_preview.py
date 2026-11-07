#!/usr/bin/env python3
"""Generates 1:1 pixel-perfect Discord Activity card previews and animations for the README.

Uses the genuine Discord 'gg sans' font family (Normal, Semibold, Bold), the official Discord
dark theme surface color (#1e1f22 / rgb(30, 31, 34)), authentic Discord monospace timer font (Consolas),
supersampled vector game controller in neon green (#57F287), standard Discord text truncation with '...'
when status lines exceed the container width, and antialiased rounded corners with 100% transparency.

Produces:
  - docs/github/preview_combat.gif      (1:1 calibrated to Discord client recording)
  - docs/github/preview_tower.gif       (1:1 calibrated with ellipsis truncation on long status lines)
  - docs/github/preview_antispoiler.gif (1:1 calibrated to Discord client recording)
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_GITHUB = REPO_ROOT / "docs" / "github"
DOCS_FONTS = REPO_ROOT / "docs" / "fonts"
PORTAL_DIR = REPO_ROOT / "docs" / "discord_portal"
ASSETS_DIR = REPO_ROOT / "src" / "expedition33_rpc" / "assets"

# Card geometry (High-DPI 2x scale matching Discord client aspect ratio)
W, H = 1000, 410
CARD_RADIUS = 28

# Official Discord Dark Theme Color Palette
DISCORD_CARD_BG = (30, 31, 34, 255)  # #1e1f22 (Discord primary dark container)
TEXT_HEADER = (242, 243, 245, 255)  # #f2f3f5 ("Playing")
TEXT_DOTS = (148, 155, 164, 255)  # #949ba4 ("···")
TEXT_TITLE = (242, 243, 245, 255)  # #f2f3f5 ("Clair Obscur - Expedition 33")
TEXT_DETAILS = (219, 222, 225, 255)  # #dbdee1 (Details text)
TEXT_STATE = (219, 222, 225, 255)  # #dbdee1 (State text, matching client brightness)
TEXT_GREEN = (87, 242, 135, 255)  # #57f287 (Discord neon green gamepad & timer)


def get_ggsans_font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads genuine Discord 'gg sans' font (Normal, Semibold, Bold) with graceful fallback."""
    font_file = {
        "bold": DOCS_FONTS / "ggsans-Bold.ttf",
        "semibold": DOCS_FONTS / "ggsans-Semibold.ttf",
        "normal": DOCS_FONTS / "ggsans-Normal.ttf",
    }.get(weight.lower(), DOCS_FONTS / "ggsans-Normal.ttf")

    if font_file.exists():
        try:
            return ImageFont.truetype(str(font_file), size)
        except Exception:
            pass

    # System fallback
    sys_name = "segoeuib.ttf" if weight.lower() in ("bold", "semibold") else "segoeui.ttf"
    for prefix in [r"C:\Windows\Fonts", "/usr/share/fonts/truetype", "/Library/Fonts"]:
        candidate = os.path.join(prefix, sys_name)
        if os.path.isfile(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    return ImageFont.load_default()


def get_timer_font(size: int = 48) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads Consolas (Discord desktop monospace stack for timers on Windows) with fallback."""
    for cand in [
        r"C:\Windows\Fonts\consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/SFNSMono.ttf",
    ]:
        if os.path.isfile(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return get_ggsans_font("semibold", size)


def create_card_mask(width: int = W, height: int = H, radius: int = CARD_RADIUS) -> Image.Image:
    """Creates a 4x supersampled antialiased alpha mask for rounded card corners."""
    scale = 4
    sw, sh = width * scale, height * scale
    mask = Image.new("L", (sw, sh), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=radius * scale, fill=255)
    return mask.resize((width, height), Image.Resampling.LANCZOS)


def create_antialiased_gamepad(width: int = 40, height: int = 30) -> Image.Image:
    """Renders the enhanced, ergonomic modern game controller vector with 4x supersampled antialiasing."""
    scale = 4
    w, h = width * scale, height * scale
    pad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(pad)

    # Controller outer contour
    points = [
        (w * 0.35, h * 0.08),
        (w * 0.65, h * 0.08),
        (w * 0.85, h * 0.16),
        (w * 0.98, h * 0.38),
        (w * 0.96, h * 0.72),
        (w * 0.88, h * 0.96),
        (w * 0.76, h * 0.96),
        (w * 0.68, h * 0.70),
        (w * 0.58, h * 0.52),
        (w * 0.50, h * 0.48),
        (w * 0.42, h * 0.52),
        (w * 0.32, h * 0.70),
        (w * 0.24, h * 0.96),
        (w * 0.12, h * 0.96),
        (w * 0.04, h * 0.72),
        (w * 0.02, h * 0.38),
        (w * 0.15, h * 0.16),
    ]
    draw.polygon(points, fill=TEXT_GREEN)

    # D-pad cross on left
    cx, cy = w * 0.28, h * 0.38
    arm = 5 * scale
    thick = 3 * scale
    draw.rectangle(
        (cx - arm, cy - thick / 2, cx + arm, cy + thick / 2),
        fill=DISCORD_CARD_BG,
    )
    draw.rectangle(
        (cx - thick / 2, cy - arm, cx + thick / 2, cy + arm),
        fill=DISCORD_CARD_BG,
    )

    # 4 Action buttons diamond on right
    bx, by = w * 0.72, h * 0.38
    spacing = 5 * scale
    dot_r = 1.6 * scale
    for dx, dy in [(0, -spacing), (0, spacing), (-spacing, 0), (spacing, 0)]:
        draw.ellipse(
            (bx + dx - dot_r, by + dy - dot_r, bx + dx + dot_r, by + dy + dot_r),
            fill=DISCORD_CARD_BG,
        )

    return pad.resize((width, height), Image.Resampling.LANCZOS)


def prepare_icon_tile(icon_size: int = 224, radius: int = 28) -> tuple[Image.Image, Image.Image]:
    """Generates the black rounded-corner icon tile with the official golden '33' glyph."""
    tile = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 255))
    glyph_path = PORTAL_DIR / "icon_512_transparent.png"
    if not glyph_path.exists():
        glyph_path = ASSETS_DIR / "icon.png"

    glyph = Image.open(glyph_path).convert("RGBA")
    glyph = glyph.resize((190, 190), Image.Resampling.LANCZOS)
    tile.paste(glyph, (17, 17), mask=glyph)

    scale = 4
    mask = Image.new("L", (icon_size * scale, icon_size * scale), 0)
    m_draw = ImageDraw.Draw(mask)
    m_draw.rounded_rectangle(
        (0, 0, icon_size * scale - 1, icon_size * scale - 1),
        radius=radius * scale,
        fill=255,
    )
    mask = mask.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    return tile, mask


def truncate_with_ellipsis(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Truncates text with '...' if it exceeds max_width, leaving proper margin before the card edge."""
    bbox = font.getbbox(text)
    if bbox[2] - bbox[0] <= max_width:
        return text

    for i in range(len(text), 0, -1):
        candidate = text[:i].rstrip() + "..."
        cb = font.getbbox(candidate)
        if cb[2] - cb[0] <= max_width:
            return candidate
    return "..."


def render_1to1_card(
    details: str,
    state: str,
    timer: str,
    icon_tile: Image.Image,
    icon_mask: Image.Image,
    gamepad_icon: Image.Image,
    card_mask: Image.Image,
) -> Image.Image:
    """Renders a 1:1 pixel-perfect frame with rounded corners, Discord #1e1f22 bg, and calibrated typography."""
    # Transparent canvas with Discord #1e1f22 RGB to eliminate any black fringing on rounded edges
    card = Image.new("RGBA", (W, H), (30, 31, 34, 0))
    card.putalpha(card_mask)

    draw = ImageDraw.Draw(card)

    f_header = get_ggsans_font("semibold", 46)
    f_title = get_ggsans_font("bold", 50)
    f_details = get_ggsans_font("semibold", 43)
    f_state = get_ggsans_font("semibold", 43)
    f_timer = get_timer_font(48)

    # 1. Header ("Playing" and antialiased "···")
    draw.text((27, 25), "Playing", fill=TEXT_HEADER, font=f_header)
    for dx in [909, 929, 949]:
        draw.ellipse((dx - 5.5, 59 - 5.5, dx + 5.5, 59 + 5.5), fill=TEXT_DOTS)

    # 2. Black Icon Tile at exact (30, 119)
    card.paste(icon_tile, (30, 119), mask=icon_mask)

    # Available text width before right margin (max_x = 938, leaving ~62px from card edge 1000)
    tx = 282
    max_w = 938 - tx

    # 3. Text block: crisp ellipsis truncation if string is too long (Line 1 & 3 fit in their entirety)
    trunc_title = truncate_with_ellipsis("Clair Obscur - Expedition 33", f_title, max_w)
    trunc_details = truncate_with_ellipsis(details, f_details, max_w)
    trunc_state = truncate_with_ellipsis(state, f_state, max_w)

    draw.text((tx, 122), trunc_title, fill=TEXT_TITLE, font=f_title)
    draw.text((tx, 185), trunc_details, fill=TEXT_DETAILS, font=f_details)
    draw.text((tx, 246), trunc_state, fill=TEXT_STATE, font=f_state)

    # 4. Enhanced Vector Gamepad Icon & Monospace Green Timer
    card.paste(gamepad_icon, (285, 337), mask=gamepad_icon)
    draw.text((340, 332), timer, fill=TEXT_GREEN, font=f_timer)

    return card


def prepare_transparent_p_frame(rgba_img: Image.Image) -> Image.Image:
    """Converts an RGBA frame to P mode with guaranteed transparent color index (255) for corners."""
    alpha = rgba_img.split()[3]
    rgb = rgba_img.convert("RGB")
    p = rgb.quantize(colors=255, method=Image.Resampling.LANCZOS)
    # Mask all pixels where alpha < 128 (outside the rounded card)
    trans_mask = Image.eval(alpha, lambda a: 255 if a < 128 else 0)
    p.paste(255, trans_mask)
    p.info["transparency"] = 255
    p.info["disposal"] = 2
    return p


def build_transition_gif(
    frame_a: Image.Image,
    frame_b: Image.Image,
    out_path: Path,
    hold_a_count: int = 22,
    hold_b_count: int = 25,
) -> None:
    """Builds an animated GIF cycling between two presence states with truly transparent rounded corners."""
    pa = prepare_transparent_p_frame(frame_a)
    pb = prepare_transparent_p_frame(frame_b)
    frames = [pa] * hold_a_count + [pb] * hold_b_count
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        transparency=255,
        disposal=2,
    )
    print(f"  -> Generated {out_path.name} ({os.path.getsize(out_path) // 1024} KB)")


def main() -> None:
    DOCS_GITHUB.mkdir(parents=True, exist_ok=True)
    print("[1/3] Preparing icon tile, antialiased controller, and rounded card mask...")
    tile, icon_mask = prepare_icon_tile(icon_size=224, radius=28)
    gamepad_icon = create_antialiased_gamepad(width=40, height=30)
    card_mask = create_card_mask(width=W, height=H, radius=CARD_RADIUS)

    print("[2/3] Rendering 1:1 calibrated Discord presence frames...")
    # Combat scenario: Exploration -> Combat
    combat_1 = render_1to1_card(
        "Exploring",
        "Spring Meadows (Grand Meadow)",
        "1:13",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )
    combat_2 = render_1to1_card(
        "Fighting: Lancelier",
        "Spring Meadows (Grand Meadow)",
        "0:02",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )

    # Tower scenario: Entrance Exploration -> Combat on Tower Floor (Stage 1, Trial 1)
    tower_1 = render_1to1_card(
        "Exploring",
        "Endless Tower (Entrance)",
        "0:28",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )
    tower_2 = render_1to1_card(
        "Fighting: Luster, Ramasseur, Gault",
        "Endless Tower (Stage 1, Trial 1)",
        "0:02",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )

    # Anti-Spoiler scenario: Normal Combat -> Masked Shield
    shield_1 = render_1to1_card(
        "Fighting: Lancelier",
        "Spring Meadows (Grand Meadow)",
        "0:15",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )
    shield_2 = render_1to1_card(
        "In Combat",
        "Hidden Location",
        "0:16",
        tile,
        icon_mask,
        gamepad_icon,
        card_mask,
    )

    print("[3/3] Exporting 1:1 GIFs with rounded corners & Discord #1e1f22 bg...")
    build_transition_gif(combat_1, combat_2, DOCS_GITHUB / "preview_combat.gif")
    build_transition_gif(tower_1, tower_2, DOCS_GITHUB / "preview_tower.gif")
    build_transition_gif(shield_1, shield_2, DOCS_GITHUB / "preview_antispoiler.gif")

    print(
        "\n[Done] All 3 1:1 Discord GIFs successfully generated with calibrated layout & #1e1f22 bg in docs/github/!"
    )


if __name__ == "__main__":
    main()
