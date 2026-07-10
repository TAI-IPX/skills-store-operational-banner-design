#!/usr/bin/env python3
"""
战报长图合成：1080 宽竖拼。
- 全部叠字：fonts.load_font() → scripts/assets/fonts/battle-report/（禁止系统默认字体）
- 头图：KV + 本地叠字；数据区 plain 无装饰叠字（默认不生图）；小 Banner 默认程序化底 + 透明角色
- B/C/D：栏头 + 文件夹内全部截图（`order.txt` 或数字前缀排序）
"""
from __future__ import annotations

import colorsys
import os
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.battle_report.color_extract import build_theme_json, save_theme
from scripts.battle_report.fonts import load_font, log_font_configuration
from scripts.battle_report.hero_design import DEFAULT_HERO_DESIGN, resolve_hero_design
from scripts.battle_report.nano_banana_visual import (
    SECTION_BANNER_AI_H,
    ai_hero_strip_height,
    hero_data_image_enabled,
    is_kv_ai_hybrid_mode,
    prepare_visual_assets,
    resolve_or_create_hero_data_bg,
    section_banner_image_enabled,
)
from scripts.battle_report.section_assets import (
    SectionFolderAssets,
    keyword_character_png_path,
    png_has_transparent_alpha,
    parse_section_folder,
    resolve_section_character_png,
    SECTION_CHARACTER_KEYWORDS,
    _is_keyword_character_png,
)

CANVAS_W = 1080
SECTION_GAP = 0

HERO_TEXT_CENTER_X = CANVAS_W // 2
HERO_CONTENT_MAX_W = 760

# 文案落在 KV 下半区，避开中上人物/动物（按 KV 高比例，1080×607 时约 y≥330）
HERO_KV_SUBJECT_BOTTOM_RATIO = 0.66
HERO_GAP_AFTER_SUBJECT = 56
HERO_KV_BOTTOM_PAD = 20

HERO_TITLE_SIZE = 100
HERO_TAGLINE_SIZE = 60
HERO_BAR_TEXT_SIZE = 70

HERO_TAGLINE_GAP = 14
HERO_PLATFORM_LOGO_GAP = 40
HERO_UPPER_TO_LOWER_GAP = 40
HERO_LOWER_BLOCK_W = 1040
HERO_LOWER_BLOCK_PAD_TOP = 32
HERO_LOWER_BLOCK_PAD_BOTTOM = 36
HERO_LOWER_BLOCK_INNER_GAP = 20
HERO_LOWER_BLOCK_BAR_TO_DATA_GAP = 12
HERO_LAUNCH_BAR_INSET_X = 28
HERO_LAUNCH_DATA_STATS_H = 156
HERO_LAUNCH_PRE_BAND_H = 22
HERO_LAUNCH_PRE_GAP = 20
HERO_BAR_PAD_X = 56
HERO_DATA_PANEL_W = HERO_LOWER_BLOCK_W
HERO_DATA_PANEL_H = 268
HERO_DATA_PAD_X = 40
HERO_DATA_INNER_PAD = 32
HERO_DATA_STAT_GAP = 56
HERO_STAT_LABEL_SIZE = 32
HERO_STAT_VALUE_SIZE = 64
HERO_MONUMENT_DEFAULT_PANEL_H = 300
# 首发条字号与副标题一致（本地 display 字体，非 AI 生成字）
HERO_LAUNCH_BAR_FONT_SIZE = HERO_TAGLINE_SIZE
HERO_MONUMENT_PILL_SIZE = HERO_LAUNCH_BAR_FONT_SIZE
HERO_MONUMENT_PILL_H = 72
HERO_MONUMENT_BAR_TO_STAGE_GAP = 40
# 首发条 + 数据指标同一模块内的间距（非上下两块分离）
HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP = 22
HERO_LAUNCH_DATA_MODULE_INNER_GAP = 18
HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM = 20
HERO_MONUMENT_VALUE_BASELINE_OFFSET = 52
HERO_STAT_COL_GAP = 80
HERO_STAT_LABEL_VALUE_GAP = 14
HERO_DATA_BLOCK_SHIFT_Y = 50  # 首发条 + 曝光/下载整体下移
HERO_DATA_BG_STAGE_INSET = 28
HERO_DATA_STAT_SCRIM_ALPHA = 235
HERO_NANO_DATA_VEIL_ALPHA = 36
HERO_KV_AI_VEIL_ALPHA = 22
# 参考图：羊皮纸外框 + 奶油色内卡 + 黄标 pill + 描边大数字（颜色来自 KV theme）
HERO_FRAMED_PANEL_W = 1000
HERO_FRAMED_OUTER_BLEED = 22
HERO_FRAMED_INNER_RADIUS = 28
HERO_FRAMED_INNER_PAD_X = 44
HERO_FRAMED_INNER_PAD_TOP = 52
HERO_FRAMED_INNER_PAD_BOTTOM = 48
HERO_FRAMED_TITLE_TO_PILL_GAP = 28
HERO_FRAMED_PILL_TO_STATS_GAP = 38
HERO_FRAMED_PILL_H = 56
HERO_FRAMED_STAT_LABEL_VALUE_GAP = 24
HERO_FRAMED_PILL_PAD_X = 28
HERO_FRAMED_VALUE_STROKE = 5
HERO_FRAMED_BORDER_W = 3
HERO_FRAMED_TITLE_SIZE = 44


def _hero_data_layout(design: dict | None) -> str:
    d = design or DEFAULT_HERO_DESIGN
    layout = d.get("layout", "plain")
    allowed = ("monument", "classic", "framed", "ai_stage", "plain")
    return layout if layout in allowed else "plain"


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _lighten(rgb: tuple[int, int, int], amount: float = 0.22) -> tuple[int, int, int]:
    return _mix_rgb(rgb, (255, 255, 255), amount)


def _darken(rgb: tuple[int, int, int], amount: float = 0.35) -> tuple[int, int, int]:
    return _mix_rgb(rgb, (0, 0, 0), amount)


def _boost_vivid(rgb: tuple[int, int, int], *, sat_mul: float = 1.1, val_mul: float = 1.12) -> tuple[int, int, int]:
    r, g, b = (x / 255.0 for x in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, s * sat_mul)
    v = min(1.0, v * val_mul)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return tuple(int(round(x * 255)) for x in (r2, g2, b2))


def _theme_hex_rgb(theme: dict, key: str) -> tuple[int, int, int] | None:
    raw = theme.get(key)
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("#") and len(s) >= 7:
        return _hex_rgb(s[:7])
    return _hex_rgb(s)


def _color_chroma(rgb: tuple[int, int, int]) -> float:
    r, g, b = (x / 255.0 for x in rgb)
    _, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s * v


def _hue_sep(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    ha = colorsys.rgb_to_hsv(*(x / 255.0 for x in a))[0]
    hb = colorsys.rgb_to_hsv(*(x / 255.0 for x in b))[0]
    d = abs(ha - hb)
    return min(d, 1.0 - d)


def _collect_kv_highlight_swatches(theme: dict) -> list[tuple[int, int, int]]:
    """KV 亮色与点缀：theme Token + extract_meta 候选，去重后按鲜艳度排序。"""
    seen: list[tuple[int, int, int]] = []

    def add(rgb: tuple[int, int, int] | None) -> None:
        if not rgb:
            return
        for existing in seen:
            if sum((a - b) ** 2 for a, b in zip(rgb, existing)) < 28 * 28:
                return
        seen.append(rgb)

    for key in (
        "accent_bright",
        "accent_bright_alt",
        "accent_primary",
        "accent_secondary",
        "stroke_decor",
    ):
        add(_theme_hex_rgb(theme, key))
    meta = theme.get("extract_meta")
    if isinstance(meta, dict):
        warm = meta.get("warm_accent")
        if isinstance(warm, dict) and warm.get("hex"):
            add(_hex_rgb(str(warm["hex"])))
        for item in meta.get("accent_candidates") or []:
            if isinstance(item, dict) and item.get("hex"):
                add(_hex_rgb(str(item["hex"])))
    return sorted(seen, key=_color_chroma, reverse=True)


def _kv_accent_roles(theme: dict) -> dict[str, tuple[int, int, int]]:
    """
    从 KV 取色划分角色：点缀(pop)、主亮(warm)、辅亮(cool)、底衬暗色。
    不注入固定色相，保证与整页 theme 一致。
    """
    bg_page = _theme_hex_rgb(theme, "bg_page") or (17, 18, 23)
    dark = _theme_hex_rgb(theme, "bg_card_dark") or _darken(bg_page, 0.15)
    card = _theme_hex_rgb(theme, "bg_card") or _lighten(dark, 0.35)
    swatches = _collect_kv_highlight_swatches(theme)
    warm = _theme_hex_rgb(theme, "accent_primary") or (swatches[0] if swatches else (220, 190, 50))
    secondary = _theme_hex_rgb(theme, "accent_secondary") or warm
    pop = _theme_hex_rgb(theme, "accent_bright") or (swatches[0] if swatches else warm)
    if swatches and _color_chroma(swatches[0]) > _color_chroma(pop) * 1.05:
        pop = swatches[0]
    alt = _theme_hex_rgb(theme, "accent_bright_alt")
    cool_candidates = [c for c in (alt, secondary) if c]
    if cool_candidates:
        cool = max(cool_candidates, key=lambda c: _hue_sep(c, pop))
    else:
        cool = secondary
    stroke = _theme_hex_rgb(theme, "stroke_decor") or cool
    muted_warm = _mix_rgb(bg_page, warm, 0.28)
    muted_cool = _mix_rgb(bg_page, cool, 0.18)
    halftone = _mix_rgb(muted_warm, muted_cool, 0.42)
    glow = _lighten(_mix_rgb(warm, pop, 0.45), 0.1)
    return {
        "bg_page": bg_page,
        "dark": dark,
        "card": card,
        "warm": warm,
        "cool": cool,
        "pop": pop,
        "stroke": stroke,
        "halftone": halftone,
        "glow": glow,
        "title": pop if _color_chroma(pop) >= _color_chroma(warm) * 0.85 else warm,
    }


def _hero_data_text_fills(
    theme: dict, text_c: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """数据区叠字：数值 / 标签 / 首发条，取自 KV 亮色与点缀。"""
    roles = _kv_accent_roles(theme)
    value = roles["pop"]
    if theme.get("text_secondary"):
        label = _hex_rgb(theme["text_secondary"])
    else:
        label = _mix_rgb(text_c, (160, 160, 160), 0.42)
    bar = text_c
    return value, label, bar


def _framed_data_palette(theme: dict) -> dict[str, tuple[int, int, int]]:
    """框式数据卡：外框 KV 撞色，内底 theme.bg_page。"""
    roles = _kv_accent_roles(theme)
    text_c = _theme_hex_rgb(theme, "text_primary") or (255, 255, 255)
    inner = roles["bg_page"]
    outer = _boost_vivid(
        _mix_rgb(roles["warm"], roles["cool"], 0.48),
        sat_mul=1.2,
        val_mul=1.1,
    )
    border = _boost_vivid(roles["pop"], sat_mul=1.1, val_mul=1.05)
    border_alt = _boost_vivid(roles["cool"], sat_mul=1.12, val_mul=1.08)
    pill = roles["pop"]
    value = _boost_vivid(roles["pop"], sat_mul=1.08, val_mul=1.06)
    label = text_c
    return {
        "outer": outer,
        "inner": inner,
        "border": border,
        "border_alt": border_alt,
        "pill": pill,
        "pill_text": (20, 20, 20),
        "value": value,
        "label": label,
        "sparkle": _mix_rgb(roles["warm"], roles["pop"], 0.45),
    }


def _draw_hero_data_plain_text(
    base: Image.Image,
    *,
    cx: int,
    y: int,
    text: str,
    font,
    fill: tuple[int, int, int],
    anchor: str = "mt",
    trailing_gap: int | None = None,
) -> int:
    draw = ImageDraw.Draw(base)
    draw.text((cx, y), text, font=font, fill=fill, anchor=anchor)
    gap = HERO_MONUMENT_BAR_TO_STAGE_GAP if trailing_gap is None else trailing_gap
    return draw.textbbox((cx, y), text, font=font, anchor=anchor)[3] + gap


def _theme_vivid_pair(theme: dict) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """叠字/色块：KV 高反差 accent_bright 对（取色阶段已加强饱和）。"""
    if theme.get("accent_bright"):
        a = _hex_rgb(theme["accent_bright"])
        b = _hex_rgb(theme.get("accent_bright_alt", theme["accent_secondary"]))
        return _boost_vivid(a, sat_mul=1.05, val_mul=1.04), _boost_vivid(b, sat_mul=1.05, val_mul=1.04)
    return (
        _boost_vivid(_hex_rgb(theme["accent_primary"]), sat_mul=1.14, val_mul=1.12),
        _boost_vivid(_hex_rgb(theme["accent_secondary"]), sat_mul=1.14, val_mul=1.12),
    )


def _hero_layout_fonts(design: dict | None = None) -> dict:
    d = design or DEFAULT_HERO_DESIGN
    label_sz = int(d.get("label_font_size", HERO_STAT_LABEL_SIZE))
    value_sz = int(d.get("value_font_size", HERO_STAT_VALUE_SIZE))
    return {
        "title": load_font("display_bold", HERO_TITLE_SIZE),
        "tag": load_font("display_medium", HERO_TAGLINE_SIZE),
        "bar": load_font("display_bold", HERO_BAR_TEXT_SIZE),
        "bar_pill": load_font("display_bold", HERO_LAUNCH_BAR_FONT_SIZE),
        "stat_label": load_font("body_regular", label_sz),
        "stat_value": load_font("data_bold", value_sz),
        "panel_title": load_font("display_bold", max(28, label_sz - 2)),
        "framed_title": load_font("display_bold", HERO_FRAMED_TITLE_SIZE),
    }


def _measure_hero_launch_bar_block_height(bar_text: str, font) -> int:
    """模块内首发条占用高度（含顶内边距）。"""
    if not bar_text.strip():
        return 0
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bb = probe.textbbox((0, 0), bar_text, font=font, anchor="mt")
    text_h = max(1, bb[3] - bb[1])
    return HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP + max(HERO_MONUMENT_PILL_H - 28, text_h)


def _hero_launch_data_module_metrics(
    *,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    design: dict | None,
) -> tuple[int, int, int]:
    """返回 (module_h, bar_block_h, stats_h) — 首发+数据一体模块。"""
    d = design or DEFAULT_HERO_DESIGN
    bar_block_h = _measure_hero_launch_bar_block_height(bar_text, fonts["bar_pill"])
    stats_h = int(d.get("panel_height", HERO_MONUMENT_DEFAULT_PANEL_H)) if stats else 0
    module_h = bar_block_h
    if bar_block_h and stats_h:
        module_h += HERO_LAUNCH_DATA_MODULE_INNER_GAP + stats_h
    elif stats_h:
        module_h = stats_h
    if module_h > 0:
        module_h += HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
    return module_h, bar_block_h, stats_h


def _hero_data_panel_height(design: dict | None = None) -> int:
    d = design or DEFAULT_HERO_DESIGN
    return int(d.get("panel_height", HERO_DATA_PANEL_H))


def _find_hero_character(assets_dir: Path) -> Path | None:
    for name in ("hero_character.png", "KV角色.png", "hero角色.png", "角色.png"):
        p = assets_dir / name
        if p.is_file():
            return p
    return None


def _find_platform_logos(assets_dir: Path) -> Path | None:
    """三平台 logo 条：优先素材根目录 `3个平台logo.png`。"""
    for name in ("3个平台logo.png", "3个平台logo.jpg", "platform_logos.png", "平台logo.png"):
        p = assets_dir / name
        if p.is_file():
            return p
    return None


def _platform_logos_display_height(path: Path) -> int:
    with Image.open(path) as im:
        return max(1, im.height)


def _paste_platform_logos_strip(
    base: Image.Image,
    *,
    cx: int,
    y: int,
    logo_path: Path,
) -> int:
    """副标题下居中贴三平台 logo 条（原图尺寸，不缩放），返回占用高度。"""
    img = Image.open(logo_path).convert("RGBA")
    w, h = img.width, img.height
    x = cx - w // 2
    _paste_rgba_on_rgb(base, img, x, y)
    return h


def _launch_bar_height(font_bar) -> int:
    return max(88, int(HERO_BAR_TEXT_SIZE * 1.32))


def _hero_has_lower_block(bar_text: str, stats: list | None, *, stat_groups: list | None = None) -> bool:
    return bool(bar_text.strip() or stats or stat_groups)


def _measure_hero_lower_block_inner_height(
    draw: ImageDraw.ImageDraw,
    *,
    bar_text: str,
    stats: list | None,
    fonts: dict,
    design: dict | None = None,
    ai_strip_h: int = 0,
) -> int:
    """首发条 + 数据指标；ai_strip_h>0 时为 KV 纯 AI 数据区整图高度。"""
    if ai_strip_h > 0:
        del draw, bar_text, stats, fonts, design
        return ai_strip_h
    d = design or DEFAULT_HERO_DESIGN
    layout = _hero_data_layout(d)
    if layout == "framed":
        card_title = str(d.get("panel_title") or "").strip()
        module_h = _measure_framed_data_module_height(
            card_title=card_title,
            bar_text=bar_text,
            stats=stats,
            fonts=fonts,
            design=d,
        )
        return HERO_LOWER_BLOCK_PAD_TOP + module_h + HERO_LOWER_BLOCK_PAD_BOTTOM
    if layout in ("monument", "ai_stage", "plain"):
        module_h, _, _ = _hero_launch_data_module_metrics(
            bar_text=bar_text, stats=stats, fonts=fonts, design=d,
        )
        if module_h <= 0:
            return HERO_LOWER_BLOCK_PAD_TOP + HERO_LOWER_BLOCK_PAD_BOTTOM
        return HERO_LOWER_BLOCK_PAD_TOP + module_h + HERO_LOWER_BLOCK_PAD_BOTTOM
    del draw, design
    font_bar = fonts["bar"]
    h = HERO_LOWER_BLOCK_PAD_TOP + HERO_LOWER_BLOCK_PAD_BOTTOM
    if bar_text.strip():
        h += HERO_LAUNCH_PRE_BAND_H + HERO_LAUNCH_PRE_GAP
        h += _launch_bar_height(font_bar)
        if stats:
            h += HERO_LOWER_BLOCK_BAR_TO_DATA_GAP
    elif stats:
        h += HERO_LOWER_BLOCK_INNER_GAP
    if stats:
        h += HERO_LAUNCH_DATA_STATS_H
    return h


def _draw_hero_spotlight_stage(
    base: Image.Image,
    box: tuple[int, int, int, int],
    *,
    theme: dict,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    use_glow: bool = True,
    vivid_primary: tuple[int, int, int] | None = None,
    vivid_secondary: tuple[int, int, int] | None = None,
) -> None:
    """聚光灯舞台：底中强光 + 顶侧暗角（无 nano 时程序化；有 nano 时叠加强化）。"""
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    h = max(1, y1 - y0)
    bg_page = _hex_rgb(theme["bg_page"])
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(12):
        t = (i + 1) / 12
        band_h = max(2, int(h * 0.12 * t))
        ld.rectangle([x0, y0, x1, y0 + band_h], fill=(*bg_page, int(55 * t)))
    vp = vivid_primary or primary
    vs = vivid_secondary or secondary
    floor_y = y1 - int(h * 0.38)
    if use_glow:
        ld.ellipse(
            [cx - 460, floor_y - 50, cx + 460, y1 + 28],
            fill=(*_mix_rgb(vp, vs, 0.35), 95),
        )
        ld.ellipse(
            [cx - 300, floor_y + 10, cx + 300, y1 + 12],
            fill=(*_lighten(vp, 0.35), 58),
        )
    ld.ellipse(
        [cx - 180, y1 - 18, cx + 180, y1 + 6],
        fill=(255, 255, 255, 55),
    )
    _draw_halftone_band(ld, (x0 + 8, y0 + 8, x0 + 100, y1 - 12), vp, dot=5, alpha=75)
    _draw_halftone_band(ld, (x1 - 100, y0 + 8, x1 - 8, y1 - 12), vs, dot=5, alpha=65)
    _draw_hazard_stripes(
        ld,
        (x0 + 12, y1 - 10, x1 - 12, y1),
        _darken(vp, 0.5),
        _mix_rgb(vs, (40, 40, 40), 0.5),
        stripe_h=4,
    )
    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))


def _draw_skew_quad(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    skew: int,
    fill: tuple[int, int, int, int],
    *,
    outline: tuple[int, int, int, int] | None = None,
    outline_w: int = 0,
) -> None:
    x0, y0, x1, y1 = box
    s = skew
    pts = [(x0 + s, y0), (x1, y0), (x1 - s, y1), (x0, y1)]
    ld.polygon(pts, fill=fill)
    if outline and outline_w > 0:
        ld.polygon(pts, outline=outline, width=outline_w)


def _draw_hazard_stripes(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
    *,
    stripe_h: int = 5,
) -> None:
    x0, y0, x1, y1 = box
    i = 0
    for yy in range(y0, y1, stripe_h):
        c = (*dark, 255) if i % 2 == 0 else (*light, 255)
        ld.rectangle([x0, yy, x1, min(yy + stripe_h, y1)], fill=c)
        i += 1


def _draw_checker_patch(
    ld: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> None:
    cell = max(4, size // 4)
    for row in range(size // cell):
        for col in range(size // cell):
            c = c1 if (row + col) % 2 == 0 else c2
            x0 = x + col * cell
            y0 = y + row * cell
            ld.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=(*c, 220))


def _composite_rgba_layer(base: Image.Image, layer: Image.Image) -> None:
    if base.mode == "RGBA":
        base_comp = Image.alpha_composite(base, layer)
        base.paste(base_comp)
    else:
        base_rgba = base.convert("RGBA")
        base_rgba = Image.alpha_composite(base_rgba, layer)
        base.paste(base_rgba.convert("RGB"))


def _draw_game_corner_brackets(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    vivid: tuple[int, int, int],
    alt: tuple[int, int, int],
    *,
    arm: int = 18,
    width: int = 3,
) -> None:
    """游戏 UI 四角 L 形描边。"""
    x0, y0, x1, y1 = box
    for ox, oy, dx, dy, col in (
        (x0 + 6, y0 + 6, 1, 0, vivid),
        (x0 + 6, y0 + 6, 0, 1, vivid),
        (x1 - 6, y0 + 6, -1, 0, alt),
        (x1 - 6, y0 + 6, 0, 1, alt),
        (x0 + 6, y1 - 6, 1, 0, alt),
        (x0 + 6, y1 - 6, 0, -1, alt),
        (x1 - 6, y1 - 6, -1, 0, vivid),
        (x1 - 6, y1 - 6, 0, -1, vivid),
    ):
        x_end = ox + dx * arm
        y_end = oy + dy * arm
        ld.line([(ox, oy), (x_end, oy)], fill=(*col, 255), width=width)
        ld.line([(ox, oy), (ox, y_end)], fill=(*col, 255), width=width)


def _draw_game_border_frame(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    vivid: tuple[int, int, int],
    alt: tuple[int, int, int],
    dark: tuple[int, int, int],
    skew: int = 14,
    minimal: bool = False,
) -> None:
    """游戏风边框；minimal=True 时仅外框+淡底（小 Banner 标题区，无文字下装饰）。"""
    x0, y0, x1, y1 = box
    s = max(0, skew)
    _draw_skew_quad(
        ld,
        box,
        s,
        (*_darken(vivid, 0.48), 238),
        outline=(*_lighten(vivid, 0.12), 255),
        outline_w=4,
    )
    inner_pad = (7, 6, 7, 8 if minimal else 14)
    inner = (x0 + inner_pad[0], y0 + inner_pad[1], x1 - inner_pad[2], y1 - inner_pad[3])
    _draw_skew_quad(ld, inner, max(4, s - 5), (0, 0, 0, 200 if minimal else 225))
    if minimal:
        glow = (x0 + 10, y0 + 8, x1 - 10, y1 - 10)
        _draw_skew_quad(
            ld,
            glow,
            max(2, s - 6),
            (*_mix_rgb(dark, vivid, 0.2), 140),
        )
        _draw_game_corner_brackets(ld, box, vivid, alt)
        return
    glow = (x0 + 12, y0 + 10, x1 - 12, y1 - 20)
    _draw_skew_quad(
        ld,
        glow,
        max(2, s - 8),
        (*_mix_rgb(_mix_rgb(dark, vivid, 0.38), alt, 0.22), 165),
    )
    _draw_halftone_band(ld, (x0 + 12, y0 + 10, x0 + 110, y1 - 14), vivid, dot=5, alpha=95)
    _draw_halftone_band(ld, (x1 - 110, y0 + 10, x1 - 12, y1 - 14), alt, dot=5, alpha=80)
    _draw_hazard_stripes(
        ld,
        (x0 + 8, y1 - 12, x1 - 8, y1 - 3),
        _darken(vivid, 0.55),
        _mix_rgb(alt, (255, 255, 255), 0.38),
        stripe_h=3,
    )
    _draw_game_corner_brackets(ld, box, vivid, alt)
    _draw_checker_patch(ld, x0 + 10, y0 + 8, 20, vivid, (0, 0, 0))
    _draw_checker_patch(ld, x1 - 30, y0 + 8, 20, (0, 0, 0), alt)


def _draw_hero_launch_text_kv(
    base: Image.Image,
    *,
    cx: int,
    y: int,
    text: str,
    font,
    text_c: tuple[int, int, int],
    vivid: tuple[int, int, int] | None = None,
    alt: tuple[int, int, int] | None = None,
    trailing_gap: int | None = None,
) -> int:
    """首发条：本地字体（与副标题同字号），无 AI 字、无文字框。"""
    del vivid, alt
    draw = ImageDraw.Draw(base)
    ty = y
    fill = _lighten(text_c, 0.08)
    for dx, dy in ((2, 2), (1, 1)):
        draw.text((cx + dx, ty + dy), text, font=font, fill=(0, 0, 0), anchor="mt")
    draw.text(
        (cx, ty),
        text,
        font=font,
        fill=fill,
        anchor="mt",
        stroke_width=4,
        stroke_fill=(0, 0, 0),
    )
    gap = (
        HERO_MONUMENT_BAR_TO_STAGE_GAP if trailing_gap is None else trailing_gap
    )
    return draw.textbbox((cx, ty), text, font=font, anchor="mt")[3] + gap


def _draw_hero_launch_skew_band(
    base: Image.Image,
    *,
    cx: int,
    y: int,
    text: str,
    font,
    vivid: tuple[int, int, int],
    alt: tuple[int, int, int],
    text_c: tuple[int, int, int],
) -> int:
    """首发条：游戏风边框（无 KV 底图时同逻辑）。"""
    return _draw_hero_launch_text_kv(
        base,
        cx=cx,
        y=y,
        text=text,
        font=font,
        text_c=text_c,
        vivid=vivid,
        alt=alt,
    )


def _measure_hero_stats_column_block(
    pairs: list[tuple[str, str]],
    font_l,
    font_v,
    *,
    col_gap: int = HERO_STAT_COL_GAP,
) -> tuple[list[int], int, int, int]:
    """每列宽、总宽、标签行高、数值行高（标签在上、数值在下）。"""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    col_ws: list[int] = []
    label_h = 0
    value_h = 0
    for label, value in pairs:
        lb = probe.textbbox((0, 0), label, font=font_l, anchor="lt")
        vb = probe.textbbox((0, 0), value, font=font_v, anchor="lt")
        col_ws.append(max(lb[2] - lb[0], vb[2] - vb[0], 120))
        label_h = max(label_h, lb[3] - lb[1])
        value_h = max(value_h, vb[3] - vb[1])
    block_w = sum(col_ws) + col_gap * max(0, len(pairs) - 1)
    return col_ws, block_w, label_h, value_h


def _draw_hero_stats_columns(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    y: int,
    height: int,
    pairs: list[tuple[str, str]],
    font_l,
    font_v,
    label_fill: tuple[int, int, int],
    value_fill: tuple[int, int, int],
    col_gap: int = HERO_STAT_COL_GAP,
) -> None:
    """曝光/下载等：每列标签在上、数值在下，多列并排整体水平居中。"""
    if not pairs:
        return
    col_ws, block_w, label_h, value_h = _measure_hero_stats_column_block(
        pairs, font_l, font_v, col_gap=col_gap,
    )
    block_h = label_h + HERO_STAT_LABEL_VALUE_GAP + value_h
    block_top = y + max(0, (height - block_h) // 2)
    label_y = block_top
    value_y = block_top + label_h + HERO_STAT_LABEL_VALUE_GAP
    x = cx - block_w // 2
    for i, (label, value) in enumerate(pairs):
        col_cx = x + col_ws[i] // 2
        draw.text((col_cx, label_y), label, font=font_l, fill=label_fill, anchor="mt")
        draw.text((col_cx, value_y), value, font=font_v, fill=value_fill, anchor="mt")
        x += col_ws[i] + (col_gap if i < len(pairs) - 1 else 0)


def _draw_hero_monument_stats(
    base: Image.Image,
    *,
    y: int,
    height: int,
    pairs: list[tuple[str, str]],
    fonts: dict,
    text_c: tuple[int, int, int],
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    cx: int = HERO_TEXT_CENTER_X,
    kv_ai_overlay: bool = False,
    stage_box: tuple[int, int, int, int] | None = None,
    theme: dict | None = None,
) -> None:
    """数据指标：标签在上数值在下，分列横排居中（AI 底图时可选遮罩）。"""
    del primary, secondary
    if not pairs:
        return
    if kv_ai_overlay and stage_box and theme:
        _draw_hero_stat_value_scrim(base, stage_box, theme)
    value_fill, label_fill, _ = _hero_data_text_fills(theme or {}, text_c)
    _draw_hero_stats_columns(
        ImageDraw.Draw(base),
        cx=cx,
        y=y,
        height=height,
        pairs=pairs,
        font_l=fonts["stat_label"],
        font_v=fonts["stat_value"],
        label_fill=label_fill,
        value_fill=value_fill,
    )


def _draw_framed_deckle_outer(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
) -> None:
    """外框顶部撕边/卷边（参考图羊皮纸层）。"""
    x0, y0, x1, y1 = box
    w = x1 - x0
    wave = [
        (x0, y0 + 10),
        (x0 + int(w * 0.08), y0 + 2),
        (x0 + int(w * 0.18), y0 + 12),
        (x0 + int(w * 0.28), y0 + 4),
        (x0 + int(w * 0.38), y0 + 14),
        (x0 + int(w * 0.5), y0 + 3),
        (x0 + int(w * 0.62), y0 + 13),
        (x0 + int(w * 0.72), y0 + 5),
        (x0 + int(w * 0.82), y0 + 11),
        (x0 + int(w * 0.92), y0 + 4),
        (x1, y0 + 9),
        (x1, y1),
        (x0, y1),
    ]
    ld.polygon(wave, fill=(*fill, 255))


def _draw_framed_pill(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    cy: int,
    text: str,
    font,
    bg: tuple[int, int, int],
    text_fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bb = probe.textbbox((0, 0), text, font=font, anchor="mm")
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    pill_w = tw + HERO_FRAMED_PILL_PAD_X * 2
    pill_h = max(HERO_FRAMED_PILL_H, th + 18)
    box = (cx - pill_w // 2, cy - pill_h // 2, cx + pill_w // 2, cy + pill_h // 2)
    draw.rounded_rectangle(box, radius=pill_h // 2, fill=bg)
    draw.text((cx, cy), text, font=font, fill=text_fill, anchor="mm")
    return box


def _draw_framed_stats_columns(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    y: int,
    height: int,
    pairs: list[tuple[str, str]],
    font_l,
    font_v,
    palette: dict[str, tuple[int, int, int]],
    col_gap: int = HERO_STAT_COL_GAP,
) -> None:
    """标签在上、黄字黑描边数值在下，多列居中。"""
    if not pairs:
        return
    col_ws, block_w, label_h, value_h = _measure_hero_stats_column_block(
        pairs, font_l, font_v, col_gap=col_gap,
    )
    gap_lv = HERO_FRAMED_STAT_LABEL_VALUE_GAP
    block_h = label_h + gap_lv + value_h
    block_top = y + max(0, (height - block_h) // 2)
    label_y = block_top
    value_y = block_top + label_h + gap_lv
    x = cx - block_w // 2
    for i, (label, value) in enumerate(pairs):
        col_cx = x + col_ws[i] // 2
        draw.text((col_cx, label_y), label, font=font_l, fill=palette["label"], anchor="mt")
        draw.text(
            (col_cx, value_y),
            value,
            font=font_v,
            fill=palette["value"],
            anchor="mt",
            stroke_width=HERO_FRAMED_VALUE_STROKE,
            stroke_fill=(0, 0, 0),
        )
        x += col_ws[i] + (col_gap if i < len(pairs) - 1 else 0)


def _measure_framed_data_module_height(
    *,
    card_title: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    design: dict | None,
) -> int:
    d = design or DEFAULT_HERO_DESIGN
    panel_w = int(d.get("panel_width", HERO_FRAMED_PANEL_W))
    probe = ImageDraw.Draw(Image.new("RGB", (panel_w, 800)))
    y = HERO_FRAMED_INNER_PAD_TOP
    if card_title.strip():
        bb = probe.textbbox((0, 0), card_title, font=fonts["framed_title"], anchor="mt")
        y = bb[3] + HERO_FRAMED_TITLE_TO_PILL_GAP
    if bar_text.strip():
        y += HERO_FRAMED_PILL_H + HERO_FRAMED_PILL_TO_STATS_GAP
    if stats:
        _, _, lh, vh = _measure_hero_stats_column_block(
            stats, fonts["stat_label"], fonts["stat_value"],
        )
        y += lh + HERO_FRAMED_STAT_LABEL_VALUE_GAP + vh
    y += HERO_FRAMED_INNER_PAD_BOTTOM
    min_inner = int(d.get("panel_height", 340))
    if y < min_inner:
        y = min_inner
    return y + HERO_FRAMED_OUTER_BLEED * 2 + 12


def _measure_multi_group_data_height(
    stat_groups: list[dict], fonts: dict, design: dict | None = None,
) -> int:
    total = 0
    n = len(stat_groups)
    for i, group in enumerate(stat_groups):
        total += _measure_framed_data_module_height(
            card_title=group["title"],
            bar_text="",
            stats=group["stats"],
            fonts=fonts,
            design=design,
        )
        if i < n - 1:
            total += HERO_LOWER_BLOCK_INNER_GAP
    return total


def _draw_hero_framed_data_card(
    base: Image.Image,
    *,
    y: int,
    card_title: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    design: dict | None = None,
) -> int:
    """KV 配色框式数据卡：羊皮纸外框 + 圆角内卡 + 可选标题 + 黄标 pill + 描边数值（不生图）。"""
    d = design or DEFAULT_HERO_DESIGN
    panel_w = int(d.get("panel_width", HERO_FRAMED_PANEL_W))
    panel_x0 = (CANVAS_W - panel_w) // 2
    module_h = _measure_framed_data_module_height(
        card_title=card_title,
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
        design=d,
    )
    outer_box = (
        panel_x0 - HERO_FRAMED_OUTER_BLEED,
        y,
        panel_x0 + panel_w + HERO_FRAMED_OUTER_BLEED,
        y + module_h,
    )
    inner_box = (
        panel_x0,
        y + HERO_FRAMED_OUTER_BLEED + 6,
        panel_x0 + panel_w,
        y + module_h - HERO_FRAMED_OUTER_BLEED,
    )
    palette = _framed_data_palette(theme)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    _draw_framed_deckle_outer(ld, outer_box, palette["outer"])
    ix0, iy0, ix1, iy1 = inner_box
    accent_alt = palette.get("border_alt", palette["border"])
    ld.rounded_rectangle(
        (ix0 - 3, iy0 - 3, ix1 + 3, iy1 + 3),
        radius=HERO_FRAMED_INNER_RADIUS + 3,
        outline=(*accent_alt, 255),
        width=2,
    )
    ld.rounded_rectangle(
        inner_box,
        radius=HERO_FRAMED_INNER_RADIUS,
        fill=(*palette["inner"], 255),
        outline=(*palette["border"], 255),
        width=HERO_FRAMED_BORDER_W,
    )
    _composite_rgba_layer(base, layer)

    draw = ImageDraw.Draw(base)
    cx = (inner_box[0] + inner_box[2]) // 2
    cy = inner_box[1] + HERO_FRAMED_INNER_PAD_TOP
    if card_title.strip():
        draw.text((cx, cy), card_title, font=fonts["framed_title"], fill=palette["label"], anchor="mt")
        cy = draw.textbbox((cx, cy), card_title, font=fonts["framed_title"], anchor="mt")[3]
        cy += HERO_FRAMED_TITLE_TO_PILL_GAP
        for sx, sy in ((inner_box[0] + 28, inner_box[1] + 22), (inner_box[2] - 36, inner_box[1] + 30)):
            _draw_sparkle(draw, sx, sy, palette["sparkle"], 5)
    if bar_text.strip():
        pill_box = _draw_framed_pill(
            draw,
            cx=cx,
            cy=cy + HERO_FRAMED_PILL_H // 2,
            text=bar_text,
            font=fonts["bar_pill"],
            bg=palette["pill"],
            text_fill=palette["pill_text"],
        )
        cy = pill_box[3] + HERO_FRAMED_PILL_TO_STATS_GAP
        _draw_sparkle(draw, pill_box[2] + 8, pill_box[1] + 6, palette["sparkle"], 6)
    if stats:
        stats_h = inner_box[3] - cy - HERO_FRAMED_INNER_PAD_BOTTOM
        _draw_framed_stats_columns(
            draw,
            cx=cx,
            y=cy,
            height=max(80, stats_h),
            pairs=stats,
            font_l=fonts["stat_label"],
            font_v=fonts["stat_value"],
            palette=palette,
        )
    return y + module_h


def _draw_hero_ai_stage_backdrop(
    base: Image.Image,
    module_box: tuple[int, int, int, int],
    theme: dict,
) -> None:
    """
    程序化数据舞台：暗色渐变、底部聚光、KV rim 光（不调用文生图）。
    """
    x0, y0, x1, y1 = module_box
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    panel_cx = (x0 + x1) // 2
    roles = _kv_accent_roles(theme)
    vivid_p, vivid_s = _theme_vivid_pair(theme)
    pop = _boost_vivid(roles["pop"], sat_mul=1.12, val_mul=1.08)
    dark = roles["dark"]
    bg_page = roles["bg_page"]
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    top_c = _mix_rgb(dark, bg_page, 0.35)
    mid_c = _mix_rgb(dark, _mix_rgb(vivid_p, vivid_s, 0.45), 0.55)
    bot_c = _mix_rgb(_mix_rgb(dark, vivid_p, 0.42), pop, 0.38)
    for i in range(h):
        t = i / max(1, h - 1)
        if t < 0.45:
            c = _mix_rgb(top_c, mid_c, t / 0.45)
        else:
            c = _mix_rgb(mid_c, bot_c, (t - 0.45) / 0.55)
        ld.line([(x0, y0 + i), (x1, y0 + i)], fill=(*c, 255))
    _draw_halftone_band(ld, module_box, _mix_rgb(vivid_p, pop, 0.4), dot=7, alpha=42)
    floor_y = y1 - int(h * 0.12)
    ld.ellipse(
        [panel_cx - 340, floor_y - 55, panel_cx + 340, floor_y + 95],
        fill=(*_lighten(vivid_p, 0.28), 125),
    )
    ld.ellipse(
        [panel_cx - 200, floor_y - 30, panel_cx + 200, floor_y + 60],
        fill=(*_lighten(pop, 0.18), 95),
    )
    ld.ellipse(
        [panel_cx - 90, floor_y - 12, panel_cx + 90, floor_y + 28],
        fill=(*_lighten(vivid_s, 0.12), 70),
    )
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(w):
        t = abs(i - w / 2) / (w / 2)
        if t > 0.55:
            alpha = int(min(90, (t - 0.55) * 200))
            vd.line([(i, 0), (i, h)], fill=(0, 0, 0, alpha))
    layer.paste(vignette, (x0, y0), vignette)
    ld.line([(x0 + 16, y0 + 2), (x1 - 16, y0 + 2)], fill=(*vivid_p, 220), width=3)
    ld.line([(x0 + 16, y1 - 2), (x1 - 16, y1 - 2)], fill=(*_mix_rgb(vivid_s, pop, 0.5), 180), width=2)
    skew = 36
    ld.polygon(
        [(x0, y0), (x0 + skew, y0), (x0 + skew, y1), (x0, y1)],
        fill=(*_mix_rgb(vivid_p, (0, 0, 0), 0.65), 55),
    )
    ld.polygon(
        [(x1 - skew, y0), (x1, y0), (x1, y1), (x1 - skew, y1)],
        fill=(*_mix_rgb(vivid_s, (0, 0, 0), 0.65), 55),
    )
    _composite_rgba_layer(base, layer)


def _draw_hero_ai_launch_pill(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    cy: int,
    text: str,
    font,
    theme: dict,
) -> tuple[int, int, int, int]:
    """生图风格首发条：半透明暗底 + KV 亮色 pill（本地字）。"""
    roles = _kv_accent_roles(theme)
    pill_bg = _boost_vivid(roles["pop"], sat_mul=1.08, val_mul=1.05)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bb = probe.textbbox((0, 0), text, font=font, anchor="mm")
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad_x, pad_y = 26, 14
    pill_w = tw + pad_x * 2
    pill_h = max(HERO_FRAMED_PILL_H, th + pad_y * 2)
    box = (cx - pill_w // 2, cy - pill_h // 2, cx + pill_w // 2, cy + pill_h // 2)
    draw.rounded_rectangle(
        (box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4),
        radius=pill_h // 2 + 4,
        fill=_mix_rgb(roles["dark"], (0, 0, 0), 0.72),
    )
    draw.rounded_rectangle(box, radius=pill_h // 2, fill=pill_bg)
    draw.text(
        (cx, cy), text, font=font, fill=(18, 18, 18), anchor="mm",
        stroke_width=2, stroke_fill=(0, 0, 0),
    )
    return box


def _draw_hero_ai_stage_stats(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    y: int,
    height: int,
    pairs: list[tuple[str, str]],
    font_l,
    font_v,
    label_fill: tuple[int, int, int],
) -> None:
    """巨幕白字 + 黑描边（对齐 ensure_ai_hero_data_strip 叠字观感）。"""
    if not pairs:
        return
    col_ws, block_w, label_h, value_h = _measure_hero_stats_column_block(
        pairs, font_l, font_v, col_gap=HERO_DATA_STAT_GAP,
    )
    gap_lv = HERO_STAT_LABEL_VALUE_GAP + 4
    block_h = label_h + gap_lv + value_h
    block_top = y + max(0, (height - block_h) // 2)
    label_y = block_top
    value_y = block_top + label_h + gap_lv
    value_fill = (255, 255, 255)
    x = cx - block_w // 2
    for i, (label, value) in enumerate(pairs):
        col_cx = x + col_ws[i] // 2
        draw.text((col_cx, label_y), label, font=font_l, fill=label_fill, anchor="mt")
        draw.text(
            (col_cx, value_y),
            value,
            font=font_v,
            fill=value_fill,
            anchor="mt",
            stroke_width=6,
            stroke_fill=(0, 0, 0),
        )
        x += col_ws[i] + (HERO_DATA_STAT_GAP if i < len(pairs) - 1 else 0)


def _draw_hero_launch_data_block_ai_stage(
    base: Image.Image,
    *,
    y: int,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    text_c: tuple[int, int, int],
    design: dict | None = None,
) -> int:
    """生图风格数据模块：程序化舞台底 + 本地 pill/巨幕数字，不文生图。"""
    d = design or DEFAULT_HERO_DESIGN
    panel_w = HERO_LOWER_BLOCK_W
    panel_x0 = (CANVAS_W - panel_w) // 2
    panel_cx = CANVAS_W // 2
    inner_h = _measure_hero_lower_block_inner_height(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
        design=d,
    )
    y1 = y + inner_h
    module_h, bar_block_h, stats_h = _hero_launch_data_module_metrics(
        bar_text=bar_text, stats=stats, fonts=fonts, design=d,
    )
    if module_h <= 0:
        return y1
    module_y0 = y + HERO_LOWER_BLOCK_PAD_TOP
    module_y1 = module_y0 + module_h
    module_box = (panel_x0, module_y0, panel_x0 + panel_w, module_y1)
    _draw_hero_ai_stage_backdrop(base, module_box, theme)
    _, label_fill, _ = _hero_data_text_fills(theme, text_c)
    draw = ImageDraw.Draw(base)
    if bar_text.strip():
        bar_y = module_y0 + HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP
        pill_cy = bar_y + HERO_FRAMED_PILL_H // 2
        _draw_hero_ai_launch_pill(
            draw, cx=panel_cx, cy=pill_cy, text=bar_text, font=fonts["bar_pill"], theme=theme,
        )
    if stats:
        stats_y0 = (
            module_y0 + bar_block_h + HERO_LAUNCH_DATA_MODULE_INNER_GAP
            if bar_block_h
            else module_y0
        )
        stats_y1 = module_y1 - HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        stats_draw_h = max(120, stats_y1 - stats_y0)
        _draw_hero_ai_stage_stats(
            draw,
            cx=panel_cx,
            y=stats_y0,
            height=stats_draw_h,
            pairs=stats,
            font_l=fonts["stat_label"],
            font_v=fonts["stat_value"],
            label_fill=label_fill,
        )
    return y1


def _draw_hero_launch_data_block_plain(
    base: Image.Image,
    *,
    y: int,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    text_c: tuple[int, int, int],
    design: dict | None = None,
) -> int:
    """数据区：无底色块/框/光效，仅 KV 上分色叠字。"""
    d = design or DEFAULT_HERO_DESIGN
    panel_cx = CANVAS_W // 2
    inner_h = _measure_hero_lower_block_inner_height(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
        design=d,
    )
    y1 = y + inner_h
    module_h, bar_block_h, _stats_h = _hero_launch_data_module_metrics(
        bar_text=bar_text, stats=stats, fonts=fonts, design=d,
    )
    if module_h <= 0:
        return y1
    module_y0 = y + HERO_LOWER_BLOCK_PAD_TOP
    module_y1 = module_y0 + module_h
    value_fill, label_fill, bar_fill = _hero_data_text_fills(theme, text_c)
    if bar_text.strip():
        bar_y = module_y0 + HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP
        trail = HERO_LAUNCH_DATA_MODULE_INNER_GAP if stats else HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        _draw_hero_data_plain_text(
            base,
            cx=panel_cx,
            y=bar_y,
            text=bar_text,
            font=fonts["bar_pill"],
            fill=bar_fill,
            trailing_gap=trail,
        )
    if stats:
        stats_y0 = (
            module_y0 + bar_block_h + HERO_LAUNCH_DATA_MODULE_INNER_GAP
            if bar_block_h
            else module_y0
        )
        stats_y1 = module_y1 - HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        stats_draw_h = max(120, stats_y1 - stats_y0)
        _draw_hero_stats_columns(
            ImageDraw.Draw(base),
            cx=panel_cx,
            y=stats_y0,
            height=stats_draw_h,
            pairs=stats,
            font_l=fonts["stat_label"],
            font_v=fonts["stat_value"],
            label_fill=label_fill,
            value_fill=value_fill,
            col_gap=HERO_DATA_STAT_GAP,
        )
    return y1


def _draw_hero_lower_unified_backdrop(
    base: Image.Image,
    *,
    y: int,
    height: int,
    theme: dict,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    card_dark: tuple[int, int, int],
    stroke_c: tuple[int, int, int],
) -> None:
    """首发+数据底卡：配色来自 KV theme，左右对称，中部留白给居中叠字。"""
    panel_w = HERO_LOWER_BLOCK_W
    panel_x0 = (CANVAS_W - panel_w) // 2
    panel_cx = CANVAS_W // 2
    y1 = y + height
    skew = 20
    bg_page = _hex_rgb(theme["bg_page"])
    fill_panel = (*_mix_rgb(card_dark, bg_page, 0.48), 235)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.polygon(
        [
            (panel_x0 + skew, y),
            (panel_x0 + panel_w, y),
            (panel_x0 + panel_w - skew, y1),
            (panel_x0, y1),
        ],
        fill=fill_panel,
    )
    mid_y = (y + y1) // 2
    glow_c = (*_mix_rgb(primary, secondary, 0.35), 55)
    ld.ellipse(
        [panel_cx - 280, mid_y - 90, panel_cx + 280, mid_y + 90],
        fill=glow_c,
    )
    ld.line(
        [(panel_x0 + skew, y), (panel_x0 + panel_w, y)],
        fill=(*primary, 255),
        width=3,
    )
    ld.line(
        [(panel_x0, y1), (panel_x0 + panel_w - skew, y1)],
        fill=(*secondary, 210),
        width=2,
    )
    for ox, hatch_c in (
        (panel_x0 + 24, primary),
        (panel_x0 + panel_w - 48, secondary),
    ):
        _draw_diagonal_hatch(
            ld,
            (ox, y + 16, ox + 28, y1 - 16),
            hatch_c,
            step=8,
        )
    ld.line(
        [(panel_cx, y + 12), (panel_cx, y1 - 12)],
        fill=(*_mix_rgb(primary, secondary, 0.5), 50),
        width=1,
    )
    inset = 3
    ld.rectangle(
        [panel_x0 + skew + inset, y + inset, panel_x0 + panel_w - inset, y1 - inset],
        outline=(*stroke_c[:3], 80),
        width=1,
    )
    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))


def _draw_hero_stats_row(
    draw: ImageDraw.ImageDraw,
    *,
    panel_cx: int,
    y: int,
    pairs: list[tuple[str, str]],
    fonts: dict,
    value_fill: tuple[int, int, int],
    label_fill: tuple[int, int, int],
    block_height: int = 140,
) -> None:
    """classic 布局：与 monument 相同，标签上数值下、横排居中。"""
    _draw_hero_stats_columns(
        draw,
        cx=panel_cx,
        y=y,
        height=block_height,
        pairs=pairs,
        font_l=fonts["stat_label"],
        font_v=fonts["stat_value"],
        label_fill=label_fill,
        value_fill=value_fill,
        col_gap=HERO_DATA_STAT_GAP,
    )


def _draw_hero_launch_data_block_classic(
    base: Image.Image,
    *,
    y: int,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    card_dark: tuple[int, int, int],
    text_c: tuple[int, int, int],
    stroke_c: tuple[int, int, int],
    hero_character: Path | None = None,
    nano_data_bg: Path | None = None,
    design: dict | None = None,
) -> int:
    """classic：1040 斜切底卡 + 居中首发条 + 常规数据行。"""
    _ = hero_character, design
    panel_w = HERO_LOWER_BLOCK_W
    panel_x0 = (CANVAS_W - panel_w) // 2
    panel_cx = CANVAS_W // 2
    inner_h = _measure_hero_lower_block_inner_height(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
    )
    y1 = y + inner_h
    data_box = (panel_x0, y, panel_x0 + panel_w, y + inner_h)

    if nano_data_bg and nano_data_bg.is_file() and (bar_text.strip() or stats):
        _paste_cover_in_box(base, Image.open(nano_data_bg), data_box)

    value_fill, label_fill, bar_fill = _hero_data_text_fills(theme, text_c)
    cy = y + HERO_LOWER_BLOCK_PAD_TOP
    font_bar = fonts["bar"]

    if bar_text.strip():
        cy = _draw_hero_data_plain_text(
            base,
            cx=panel_cx,
            y=cy,
            text=bar_text,
            font=font_bar,
            fill=bar_fill,
        )
        if stats:
            cy += HERO_LOWER_BLOCK_BAR_TO_DATA_GAP
    elif stats:
        cy += HERO_LOWER_BLOCK_INNER_GAP

    if stats:
        _draw_hero_stats_row(
            ImageDraw.Draw(base),
            panel_cx=panel_cx,
            y=cy,
            pairs=stats,
            fonts=fonts,
            value_fill=value_fill,
            label_fill=label_fill,
        )

    return y1


def _draw_hero_launch_data_block(
    base: Image.Image,
    *,
    y: int,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    card_dark: tuple[int, int, int],
    text_c: tuple[int, int, int],
    stroke_c: tuple[int, int, int],
    hero_character: Path | None = None,
    nano_data_bg: Path | None = None,
    design: dict | None = None,
    kv_ai_bg: bool = False,
    card_title: str = "",
) -> int:
    """plain（默认）：无装饰叠字；ai_stage 舞台；framed 框式卡；monument / classic 旧版。"""
    design = design or DEFAULT_HERO_DESIGN
    layout = _hero_data_layout(design)
    if layout == "plain":
        return _draw_hero_launch_data_block_plain(
            base,
            y=y,
            bar_text=bar_text,
            stats=stats,
            fonts=fonts,
            theme=theme,
            text_c=text_c,
            design=design,
        )
    if layout == "ai_stage":
        return _draw_hero_launch_data_block_ai_stage(
            base,
            y=y,
            bar_text=bar_text,
            stats=stats,
            fonts=fonts,
            theme=theme,
            text_c=text_c,
            design=design,
        )
    if layout == "framed":
        title = card_title.strip() or str(design.get("panel_title") or "").strip()
        return _draw_hero_framed_data_card(
            base,
            y=y + HERO_LOWER_BLOCK_PAD_TOP,
            card_title=title,
            bar_text=bar_text,
            stats=stats,
            fonts=fonts,
            theme=theme,
            design=design,
        ) + HERO_LOWER_BLOCK_PAD_BOTTOM
    if layout == "classic":
        return _draw_hero_launch_data_block_classic(
            base,
            y=y,
            bar_text=bar_text,
            stats=stats,
            fonts=fonts,
            theme=theme,
            primary=primary,
            secondary=secondary,
            card_dark=card_dark,
            text_c=text_c,
            stroke_c=stroke_c,
            hero_character=hero_character,
            nano_data_bg=nano_data_bg,
            design=design,
        )

    panel_w = HERO_LOWER_BLOCK_W
    panel_x0 = (CANVAS_W - panel_w) // 2
    panel_cx = CANVAS_W // 2
    inner_h = _measure_hero_lower_block_inner_height(
        ImageDraw.Draw(Image.new("RGB", (1, 1))),
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
        design=design,
    )
    y1 = y + inner_h
    module_h, bar_block_h, stats_h = _hero_launch_data_module_metrics(
        bar_text=bar_text, stats=stats, fonts=fonts, design=design,
    )
    if module_h <= 0:
        return y1
    module_y0 = y + HERO_LOWER_BLOCK_PAD_TOP
    module_y1 = module_y0 + module_h
    module_box = (panel_x0, module_y0, panel_x0 + panel_w, module_y1)
    if stats_h > 0:
        stats_y0 = (
            module_y0 + bar_block_h + HERO_LAUNCH_DATA_MODULE_INNER_GAP
            if bar_block_h
            else module_y0
        )
    else:
        stats_y0 = module_y1
    stats_box = (panel_x0, stats_y0, panel_x0 + panel_w, module_y1 - HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM)
    vivid_p, vivid_s = _theme_vivid_pair(theme)
    has_module_bg = bool(nano_data_bg and nano_data_bg.is_file() and (bar_text.strip() or stats))

    if has_module_bg:
        _paste_hero_data_module_bg(base, nano_data_bg, module_box, theme)

    value_fill, label_fill, bar_fill = _hero_data_text_fills(theme, text_c)
    if bar_text.strip():
        bar_y = module_y0 + HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP
        trail = HERO_LAUNCH_DATA_MODULE_INNER_GAP if stats else HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        _draw_hero_data_plain_text(
            base,
            cx=panel_cx,
            y=bar_y,
            text=bar_text,
            font=fonts["bar_pill"],
            fill=bar_fill,
            trailing_gap=trail,
        )

    if stats and hero_character and hero_character.is_file() and not kv_ai_bg:
        char_box = (
            module_box[0] + int(panel_w * 0.58),
            module_box[1] + 4,
            module_box[2] - 8,
            module_box[3] - 8,
        )
        try:
            _paste_contain_in_box(base, Image.open(hero_character), char_box)
        except OSError:
            pass

    if stats:
        stats_draw_h = max(1, stats_box[3] - stats_box[1])
        _draw_hero_monument_stats(
            base,
            y=stats_box[1],
            height=stats_draw_h,
            pairs=stats,
            fonts=fonts,
            text_c=text_c,
            primary=vivid_p,
            secondary=vivid_s,
            cx=panel_cx,
            kv_ai_overlay=has_module_bg,
            stage_box=stats_box,
            theme=theme,
        )

    return y1


def _draw_hero_data_text_overlay_on_strip(
    base: Image.Image,
    *,
    y: int,
    strip_h: int,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    theme: dict,
    text_c: tuple[int, int, int],
    design: dict | None = None,
) -> int:
    """无字底图上叠本地首发条+数据（一体模块，不用 AI 生成字）。"""
    design = design or DEFAULT_HERO_DESIGN
    vivid_p, vivid_s = _theme_vivid_pair(theme)
    _, _, bar_fill = _hero_data_text_fills(theme, text_c)
    panel_cx = CANVAS_W // 2
    module_y0 = y + HERO_LOWER_BLOCK_PAD_TOP
    module_h, bar_block_h, _stats_h = _hero_launch_data_module_metrics(
        bar_text=bar_text, stats=stats, fonts=fonts, design=design,
    )
    if bar_text.strip():
        bar_y = module_y0 + HERO_LAUNCH_DATA_MODULE_BAR_PAD_TOP
        trail = HERO_LAUNCH_DATA_MODULE_INNER_GAP if stats else HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        _draw_hero_data_plain_text(
            base,
            cx=panel_cx,
            y=bar_y,
            text=bar_text,
            font=fonts["bar_pill"],
            fill=bar_fill,
            trailing_gap=trail,
        )
    if stats:
        stats_y0 = (
            module_y0 + bar_block_h + HERO_LAUNCH_DATA_MODULE_INNER_GAP
            if bar_block_h
            else module_y0
        )
        stats_y1 = module_y0 + max(module_h, 1) - HERO_LAUNCH_DATA_MODULE_PAD_BOTTOM
        stats_draw_h = max(120, stats_y1 - stats_y0)
        stats_box = (0, stats_y0, CANVAS_W, stats_y0 + stats_draw_h)
        _draw_hero_monument_stats(
            base,
            y=stats_y0,
            height=stats_draw_h,
            pairs=stats,
            fonts=fonts,
            text_c=text_c,
            primary=vivid_p,
            secondary=vivid_s,
            cx=panel_cx,
            kv_ai_overlay=True,
            stage_box=stats_box,
            theme=theme,
        )
    return y + strip_h


def _measure_hero_block_height(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    y_top: int,
    main_title: str,
    tagline: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
    design: dict | None = None,
    platform_logos: Path | None = None,
    ai_strip_h: int = 0,
    stat_groups: list | None = None,
) -> int:
    font_title = fonts["title"]
    font_tag = fonts["tag"]
    font_bar = fonts["bar"]

    tb = draw.textbbox((cx, y_top), main_title, font=font_title, anchor="mt")
    y = tb[3] + HERO_TAGLINE_GAP
    if tagline.strip():
        y = draw.textbbox((cx, y), tagline, font=font_tag, anchor="mt")[3]
    if platform_logos and platform_logos.is_file():
        y += HERO_PLATFORM_LOGO_GAP + _platform_logos_display_height(platform_logos)
    if _hero_has_lower_block(bar_text, stats, stat_groups=stat_groups):
        y += HERO_UPPER_TO_LOWER_GAP + HERO_DATA_BLOCK_SHIFT_Y
        if stat_groups:
            y += _measure_multi_group_data_height(stat_groups, fonts, design) + HERO_LOWER_BLOCK_PAD_TOP + HERO_LOWER_BLOCK_PAD_BOTTOM
        else:
            y += _measure_hero_lower_block_inner_height(
                draw,
                bar_text=bar_text,
                stats=stats,
                fonts=fonts,
                design=design,
                ai_strip_h=ai_strip_h,
            )
    return y - y_top


def _hero_text_y_start(kv_height: int, block_h: int) -> int:
    """文案顶边：固定在 KV 主体安全线以下；块过高时向下扩画布，不把字顶上移压主体。"""
    del block_h
    return int(kv_height * HERO_KV_SUBJECT_BOTTOM_RATIO) + HERO_GAP_AFTER_SUBJECT


def _draw_launch_pre_band(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    y: int,
    width: int,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
) -> int:
    """首发条上方装饰：双短线 + 中间菱形，与 KV 主体拉开层次。"""
    half = min(width // 2 - 40, 280)
    line_y = y + 6
    draw.line([(cx - half, line_y), (cx - 48, line_y)], fill=secondary, width=2)
    draw.line([(cx + 48, line_y), (cx + half, line_y)], fill=secondary, width=2)
    draw.polygon(
        [(cx, y), (cx + 8, line_y + 8), (cx, line_y + 16), (cx - 8, line_y + 8)],
        fill=primary,
    )
    return y + HERO_LAUNCH_PRE_GAP


def _draw_title_with_depth(
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    text: str,
    font,
    fill: tuple[int, int, int],
) -> None:
    shadow = _darken(fill, 0.55)
    for dx, dy in ((0, 3), (2, 3), (-2, 3)):
        draw.text((cx + dx, y + dy), text, font=font, fill=shadow, anchor="mt")
    draw.text((cx, y), text, font=font, fill=fill, anchor="mt")


def _draw_launch_banner(
    base: Image.Image,
    *,
    cx: int,
    y: int,
    text: str,
    font,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    text_c: tuple[int, int, int],
    max_w: int,
    bar_x0: int | None = None,
    bar_x1: int | None = None,
) -> int:
    """首发条：双层斜切带 + 翼形箭头 + 内高光，返回底边 y。"""
    bar_h = _launch_bar_height(font)
    if bar_x0 is not None and bar_x1 is not None:
        bx0, bx1 = bar_x0, bar_x1
    else:
        pad_x = HERO_BAR_PAD_X
        tw = min(_text_width(text, font) + pad_x * 2, max_w)
        bx0, bx1 = cx - tw // 2, cx + tw // 2
    by1 = y + bar_h
    skew = 16
    wing = 22

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    shadow_c = (*_darken(primary, 0.55), 210)
    main_c = (*primary, 255)
    inner_c = (*_lighten(primary, 0.18), 255)
    wing_c = (*secondary, 255)
    hi_c = (*_lighten(primary, 0.42), 230)

    ld.polygon(
        [(bx0 + 5, y + 6), (bx1 + 5, y + 6), (bx1 + 5, by1 + 6), (bx0 + skew + 5, by1 + 6)],
        fill=shadow_c,
    )
    ld.polygon(
        [(bx0 + skew, y), (bx1, y), (bx1 - skew, by1), (bx0, by1)],
        fill=main_c,
    )
    inset = 6
    ld.polygon(
        [
            (bx0 + skew + inset, y + inset),
            (bx1 - inset, y + inset),
            (bx1 - skew - inset, by1 - inset),
            (bx0 + inset, by1 - inset),
        ],
        fill=inner_c,
    )
    ld.polygon([(bx0 - wing, y + bar_h // 2), (bx0, y + 2), (bx0, by1 - 2)], fill=wing_c)
    ld.polygon([(bx1 + wing, y + bar_h // 2), (bx1, y + 2), (bx1, by1 - 2)], fill=wing_c)
    ld.line([(bx0 + skew + 14, y + 4), (bx1 - 14, y + 4)], fill=hi_c, width=3)
    ld.line([(bx0 + 10, by1 - 5), (bx1 - skew - 10, by1 - 5)], fill=(*_darken(primary, 0.3), 180), width=2)

    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))

    draw = ImageDraw.Draw(base)
    stroke = _darken(text_c, 0.45)
    ty = y + bar_h // 2
    for dx, dy in ((0, 2), (2, 2), (-2, 2)):
        draw.text((cx + dx, ty + dy), text, font=font, fill=stroke, anchor="mm")
    draw.text((cx, ty), text, font=font, fill=text_c, anchor="mm")
    return by1


def _draw_diagonal_hatch(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    *,
    step: int = 10,
) -> None:
    x0, y0, x1, y1 = box
    for t in range(x0 - (y1 - y0), x1 + (y1 - y0), step):
        ld.line([(t, y1), (t + (y1 - y0), y0)], fill=(*color, 70), width=2)


def _draw_sparkle(ld: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int], size: int = 8) -> None:
    ld.line([(cx - size, cy), (cx + size, cy)], fill=(*color, 220), width=2)
    ld.line([(cx, cy - size), (cx, cy + size)], fill=(*color, 220), width=2)


def _draw_hero_data_report(
    base: Image.Image,
    *,
    y: int,
    pairs: list[tuple[str, str]],
    fonts: dict,
    design: dict,
    theme: dict,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    card_dark: tuple[int, int, int],
    text_c: tuple[int, int, int],
    stroke_c: tuple[int, int, int],
    hero_character: Path | None = None,
) -> int:
    """核心数据区：粉顶条 + 标题框 + 左数据右角色（对齐参考图）。"""
    panel_w = int(design.get("panel_width", HERO_DATA_PANEL_W))
    panel_h = int(design.get("panel_height", HERO_DATA_PANEL_H))
    panel_x0 = (CANVAS_W - panel_w) // 2
    panel_y1 = y + panel_h
    skew = 22
    ornament = design.get("ornament", "medium")
    use_glow = bool(design.get("glow", True))
    bg_page = _hex_rgb(theme["bg_page"])

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([panel_x0, y, panel_x0 + panel_w, y + 28], fill=(*primary, 255))
    ld.rectangle([panel_x0 + 12, y + 6, panel_x0 + 120, y + 22], fill=(*_darken(primary, 0.35), 200))
    fill_panel = (*_mix_rgb(card_dark, bg_page, 0.35), 245)
    ld.polygon(
        [
            (panel_x0 + skew, y),
            (panel_x0 + panel_w, y),
            (panel_x0 + panel_w - skew, panel_y1),
            (panel_x0, panel_y1),
        ],
        fill=fill_panel,
    )
    ld.line(
        [(panel_x0 + skew, y), (panel_x0 + panel_w, y)],
        fill=(*primary, 255),
        width=4,
    )
    ld.line(
        [(panel_x0, panel_y1), (panel_x0 + panel_w - skew, panel_y1)],
        fill=(*secondary, 200),
        width=2,
    )
    ld.rectangle(
        [panel_x0 + 8, y + 12, panel_x0 + 14, panel_y1 - 12],
        fill=(*primary, 255),
    )
    if use_glow:
        ld.line(
            [(panel_x0 + skew + 20, y + 8), (panel_x0 + panel_w - 24, y + 8)],
            fill=(*_lighten(primary, 0.35), 140),
            width=2,
        )
    if ornament in ("medium", "high"):
        corner = 18
        c = (*secondary, 220)
        ld.line([(panel_x0 + skew, y), (panel_x0 + skew + corner, y)], fill=c, width=2)
        ld.line([(panel_x0 + skew, y), (panel_x0 + skew, y + corner)], fill=c, width=2)
        ld.line([(panel_x0 + panel_w, y), (panel_x0 + panel_w - corner, y)], fill=c, width=2)
        ld.line([(panel_x0 + panel_w, y), (panel_x0 + panel_w, y + corner)], fill=c, width=2)
    if ornament == "high":
        for ox in (panel_x0 + panel_w - 80, panel_x0 + panel_w - 40):
            ld.line([(ox, y + 16), (ox + 10, y + 16)], fill=(*stroke_c[:3], 180), width=1)

    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))

    title_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tld = ImageDraw.Draw(title_layer)
    title_box = (panel_x0 + 20, y + 40, panel_x0 + int(panel_w * 0.55), y + 96)
    tld.rectangle(title_box, fill=(*_darken(card_dark, 0.2), 250), outline=(*primary, 255), width=3)
    _draw_diagonal_hatch(tld, (title_box[0], title_box[1], title_box[0] + 28, title_box[3]), secondary)
    _draw_diagonal_hatch(tld, (title_box[2] - 28, title_box[1], title_box[2], title_box[3]), secondary)
    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, title_layer)
    base.paste(base_rgba.convert("RGB"))

    draw = ImageDraw.Draw(base)
    title = str(design.get("panel_title", "核心数据"))
    title_x = panel_x0 + HERO_DATA_INNER_PAD + 12
    draw.text((title_x, y + 54), title, font=fonts["panel_title"], fill=text_c, anchor="lt")
    if ornament in ("medium", "high"):
        for sx, sy in ((panel_x0 + 24, y + 118), (panel_x0 + 52, y + 138)):
            _draw_sparkle(draw, sx, sy, secondary, 6)

    data_left = panel_x0 + HERO_DATA_INNER_PAD
    data_right_limit = panel_x0 + int(panel_w * 0.58)
    col_w = max(200, (data_right_limit - data_left - HERO_DATA_STAT_GAP) // max(1, len(pairs)))
    stat_y = y + 108
    for i, (label, value) in enumerate(pairs):
        lx = data_left + i * (col_w + HERO_DATA_STAT_GAP)
        draw.text((lx, stat_y), label, font=fonts["stat_label"], fill=text_c, anchor="lt")
        for dx, dy in ((2, 0), (0, 2)):
            draw.text((lx + dx, stat_y + 40 + dy), value, font=fonts["stat_value"], fill=_darken(primary, 0.5), anchor="lt")
        draw.text((lx, stat_y + 40), value, font=fonts["stat_value"], fill=primary, anchor="lt")
        if i < len(pairs) - 1:
            sep_x = lx + col_w + HERO_DATA_STAT_GAP // 2
            draw.line(
                [(sep_x, stat_y), (sep_x, panel_y1 - 28)],
                fill=(*_mix_rgb(secondary, text_c, 0.5), 90),
                width=2,
            )

    if hero_character and hero_character.is_file():
        char_box = (
            panel_x0 + int(panel_w * 0.52),
            y + 8,
            panel_x0 + panel_w - 8,
            panel_y1 - 8,
        )
        try:
            _paste_contain_in_box(base, Image.open(hero_character), char_box)
        except OSError:
            pass

    return panel_y1


# 模板图内内容区（1080 宽缩放后近似）；其内再绘统一游戏风面板
TEMPLATE_CONTENT_BOX = (40, 130, 1040, 590)

# 内容面板：外框细边距；格内四边等距留空后 contain（164430 版）
PANEL_OUTER_PAD = 8
PANEL_CELL_GAP = 6
PANEL_SLOT_PAD = 12
PANEL_RADIUS = 18
PANEL_BORDER_W = 2
SECTION_PAD_X = 40
SECTION_BANNER_MAX_H = 280
SECTION_BANNER_CHAR_RATIO = 2 / 5
SECTION_BANNER_TEXT_RATIO = 3 / 5
SECTION_BANNER_CHAR_OVERFLOW_TOP = 60
SECTION_BANNER_CHAR_W = 464
SECTION_BANNER_CHAR_H = 376
SECTION_BANNER_CHAR_ZONE_W = int(CANVAS_W * SECTION_BANNER_CHAR_RATIO)
SECTION_BANNER_TEXT_ZONE_W = int(CANVAS_W * SECTION_BANNER_TEXT_RATIO)
SECTION_BANNER_EDGE_PAD = 22
SECTION_BANNER_TITLE_SIZE = 88
SECTION_BANNER_BAND_INSET_Y = 0
SECTION_BANNER_TEXT_CHAR_GAP = 8
SECTION_BANNER_DIAGONAL_SKEW = 52
SECTION_BANNER_TITLE_SKEW = 20
SECTION_BANNER_TOP_TAPE_H = 10
HERO_DATA_PLATE_SKEW = 28
HERO_LAUNCH_SKEW = 14
TALL_SCREENSHOT_RATIO = 1.12
CONTENT_ROW_H_MIN = 200
CONTENT_ROW_H_MAX = 2000
# 核心资源矩阵：04 满宽；05+06+07 三列（与 01+02 同缝、左右贴齐、等比缩放）
ONE_THREE_MAIN_RATIO = 0.62
def _content_outer_width() -> int:
    return CANVAS_W - 2 * SECTION_PAD_X


def _content_inner_width() -> int:
    return _content_outer_width() - 2 * PANEL_OUTER_PAD


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 8:
        h = h[:6]
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def fit_width(img: Image.Image, width: int = CANVAS_W) -> Image.Image:
    if img.width == width:
        return img.convert("RGB")
    ratio = width / img.width
    h = max(1, int(img.height * ratio))
    return img.convert("RGB").resize((width, h), Image.Resampling.LANCZOS)


def _scale_image_to_width(img: Image.Image, width: int) -> Image.Image:
    """等比缩放到指定宽，不裁切；高度随原图比例。"""
    if img.width <= 0:
        return img.convert("RGBA")
    if img.width == width:
        return img.convert("RGBA")
    ratio = width / img.width
    h = max(1, int(img.height * ratio))
    return img.convert("RGBA").resize((width, h), Image.Resampling.LANCZOS)


def _image_height_at_width(path: Path, width: int) -> int:
    with Image.open(path) as im:
        return max(1, int(im.height * width / max(1, im.width)))


def _stacked_screenshots_height(paths: list[Path], inner_w: int, gap: int) -> int:
    if not paths:
        return 0
    total = 0
    for i, p in enumerate(paths):
        total += _row_height_for_paths([p], inner_w, gap)
        if i < len(paths) - 1:
            total += gap
    return total


def _row_slot_layout(inner_w: int, ncol: int, gap: int) -> list[tuple[int, int]]:
    """一行内槽贴齐内容区：|slot|gap|slot|；返回 (x 偏移, slot 宽)。"""
    if ncol <= 0:
        return []
    if ncol == 1:
        return [(0, inner_w)]
    slot_w = max(1, (inner_w - gap * (ncol - 1)) // ncol)
    slots: list[tuple[int, int]] = []
    x = 0
    for i in range(ncol):
        slots.append((x, slot_w))
        if i < ncol - 1:
            x += slot_w + gap
    return slots


def _row_slot_layout_for_paths(
    inner_w: int, paths: list[Path], gap: int,
) -> list[tuple[int, int]]:
    """并排双列：左右槽等宽（全板块与核心资源矩阵一致）。"""
    if len(paths) == 2:
        avail = max(2, inner_w - gap)
        w = max(1, avail // 2)
        return [(0, w), (w + gap, avail - w)]
    return _row_slot_layout(inner_w, len(paths), gap)


def _matrix_cell_inner_w(col_w: int) -> int:
    return max(1, col_w - 2 * PANEL_SLOT_PAD)


def _slot_inner_size(slot_w: int, slot_h: int, pad: int = PANEL_SLOT_PAD) -> tuple[int, int]:
    return max(1, slot_w - 2 * pad), max(1, slot_h - 2 * pad)


def _screenshot_aspect(path: Path) -> float:
    with Image.open(path) as im:
        w, h = max(1, im.width), max(1, im.height)
        return h / w


def _is_tall_screenshot(path: Path) -> bool:
    return _screenshot_aspect(path) >= TALL_SCREENSHOT_RATIO


def _file_numeric_index(path: Path) -> int | None:
    m = re.match(r"^0?(\d+)", path.stem.lower())
    return int(m.group(1)) if m else None


def _is_numbered_content_screenshot(path: Path) -> bool:
    """运营编号截图：01、02、1、04…；此类槽内 contain，不 cover 裁边。"""
    return _file_numeric_index(path) is not None


def _forces_full_width_row(path: Path) -> bool:
    """03、04、08 各占满宽一行（05–07 走三列并排）。"""
    return _file_numeric_index(path) in (3, 4, 8)


def _one_three_column_widths(inner_w: int, gap: int) -> tuple[int, int]:
    main_w = max(1, int((inner_w - gap) * ONE_THREE_MAIN_RATIO))
    side_w = max(1, inner_w - gap - main_w)
    return main_w, side_w


def _is_mail_screenshot(path: Path) -> bool:
    s = path.stem.lower()
    return "邮件" in path.stem or "mail" in s or "email" in s


def _is_activity_screenshot(path: Path) -> bool:
    s = path.stem.lower()
    return "活动" in path.stem or "activity" in s or s.startswith("活动")


def _resolve_mail_activity_stack(paths: list[Path]) -> list[Path] | None:
    """邮件 + 活动并排：左邮件右活动，行内统一高度、等比缩放不裁切。"""
    if len(paths) != 2:
        return None
    mails = [p for p in paths if _is_mail_screenshot(p)]
    acts = [p for p in paths if _is_activity_screenshot(p)]
    if len(mails) == 1 and len(acts) == 1:
        return [mails[0], acts[0]]
    return None


def _paths_by_numeric_index(paths: list[Path]) -> dict[int, Path]:
    by_idx: dict[int, Path] = {}
    for p in paths:
        idx = _file_numeric_index(p)
        if idx is not None:
            by_idx[idx] = p
    return by_idx


def _build_mail_activity_only_plan(paths: list[Path]) -> list[tuple[str, list[Path]]] | None:
    """联动活动区：仅邮件+活动两张时强制并排。"""
    if len(paths) != 2:
        return None
    ordered = _resolve_mail_activity_stack(paths)
    if ordered:
        return [("mail_activity", ordered)]
    return None


def _build_matrix_numbered_flow_plan(paths: list[Path]) -> list[tuple[str, list[Path]]] | None:
    """核心资源矩阵：01+02 → 03 满宽 → 04 满宽 → 05+06+07 三列 → 08 满宽。"""
    by_idx = _paths_by_numeric_index(paths)
    if not {1, 2, 3, 4, 5, 6, 7, 8}.issubset(by_idx.keys()):
        return None
    plan: list[tuple[str, list[Path]]] = [
        ("pair", [by_idx[1], by_idx[2]]),
        ("full", [by_idx[3]]),
        ("full", [by_idx[4]]),
        ("triple", [by_idx[5], by_idx[6], by_idx[7]]),
        ("full", [by_idx[8]]),
    ]
    used = {by_idx[i] for i in range(1, 9)}
    for p in paths:
        if p not in used:
            plan.append(("full", [p]))
    return plan


def _build_flow_plan(paths: list[Path]) -> list[tuple[str, list[Path]]]:
    """flow 排版计划：pair | full | triple | one_two | mail_activity。"""
    mail_plan = _build_mail_activity_only_plan(paths)
    if mail_plan is not None:
        return mail_plan
    matrix_plan = _build_matrix_numbered_flow_plan(paths)
    if matrix_plan is not None:
        return matrix_plan

    plan: list[tuple[str, list[Path]]] = []
    i = 0
    n = len(paths)
    while i < n:
        idx = _file_numeric_index(paths[i])
        if (
            idx == 1
            and i + 1 < n
            and _file_numeric_index(paths[i + 1]) == 2
        ):
            plan.append(("pair", [paths[i], paths[i + 1]]))
            i += 2
            continue
        if idx in (3, 4):
            plan.append(("full", [paths[i]]))
            i += 1
            continue
        if (
            idx == 5
            and i + 2 < n
            and _file_numeric_index(paths[i + 1]) == 6
            and _file_numeric_index(paths[i + 2]) == 7
        ):
            plan.append(("triple", paths[i : i + 3]))
            i += 3
            continue
        if idx == 8:
            plan.append(("full", [paths[i]]))
            i += 1
            continue
        p = paths[i]
        if _forces_full_width_row(p):
            plan.append(("full", [p]))
            i += 1
            continue
        if i + 1 < n:
            mail_act = _resolve_mail_activity_stack([paths[i], paths[i + 1]])
            if mail_act:
                plan.append(("mail_activity", mail_act))
                i += 2
                continue
        if (
            i + 1 < n
            and not _forces_full_width_row(paths[i + 1])
            and _is_tall_screenshot(p)
            and _is_tall_screenshot(paths[i + 1])
        ):
            plan.append(("pair", [p, paths[i + 1]]))
            i += 2
            continue
        plan.append(("full", [p]))
        i += 1
    return plan


def _build_flow_rows(paths: list[Path]) -> list[list[Path]]:
    return [row for _, row in _build_flow_plan(paths)]


def _unified_dual_row(paths: list[Path]) -> bool:
    """并排双列（邮件+活动、01+02 等）：槽宽铺满 + 行内统一高度。"""
    return len(paths) == 2


def _image_width_at_height(path: Path, height: int) -> int:
    with Image.open(path) as im:
        sw, sh = max(1, im.width), max(1, im.height)
    return max(1, int(sw * height / sh))


def _flow_row_edge_pad() -> int:
    """与满宽单行一致：无游戏外框时不内缩，三列左右才能顶到内容区边。"""
    return PANEL_SLOT_PAD if _content_use_game_frame() else 0


def _flow_aligned_row_metrics(
    paths: list[Path], inner_w: int, gap: int,
) -> tuple[int, int, list[int]]:
    """
    Flow 行（满宽单图 / 双列 / 三列）：列缝 = PANEL_CELL_GAP；
    整体等比缩放至撑满内容区宽度；左图贴左缘、右图贴右缘，不裁切。
    """
    ncol = len(paths)
    pad = _flow_row_edge_pad()
    content_w = max(1, inner_w - 2 * pad)
    if ncol < 1:
        return 1, CONTENT_ROW_H_MIN, []
    if ncol == 1:
        uh = max(1, _image_height_at_width(paths[0], content_w))
        row_h = uh + 2 * pad
        return uh, int(max(CONTENT_ROW_H_MIN, min(CONTENT_ROW_H_MAX, row_h))), [content_w]

    layout = (
        _row_slot_layout_for_paths(inner_w, paths, gap)
        if ncol == 2
        else _row_slot_layout(inner_w, ncol, gap)
    )
    uh = 1
    for p, (_, slot_w) in zip(paths, layout):
        iw = _matrix_cell_inner_w(slot_w)
        uh = max(uh, _image_height_at_width(p, iw))
    nws = [_image_width_at_height(p, uh) for p in paths]
    total = sum(nws) + gap * (ncol - 1)
    if total > 0:
        uh = max(1, int(round(uh * content_w / total)))
        nws = [_image_width_at_height(p, uh) for p in paths]
        drift = content_w - (sum(nws) + gap * (ncol - 1))
        if drift and ncol >= 2:
            nws[-1] = max(1, nws[-1] + drift)
    row_h = uh + 2 * pad
    return uh, int(max(CONTENT_ROW_H_MIN, min(CONTENT_ROW_H_MAX, row_h))), nws


def _flow_aligned_row_x_positions(
    x0: int, inner_w: int, nws: list[int], gap: int,
) -> list[int]:
    """左图顶左、右图顶右，中间按列缝衔接（05+06+07 与 04 满宽行同宽）。"""
    pad = _flow_row_edge_pad()
    ncol = len(nws)
    if ncol == 1:
        return [x0 + pad]
    if ncol == 2:
        return [x0 + pad, x0 + inner_w - pad - nws[1]]
    return [x0 + pad, x0 + pad + nws[0] + gap, x0 + inner_w - pad - nws[2]]


def _paste_flow_aligned_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    if not paths:
        return y
    uh, row_h, nws = _flow_aligned_row_metrics(paths, inner_w, gap)
    draw_slot_bg = _content_use_game_frame()
    pad = _flow_row_edge_pad()
    if draw_slot_bg:
        ImageDraw.Draw(base).rectangle(
            (x0, y, x0 + inner_w, y + row_h), fill=slot_fill,
        )
    y_img = y + pad
    for path, px, nw in zip(
        paths, _flow_aligned_row_x_positions(x0, inner_w, nws, gap), nws,
    ):
        with Image.open(path) as im:
            src = im.convert("RGBA")
            sw, sh = max(1, src.width), max(1, src.height)
            nw = max(1, int(sw * uh / sh))
            resized = src.resize((nw, uh), Image.Resampling.LANCZOS)
            if resized.mode == "RGBA":
                base.paste(resized.convert("RGB"), (px, y_img), resized.split()[3])
            else:
                base.paste(resized.convert("RGB"), (px, y_img))
    return y + row_h


def _pair_row_layout_metrics(
    paths: list[Path], inner_w: int, gap: int,
) -> tuple[int, int, int, int]:
    uh, row_h, nws = _flow_aligned_row_metrics(paths, inner_w, gap)
    if len(nws) < 2:
        return uh, row_h, nws[0] if nws else 1, 1
    return uh, row_h, nws[0], nws[1]


def _measure_flow_pair_row(paths: list[Path], inner_w: int, gap: int) -> int:
    return _flow_aligned_row_metrics(paths, inner_w, gap)[1]


def _paste_flow_pair_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    return _paste_flow_aligned_row(
        base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
    )


def _row_height_for_paths(
    paths: list[Path],
    inner_w: int,
    gap: int,
    *,
    unify: str = "max",
) -> int:
    """单行槽框高度：max=按较高图；shorter=按较短图（邮件+活动并排）。"""
    if not paths:
        return CONTENT_ROW_H_MIN
    layout = _row_slot_layout_for_paths(inner_w, paths, gap)
    inner_heights: list[int] = []
    for p, (_, slot_w) in zip(paths, layout):
        iw, _ = _slot_inner_size(slot_w, 9999)
        inner_heights.append(_image_height_at_width(p, iw))
    if unify == "shorter" and len(inner_heights) >= 2:
        inner_h = min(inner_heights)
    else:
        inner_h = max(inner_heights) if inner_heights else 1
    row_h = inner_h + 2 * PANEL_SLOT_PAD
    return int(max(CONTENT_ROW_H_MIN, min(CONTENT_ROW_H_MAX, row_h)))


def _scale_image_contain_box(img: Image.Image, tw: int, th: int) -> Image.Image:
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    out.paste(resized, ((tw - nw) // 2, (th - nh) // 2), resized)
    return out


def _paste_screenshot_contain_top_left(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """槽内完整展示：等比缩放至槽内（contain），顶左对齐，不裁切。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if resized.mode == "RGBA":
        base.paste(resized.convert("RGB"), (x0, y0), resized.split()[3])
    else:
        base.paste(resized, (x0, y0))


def _paste_screenshot_proportional_fill(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    valign: str = "top",
) -> None:
    """等比缩放撑满槽（宽或高至少一边贴边），不拉伸；valign 控制顶/底/中对齐。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = tw / sw
    nh = sh * scale
    if nh > th:
        scale = th / sh
        nw, nh = max(1, int(sw * scale)), th
    else:
        nw, nh = tw, max(1, int(nh))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    px = x0 + max(0, (tw - nw) // 2)
    if valign == "bottom":
        py = y1 - nh
    elif valign == "center":
        py = y0 + max(0, (th - nh) // 2)
    else:
        py = y0
    if resized.mode == "RGBA":
        base.paste(resized.convert("RGB"), (px, py), resized.split()[3])
    else:
        base.paste(resized, (px, py))


def _paste_screenshot_cover_fill(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """等比放大至槽内顶/底/左右均贴边（超出居中裁切），不变形。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = max(tw / sw, th / sh)
    nw, nh = max(tw, int(sw * scale)), max(th, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    cx = max(0, (nw - tw) // 2)
    cy = max(0, (nh - th) // 2)
    cropped = resized.crop((cx, cy, cx + tw, cy + th))
    if cropped.mode == "RGBA":
        base.paste(cropped.convert("RGB"), (x0, y0), cropped.split()[3])
    else:
        base.paste(cropped.convert("RGB"), (x0, y0))


def _paste_screenshot_contain_center(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """槽内 contain 完整展示，水平垂直居中，不裁切。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    px = x0 + (tw - nw) // 2
    py = y0 + (th - nh) // 2
    if resized.mode == "RGBA":
        base.paste(resized.convert("RGB"), (px, py), resized.split()[3])
    else:
        base.paste(resized, (px, py))


def _paste_screenshot_width_unified_height(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    valign: str = "top",
) -> None:
    """并排双列：铺满槽宽；行高统一时超高图等比缩入槽内，顶/底对齐，不裁切。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    nh_at_w = max(1, int(sh * tw / sw))
    if nh_at_w > th:
        scale = th / sh
        nw, nh = max(1, int(sw * scale)), th
        px = x0 + max(0, (tw - nw) // 2)
    else:
        nw, nh = tw, nh_at_w
        px = x0
    if valign == "bottom":
        py = y0 + max(0, th - nh)
    elif valign == "center":
        py = y0 + max(0, (th - nh) // 2)
    else:
        py = y0
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if resized.mode == "RGBA":
        base.paste(resized.convert("RGB"), (px, py), resized.split()[3])
    else:
        base.paste(resized, (px, py))


def _paste_screenshot_slot(
    base: Image.Image,
    *,
    x: int,
    y: int,
    slot_w: int,
    slot_h: int,
    path: Path,
    slot_fill: tuple[int, int, int],
    width_fill: bool = True,
    dual_unified: bool = False,
    contain_center: bool = False,
    valign: str = "top",
    draw_slot_bg: bool = True,
) -> None:
    """内容截图：等比完整展示不裁切；并排双列时槽宽铺满且行内统一高度。"""
    del width_fill
    pad = PANEL_SLOT_PAD if draw_slot_bg else 0
    if draw_slot_bg:
        ImageDraw.Draw(base).rectangle((x, y, x + slot_w, y + slot_h), fill=slot_fill)
    inner = (x + pad, y + pad, x + slot_w - pad, y + slot_h - pad)
    img = Image.open(path)
    if dual_unified:
        _paste_screenshot_width_unified_height(base, img, inner, valign=valign)
    elif contain_center:
        _paste_screenshot_contain_center(base, img, inner)
    else:
        _paste_screenshot_contain_top_left(base, img, inner)


def _paste_screenshot_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
    row_unify: str = "max",
) -> int:
    """贴一整行：等宽槽；并排双列时统一行高、槽内 contain 完整展示。"""
    if not paths:
        return y
    layout = _row_slot_layout_for_paths(inner_w, paths, gap)
    row_h = _row_height_for_paths(paths, inner_w, gap, unify=row_unify)
    dual_row = _unified_dual_row(paths)
    draw_slot_bg = _content_use_game_frame()
    for p, (ox, slot_w) in zip(paths, layout):
        _paste_screenshot_slot(
            base,
            x=x0 + ox,
            y=y,
            slot_w=slot_w,
            slot_h=row_h,
            path=p,
            slot_fill=slot_fill,
            width_fill=True,
            dual_unified=False,
            contain_center=dual_row,
            valign="top",
            draw_slot_bg=draw_slot_bg,
        )
    return y + row_h


def _prefer_side_by_side(paths: list[Path]) -> bool:
    if len(paths) != 2:
        return False
    rows = _build_flow_rows(paths)
    return len(rows) == 1 and len(rows[0]) == 2


def _resolve_content_layout(n: int, layout: str, paths: list[Path] | None = None) -> str:
    """single / flow / row_pair / grid_2x2 / hero_1_4 / stack。"""
    paths = paths or []
    if n <= 0:
        return "single"
    if layout == "grid_2x2" and n >= 4:
        return "grid_2x2"
    if layout == "flow":
        return "flow"
    if layout == "row_pair" and n >= 2:
        return "row_pair"
    if layout == "single" or n == 1:
        return "single"
    if n == 5 and layout == "auto":
        return "hero_1_4"
    if layout == "stack":
        return "stack"
    if layout == "auto" and n == 2:
        return "flow"
    if n >= 2:
        return "flow"
    return "stack"


def _grid_2x2_outer_pad(gap: int) -> int:
    """2×2 拼图区四边留白，与格缝同宽（玩家真实好评等）。"""
    return gap


def _grid_2x2_cell_w(area_w: int, gap: int) -> int:
    return max(1, (area_w - gap) // 2)


def _measure_grid_2x2_height(paths: list[Path], inner_w: int, gap: int) -> int:
    """2×2：四格等宽，上下两行等高（矩阵对齐）。"""
    pad = _grid_2x2_outer_pad(gap)
    area_w = max(1, inner_w - 2 * pad)
    cell_w = _grid_2x2_cell_w(area_w, gap)
    iw = _matrix_cell_inner_w(cell_w)
    max_inner = 1
    for p in paths[:4]:
        max_inner = max(max_inner, _image_height_at_width(p, iw))
    row_h = max_inner + 2 * PANEL_SLOT_PAD
    return 2 * pad + row_h + gap + row_h


def _measure_hero_1_4_height(paths: list[Path], inner_w: int, gap: int) -> int:
    top = _row_height_for_paths([paths[0]], inner_w, gap)
    row0 = _row_height_for_paths(paths[1:3], inner_w, gap)
    row1 = _row_height_for_paths(paths[3:5], inner_w, gap)
    return top + gap + row0 + gap + row1


def _measure_row_pair_height(paths: list[Path], inner_w: int, gap: int) -> int:
    return _row_height_for_paths(paths[:2], inner_w, gap)


def _one_two_natural_heights(
    paths: list[Path], inner_w: int, gap: int,
) -> tuple[int, int, int]:
    """04/05/06 在各自槽宽下按宽铺满时的自然高度。"""
    main_w, side_w = _one_three_column_widths(inner_w, gap)
    iw_main = _matrix_cell_inner_w(main_w)
    iw_side = _matrix_cell_inner_w(side_w)
    return (
        _image_height_at_width(paths[0], iw_main),
        _image_height_at_width(paths[1], iw_side),
        _image_height_at_width(paths[2], iw_side),
    )


def _one_two_layout_metrics(
    paths: list[Path], inner_w: int, gap: int,
) -> tuple[int, int]:
    """
    04–06：左列高 = 05 高 + 缝 + 06 高；三图整体等比缩放，contain 不裁切。
    """
    if len(paths) != 3:
        return CONTENT_ROW_H_MIN, 1
    pad = PANEL_SLOT_PAD
    main_w, side_w = _one_three_column_widths(inner_w, gap)
    iw_main = max(1, main_w - 2 * pad)
    iw_side = max(1, side_w - 2 * pad)
    h5 = _image_height_at_width(paths[1], iw_side)
    h6 = _image_height_at_width(paths[2], iw_side)
    uh = max(1, h5, h6)
    row_inner = 2 * uh + gap

    nw4 = _image_width_at_height(paths[0], row_inner)
    nw5 = _image_width_at_height(paths[1], uh)
    nw6 = _image_width_at_height(paths[2], uh)
    fit = min(
        1.0,
        iw_main / max(1, nw4),
        iw_side / max(1, nw5),
        iw_side / max(1, nw6),
    )
    grow = min(
        iw_main / max(1, nw4),
        iw_side / max(1, nw5),
        iw_side / max(1, nw6),
    )
    scale = grow if grow > 1.0 else fit
    if abs(scale - 1.0) > 0.001:
        uh = max(1, int(uh * scale))
        row_inner = 2 * uh + gap
    return row_inner, uh


def _measure_one_two_row(paths: list[Path], inner_w: int, gap: int) -> int:
    """一拖二（通用 flow 回退）。"""
    if len(paths) != 3:
        return _row_height_for_paths(paths, inner_w, gap)
    row_inner, _ = _one_two_layout_metrics(paths, inner_w, gap)
    row_h = row_inner + 2 * PANEL_SLOT_PAD
    return int(max(CONTENT_ROW_H_MIN, min(CONTENT_ROW_H_MAX, row_h)))


def _measure_triple_row(paths: list[Path], inner_w: int, gap: int) -> int:
    return _flow_aligned_row_metrics(paths, inner_w, gap)[1]


def _measure_mail_activity_stack(paths: list[Path], inner_w: int, gap: int) -> int:
    """邮件+活动：与 01+02 相同并排规则（等高、满宽、不裁切）。"""
    ordered = _resolve_mail_activity_stack(paths) or paths[:2]
    if len(ordered) != 2:
        return _row_height_for_paths(ordered, inner_w, gap)
    return _measure_flow_pair_row(ordered, inner_w, gap)


def _measure_flow_row(kind: str, paths: list[Path], inner_w: int, gap: int) -> int:
    if kind == "one_two":
        return _measure_one_two_row(paths, inner_w, gap)
    if kind in ("full", "pair", "triple", "mail_activity"):
        if kind == "mail_activity":
            ordered = _resolve_mail_activity_stack(paths) or paths
            return _flow_aligned_row_metrics(ordered, inner_w, gap)[1]
        return _flow_aligned_row_metrics(paths, inner_w, gap)[1]
    return _row_height_for_paths(paths, inner_w, gap)


def _measure_flow_rows_height(paths: list[Path], inner_w: int, gap: int) -> int:
    plan = _build_flow_plan(paths)
    if not plan:
        return 0
    total = 0
    for i, (kind, row_paths) in enumerate(plan):
        total += _measure_flow_row(kind, row_paths, inner_w, gap)
        if i < len(plan) - 1:
            total += gap
    return total


def _measure_content_layout_height(paths: list[Path], inner_w: int, gap: int, layout_mode: str) -> int:
    if layout_mode == "flow":
        return _measure_flow_rows_height(paths, inner_w, gap)
    if layout_mode == "row_pair" and len(paths) >= 2:
        return _measure_row_pair_height(paths[:2], inner_w, gap)
    if layout_mode == "grid_2x2" and len(paths) >= 4:
        return _measure_grid_2x2_height(paths[:4], inner_w, gap)
    if layout_mode == "hero_1_4" and len(paths) >= 5:
        return _measure_hero_1_4_height(paths[:5], inner_w, gap)
    return _stacked_screenshots_height(paths, inner_w, gap)


def _paste_grid_2x2(
    base: Image.Image,
    inner: tuple[int, int, int, int],
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    """2×2：四格同宽同行高，与核心资源矩阵同一套矩阵规则。"""
    x0, y0, x1, y1 = inner
    pad = _grid_2x2_outer_pad(gap)
    ax0, ay0 = x0 + pad, y0 + pad
    area_w = max(1, (x1 - x0) - 2 * pad)
    cell_w = _grid_2x2_cell_w(area_w, gap)
    iw = _matrix_cell_inner_w(cell_w)
    max_inner = max(_image_height_at_width(p, iw) for p in paths[:4])
    row_h = max_inner + 2 * PANEL_SLOT_PAD
    slots = [
        (0, 0),
        (cell_w + gap, 0),
        (0, row_h + gap),
        (cell_w + gap, row_h + gap),
    ]
    for p, (ox, oy) in zip(paths[:4], slots):
        _paste_screenshot_slot(
            base,
            x=ax0 + ox,
            y=ay0 + oy,
            slot_w=cell_w,
            slot_h=row_h,
            path=p,
            slot_fill=slot_fill,
            width_fill=True,
        )
    return ay0 + 2 * row_h + gap + pad


def _paste_hero_1_4(
    base: Image.Image,
    inner: tuple[int, int, int, int],
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    x0, y0, _, _ = inner
    inner_w = inner[2] - inner[0]
    y = _paste_screenshot_row(
        base, x0=x0, y=y0, inner_w=inner_w, paths=[paths[0]], gap=gap, slot_fill=slot_fill,
    )
    y = _paste_screenshot_row(
        base, x0=x0, y=y + gap, inner_w=inner_w, paths=paths[1:3], gap=gap, slot_fill=slot_fill,
    )
    return _paste_screenshot_row(
        base, x0=x0, y=y + gap, inner_w=inner_w, paths=paths[3:5], gap=gap, slot_fill=slot_fill,
    )


def _paste_one_two_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    """一拖二：04 高=05+缝+06；三图等比缩放，左右缘与满宽行对齐，contain 不裁切。"""
    if len(paths) != 3:
        return _paste_screenshot_row(
            base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
        )
    main_w, side_w = _one_three_column_widths(inner_w, gap)
    row_inner, uh = _one_two_layout_metrics(paths, inner_w, gap)
    row_h = row_inner + 2 * PANEL_SLOT_PAD
    pad = PANEL_SLOT_PAD if _content_use_game_frame() else 0
    draw_slot_bg = _content_use_game_frame()
    if draw_slot_bg:
        ImageDraw.Draw(base).rectangle((x0, y, x0 + inner_w, y + row_h), fill=slot_fill)

    y_inner = y + pad
    left_box = (x0 + pad, y_inner, x0 + main_w - pad, y_inner + row_inner)
    side_x = x0 + main_w + gap
    top_box = (side_x + pad, y_inner, side_x + side_w - pad, y_inner + uh)
    bot_box = (
        side_x + pad,
        y_inner + uh + gap,
        side_x + side_w - pad,
        y_inner + row_inner,
    )

    with Image.open(paths[0]) as im:
        _paste_contain_in_box_align(
            base, im, left_box, h_align="center", v_align="center",
        )
    with Image.open(paths[1]) as im:
        _paste_contain_in_box_align(
            base, im, top_box, h_align="center", v_align="top",
        )
    with Image.open(paths[2]) as im:
        _paste_contain_in_box_align(
            base, im, bot_box, h_align="center", v_align="bottom",
        )
    return y + row_h


def _paste_mail_activity_stack(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    """邮件(左)+活动(右)：等高、整体等比缩放至满宽，与 01+02 同规则，不裁切。"""
    ordered = _resolve_mail_activity_stack(paths) or paths[:2]
    return _paste_flow_pair_row(
        base,
        x0=x0,
        y=y,
        inner_w=inner_w,
        paths=ordered,
        gap=gap,
        slot_fill=slot_fill,
    )


def _paste_triple_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    return _paste_flow_aligned_row(
        base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
    )


def _paste_flow_row(
    base: Image.Image,
    *,
    x0: int,
    y: int,
    inner_w: int,
    kind: str,
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    if kind == "one_two":
        return _paste_one_two_row(
            base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
        )
    if kind in ("full", "pair", "triple", "mail_activity"):
        if kind == "mail_activity":
            ordered = _resolve_mail_activity_stack(paths) or paths
            return _paste_flow_aligned_row(
                base, x0=x0, y=y, inner_w=inner_w, paths=ordered, gap=gap, slot_fill=slot_fill,
            )
        return _paste_flow_aligned_row(
            base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
        )
    return _paste_screenshot_row(
        base, x0=x0, y=y, inner_w=inner_w, paths=paths, gap=gap, slot_fill=slot_fill,
    )


def _paste_flow_rows(
    base: Image.Image,
    inner: tuple[int, int, int, int],
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    x0, y0, _, _ = inner
    inner_w = inner[2] - inner[0]
    y = y0
    plan = _build_flow_plan(paths)
    for ri, (kind, row_paths) in enumerate(plan):
        y = _paste_flow_row(
            base,
            x0=x0,
            y=y,
            inner_w=inner_w,
            kind=kind,
            paths=row_paths,
            gap=gap,
            slot_fill=slot_fill,
        )
        if ri < len(plan) - 1:
            y += gap
    return y


def _paste_stack_full_width(
    base: Image.Image,
    inner: tuple[int, int, int, int],
    paths: list[Path],
    gap: int,
    slot_fill: tuple[int, int, int],
) -> int:
    x0, y0, _, _ = inner
    inner_w = inner[2] - inner[0]
    y = y0
    for i, p in enumerate(paths):
        y = _paste_screenshot_row(
            base, x0=x0, y=y, inner_w=inner_w, paths=[p], gap=gap, slot_fill=slot_fill,
        )
        if i < len(paths) - 1:
            y += gap
    return y


def _paste_rgba_on_rgb(base: Image.Image, img: Image.Image, x: int, y: int) -> None:
    if img.mode == "RGBA":
        if base.mode == "RGBA":
            # RGBA→RGBA: alpha composite
            tmp = Image.new("RGBA", base.size, (0, 0, 0, 0))
            tmp.paste(img, (x, y))
            base_comp = Image.alpha_composite(base, tmp)
            base.paste(base_comp)
        else:
            base.paste(img.convert("RGB"), (x, y), img.split()[3])
    else:
        base.paste(img.convert("RGB"), (x, y))


def _text_width(text: str, font) -> int:
    """用字体 advance width，避免 textbbox 左右留白导致「看起来不居中」。"""
    try:
        return int(round(font.getlength(text)))
    except AttributeError:
        b = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
        return b[2] - b[0]


def _draw_text_centered(
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    text: str,
    font,
    fill: tuple[int, int, int],
    *,
    anchor: str = "mm",
) -> None:
    """以 cx 为水平中心绘制（无阴影偏移，避免视觉偏右）。"""
    draw.text((cx, y), text, font=font, fill=fill, anchor=anchor)


def _inset_box(
    box: tuple[int, int, int, int],
    pad_x: int,
    pad_y: int | None = None,
) -> tuple[int, int, int, int]:
    pad_y = pad_x if pad_y is None else pad_y
    x0, y0, x1, y1 = box
    return (x0 + pad_x, y0 + pad_y, x1 - pad_x, y1 - pad_y)


def _paste_cover_in_box(base: Image.Image, img: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGB")
    sw, sh = src.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    cropped = resized.crop((left, top, left + tw, top + th))
    base.paste(cropped, (x0, y0))


def _paste_hero_data_module_bg(
    base: Image.Image,
    nano_data_bg: Path,
    module_box: tuple[int, int, int, int],
    theme: dict,
) -> None:
    """首发条+数据一体模块：整块铺 Gemini 无字底图 + 轻蒙版（中间无分割线）。"""
    bg_page = _hex_rgb(theme["bg_page"])
    ImageDraw.Draw(base).rectangle(module_box, fill=bg_page)
    inner = _inset_box(module_box, HERO_DATA_BG_STAGE_INSET)
    with Image.open(nano_data_bg) as im:
        _paste_contain_in_box(base, im.convert("RGB"), inner)
    if HERO_NANO_DATA_VEIL_ALPHA > 0:
        veil = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(veil).rectangle(
            module_box, fill=(*bg_page, HERO_NANO_DATA_VEIL_ALPHA),
        )
        base_rgba = base.convert("RGBA")
        base_rgba = Image.alpha_composite(base_rgba, veil)
        base.paste(base_rgba.convert("RGB"))


def _paste_hero_data_stage_bg(
    base: Image.Image,
    nano_data_bg: Path,
    stage_box: tuple[int, int, int, int],
    theme: dict,
) -> None:
    """兼容：单块舞台底图（strip 叠字等）。"""
    _paste_hero_data_module_bg(base, nano_data_bg, stage_box, theme)


def _draw_hero_stat_value_scrim(
    base: Image.Image,
    stage_box: tuple[int, int, int, int],
    theme: dict,
) -> None:
    """盖住底图上 AI 误生成的金属数字区，再叠本地 data 字体。"""
    x0, y0, x1, y1 = stage_box
    w, h = x1 - x0, y1 - y0
    band = (
        x0 + int(w * 0.06),
        y0 + int(h * 0.22),
        x1 - int(w * 0.06),
        y1 - int(h * 0.08),
    )
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(
        band, fill=(*_hex_rgb(theme["bg_page"]), HERO_DATA_STAT_SCRIM_ALPHA),
    )
    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))


def _paste_contain_in_box(base: Image.Image, img: Image.Image, box: tuple[int, int, int, int]) -> None:
    _paste_contain_in_box_align(base, img, box, h_align="center", v_align="center")


def _paste_contain_in_box_align(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    h_align: str = "center",
    v_align: str = "center",
) -> None:
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if h_align == "left":
        px = x0
    elif h_align == "right":
        px = x1 - nw
    else:
        px = x0 + (tw - nw) // 2
    if v_align == "top":
        py = y0
    elif v_align == "bottom":
        py = y1 - nh
    else:
        py = y0 + (th - nh) // 2
    if resized.mode == "RGBA":
        base.paste(resized.convert("RGB"), (px, py), resized.split()[3])
    else:
        base.paste(resized, (px, py))


def _content_use_game_frame() -> bool:
    """默认内容截图不套游戏外框；设 BATTLE_REPORT_CONTENT_FRAME=1 可恢复。"""
    return os.environ.get("BATTLE_REPORT_CONTENT_FRAME", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _inset_box(box: tuple[int, int, int, int], pad: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return x0 + pad, y0 + pad, x1 - pad, y1 - pad


def _draw_unified_game_panel(
    base: Image.Image,
    outer_box: tuple[int, int, int, int],
    theme: dict,
    *,
    accent: str = "accent_secondary",
) -> tuple[int, int, int, int]:
    """内容区外框：暗底 + KV 亮色描边 + 顶角装饰。"""
    vivid_p, vivid_s = _theme_vivid_pair(theme)
    if accent == "accent_primary":
        primary, secondary = vivid_p, vivid_s
    else:
        primary, secondary = vivid_s, vivid_p
    dark = _hex_rgb(theme["bg_card_dark"])
    x0, y0, x1, y1 = outer_box

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle(outer_box, radius=PANEL_RADIUS, fill=(*dark, 238))
    ld.rounded_rectangle(outer_box, radius=PANEL_RADIUS, outline=(*secondary, 245), width=PANEL_BORDER_W)
    ld.line([(x0 + 18, y0 + 2), (x1 - 18, y0 + 2)], fill=(*primary, 230), width=3)
    c = 14
    ld.line([(x0 + 8, y0 + 8), (x0 + 8 + c, y0 + 8)], fill=(*primary, 255), width=2)
    ld.line([(x0 + 8, y0 + 8), (x0 + 8, y0 + 8 + c)], fill=(*primary, 255), width=2)
    ld.line([(x1 - 8, y0 + 8), (x1 - 8 - c, y0 + 8)], fill=(*secondary, 255), width=2)
    ld.line([(x1 - 8, y0 + 8), (x1 - 8, y0 + 8 + c)], fill=(*secondary, 255), width=2)
    base_rgba = base.convert("RGBA")
    base_rgba = Image.alpha_composite(base_rgba, layer)
    base.paste(base_rgba.convert("RGB"))
    return _inset_box(outer_box, PANEL_OUTER_PAD)


def _paste_in_cell(
    base: Image.Image,
    img: Image.Image,
    cell: tuple[int, int, int, int],
    *,
    mode: str = "contain",
) -> None:
    if mode == "cover":
        _paste_cover_in_box(base, img, cell)
    else:
        _paste_contain_in_box(base, img, cell)


def _layout_cells_uniform(
    inner: tuple[int, int, int, int],
    n: int,
    gap: int,
) -> list[tuple[tuple[int, int, int, int], str]]:
    """等间距划分格子；(box, 'cover'|'contain')。"""
    x0, y0, x1, y1 = inner
    w, h = x1 - x0, y1 - y0
    if n <= 0:
        return []
    if n == 1:
        return [(inner, "contain")]

    if n == 2:
        ch = (h - gap) // 2
        return [
            ((x0, y0, x1, y0 + ch), "contain"),
            ((x0, y0 + ch + gap, x1, y1), "contain"),
        ]

    if n == 3:
        ch = (h - 2 * gap) // 3
        return [
            ((x0, y0 + i * (ch + gap), x1, y0 + i * (ch + gap) + ch), "contain")
            for i in range(3)
        ]

    if n == 4:
        col_w = (w - gap) // 2
        row_h = (h - gap) // 2
        return [
            ((x0, y0, x0 + col_w, y0 + row_h), "contain"),
            ((x0 + col_w + gap, y0, x1, y0 + row_h), "contain"),
            ((x0, y0 + row_h + gap, x0 + col_w, y1), "contain"),
            ((x0 + col_w + gap, y0 + row_h + gap, x1, y1), "contain"),
        ]

    # n >= 5：上 1 格 cover + 下 2×2 contain
    top_h = (h - gap) * 2 // 5
    bot_y = y0 + top_h + gap
    top_box = (x0, y0, x1, y0 + top_h)
    cell_w = (w - gap) // 2
    bot_h = y1 - bot_y
    cell_h = (bot_h - gap) // 2
    cells = [
        (top_box, "cover"),
        ((x0, bot_y, x0 + cell_w, bot_y + cell_h), "contain"),
        ((x0 + cell_w + gap, bot_y, x1, bot_y + cell_h), "contain"),
        ((x0, bot_y + cell_h + gap, x0 + cell_w, y1), "contain"),
        ((x0 + cell_w + gap, bot_y + cell_h + gap, x1, y1), "contain"),
    ]
    if n > 5:
        ch = (h - (n - 1) * gap) // n
        return [
            ((x0, y0 + i * (ch + gap), x1, y0 + i * (ch + gap) + ch), "contain")
            for i in range(n)
        ]

    return cells[:n]


def _panel_height_for_screenshots(paths: list[Path], layout: str = "auto") -> int:
    if not paths:
        return 0
    inner_w = _content_inner_width()
    gap = PANEL_CELL_GAP
    mode = _resolve_content_layout(len(paths), layout, paths)
    if mode == "grid_2x2" and len(paths) > 4:
        h = _measure_grid_2x2_height(paths[:4], inner_w, gap)
        h += gap + _stacked_screenshots_height(paths[4:], inner_w, gap)
    elif mode == "hero_1_4" and len(paths) > 5:
        h = _measure_hero_1_4_height(paths[:5], inner_w, gap)
        h += gap + _stacked_screenshots_height(paths[5:], inner_w, gap)
    else:
        h = _measure_content_layout_height(paths, inner_w, gap, mode)
    return h + 2 * PANEL_OUTER_PAD


def _paste_content_panel(
    base: Image.Image,
    content_paths: list[Path],
    theme: dict,
    *,
    panel_box: tuple[int, int, int, int] = TEMPLATE_CONTENT_BOX,
    accent: str = "accent_secondary",
    layout: str = "auto",
) -> None:
    """内容截图：默认无游戏外框，直接等宽排版贴图。"""
    if not content_paths:
        return
    if _content_use_game_frame():
        inner = _draw_unified_game_panel(base, panel_box, theme, accent=accent)
    else:
        inner = _inset_box(panel_box, PANEL_OUTER_PAD)
    gap = PANEL_CELL_GAP
    slot_fill = _hex_rgb(theme["bg_card_dark"])
    mode = _resolve_content_layout(len(content_paths), layout, content_paths)
    x0, _, x1, _ = inner
    inner_w = x1 - x0

    if mode == "flow":
        _paste_flow_rows(base, inner, content_paths, gap, slot_fill)
        return
    if mode == "row_pair":
        _paste_flow_rows(base, inner, content_paths[:2], gap, slot_fill)
        return
    if mode == "grid_2x2":
        y_end = _paste_grid_2x2(base, inner, content_paths[:4], gap, slot_fill)
        extra = content_paths[4:]
    elif mode == "hero_1_4":
        y_end = _paste_hero_1_4(base, inner, content_paths[:5], gap, slot_fill)
        extra = content_paths[5:]
    else:
        _paste_stack_full_width(base, inner, content_paths, gap, slot_fill)
        return

    if extra:
        y = y_end + gap
        for i, p in enumerate(extra):
            y = _paste_screenshot_row(
                base, x0=x0, y=y, inner_w=inner_w, paths=[p], gap=gap, slot_fill=slot_fill,
            )
            if i < len(extra) - 1:
                y += gap


def _try_banner_cutout(img: Image.Image) -> Image.Image | None:
    """默认尝试 BiRefNet 抠人物；设 BATTLE_REPORT_BANNER_NO_CUTOUT=1 可关闭。"""
    if os.environ.get("BATTLE_REPORT_BANNER_NO_CUTOUT", "").strip().lower() in ("1", "true", "yes"):
        return None
    try:
        from scripts.normalize_lz_title_art import _apply_birefnet_matte

        return _apply_birefnet_matte(img.convert("RGB"))
    except Exception as exc:
        print(f"[战报] 栏头抠图跳过: {exc}", flush=True)
        return None


def _banner_has_alpha(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    lo, hi = img.getchannel("A").getextrema()
    return lo < 240 and hi > 0


def _trim_rgba_to_subject(img: Image.Image) -> Image.Image:
    im = img.convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if not bbox:
        return im
    return im.crop(bbox)


def _banner_cutout_cache_path(banner_path: Path) -> Path:
    return banner_path.parent / ".battle_report_cache" / f"{banner_path.stem}_cutout.png"


def _find_precut_section_character(
    search_dirs: list[Path],
    section_key: str,
    *,
    keyword: str = "",
) -> Path | None:
    for folder in search_dirs:
        found = resolve_section_character_png(folder, section_key, keyword=keyword)
        if found is not None:
            return found
    return None


def _prepare_section_character_rgba(path: Path, *, section_key: str) -> tuple[Image.Image, str, bool]:
    """
    小 Banner 人物/动物：PNG 透明底直接使用；否则 BiRefNet 抠图（缓存到 .battle_report_cache）。
    返回 (RGBA 图, 来源说明, 是否按透明底处理)。
    """
    from datetime import datetime

    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    rel = f"{path.parent.name}/{path.name}"

    if path.suffix.lower() == ".png" and png_has_transparent_alpha(path):
        with Image.open(path) as im:
            img = _trim_rgba_to_subject(im.convert("RGBA"))
        tag = f"透明PNG {rel}（{mtime}）"
        print(f"[战报] 小Banner主K({section_key}): {tag}", flush=True)
        return img, tag, True

    cache = _banner_cutout_cache_path(path)
    if cache.is_file():
        with Image.open(cache) as im:
            img = _trim_rgba_to_subject(im.convert("RGBA"))
        tag = f"抠图缓存 {cache.name} ← {rel}"
        print(f"[战报] 小Banner主K({section_key}): {tag}", flush=True)
        return img, tag, True

    with Image.open(path) as im:
        rgb = im.convert("RGB")
    cutout = _try_banner_cutout(rgb)
    if cutout is not None:
        trimmed = _trim_rgba_to_subject(cutout)
        cache.parent.mkdir(parents=True, exist_ok=True)
        trimmed.save(cache, "PNG")
        tag = f"自动抠图 {rel} → {cache.name}（{mtime}）"
        print(f"[战报] 小Banner主K({section_key}): {tag}", flush=True)
        return trimmed, tag, True

    cw = max(1, int(rgb.width * 0.55))
    fallback = rgb.crop((0, 0, cw, rgb.height)).convert("RGBA")
    tag = f"抠图失败，裁切使用 {rel}"
    print(f"[战报] 小Banner主K({section_key}): {tag}", flush=True)
    return fallback, tag, False


def _resolve_section_banner_character(
    section_folder: Path,
    *,
    section_key: str,
    search_dirs: list[Path],
    character_png: Path | None = None,
    section_keyword: str = "",
) -> tuple[Image.Image, str, bool]:
    """返回 (RGBA 角色主K, 来源, 是否透明底)。透明 PNG 直用，否则自动抠图。"""
    kw_path = keyword_character_png_path(section_folder, section_keyword)
    use_path = kw_path or character_png
    if use_path is not None and use_path.is_file():
        return _prepare_section_character_rgba(use_path, section_key=section_key)

    if section_keyword in SECTION_CHARACTER_KEYWORDS:
        print(
            f"[战报] 警告: 「{section_keyword}」缺少 {section_keyword}.png 人物/动物，"
            f"请放入区块文件夹",
            flush=True,
        )
        return Image.new("RGBA", (4, 4), (0, 0, 0, 0)), "无人物主K", True

    pre = _find_precut_section_character(
        search_dirs, section_key, keyword=section_keyword,
    )
    if pre is not None:
        return _prepare_section_character_rgba(pre, section_key=section_key)

    fallback_img: Path | None = None
    for name in ("section_banner.png", "banner.png", "栏头.png", "小banner.png"):
        p = section_folder / name
        if p.is_file() and not (
            section_keyword and _is_keyword_character_png(p, section_keyword)
        ):
            fallback_img = p
            break

    if fallback_img is not None and fallback_img.suffix.lower() in (
        ".png", ".jpg", ".jpeg", ".webp",
    ):
        return _prepare_section_character_rgba(fallback_img, section_key=section_key)

    print(
        f"[战报] 警告: 区块「{section_keyword or section_key}」未找到人物/动物透明 PNG"
        f"（请放 {section_keyword}.png 或 小banner/ 内透明底图）",
        flush=True,
    )
    return Image.new("RGBA", (4, 4), (0, 0, 0, 0)), "无人物主K", True


def _paste_contain_in_box(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    h_align: str = "center",
    v_align: str = "bottom",
) -> None:
    """等比缩放至完整落入槽内（contain），保留 RGBA 镂空，不拉伸变形。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if h_align == "right":
        px = x1 - nw
    elif h_align == "left":
        px = x0
    else:
        px = x0 + (tw - nw) // 2
    if v_align == "top":
        py = y0
    elif v_align == "bottom":
        py = y1 - nh
    else:
        py = y0 + (th - nh) // 2
    _paste_rgba_on_rgb(base, resized, px, py)


def _paste_section_banner_character(
    canvas: Image.Image,
    character: Image.Image,
    char_box: tuple[int, int, int, int],
    *,
    h_align: str,
    transparent_cutout: bool,
) -> None:
    """人物/动物：464×376 槽、等比 cover 顶对齐（保头部裁下方），透明 PNG 镂空保留。"""
    del transparent_cutout
    _paste_cover_in_box_top(canvas, character, char_box, h_align=h_align)


def section_char_side_for_key(section_key: str) -> str:
    """小 Banner 角色侧：B/D 左，C 右（交替）。"""
    return "right" if section_key.lower().strip() in ("c",) else "left"


def _section_banner_character_box(char_on_right: bool, canvas_h: int) -> tuple[int, int, int, int]:
    """人物/动物槽 464×376，底对齐画布；顶 60px 溢出区可露头。"""
    y1 = canvas_h - 2
    y0 = max(0, y1 - SECTION_BANNER_CHAR_H)
    if char_on_right:
        return (CANVAS_W - SECTION_BANNER_CHAR_W, y0, CANVAS_W, y1)
    return (0, y0, SECTION_BANNER_CHAR_W, y1)


def _section_banner_layout(
    *,
    char_on_right: bool,
    band_y0: int,
    band_y1: int,
    canvas_h: int,
) -> dict:
    """角色 464×376；标题区占剩余宽度并居中叠字。"""
    char_box = _section_banner_character_box(char_on_right, canvas_h)
    gap = SECTION_BANNER_TEXT_CHAR_GAP
    if char_on_right:
        text_x0 = SECTION_BANNER_EDGE_PAD
        tx1 = char_box[0] - gap
        char_h_align = "right"
    else:
        text_x0 = char_box[2] + gap
        tx1 = CANVAS_W - SECTION_BANNER_EDGE_PAD
        char_h_align = "left"
    text_box = (text_x0, band_y0, tx1, band_y1)
    tcx = (text_x0 + tx1) // 2
    tcy = (band_y0 + band_y1) // 2
    return {
        "char_box": char_box,
        "char_h_align": char_h_align,
        "text_box": text_box,
        "text_x0": text_x0,
        "tx1": tx1,
        "tcx": tcx,
        "tcy": tcy,
    }


def _paste_cover_in_box_center(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    h_align: str = "center",
) -> None:
    """等比 cover，在槽内水平垂直居中（角色占 2/5 区中间）。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if h_align == "right":
        px = x1 - nw
    elif h_align == "left":
        px = x0
    else:
        px = x0 + (tw - nw) // 2
    py = y0 + (th - nh) // 2
    _paste_rgba_on_rgb(base, resized, px, py)


def _paste_cover_in_box_bottom(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    h_align: str = "center",
) -> None:
    """等比 cover、底对齐（裁上方）。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if h_align == "right":
        px = x1 - nw
    elif h_align == "left":
        px = x0
    else:
        px = x0 + (tw - nw) // 2
    py = y1 - nh
    _paste_rgba_on_rgb(base, resized, px, py)


def _paste_cover_in_box_top(
    base: Image.Image,
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    h_align: str = "center",
) -> None:
    """小 Banner 角色：等比 cover、顶对齐；过高时从上往下保留（裁掉下方），头部完整。"""
    x0, y0, x1, y1 = box
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    src = img.convert("RGBA")
    sw, sh = max(1, src.width), max(1, src.height)
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    if h_align == "right":
        left = max(0, nw - tw)
    elif h_align == "left":
        left = 0
    else:
        left = max(0, (nw - tw) // 2)
    cropped = resized.crop((left, 0, min(left + tw, nw), min(th, nh)))
    _paste_rgba_on_rgb(base, cropped, x0, y0)


def _draw_halftone_band(
    ld: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    rgb: tuple[int, int, int],
    *,
    dot: int = 6,
    alpha: int = 160,
) -> None:
    x0, y0, x1, y1 = box
    for yy in range(y0, y1, dot):
        for xx in range(x0, x1, dot):
            if ((xx - x0) // dot + (yy - y0) // dot) % 2 == 0:
                ld.rectangle([xx, yy, xx + dot - 2, yy + dot - 2], fill=(*rgb, alpha))


def _draw_splash_blobs(ld: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int]) -> None:
    for dx, dy, rw, rh in ((0, 0, 90, 50), (40, -20, 70, 40), (-30, 25, 60, 35)):
        ld.ellipse([cx + dx - rw, cy + dy - rh, cx + dx + rw, cy + dy + rh], fill=(*color, 85))


def _section_banner_title_font() -> object:
    """小 Banner 标题：全分区统一字号。"""
    return load_font("display_bold", SECTION_BANNER_TITLE_SIZE)


def _section_banner_bg_path(
    assets_dir: Path,
    section_key: str,
    generated: Path | None = None,
) -> Path | None:
    """优先合成阶段生成的底图，否则复用素材目录下 banner_kv_* 缓存（161845 MICU 步）。"""
    if generated and generated.is_file():
        return generated
    for base in (assets_dir / ".battle_report_nano", assets_dir):
        p = base / f"banner_kv_{section_key}.png"
        if p.is_file():
            return p
    return None


def _section_banner_urban_palette(theme: dict) -> dict[str, tuple[int, int, int]]:
    """NTE 栏头格局：半调/泼墨/扫描线均用 KV 亮色+点缀，与头图 theme 一致。"""
    roles = _kv_accent_roles(theme)
    return {
        "halftone": roles["halftone"],
        "glow": roles["glow"],
        "dark": roles["dark"],
        "black": _darken(roles["bg_page"], 0.35),
        "splash": _boost_vivid(roles["pop"], sat_mul=1.08, val_mul=1.05),
        "accent": roles["warm"],
        "accent_alt": roles["cool"],
        "bg_page": roles["bg_page"],
        "title": roles["title"],
        "title_stroke": (0, 0, 0),
        "scan": _lighten(_mix_rgb(roles["cool"], roles["pop"], 0.35), 0.08),
        "deco": _mix_rgb(roles["cool"], roles["stroke"], 0.4),
    }


def _draw_section_banner_urban_kv_bg(
    layer: Image.Image,
    *,
    y0: int,
    y1: int,
    char_on_right: bool,
    palette: dict[str, tuple[int, int, int]],
    section_key: str = "b",
) -> None:
    """
    小 Banner 程序化底：半调铺底 + 黑斜条 + 泼墨 + 底扫描线 + 技术装饰字（无人物、无 AI 生图）。
    格局：角色槽 2/5 + 标题区 3/5，与参考图一致。
    """
    ld = ImageDraw.Draw(layer)
    box = (0, y0, CANVAS_W, y1)
    h = max(1, y1 - y0)
    _draw_halftone_band(ld, box, palette["halftone"], dot=5, alpha=195)
    for i in range(h):
        t = i / max(1, h - 1)
        c = _mix_rgb(palette["bg_page"], palette["glow"], 0.35 + 0.45 * (1 - abs(t - 0.55) * 1.6))
        ld.line([(0, y0 + i), (CANVAS_W, y0 + i)], fill=(*c, 255))

    split = int(CANVAS_W * SECTION_BANNER_CHAR_RATIO)
    skew = SECTION_BANNER_DIAGONAL_SKEW
    char_dark = _mix_rgb(palette["black"], palette["dark"], 0.35)
    if char_on_right:
        char_poly = [(split - skew, y0), (CANVAS_W, y0), (CANVAS_W, y1), (split + skew, y1)]
        text_poly = [(0, y0), (split + skew, y0), (split - skew, y1), (0, y1)]
        splash_cx = split // 2 + 40
    else:
        char_poly = [(0, y0), (split + skew, y0), (split - skew, y1), (0, y1)]
        text_poly = [(split - skew, y0), (CANVAS_W, y0), (CANVAS_W, y1), (split + skew, y1)]
        splash_cx = split + (CANVAS_W - split) // 2 - 30
    ld.polygon(char_poly, fill=(*char_dark, 165))
    ld.polygon(text_poly, fill=(*_mix_rgb(palette["dark"], palette["halftone"], 0.25), 120))

    bar_h = max(28, h // 5)
    bar_y = y0 + int(h * 0.38)
    if char_on_right:
        bar_box = (24, bar_y, split + 80, bar_y + bar_h)
    else:
        bar_box = (split - 60, bar_y, CANVAS_W - 24, bar_y + bar_h)
    _draw_skew_quad(ld, bar_box, skew=18, fill=(*palette["black"], 240))
    _draw_skew_quad(
        ld,
        (bar_box[0] + 6, bar_box[1] + 5, bar_box[2] - 6, bar_box[3] - 5),
        skew=12,
        fill=(*_mix_rgb(palette["accent"], palette["splash"], 0.35), 90),
    )

    seed = sum(ord(c) for c in section_key) * 17
    splash_cy = y0 + int(h * 0.52)
    for j, (dx, dy, rw, rh) in enumerate(
        ((0, 0, 110, 58), (55, -18, 85, 48), (-40, 22, 72, 42), (90, 30, 50, 35)),
    ):
        ox = ((seed + j * 31) % 50) - 25
        oy = ((seed + j * 13) % 30) - 15
        ld.ellipse(
            [
                splash_cx + dx + ox - rw,
                splash_cy + dy + oy - rh,
                splash_cx + dx + ox + rw,
                splash_cy + dy + oy + rh,
            ],
            fill=(*palette["splash"], 78 + j * 12),
        )

    scan_y = y1 - max(14, h // 8)
    scan_c = palette.get("scan", _lighten(palette["halftone"], 0.2))
    for k in range(4):
        yy = scan_y + k * 3
        ld.line(
            [(32, yy), (CANVAS_W - 32, yy)],
            fill=(*scan_c, 175 - k * 28),
            width=2 if k == 0 else 1,
        )

    deco_font = load_font("body_regular", 18)
    deco = palette.get("deco", palette["accent_alt"])
    for text, px, py in (
        ("/////", 36, y0 + 14),
        ("777", CANVAS_W - 72, y0 + 12),
        ("///", CANVAS_W - 120, y1 - 28),
    ):
        ld.text((px, py), text, font=deco_font, fill=(*deco, 140))

    _draw_section_banner_top_tape(
        ld, y0=y0, vivid_p=palette["accent"], vivid_s=palette["accent_alt"],
    )
    ld.line([(0, y1 - 1), (CANVAS_W, y1 - 1)], fill=(*palette["accent"], 255), width=2)


def _draw_section_banner_vivid_kv_bg(
    layer: Image.Image,
    *,
    y0: int,
    y1: int,
    char_on_right: bool,
    theme: dict,
) -> None:
    """小 Banner 程序化炫彩底：KV 亮色饱和斜切分区，无标题下暗框（靠描边保证可读）。"""
    roles = _kv_accent_roles(theme)
    vp = _boost_vivid(roles["warm"], sat_mul=1.28, val_mul=1.18)
    vs = _boost_vivid(roles["cool"], sat_mul=1.24, val_mul=1.16)
    pop = _boost_vivid(roles["pop"], sat_mul=1.22, val_mul=1.15)
    bg_page = roles["dark"]
    ld = ImageDraw.Draw(layer)
    h = max(1, y1 - y0)
    base_top = _mix_rgb(bg_page, _mix_rgb(vp, pop, 0.55), 0.48)
    base_bot = _mix_rgb(bg_page, _mix_rgb(vs, vp, 0.52), 0.5)
    for i in range(h):
        t = i / max(1, h - 1)
        c = _mix_rgb(base_top, base_bot, t)
        ld.line([(0, y0 + i), (CANVAS_W, y0 + i)], fill=(*c, 255))
    _draw_halftone_band(ld, (0, y0, CANVAS_W, y1), _mix_rgb(vp, pop, 0.45), dot=5, alpha=100)
    _draw_halftone_band(ld, (0, y0, CANVAS_W, y1), _mix_rgb(vs, pop, 0.55), dot=8, alpha=55)

    split = int(CANVAS_W * SECTION_BANNER_CHAR_RATIO)
    skew = SECTION_BANNER_DIAGONAL_SKEW
    char_tint = _mix_rgb(bg_page, vp if char_on_right else vs, 0.55)
    text_tint = _mix_rgb(_mix_rgb(vp, pop, 0.45), vs if char_on_right else vp, 0.55)
    if char_on_right:
        char_poly = [
            (split - skew, y0), (CANVAS_W, y0), (CANVAS_W, y1), (split + skew, y1),
        ]
        text_poly = [(0, y0), (split + skew, y0), (split - skew, y1), (0, y1)]
        glow_cx = split + (CANVAS_W - split) // 2
        text_glow_c = pop
    else:
        char_poly = [(0, y0), (split + skew, y0), (split - skew, y1), (0, y1)]
        text_poly = [
            (split - skew, y0), (CANVAS_W, y0), (CANVAS_W, y1), (split + skew, y1),
        ]
        glow_cx = split // 2
        text_glow_c = pop
    ld.polygon(char_poly, fill=(*char_tint, 150))
    ld.polygon(text_poly, fill=(*text_tint, 125))
    glow_cy = y0 + int(h * 0.55)
    ld.ellipse(
        [glow_cx - 280, glow_cy - 95, glow_cx + 280, glow_cy + 95],
        fill=(*_lighten(vp if char_on_right else vs, 0.32), 115),
    )
    ld.ellipse(
        [glow_cx - 140, glow_cy - 48, glow_cx + 140, glow_cy + 48],
        fill=(*_lighten(text_glow_c, 0.2), 75),
    )
    _draw_section_banner_top_tape(ld, y0=y0, vivid_p=vp, vivid_s=pop)
    ld.line([(12, y0 + 2), (CANVAS_W - 12, y0 + 2)], fill=(*vp, 255), width=4)
    ld.line([(12, y1 - 2), (CANVAS_W - 12, y1 - 2)], fill=(*_lighten(pop, 0.1), 255), width=3)


def _draw_section_banner_gradient_bg(
    layer: Image.Image,
    *,
    y0: int,
    y1: int,
    char_on_right: bool,
    dark: tuple[int, int, int],
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    bg_page: tuple[int, int, int],
    vivid_primary: tuple[int, int, int] | None = None,
    vivid_secondary: tuple[int, int, int] | None = None,
) -> None:
    """小 Banner 底：斜切双色分区（委托炫彩版）。"""
    del dark, primary, secondary, bg_page, vivid_primary, vivid_secondary
    theme_stub = {
        "bg_page": f"#{bg_page[0]:02X}{bg_page[1]:02X}{bg_page[2]:02X}",
        "bg_card_dark": f"#{dark[0]:02X}{dark[1]:02X}{dark[2]:02X}",
        "accent_primary": f"#{primary[0]:02X}{primary[1]:02X}{primary[2]:02X}",
        "accent_secondary": f"#{secondary[0]:02X}{secondary[1]:02X}{secondary[2]:02X}",
    }
    _draw_section_banner_vivid_kv_bg(
        layer, y0=y0, y1=y1, char_on_right=char_on_right, theme=theme_stub,
    )


def _draw_section_banner_top_tape(
    ld: ImageDraw.ImageDraw,
    *,
    y0: int,
    vivid_p: tuple[int, int, int],
    vivid_s: tuple[int, int, int],
) -> None:
    h = SECTION_BANNER_TOP_TAPE_H
    _draw_hazard_stripes(ld, (0, y0, CANVAS_W, y0 + h), vivid_p, vivid_s, stripe_h=3)
    ld.line([(0, y0 + h), (CANVAS_W, y0 + h)], fill=(0, 0, 0, 255), width=2)
    for xx in range(0, CANVAS_W, 48):
        ld.line([(xx, y0 + 2), (xx + 24, y0 + h - 2)], fill=(*_lighten(vivid_s, 0.2), 90), width=1)


def _paste_section_banner_nano_bg(
    canvas: Image.Image,
    nano_bg: Path,
    *,
    y_off: int,
    band_h: int,
    bg_page: tuple[int, int, int],
) -> None:
    """MICU/缓存纯背景：cover 铺满 1080×280 栏条区；overflow 区保持透明，不延伸填充。"""
    with Image.open(nano_bg) as im:
        bg = im.convert("RGB")
        if bg.size != (CANVAS_W, band_h):
            sw, sh = bg.size
            scale = max(CANVAS_W / sw, band_h / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            bg = bg.resize((nw, nh), Image.Resampling.LANCZOS)
            left = (nw - CANVAS_W) // 2
            top = (nh - band_h) // 2
            bg = bg.crop((left, top, left + CANVAS_W, top + band_h))
        canvas.paste(bg, (0, y_off))


def _section_banner_title_fill(theme: dict) -> tuple[int, int, int]:
    """标题：优先 accent_bright（参考图粉/黄强调），否则主文字色。"""
    pal = _section_banner_urban_palette(theme)
    return pal["title"]


def _draw_section_banner_title_text(
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    cy: int,
    title: str,
    font,
    fill: tuple[int, int, int],
    on_vivid_bg: bool = False,
    anchor: str = "mm",
) -> None:
    """小 Banner 标题：描边 + 可选阴影，炫底上保证可读。"""
    stroke = (0, 0, 0)
    shadow = _darken(fill, 0.55) if on_vivid_bg else (0, 0, 0)
    stroke_w = 6 if on_vivid_bg else 4
    if on_vivid_bg:
        for dx, dy in ((5, 5), (3, 3)):
            draw.text((cx + dx, cy + dy), title, font=font, fill=shadow, anchor=anchor)
    else:
        for dx, dy in ((3, 3), (1, 1)):
            draw.text((cx + dx, cy + dy), title, font=font, fill=stroke, anchor=anchor)
    inner = _lighten(fill, 0.14) if on_vivid_bg else fill
    draw.text(
        (cx, cy), title, font=font, fill=inner, anchor=anchor,
        stroke_width=stroke_w,
        stroke_fill=stroke,
    )


def _draw_banner_title_rich(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    title: str,
    font,
    *,
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int],
    shadow: tuple[int, int, int],
    anchor: str = "mm",
    stroke_width: int = 4,
) -> None:
    tx, ty = xy
    for dx, dy in ((5, 4), (3, 2)):
        draw.text((tx + dx, ty + dy), title, font=font, fill=shadow, anchor=anchor)
    draw.text(
        (tx, ty), title, font=font, fill=fill, anchor=anchor,
        stroke_width=stroke_width, stroke_fill=stroke,
    )


def _nano_banner_bg_path(section_folder: Path, section_key: str) -> Path | None:
    names = (f"banner_kv_{section_key}.png", f"banner_bg_{section_key}.png")
    for base in (section_folder / ".battle_report_nano", section_folder.parent / ".battle_report_nano"):
        for name in names:
            p = base / name
            if p.is_file():
                return p
    return None


def _resolve_nano_hero_data_bg(nano_dir: Path | None) -> Path | None:
    if not nano_dir:
        return None
    for name in ("hero_data_kv_bg.png", "hero_data_bg.png"):
        p = nano_dir / name
        if p.is_file():
            return p
    return None


def _render_section_banner(
    section_folder: Path,
    theme: dict,
    *,
    section_key: str = "b",
    char_side: str = "left",
    search_dirs: list[Path] | None = None,
    character_png: Path | None = None,
    section_keyword: str = "",
    title: str | None = None,
    kv_ai_hybrid: bool = False,
    nano_banner_bg: Path | None = None,
) -> Image.Image:
    """小 Banner 栏条 1080×280 + 顶溢出 60px；角色 cover 顶裁 + 统一字号标题。"""
    title = (title or section_keyword or section_folder.name).strip()
    band_h = SECTION_BANNER_AI_H
    overflow = SECTION_BANNER_CHAR_OVERFLOW_TOP
    canvas_h = band_h + overflow
    bg_page = _hex_rgb(theme["bg_page"])
    title_fill = _section_banner_title_fill(theme)
    char_on_right = char_side == "right"
    dirs = search_dirs or [section_folder]
    cover_bg = None
    if nano_banner_bg and nano_banner_bg.is_file():
        cover_bg = nano_banner_bg
    else:
        cover_bg = _nano_banner_bg_path(section_folder, section_key)
    use_cover_bg = cover_bg is not None and cover_bg.is_file()

    canvas = Image.new("RGBA", (CANVAS_W, canvas_h), (0, 0, 0, 0))
    y_off = overflow
    inset = SECTION_BANNER_BAND_INSET_Y
    band_y0, band_y1 = y_off + inset, y_off + band_h - inset
    layout = _section_banner_layout(
        char_on_right=char_on_right,
        band_y0=band_y0,
        band_y1=band_y1,
        canvas_h=canvas_h,
    )
    char_box = layout["char_box"]
    char_h_align = layout["char_h_align"]
    text_x0 = layout["text_x0"]
    tx1 = layout["tx1"]
    tcx = layout["tcx"]
    tcy = layout["tcy"]

    if use_cover_bg and cover_bg is not None:
        _paste_section_banner_nano_bg(
            canvas, cover_bg, y_off=y_off, band_h=band_h, bg_page=bg_page,
        )
    else:
        bg_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bg_y0 = band_y0
        _draw_section_banner_vivid_kv_bg(
            bg_layer,
            y0=bg_y0,
            y1=band_y1,
            char_on_right=char_on_right,
            theme=theme,
        )
        _composite_rgba_layer(canvas, bg_layer)

    character, char_src, cutout = _resolve_section_banner_character(
        section_folder,
        section_key=section_key,
        search_dirs=dirs,
        character_png=character_png,
        section_keyword=section_keyword,
    )
    _paste_section_banner_character(
        canvas, character, char_box, h_align=char_h_align, transparent_cutout=cutout,
    )

    draw = ImageDraw.Draw(canvas)
    font = _section_banner_title_font()
    if char_side == "left":
        _draw_section_banner_title_text(
            draw, cx=CANVAS_W - 50, cy=tcy, title=title,
            font=font, fill=title_fill, on_vivid_bg=True, anchor="rm",
        )
    else:
        _draw_section_banner_title_text(
            draw, cx=50, cy=tcy, title=title,
            font=font, fill=title_fill, on_vivid_bg=True, anchor="lm",
        )

    return canvas


def _section_banner_strip_height(*, kv_ai_hybrid: bool = False) -> int:
    del kv_ai_hybrid
    return SECTION_BANNER_AI_H + SECTION_BANNER_CHAR_OVERFLOW_TOP


def _paste_section_banner_strip(
    base: Image.Image,
    y: int,
    section_folder: Path,
    theme: dict,
    *,
    section_key: str = "b",
    char_side: str = "left",
    search_dirs: list[Path] | None = None,
    character_png: Path | None = None,
    section_keyword: str = "",
    title: str | None = None,
    kv_ai_hybrid: bool = False,
    nano_banner_bg: Path | None = None,
) -> int:
    strip = _render_section_banner(
        section_folder,
        theme,
        section_key=section_key,
        char_side=char_side,
        search_dirs=search_dirs,
        character_png=character_png,
        section_keyword=section_keyword,
        title=title,
        kv_ai_hybrid=kv_ai_hybrid,
        nano_banner_bg=nano_banner_bg,
    )
    base.paste(strip.convert("RGB"), (0, y), strip.split()[3] if strip.mode == "RGBA" else None)
    return y + strip.height


def _paste_ai_kv_banner_strip(base: Image.Image, y: int, banner_path: Path) -> int:
    """KV 纯 AI 生成的小 Banner 整图，直接贴入，不用本地栏头/抠图。"""
    strip = fit_width(Image.open(banner_path))
    base.paste(strip, (0, y))
    return y + strip.height


def _ai_banner_strip_height(banner_path: Path | None) -> int:
    if not banner_path or not banner_path.is_file():
        return 0
    with Image.open(banner_path) as im:
        w, h = im.size
        if w <= 0:
            return 0
        return max(1, int(h * CANVAS_W / w))


def _build_section(
    assets: SectionFolderAssets,
    *,
    theme: dict,
    accent: str = "accent_secondary",
    layout: str = "auto",
    section_key: str = "b",
    char_side: str = "left",
    search_dirs: list[Path] | None = None,
    ai_banner: Path | None = None,
    banner_title: str | None = None,
    kv_ai_hybrid: bool = False,
    nano_banner_bg: Path | None = None,
) -> Image.Image | None:
    """区块 = AI 整栏 / KV 底图+本地标题 / 程序栏头 + 内容截图。"""
    has_banner = (
        ai_banner is not None
        or assets.character_png is not None
        or assets.banner_image is not None
        or bool(banner_title and banner_title.strip())
    )
    if not assets.screenshots and not has_banner:
        return None

    bg_page = _hex_rgb(theme["bg_page"])
    n = len(assets.screenshots)
    panel_h = _panel_height_for_screenshots(assets.screenshots, layout) if n else 0
    gap_after_banner = 12 if has_banner else 0
    if ai_banner:
        banner_h_est = _ai_banner_strip_height(ai_banner)
    elif assets.character_png or assets.banner_image or banner_title:
        use_hybrid_bg = kv_ai_hybrid or bool(nano_banner_bg and nano_banner_bg.is_file())
        banner_h_est = _section_banner_strip_height(kv_ai_hybrid=use_hybrid_bg)
    else:
        banner_h_est = 0
    total_h = banner_h_est + gap_after_banner + panel_h + 8
    banner_search = list(search_dirs or [])
    if assets.folder not in banner_search:
        banner_search.insert(0, assets.folder)
    root = assets.folder.parent
    for extra in (root / "小banner", root / "banners"):
        if extra.is_dir() and extra not in banner_search:
            banner_search.append(extra)

    canvas = Image.new("RGBA", (CANVAS_W, max(total_h, 120)), (0, 0, 0, 0))
    y = 0
    if ai_banner:
        y = _paste_ai_kv_banner_strip(canvas, y, ai_banner)
        y += gap_after_banner
    elif assets.character_png or assets.banner_image or banner_title:
        use_hybrid_bg = kv_ai_hybrid or bool(nano_banner_bg and nano_banner_bg.is_file())
        y = _paste_section_banner_strip(
            canvas,
            y,
            assets.folder,
            theme,
            section_key=section_key,
            char_side=char_side,
            search_dirs=banner_search,
            character_png=assets.character_png,
            section_keyword=assets.keyword,
            title=banner_title or assets.keyword,
            kv_ai_hybrid=use_hybrid_bg,
            nano_banner_bg=nano_banner_bg,
        )
        y += gap_after_banner

    if n:
        x1 = CANVAS_W - SECTION_PAD_X
        panel_box = (SECTION_PAD_X, y, x1, y + panel_h)
        _paste_content_panel(
            canvas,
            assets.screenshots,
            theme,
            panel_box=panel_box,
            accent=accent,
            layout=layout,
        )
    return canvas


def _measure_hero_bottom(
    kv_height: int,
    draw: ImageDraw.ImageDraw,
    *,
    cx: int,
    main_title: str,
    tagline: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    fonts: dict,
) -> int:
    block_h = _measure_hero_block_height(
        draw,
        cx=cx,
        y_top=0,
        main_title=main_title,
        tagline=tagline,
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
    )
    y_start = _hero_text_y_start(kv_height, block_h)
    return y_start + block_h + 40


def _draw_hero_text(
    hero: Image.Image,
    theme: dict,
    *,
    main_title: str,
    tagline: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    hero_design: dict | None = None,
    hero_character: Path | None = None,
    platform_logos: Path | None = None,
    nano_data_bg: Path | None = None,
    ai_hero_data_strip: Path | None = None,
    ai_strip_h: int = 0,
    kv_ai_bg: bool = False,
    kv_style_ref_strip: bool = False,
    stat_groups: list | None = None,
) -> Image.Image:
    vivid_p, vivid_s = _theme_vivid_pair(theme)
    primary = vivid_p
    secondary = vivid_s
    text_c = _hex_rgb(theme["text_primary"])
    card_dark = _hex_rgb(theme["bg_card_dark"])
    stroke_c = _hex_rgb(theme["stroke_decor"])
    bg_page = _hex_rgb(theme["bg_page"])
    cx = HERO_TEXT_CENTER_X

    design = hero_design or DEFAULT_HERO_DESIGN
    fonts = _hero_layout_fonts(design)
    kv = hero.convert("RGB")
    probe = Image.new("RGB", (kv.width, kv.height))
    probe_draw = ImageDraw.Draw(probe)
    block_h = _measure_hero_block_height(
        probe_draw,
        cx=cx,
        y_top=0,
        main_title=main_title,
        tagline=tagline,
        bar_text=bar_text,
        stats=stats,
        fonts=fonts,
        design=design,
        platform_logos=platform_logos,
        ai_strip_h=ai_strip_h,
        stat_groups=stat_groups,
    )
    y_start = _hero_text_y_start(kv.height, block_h)
    bottom = y_start + block_h + 40
    img = Image.new("RGB", (kv.width, bottom), bg_page)
    img.paste(kv, (0, 0))

    draw = ImageDraw.Draw(img)
    font_title = fonts["title"]
    font_tag = fonts["tag"]

    _draw_title_with_depth(draw, cx, y_start, main_title, font_title, text_c)
    y = draw.textbbox((cx, y_start), main_title, font=font_title, anchor="mt")[3] + HERO_TAGLINE_GAP

    if tagline.strip():
        tag_fill = _lighten(text_c, 0.08)
        _draw_text_centered(draw, cx, y, tagline, font_tag, tag_fill, anchor="mt")
        y = draw.textbbox((cx, y), tagline, font=font_tag, anchor="mt")[3]

    if platform_logos and platform_logos.is_file():
        y += HERO_PLATFORM_LOGO_GAP
        y += _paste_platform_logos_strip(img, cx=cx, y=y, logo_path=platform_logos)

    if _hero_has_lower_block(bar_text, stats, stat_groups=stat_groups):
        y += HERO_UPPER_TO_LOWER_GAP + HERO_DATA_BLOCK_SHIFT_Y
        if ai_hero_data_strip and ai_hero_data_strip.is_file():
            strip = fit_width(Image.open(ai_hero_data_strip))
            img.paste(strip, (0, y))
        elif stat_groups:
            y += HERO_LOWER_BLOCK_PAD_TOP
            for i, group in enumerate(stat_groups):
                y = _draw_hero_framed_data_card(
                    img,
                    y=y,
                    card_title=group["title"],
                    bar_text="",
                    stats=group["stats"],
                    fonts=fonts,
                    theme=theme,
                    design=design,
                )
                if i < len(stat_groups) - 1:
                    y += HERO_LOWER_BLOCK_INNER_GAP
        else:
            card_title = ""
            if os.environ.get("BATTLE_REPORT_DATA_CARD_MAIN_TITLE", "").strip().lower() in (
                "1",
                "true",
                "yes",
            ):
                card_title = main_title
            _draw_hero_launch_data_block(
                img,
                y=y,
                bar_text=bar_text,
                stats=stats,
                fonts=fonts,
                theme=theme,
                primary=primary,
                secondary=secondary,
                card_dark=card_dark,
                text_c=text_c,
                stroke_c=stroke_c,
                hero_character=hero_character,
                nano_data_bg=nano_data_bg,
                design=design,
                kv_ai_bg=kv_ai_bg,
                card_title=card_title,
            )
    return img


def _log_section_assets(label: str, assets: SectionFolderAssets, *, section_key: str = "") -> None:
    refs = ", ".join(p.name for p in assets.design_refs) or "无"
    banner = assets.banner_image.name if assets.banner_image else "无（请放 section_banner.png）"
    shots = ", ".join(p.name for p in assets.screenshots) or "无"
    key = section_key or {"核心资源矩阵": "b", "联动活动火热开启": "c", "玩家真实好评": "d"}.get(
        assets.keyword, "b",
    )
    char_png = (
        f"{assets.keyword}/{assets.character_png.name}"
        if assets.character_png
        else f"无（请放 {assets.keyword}.png 透明人物）"
    )
    print(
        f"[战报] 区块 {label}: 截图 {len(assets.screenshots)} 张, 排序={assets.order_source}, "
        f"栏头底图={banner}, 人物主K={char_png}, 角色侧={section_char_side_for_key(key)} (2/5区)",
        flush=True,
    )
    if assets.design_refs:
        print(f"[战报]   设计参考(已忽略): {refs}", flush=True)
    if assets.screenshots:
        print(f"[战报]   顺序: {shots}", flush=True)


def _log_battle_report_assets_root(assets_dir: Path) -> None:
    """合成前扫描桌面/战报：栏头、截图、区块抠图。"""
    root = assets_dir.resolve()
    print(f"[战报] 读取素材目录: {root}", flush=True)
    kv = root / "KV.jpg"
    if not kv.is_file():
        kv = next(root.glob("KV.*"), None)
    print(f"[战报]   KV: {kv.name if kv else '未找到'}", flush=True)
    for folder_name, key in (
        ("核心资源矩阵", "b"),
        ("联动活动火热开启", "c"),
        ("玩家真实好评", "d"),
    ):
        folder = root / folder_name
        if not folder.is_dir():
            print(f"[战报]   缺文件夹: {folder_name}", flush=True)
            continue
        a = parse_section_folder(folder, folder_name, kv_path=kv, section_key=key)
        char_png = a.character_png or _find_precut_section_character(
            [folder, root / "小banner", root / "banners", root], key, keyword=folder_name,
        )
        print(
            f"[战报]   {folder_name}: 栏头底图={a.banner_image.name if a.banner_image else '无'}, "
            f"截图={len(a.screenshots)}, "
            f"人物主K={char_png.name if char_png else f'无（{folder_name}.png 透明底）'}, "
            f"角色侧={section_char_side_for_key(key)}",
            flush=True,
        )


def compose_from_desktop_folder(
    assets_dir: Path,
    *,
    main_title: str,
    tagline: str,
    bar_text: str,
    stats: list[tuple[str, str]] | None = None,
    stat_groups: list | None = None,
    theme_id: str = "desktop_zhanbao",
    out_dir: Path | None = None,
) -> Path:
    assets_dir = assets_dir.resolve()
    log_font_configuration()
    _log_battle_report_assets_root(assets_dir)
    kv_path = assets_dir / "KV.jpg"
    if not kv_path.is_file():
        kv_path = next(assets_dir.glob("KV.*"), None)
    if kv_path is None:
        raise FileNotFoundError(f"未找到 KV: {assets_dir}")

    footer_path = assets_dir / "AI TAI.png"
    project_root = Path(__file__).resolve().parent.parent.parent
    out_dir = out_dir or (project_root / "output" / "battle-report")
    out_dir.mkdir(parents=True, exist_ok=True)

    theme = build_theme_json(kv_path, theme_id)
    theme_path = project_root / "scripts/assets/battle-report/themes" / f"{theme_id}.json"
    save_theme(theme, theme_path)
    section_specs = [
        ("b", "核心资源矩阵", section_char_side_for_key("b")),
        ("c", "联动活动火热开启", section_char_side_for_key("c")),
        ("d", "玩家真实好评", section_char_side_for_key("d")),
    ]
    visuals = prepare_visual_assets(
        assets_dir,
        kv_path,
        theme,
        section_specs=section_specs,
        bar_text=bar_text,
        stats=stats,
    )
    kv_ai_full = visuals.mode == "full"
    nano_data_bg = None
    # 数据区底图：BATTLE_REPORT_HERO_DATA_IMAGE=1 时 GPT 生成
    if hero_data_image_enabled() and not kv_ai_full and visuals.nano_dir:
        nano_data_bg = resolve_or_create_hero_data_bg(
            kv_path,
            theme,
            visuals.nano_dir,
            bar_text=bar_text,
            stats=stats,
        )
    hero_design = None if kv_ai_full else resolve_hero_design(kv_path, theme)
    if not kv_ai_full and (bar_text.strip() or stats or stat_groups):
        layout_name = _hero_data_layout(hero_design)
        print(
            f"[战报] 数据区: 无装饰叠字（layout={layout_name}），不生图",
            flush=True,
        )
    hero_character = None if kv_ai_full else _find_hero_character(assets_dir)
    ai_hero_strip = (
        visuals.hero_data_strip
        if kv_ai_full and hero_data_image_enabled() and visuals.hero_data_strip
        else None
    )
    ai_strip_h = ai_hero_strip_height(ai_hero_strip) if kv_ai_full else 0
    kv_hybrid = not kv_ai_full
    cached_banners = {
        k: p
        for k in ("b", "c", "d")
        if (p := _section_banner_bg_path(assets_dir, k, visuals.section_banners.get(k)))
    }
    if section_banner_image_enabled() and visuals.section_banners:
        names = ", ".join(f"{k}={p.name}" for k, p in sorted(visuals.section_banners.items()))
        print(f"[战报/MICU] 小 Banner 底图已生成: {names}", flush=True)
    elif cached_banners:
        names = ", ".join(f"{k}={p.name}" for k, p in sorted(cached_banners.items()))
        print(f"[战报] 小 Banner: 复用缓存底图（161845 步）{names}", flush=True)
    else:
        print("[战报] 小 Banner: KV 炫彩程序化底 + 标题衬底，不生图", flush=True)
    platform_logos = _find_platform_logos(assets_dir)
    bg_page = _hex_rgb(theme["bg_page"])
    blocks: list[Image.Image] = []

    hero = fit_width(Image.open(kv_path))
    hero = _draw_hero_text(
        hero, theme,
        main_title=main_title,
        tagline=tagline,
        bar_text=bar_text,
        stats=stats,
        hero_design=hero_design,
        hero_character=hero_character,
        platform_logos=platform_logos,
        nano_data_bg=nano_data_bg,
        ai_hero_data_strip=ai_hero_strip,
        ai_strip_h=ai_strip_h,
        kv_ai_bg=False,
        kv_style_ref_strip=False,
        stat_groups=stat_groups,
    )
    blocks.append(hero)

    br_roots = [
        assets_dir,
        assets_dir / "banners",
        Path(__file__).resolve().parent.parent.parent / "scripts/assets/battle-report/banners",
    ]

    assets_b = parse_section_folder(
        assets_dir / "核心资源矩阵", "核心资源矩阵", kv_path=kv_path, section_key="b",
    )
    block_b = _build_section(
        assets_b,
        theme=theme,
        accent="accent_secondary",
        layout="flow",
        section_key="b",
        char_side=section_char_side_for_key("b"),
        search_dirs=br_roots,
        ai_banner=visuals.section_banners.get("b") if kv_ai_full else None,
        banner_title=assets_b.keyword if not kv_ai_full else None,
        kv_ai_hybrid=kv_hybrid,
        nano_banner_bg=_section_banner_bg_path(assets_dir, "b", visuals.section_banners.get("b")),
    )
    if block_b:
        blocks.append(block_b)
        _log_section_assets("B 核心资源矩阵", assets_b, section_key="b")

    assets_c = parse_section_folder(
        assets_dir / "联动活动火热开启", "联动活动火热开启", kv_path=kv_path, section_key="c",
    )
    n_c = len(assets_c.screenshots)
    layout_c = "flow"
    block_c = _build_section(
        assets_c,
        theme=theme,
        accent="accent_primary",
        layout=layout_c,
        section_key="c",
        char_side=section_char_side_for_key("c"),
        search_dirs=br_roots,
        ai_banner=visuals.section_banners.get("c") if kv_ai_full else None,
        banner_title=assets_c.keyword if not kv_ai_full else None,
        kv_ai_hybrid=kv_hybrid,
        nano_banner_bg=_section_banner_bg_path(assets_dir, "c", visuals.section_banners.get("c")),
    )
    if block_c:
        blocks.append(block_c)
        _log_section_assets("C 联动活动", assets_c, section_key="c")

    assets_d = parse_section_folder(
        assets_dir / "玩家真实好评", "玩家真实好评", kv_path=kv_path, section_key="d",
    )
    layout_d = "grid_2x2" if len(assets_d.screenshots) >= 4 else "auto"
    block_d = _build_section(
        assets_d,
        theme=theme,
        accent="accent_secondary",
        layout=layout_d,
        section_key="d",
        char_side=section_char_side_for_key("d"),
        search_dirs=br_roots,
        ai_banner=visuals.section_banners.get("d") if kv_ai_full else None,
        banner_title=assets_d.keyword if not kv_ai_full else None,
        kv_ai_hybrid=kv_hybrid,
        nano_banner_bg=_section_banner_bg_path(assets_dir, "d", visuals.section_banners.get("d")),
    )
    if block_d:
        blocks.append(block_d)
        _log_section_assets("D 玩家好评", assets_d, section_key="d")

    if footer_path.is_file():
        blocks.append(fit_width(Image.open(footer_path)))

    total_h = sum(b.height for b in blocks) - sum(SECTION_BANNER_CHAR_OVERFLOW_TOP if b.mode == "RGBA" else 0 for b in blocks) + SECTION_GAP * max(0, len(blocks) - 1)
    canvas = Image.new("RGB", (CANVAS_W, max(total_h, 100)), bg_page)
    y = 0
    for i, block in enumerate(blocks):
        if block.mode == "RGBA":
            paste_y = y - SECTION_BANNER_CHAR_OVERFLOW_TOP
            canvas.paste(block.convert("RGB"), (0, paste_y), block.split()[3])
            y += block.height - SECTION_BANNER_CHAR_OVERFLOW_TOP
        else:
            canvas.paste(block, (0, y))
            y += block.height
        if i < len(blocks) - 1:
            y += SECTION_GAP

    safe = re.sub(r'[\\/:*?"<>|]', "_", main_title)[:20]
    out_path = out_dir / f"战报_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    canvas.convert("RGB").save(out_path, "JPEG", quality=92, subsampling=0, optimize=True)
    print(f"[战报] 输出: {out_path} ({CANVAS_W}×{total_h})", flush=True)
    return out_path


def main() -> int:
    import argparse
    import sys

    from scripts.battle_report.env_setup import setup_battle_report_env

    setup_battle_report_env()

    parser = argparse.ArgumentParser(
        description="战报长图合成（1080 宽竖拼；小 Banner 底图默认 MICU）。详见 docs/战报合成使用说明.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 scripts/run_battle_report.py ~/Desktop/战报 \\\n"
            '    --main-title "S2赛季狂欢怪谈" --theme-id rocom_zhanbao\n'
            "或: ./scripts/build_battle_report.sh\n"
        ),
    )
    parser.add_argument("assets_dir", type=Path, nargs="?", default=Path.home() / "Desktop" / "战报")
    parser.add_argument("--main-title", required=True)
    parser.add_argument("--tagline", default="下载赢拯救者平板", help="副标题")
    parser.add_argument("--bar-text", default="首发启幕 联动数据重磅揭晓", help="粉条文案")
    parser.add_argument("--stat-exposure", default="2亿+")
    parser.add_argument("--stat-download", default="100万+")
    parser.add_argument("--stat-group", action="append", default=None, dest="stat_groups",
                        help="多组数据模块：格式 '标题|标签1|值1|标签2|值2'，可重复指定")
    parser.add_argument("--no-stats", action="store_true")
    parser.add_argument("--theme-id", default="desktop_zhanbao")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    stats = None if args.no_stats else [("曝光：", args.stat_exposure), ("下载：", args.stat_download)]
    stat_groups = None
    if args.stat_groups:
        stat_groups = []
        for sg in args.stat_groups:
            parts = [p.strip() for p in sg.split("|")]
            if len(parts) >= 5 and (len(parts) - 1) % 2 == 0:
                title = parts[0]
                pairs = [(parts[i], parts[i+1]) for i in range(1, len(parts), 2)]
                stat_groups.append({"title": title, "stats": pairs})
    compose_from_desktop_folder(
        args.assets_dir,
        main_title=args.main_title,
        tagline=args.tagline,
        bar_text=args.bar_text,
        stats=stats,
        stat_groups=stat_groups,
        theme_id=args.theme_id,
        out_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
