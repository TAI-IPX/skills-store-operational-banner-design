#!/usr/bin/env python3
"""
邮件长图生成：1920 宽竖版，KV + EVENT01~04 四区排版。
色调从 KV 图自动提取，装饰纹理走 Vision 风格分析后 API 生图，
标题使用指定字体，正文使用微软雅黑。

编程调用：
    from email_poster import make_email_poster
    make_email_poster(kv="kv.png", font_title="fonts/title.otf", ...)
"""
from __future__ import annotations

import sys
import os
import io
import re
import base64
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Canvas ──
CANVAS_W = 1920

# ── KV title ──
KV_TITLE_SIZE = 200
KV_SUBTITLE_SIZE = 84
KV_TITLE_SUB_GAP = 20

# ── Section layout ──
SECTION_GAP = 60
SECTION_PAD_LR = 72
SECTION_PAD_TOP = 60
SECTION_PAD_BOTTOM = 60
SECTION_TITLE_SIZE = 72

# ── Event badge ──
BADGE_PAD_X = 40
BADGE_PAD_Y = 16
BADGE_ENUM_SIZE = 28
BADGE_ENUM_PAD = 12
BADGE_RADIUS = 16
BADGE_CONTENT_GAP = 60

# ── Text box ──
TEXT_BOX_PAD_X = 60
TEXT_BOX_PAD_Y = 60
TEXT_BOX_RADIUS = 16

LINE_HEIGHT_RATIO = 1.6

EVENT_DATE_SIZE = 46
EVENT_DESC_SIZE = 42
EVENT_INTRO_SIZE = 36

# ── Cards ──
CARD_GAP = 40
CARD_RADIUS = 16
CARD_NAME_SIZE = 36
CARD_NAME_H = 56
CARD_IMG_PAD = 24

# ── Shadows ──
SHADOW_OFFSET = (8, 12)
SHADOW_BLUR = 8
SHADOW_ALPHA = 200

# ── Frosted frame ──
FRAME_BORDER_WIDTH = 2
FRAME_BLUR_RADIUS = 16
FRAME_TINT_ALPHA = 80

# ── Decor ──
DECOR_MAX_H = 4800

_YAHEI_FONT_PATH: str | None = None


# ══════════════════════════════════════════════════════════════════
#  Utility functions (adapted from changtu/poster.py)
# ══════════════════════════════════════════════════════════════════

def set_yahei_font(path: str | Path) -> None:
    global _YAHEI_FONT_PATH
    _YAHEI_FONT_PATH = str(Path(path).resolve())


def _check_fonts(font_title_path: str | Path, font_yahei_path: str | Path | None) -> None:
    title_path = Path(font_title_path)
    if not title_path.is_file():
        print(f"[邮件长图/字体] 标题字体不存在: {title_path}", file=sys.stderr)
        print("  请使用 --font-title 指定有效的 .otf 或 .ttf 字体文件路径。", file=sys.stderr)
        sys.exit(1)
    if font_yahei_path:
        set_yahei_font(font_yahei_path)
    try:
        _yahei(24)
    except (RuntimeError, OSError) as e:
        print(f"[邮件长图/字体] 微软雅黑加载失败: {e}", file=sys.stderr)
        print("  正文使用微软雅黑，请确保已安装。或使用 --font-yahei 手动指定路径。", file=sys.stderr)
        sys.exit(1)


def _drop_shadow(canvas, _draw,
                 x: int, y: int, w: int, h: int,
                 radius: int,
                 shadow_color: tuple[int, int, int] | None = None) -> None:
    sx, sy = SHADOW_OFFSET
    shadow = Image.new("RGBA", (w + sx * 2 + SHADOW_BLUR * 2,
                                 h + sy * 2 + SHADOW_BLUR * 2), (0, 0, 0, 0))
    fill = (*shadow_color, SHADOW_ALPHA) if shadow_color else (0, 0, 0, SHADOW_ALPHA)
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        [SHADOW_BLUR, SHADOW_BLUR, SHADOW_BLUR + w, SHADOW_BLUR + h],
        radius=radius, fill=fill)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas.paste(shadow, (x - SHADOW_BLUR + sx, y - SHADOW_BLUR + sy), shadow)


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    return int(round(font.size * LINE_HEIGHT_RATIO))


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")[:6]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def _c(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * _c(rgb[0]) + 0.7152 * _c(rgb[1]) + 0.0722 * _c(rgb[2])


def _contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1, l2 = _relative_luminance(c1), _relative_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _lighten(rgb: tuple[int, int, int], amt: float = 0.2) -> tuple[int, int, int]:
    return _mix_rgb(rgb, (255, 255, 255), amt)


def _darken(rgb: tuple[int, int, int], amt: float = 0.3) -> tuple[int, int, int]:
    return _mix_rgb(rgb, (0, 0, 0), amt)


def _load_font(path: str | Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(Path(path).resolve()), size)


def _resolve_yahei_path() -> Path:
    global _YAHEI_FONT_PATH
    if _YAHEI_FONT_PATH:
        p = Path(_YAHEI_FONT_PATH)
        if p.is_file():
            return p
    name = "msyh.ttc"
    alt_names = ["MSYH.TTC", "msyh.ttf", "msyhbd.ttc", "msyhbd.ttf", "Microsoft YaHei.ttf"]
    search_dirs: list[Path] = []
    cwd = Path.cwd()
    search_dirs.append(cwd / "fonts")
    search_dirs.append(cwd)
    search_dirs.append(Path.home() / "Library" / "Fonts")
    search_dirs.append(Path("/Library/Fonts"))
    windir = Path("C:/Windows/Fonts")
    if windir.is_dir():
        search_dirs.append(windir)
    for d in search_dirs:
        if not d.is_dir():
            continue
        for n in [name] + alt_names:
            p = d / n
            if p.is_file():
                _YAHEI_FONT_PATH = str(p.resolve())
                return p
    raise RuntimeError(
        "Microsoft YaHei font not found. "
        "Use set_yahei_font() or --font-yahei to specify the path."
    )


def _yahei(size: int, font_path: str | Path | None = None) -> ImageFont.FreeTypeFont:
    if font_path:
        return ImageFont.truetype(str(Path(font_path).resolve()), size)
    return ImageFont.truetype(str(_resolve_yahei_path()), size)


def _prize_rows(count: int) -> list[int]:
    if count <= 3:
        return [count]
    if count == 4:
        return [2, 2]
    if count == 5:
        return [2, 3]
    if count == 6:
        return [3, 3]
    if count == 7:
        return [3, 4]
    if count == 8:
        return [4, 4]
    rows = []
    while count > 0:
        rows.append(min(4, count))
        count -= min(4, count)
    return rows


NO_LINE_START = set("\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a\u300d\u300f\u3015\u3011\u201d\u2014\u2026")


def _wrap_text(draw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            test = current + ch
            if draw.textbbox((0, 0), test, font=font)[2] > max_w and current:
                if ch in NO_LINE_START:
                    lines.append(current + ch)
                    current = ""
                else:
                    lines.append(current)
                    current = ch
            else:
                current = test
        if current:
            lines.append(current)
    i = 1
    while i < len(lines):
        if len(lines[i]) <= 1 and lines[i] not in NO_LINE_START:
            merged = lines[i - 1] + lines[i]
            if draw.textbbox((0, 0), merged, font=font)[2] <= max_w:
                lines[i - 1] = merged
                lines.pop(i)
                continue
        i += 1
    return lines


def _load_prizes(prize_dir: str, order: list[str] | None = None) -> list[tuple[str, Image.Image]]:
    pdir = Path(prize_dir)
    if not pdir.is_dir():
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    items: dict[str, Path] = {}
    for f in sorted(pdir.iterdir()):
        if f.suffix.lower() in exts and not f.name.startswith("."):
            items[f.stem] = f
    if order:
        ordered: list[tuple[str, Path]] = []
        used = set()
        for kw in order:
            matched = [(k, v) for k, v in items.items() if kw in k and k not in used]
            if matched:
                ordered.extend(matched)
                used.update(k for k, _ in matched)
        for k, v in items.items():
            if k not in used:
                ordered.append((k, v))
                used.add(k)
        items_list = ordered
    else:
        items_list = sorted(items.items())
    result: list[tuple[str, Image.Image]] = []
    for name, path in items_list:
        try:
            img = Image.open(path).convert("RGBA")
            result.append((name, img))
        except Exception as e:
            print(f"  [warn] skip prize {name}: {e}")
    return result


def _trim_transparency(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any():
        return img
    ys = np.where(rows)[0]
    xs = np.where(cols)[0]
    return img.crop((xs[0], ys[0], xs[-1] + 1, ys[-1] + 1))


def _fit_trimmed(img: Image.Image, tw: int, th: int) -> Image.Image:
    trimmed = _trim_transparency(img)
    w, h = trimmed.size
    scale = min(tw / w, th / h)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    result = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    resized = trimmed.resize((nw, nh), Image.Resampling.LANCZOS)
    px = (tw - nw) // 2
    py = (th - nh) // 2
    result.paste(resized, (px, py), resized if resized.mode == "RGBA" else None)
    return result


def _frosted_frame(canvas, draw,
                   x: int, y: int, w: int, h: int,
                   tint_rgb: tuple[int, int, int],
                   border_color: tuple[int, int, int],
                   radius: int, border_width: int) -> None:
    _drop_shadow(canvas, draw, x, y, w, h, radius, shadow_color=border_color)
    region = canvas.crop((x, y, x + w, y + h))
    blurred = region.filter(ImageFilter.GaussianBlur(FRAME_BLUR_RADIUS))
    tint = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tp = tint.load()
    for py in range(h):
        t = py / max(h - 1, 1)
        a = int(FRAME_TINT_ALPHA * (0.6 + 0.4 * t))
        for px in range(w):
            tp[px, py] = (*tint_rgb, a)
    blended = Image.alpha_composite(blurred.convert("RGBA"), tint)
    canvas.paste(blended, (x, y), blended)
    draw.rounded_rectangle(
        [x, y, x + w, y + h], radius=radius, outline=border_color, width=border_width)


# ══════════════════════════════════════════════════════════════════
#  Event badge  (EVENT01 中文标题)
# ══════════════════════════════════════════════════════════════════

def _draw_event_badge(canvas, draw, y: int,
                      enum_label: str, section_title: str,
                      font_enum, font_sec,
                      accent: tuple[int, int, int],
                      border_color: tuple[int, int, int],
                      text_color: tuple[int, int, int]) -> tuple[int, int]:
    """Draw EVENT0X + 中文标题 badge, return (y_after, badge_center_x)."""
    ew = draw.textbbox((0, 0), enum_label, font=font_enum)[2]
    tw = draw.textbbox((0, 0), section_title, font=font_sec)[2]
    gap = BADGE_ENUM_PAD
    total_w = BADGE_PAD_X * 2 + ew + gap + tw
    badge_h = BADGE_PAD_Y * 2 + max(
        font_enum.size, font_sec.size
    )
    bx = (CANVAS_W - total_w) // 2
    by = y

    _drop_shadow(canvas, draw, bx, by, total_w, badge_h, BADGE_RADIUS, shadow_color=accent)
    draw.rounded_rectangle(
        [bx, by, bx + total_w, by + badge_h],
        radius=BADGE_RADIUS, fill=accent, outline=border_color, width=FRAME_BORDER_WIDTH)

    ex = bx + BADGE_PAD_X
    ey = by + (badge_h - font_enum.size) // 2
    draw.text((ex, ey), enum_label, fill=text_color, font=font_enum)

    sx = ex + ew + gap
    sy = by + (badge_h - font_sec.size) // 2
    draw.text((sx, sy), section_title, fill=text_color, font=font_sec)

    return by + badge_h, bx + total_w // 2


# ══════════════════════════════════════════════════════════════════
#  EVENT01: 活动时间 + 圆形图标网格
# ══════════════════════════════════════════════════════════════════

def _draw_date_line(canvas, draw, y: int, event_date: str,
                    font_date, accent: tuple[int, int, int],
                    text_primary: tuple[int, int, int]) -> int:
    """Draw a date line like 2026/7/6-2026/10/10, return y_after."""
    if not event_date.strip():
        return y
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    label = "活动时间："
    label_w = draw.textbbox((0, 0), label, font=font_date)[2]
    date_w = draw.textbbox((0, 0), event_date, font=font_date)[2]
    total_w = label_w + date_w
    sx = (CANVAS_W - total_w) // 2
    sy = y + SECTION_PAD_TOP // 2
    if sx < SECTION_PAD_LR:
        sx = SECTION_PAD_LR
    draw.text((sx, sy), label, fill=accent, font=font_date)
    draw.text((sx + label_w, sy), event_date, fill=text_primary, font=font_date)
    return sy + _line_height(font_date)


def _draw_circular_icon_grid(canvas, draw, y: int,
                             prizes: list[tuple[str, Image.Image]],
                             font_name,
                             accent: tuple[int, int, int],
                             bg_card: tuple[int, int, int],
                             border_color: tuple[int, int, int],
                             text_secondary: tuple[int, int, int]) -> int:
    """Draw prizes as circular icons in a grid, return y_after."""
    if not prizes:
        return y
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    rows = _prize_rows(len(prizes))
    max_row = max(rows)
    card_w = (content_w - (max_row - 1) * CARD_GAP) // max_row
    icon_size = min(card_w - CARD_IMG_PAD * 2, card_w - CARD_NAME_H, 320)
    name_h = CARD_NAME_H
    card_h = icon_size + CARD_IMG_PAD + name_h

    cy = y
    idx = 0
    for row_items in rows:
        total_w = row_items * (card_w + CARD_GAP) - CARD_GAP
        rx = (CANVAS_W - total_w) // 2
        for _ in range(row_items):
            if idx >= len(prizes):
                break
            name, pimg = prizes[idx]
            # circular clip
            icon_img = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
            mask = Image.new("L", (icon_size, icon_size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, icon_size, icon_size], fill=255)
            fitted = _fit_trimmed(pimg, icon_size, icon_size)
            icon_img.paste(fitted, (0, 0), mask)
            # card shadow + bg
            _drop_shadow(canvas, draw, rx, cy, card_w, card_h, CARD_RADIUS, shadow_color=border_color)
            card_fill = Image.new("RGBA", (card_w, card_h), (*bg_card, 180))
            canvas.paste(card_fill, (rx, cy), card_fill)
            draw.rounded_rectangle(
                [rx, cy, rx + card_w, cy + card_h],
                radius=CARD_RADIUS, outline=border_color, width=FRAME_BORDER_WIDTH)
            # icon centered in top portion
            ix = rx + (card_w - icon_size) // 2
            iy = cy + CARD_IMG_PAD
            canvas.paste(icon_img, (ix, iy), icon_img)
            # name below
            name_w = draw.textbbox((0, 0), name, font=font_name)[2]
            nx = rx + (card_w - name_w) // 2
            ny = iy + icon_size + (name_h - font_name.size) // 2
            if name_w > card_w - 8:
                while name_w > card_w - 8 and len(name) > 1:
                    name = name[:-1]
                    name_w = draw.textbbox((0, 0), name + "…", font=font_name)[2]
                name += "…"
                nx = rx + (card_w - name_w) // 2
            draw.text((nx, ny), name, fill=text_secondary, font=font_name)
            rx += card_w + CARD_GAP
            idx += 1
        cy += card_h + CARD_GAP
    return cy


# ══════════════════════════════════════════════════════════════════
#  EVENT02: 参与方法 (文字 + 截图)
# ══════════════════════════════════════════════════════════════════

def _draw_method_section(canvas, draw, y: int,
                         method_texts: list[str],
                         screenshots: list[tuple[str, Image.Image]],
                         font_desc,
                         accent: tuple[int, int, int],
                         bg_card: tuple[int, int, int],
                         border_color: tuple[int, int, int],
                         text_secondary: tuple[int, int, int]) -> int:
    """EVENT02: stacked rows of text + screenshot. Returns y_after."""
    if not method_texts:
        return y
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    text_w = int(content_w * 0.52)
    img_w = content_w - text_w - CARD_GAP

    cy = y
    for i, text in enumerate(method_texts):
        lines = _wrap_text(draw, text, font_desc, text_w)
        lh = _line_height(font_desc)
        text_h = lh * len(lines)
        shot_img = screenshots[i][1] if i < len(screenshots) else None
        if shot_img:
            shot_h = int(img_w * shot_img.height / max(shot_img.width, 1))
            row_h = max(text_h, shot_h) + TEXT_BOX_PAD_Y * 2
        else:
            shot_h = 0
            row_h = text_h + TEXT_BOX_PAD_Y * 2

        # Frosted frame for the whole row
        _frosted_frame(canvas, draw,
                       SECTION_PAD_LR, cy,
                       content_w, row_h,
                       bg_card, border_color,
                       TEXT_BOX_RADIUS, FRAME_BORDER_WIDTH)

        # Text
        tx = SECTION_PAD_LR + TEXT_BOX_PAD_X
        ty = cy + (row_h - text_h) // 2
        for li, line in enumerate(lines):
            draw.text((tx, ty + li * lh), line, fill=text_secondary, font=font_desc)

        # Screenshot
        if shot_img:
            sr = shot_img.resize((img_w, shot_h), Image.Resampling.LANCZOS)
            six = SECTION_PAD_LR + text_w + CARD_GAP
            siy = cy + (row_h - shot_h) // 2
            ss = Image.new("RGBA", (img_w, shot_h), (0, 0, 0, 0))
            sm = Image.new("L", (img_w, shot_h), 0)
            ImageDraw.Draw(sm).rounded_rectangle(
                [0, 0, img_w, shot_h], radius=CARD_RADIUS, fill=255)
            ssr = sr.convert("RGBA") if sr.mode != "RGBA" else sr
            ss = Image.composite(ssr, ss, sm)
            canvas.paste(ss, (six, siy), ss)

        cy += row_h + CARD_GAP
    return cy


# ══════════════════════════════════════════════════════════════════
#  EVENT03: 往期中奖 (方形卡片网格)
# ══════════════════════════════════════════════════════════════════

def _draw_history_cards(canvas, draw, y: int,
                        items: list[tuple[str, Image.Image]],
                        font_name,
                        accent: tuple[int, int, int],
                        bg_card: tuple[int, int, int],
                        border_color: tuple[int, int, int],
                        text_secondary: tuple[int, int, int]) -> int:
    """EVENT03: screenshot cards with name labels in a grid. Returns y_after."""
    if not items:
        return y
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    rows = _prize_rows(len(items))
    max_row = max(rows)
    card_w = (content_w - (max_row - 1) * CARD_GAP) // max_row
    img_ratio = 0.72
    img_h = int(card_w * img_ratio)
    name_h = CARD_NAME_H
    card_h = img_h + name_h

    cy = y
    idx = 0
    for row_items in rows:
        total_w = row_items * (card_w + CARD_GAP) - CARD_GAP
        rx = (CANVAS_W - total_w) // 2
        for _ in range(row_items):
            if idx >= len(items):
                break
            name, pimg = items[idx]
            _drop_shadow(canvas, draw, rx, cy, card_w, card_h, CARD_RADIUS, shadow_color=border_color)
            card_fill = Image.new("RGBA", (card_w, card_h), (*bg_card, 180))
            canvas.paste(card_fill, (rx, cy), card_fill)
            draw.rounded_rectangle(
                [rx, cy, rx + card_w, cy + card_h],
                radius=CARD_RADIUS, outline=border_color, width=FRAME_BORDER_WIDTH)
            # image
            fitted = _fit_trimmed(pimg, card_w - CARD_IMG_PAD * 2, img_h - CARD_IMG_PAD * 2)
            fw, fh = fitted.size
            fx = rx + (card_w - fw) // 2
            fy = cy + (img_h - fh) // 2
            canvas.paste(fitted, (fx, fy), fitted)
            # name bar with gradient
            bar = Image.new("RGBA", (card_w, name_h), (0, 0, 0, 0))
            bp = bar.load()
            for ppx in range(name_h):
                a_val = max(0, 200 - int(ppx * 200 / name_h))
                for ppy in range(card_w):
                    bp[ppy, ppx] = (*accent, a_val)
            canvas.paste(bar, (rx, cy + img_h), bar)
            # name text
            text = name
            nw = draw.textbbox((0, 0), text, font=font_name)[2]
            if nw > card_w - 8:
                while nw > card_w - 8 and len(text) > 1:
                    text = text[:-1]
                    nw = draw.textbbox((0, 0), text + "…", font=font_name)[2]
                text += "…"
            nx = rx + (card_w - nw) // 2
            ny = cy + img_h + (name_h - font_name.size) // 2
            draw.text((nx, ny), text, fill=text_secondary, font=font_name)
            rx += card_w + CARD_GAP
            idx += 1
        cy += card_h + CARD_GAP
    return cy


# ══════════════════════════════════════════════════════════════════
#  EVENT04: 游戏介绍 (磨砂框文字卡)
# ══════════════════════════════════════════════════════════════════

def _draw_intro_section(canvas, draw, y: int,
                        intro_text: str,
                        font_intro,
                        bg_card: tuple[int, int, int],
                        border_color: tuple[int, int, int],
                        text_secondary: tuple[int, int, int]) -> int:
    """EVENT04: frosted frame with game description. Returns y_after."""
    if not intro_text.strip():
        return y
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    text_box_w = content_w - TEXT_BOX_PAD_X * 2
    lines = _wrap_text(draw, intro_text, font_intro, text_box_w)
    lh = _line_height(font_intro)
    text_h = lh * len(lines)
    box_h = text_h + TEXT_BOX_PAD_Y * 2
    bx = SECTION_PAD_LR
    by = y

    _frosted_frame(canvas, draw, bx, by, content_w, box_h,
                   bg_card, border_color,
                   TEXT_BOX_RADIUS, FRAME_BORDER_WIDTH)
    ty = by + (box_h - text_h) // 2
    for li, line in enumerate(lines):
        draw.text((bx + TEXT_BOX_PAD_X, ty + li * lh), line,
                  fill=text_secondary, font=font_intro)
    return by + box_h


# ══════════════════════════════════════════════════════════════════
#  KV title
# ══════════════════════════════════════════════════════════════════

def _draw_kv_title(draw, kv_display_h: int,
                   main_title: str, sub_title: str,
                   font_title, font_sub) -> None:
    sub_bottom = kv_display_h - 80
    text_y = sub_bottom - KV_SUBTITLE_SIZE - KV_TITLE_SUB_GAP - KV_TITLE_SIZE
    fw = draw.textbbox((0, 0), main_title, font=font_title)[2]
    draw.text(((CANVAS_W - fw) // 2, text_y), main_title,
              fill=(255, 255, 255), font=font_title)
    sy = text_y + KV_TITLE_SIZE + KV_TITLE_SUB_GAP
    fw2 = draw.textbbox((0, 0), sub_title, font=font_sub)[2]
    draw.text(((CANVAS_W - fw2) // 2, sy), sub_title,
              fill=(255, 255, 255), font=font_sub)


# ══════════════════════════════════════════════════════════════════
#  KV Vision 风格分析 (OpenAI chat/completions protocol)
# ══════════════════════════════════════════════════════════════════

def _vision_analyze_kv_style(kv_path: Path, out_dir: Path) -> dict:
    """使用 OpenAI chat/completions 协议分析 KV 风格，缓存到 JSON。"""
    cache = out_dir / "kv_style.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    api_key = ""
    base_url = ""
    # 优先使用 PackyGPT（支持 chat/completions），其次 MicuAPI，其次 centos.hk
    packygpt_key = os.environ.get("PACKYGPT_API_KEY", "").strip()
    if packygpt_key and packygpt_key.startswith("sk-"):
        api_key = packygpt_key
        base_url = "https://www.packyapi.com"
    if not api_key:
        micu_key = os.environ.get("MICUGEMINI_API_KEY", "").strip()
        if micu_key and micu_key.startswith("sk-"):
            api_key = micu_key
            base_url = "https://www.micuapi.ai"
    if not api_key:
        micu_key2 = os.environ.get("MICUAPI_API_KEY", "").strip()
        if micu_key2 and micu_key2.startswith("sk-"):
            api_key = micu_key2
            base_url = "https://www.micuapi.ai"
    if not api_key:
        for key_var in ("XINGCHENGGPT_API_KEY", "XINGCHENGEMINI_API_KEY", "PACKY7S_API_KEY", "GEMINI_API_KEY"):
            k = os.environ.get(key_var, "").strip()
            if k and k.startswith("sk-"):
                api_key = k
                break
    if not api_key:
        print("[邮件长图/Vision] 未找到可用的 Gemini Key，使用默认风格描述", flush=True)
        return _default_style_info()

    # Pick base_url matching the selected key's backend (only if not already set)
    if not base_url:
        if os.environ.get("XINGCHENGGPT_API_KEY", "").strip():
            base_url = os.environ.get("XINGCHENGGPT_BASE_URL", "").strip()
    if not base_url:
        if os.environ.get("XINGCHENGEMINI_API_KEY", "").strip():
            base_url = os.environ.get("XINGCHENGEMINI_BASE_URL", "").strip()
    if not base_url:
        base_url = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
    if not base_url:
        base_url = "https://api.centos.hk"
    base_url = base_url.rstrip("/")

    # Encode KV image to base64
    with Image.open(kv_path) as im:
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        kv_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = """You are a game art style analyst. Analyze this KV key visual image and output ONLY a JSON object (no markdown, no explanation):

{
  "art_style": "选择最匹配的一项: realistic / anime / cyberpunk / guofeng_chinese / painterly / Q_style / sci_fi / fantasy / minimalist / dark_gothic / pop_art / cel_shaded",
  "composition": "选择最匹配的一项: center_focus / asymmetric_left / asymmetric_right / symmetric / diagonal / scattered / radial / rule_of_thirds",
  "lighting": "选择最匹配的一项: bottom_spotlight / side_rim_light / soft_diffuse / hard_key_light / neon_glow / volumetric_god_rays / dramatic_chiaroscuro / flat_even",
  "mood": "选择最匹配的一项: epic_heroic / dark_mysterious / joyful_celebration / serene_narrative / intense_battle / futuristic_tech / magical_fantasy / cute_playful",
  "motifs": ["列出 2-5 个视觉母题，如 crystal, magic_circle, fire, tech_lines, ink_wash, neon_grid, particle_splash, energy_beam, hologram, smoke, water_ripple, mechanical_gear, feather, nebula"],
  "color_mood": "选择最匹配的一项: warm_gold_orange / cool_blue_purple / high_saturation_clash / muted_earth / monochrome / pastel_soft / neon_dark / split_complementary",
  "depth_style": "选择最匹配的一项: shallow_bokeh / deep_atmospheric / flat_graphic / layered_parallax"
}"""

    body = json.dumps({
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{kv_b64}"}}
        ]}],
        "temperature": 0.2,
        "max_tokens": 512,
    }).encode()

    url = f"{base_url}/v1/chat/completions"
    style_info = _default_style_info()
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                m = re.search(r"\{[\s\S]*\}", content)
                if m:
                    style_info = json.loads(m.group())
                    break
        except Exception as e:
            detail = str(e)[:200]
            if hasattr(e, "code"):
                detail = f"HTTP {e.code}: {e.reason} | {detail}"
            print(f"[邮件长图/Vision] 请求失败 (attempt {attempt+1}): {detail}", flush=True)
            if attempt == 0:
                import time
                time.sleep(2)

    # Cascade save: keep last 2 snapshots
    if style_info != _default_style_info():
        if cache.is_file():
            c1 = cache.with_suffix(".json.1")
            c2 = cache.with_suffix(".json.2")
            if c2.is_file():
                c2.unlink(missing_ok=True)
            if c1.is_file():
                c1.rename(c2)
            cache.rename(c1)
        cache.write_text(json.dumps(style_info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[邮件长图/Vision] KV 风格分析: art={style_info.get('art_style')} "
            f"compo={style_info.get('composition')} light={style_info.get('lighting')} "
            f"mood={style_info.get('mood')} motifs={style_info.get('motifs')}",
            flush=True,
        )
    else:
        print("[邮件长图/Vision] 未返回有效 JSON，使用默认风格描述", flush=True)

    return style_info


def _default_style_info() -> dict:
    return {
        "art_style": "fantasy",
        "composition": "center_focus",
        "lighting": "soft_diffuse",
        "mood": "epic_heroic",
        "motifs": [],
        "color_mood": "warm_gold_orange",
        "depth_style": "shallow_bokeh",
    }


# ══════════════════════════════════════════════════════════════════
#  Decoration background (Vision analysis → API t2i)
# ══════════════════════════════════════════════════════════════════

def _build_decor_prompt(style_info: dict, theme: dict) -> str:
    art_style_en = {
        "realistic": "photorealistic cinematic style",
        "anime": "Japanese anime cel style",
        "cyberpunk": "cyberpunk neon aesthetic",
        "guofeng_chinese": "Chinese guofeng ink-painting fusion",
        "painterly": "painterly concept art with visible brush strokes",
        "Q_style": "chibi Q-style cute illustrations",
        "sci_fi": "sci-fi futuristic technology aesthetic",
        "fantasy": "high fantasy epic style",
        "minimalist": "minimalist clean geometric design",
        "dark_gothic": "dark gothic ornate style",
        "pop_art": "pop art bold graphic comic style",
        "cel_shaded": "cel-shaded toon render style",
    }.get(style_info.get("art_style", ""), "fantasy game art style")

    mood_en = {
        "epic_heroic": "epic and heroic atmosphere",
        "dark_mysterious": "dark mysterious tension",
        "joyful_celebration": "joyful festive celebration energy",
        "serene_narrative": "serene calm tranquility",
        "intense_battle": "intense battle action",
        "futuristic_tech": "futuristic high-tech vibe",
        "magical_fantasy": "magical enchanting wonder",
        "cute_playful": "cute playful charm",
    }.get(style_info.get("mood", ""), "magical fantasy atmosphere")

    color_mood_en = {
        "warm_gold_orange": "warm gold-orange-amber tones",
        "cool_blue_purple": "cool blue-cyan-purple tones",
        "high_saturation_clash": "vivid high-saturation colors",
        "muted_earth": "muted earthy desaturated tones",
        "monochrome": "monochrome single-hue scheme",
        "pastel_soft": "soft pastel dreamy palette",
        "neon_dark": "dark with neon accent pops",
        "split_complementary": "dual-color split-complementary scheme",
    }.get(style_info.get("color_mood", ""), "cool blue-purple gradient")

    motifs = style_info.get("motifs", [])
    motif_str = ", ".join(motifs) if motifs else "flowing cloud swirls, gentle water ripples"

    a1 = theme.get("accent_bright", "#4488FF")
    a2 = theme.get("accent_bright_alt", "#88CCFF")

    return (
        f"Design a seamless decorative background texture for a game event poster, "
        f"in {art_style_en}, with {mood_en}. "
        f"Color palette: {color_mood_en}, accented with {a1} and {a2} subtle glow. "
        f"Dominant decorative elements: {motif_str} — woven elegantly throughout the canvas "
        f"as flowing abstract patterns, soft gradients, and gentle atmospheric lighting. "
        f"Clean premium UI-background quality, suitable for text overlay. "
        f"NO characters, NO faces, NO text, NO logos, NO hard edges. "
        f"Purely abstract decorative atmosphere. Film grain texture."
    )


def _generate_decor_bg(height: int, theme: dict, style_info: dict,
                       output_path: Path) -> Image.Image:
    from scripts.changtu.micu_image_gen import run_micu_t2i

    prompt = _build_decor_prompt(style_info, theme)
    h16 = (height + 15) // 16 * 16
    print(f"[邮件长图/装饰] 生成装饰背景 1920x{h16}...", flush=True)
    result = run_micu_t2i(prompt, output_path, width=1920, height=h16)
    if result is None:
        raise RuntimeError("[邮件长图/装饰] API 装饰背景生成失败")
    bg = Image.open(result).convert("RGB")
    if bg.size != (CANVAS_W, height):
        bg = bg.resize((CANVAS_W, height), Image.Resampling.LANCZOS)
    return bg


# ══════════════════════════════════════════════════════════════════
#  Height calculation (pre-flight)
# ══════════════════════════════════════════════════════════════════

def _calc_event01_height(draw, event_date: str, prizes: list,
                         font_date, font_name) -> int:
    h = BADGE_PAD_Y * 2 + max(BADGE_ENUM_SIZE, SECTION_TITLE_SIZE)  # badge
    h += BADGE_CONTENT_GAP
    if event_date.strip():
        h += SECTION_PAD_TOP // 2 + _line_height(font_date)
    if prizes:
        rows = _prize_rows(len(prizes))
        content_w = CANVAS_W - SECTION_PAD_LR * 2
        card_w = (content_w - (max(rows) - 1) * CARD_GAP) // max(rows)
        icon_size = min(card_w - CARD_IMG_PAD * 2, 320)
        card_h = icon_size + CARD_IMG_PAD + CARD_NAME_H
        h += (card_h + CARD_GAP) * len(rows) - CARD_GAP + SECTION_PAD_BOTTOM
    else:
        h += SECTION_PAD_BOTTOM
    return h


def _calc_event02_height(draw, method_texts: list[str], screenshots: list,
                         font_desc) -> int:
    h = BADGE_PAD_Y * 2 + max(BADGE_ENUM_SIZE, SECTION_TITLE_SIZE)
    h += BADGE_CONTENT_GAP
    if not method_texts:
        return h + SECTION_PAD_BOTTOM
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    text_w = int(content_w * 0.52)
    img_w = content_w - text_w - CARD_GAP
    for i, text in enumerate(method_texts):
        lines = _wrap_text(draw, text, font_desc, text_w)
        text_h = _line_height(font_desc) * len(lines)
        shot_img = screenshots[i][1] if i < len(screenshots) else None
        if shot_img:
            shot_h = int(img_w * shot_img.height / max(shot_img.width, 1))
            row_h = max(text_h, shot_h) + TEXT_BOX_PAD_Y * 2
        else:
            row_h = text_h + TEXT_BOX_PAD_Y * 2
        h += row_h + CARD_GAP
    h -= CARD_GAP
    h += SECTION_PAD_BOTTOM
    return h


def _calc_event03_height(items: list) -> int:
    h = BADGE_PAD_Y * 2 + max(BADGE_ENUM_SIZE, SECTION_TITLE_SIZE)
    h += BADGE_CONTENT_GAP
    if not items:
        return h + SECTION_PAD_BOTTOM
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    rows = _prize_rows(len(items))
    card_w = (content_w - (max(rows) - 1) * CARD_GAP) // max(rows)
    img_ratio = 0.72
    card_h = int(card_w * img_ratio) + CARD_NAME_H
    h += (card_h + CARD_GAP) * len(rows) - CARD_GAP + SECTION_PAD_BOTTOM
    return h


def _calc_event04_height(draw, intro_text: str, font_intro) -> int:
    h = BADGE_PAD_Y * 2 + max(BADGE_ENUM_SIZE, SECTION_TITLE_SIZE)
    h += BADGE_CONTENT_GAP
    if not intro_text.strip():
        return h + SECTION_PAD_BOTTOM
    content_w = CANVAS_W - SECTION_PAD_LR * 2
    text_box_w = content_w - TEXT_BOX_PAD_X * 2
    lines = _wrap_text(draw, intro_text, font_intro, text_box_w)
    text_h = _line_height(font_intro) * len(lines)
    h += text_h + TEXT_BOX_PAD_Y * 2 + SECTION_PAD_BOTTOM
    return h


# ══════════════════════════════════════════════════════════════════
#  make_email_poster  — 主入口
# ══════════════════════════════════════════════════════════════════

def make_email_poster(
    kv: str | Path,
    font_title: str | Path,
    *,
    font_yahei: str | Path | None = None,
    main_title: str = "",
    sub_title: str = "",
    event_date: str = "",
    prize_dir: str = "",
    prize_order: list[str] | None = None,
    method_desc: str = "",
    method_dir: str = "",
    history_dir: str = "",
    history_order: list[str] | None = None,
    intro_text: str = "",
    output: str | Path = "output/邮件长图.jpg",
) -> Path:
    """Generate the email poster (1920px wide, 4-section layout)."""
    # ── Fonts ──
    _check_fonts(font_title, font_yahei)
    font_title_big = _load_font(font_title, KV_TITLE_SIZE)
    font_sec = _load_font(font_title, SECTION_TITLE_SIZE)
    font_enum_local = _yahei(BADGE_ENUM_SIZE)
    font_date = _yahei(EVENT_DATE_SIZE)
    font_desc = _yahei(EVENT_DESC_SIZE)
    font_intro = _yahei(EVENT_INTRO_SIZE)
    font_name = _yahei(CARD_NAME_SIZE)

    # ── KV ──
    kv_path = Path(kv).resolve()
    kv_img = Image.open(kv_path).convert("RGB")
    kv_scale = CANVAS_W / kv_img.width
    kv_resized = kv_img.resize((CANVAS_W, int(kv_img.height * kv_scale)), Image.Resampling.LANCZOS)
    kv_display_h = kv_resized.height

    # ── Theme + Style ──
    from scripts.changtu.color_extract import extract_theme_from_kv

    theme = extract_theme_from_kv(kv_path)
    bg_page = _hex_rgb(theme.get("bg_page", "#1A1A2E"))
    accent = _hex_rgb(theme.get("accent_bright", "#FF6B35"))
    accent_primary = _hex_rgb(theme.get("accent_primary", "#FF6B35"))
    border_color = _hex_rgb(theme.get("accent_secondary", "#E755BE"))
    text_primary = _hex_rgb(theme.get("text_primary", "#FFFFFF"))
    text_secondary = _hex_rgb(theme.get("text_secondary", "#AAAAAA"))
    bg_card = _hex_rgb(theme.get("bg_card", "#F2F2F2"))
    bg_card_dark = _hex_rgb(theme.get("bg_card_dark", "#2A2A3E"))

    accent_text_white = _contrast_ratio(accent, (255, 255, 255)) >= 3.0
    badge_text_color = (255, 255, 255) if accent_text_white else (51, 51, 51)

    # ── Vision KV 风格分析：直接走 xingchengemini / packy 等 Gemini Key 的 OpenAI chat/completions 协议
    out_dir = Path(output).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    style_info = _vision_analyze_kv_style(kv_path, out_dir)

    # ── Load materials ──
    prizes = _load_prizes(prize_dir, prize_order)
    method_screenshots = _load_prizes(method_dir)
    history_items = _load_prizes(history_dir, history_order)
    method_texts = [t.strip() for t in method_desc.split("|") if t.strip()] if method_desc else []

    # ── Pre-calc heights ──
    draw_dummy = ImageDraw.Draw(Image.new("RGB", (CANVAS_W, 100)))
    s1_h = _calc_event01_height(draw_dummy, event_date, prizes, font_date, font_name)
    s2_h = _calc_event02_height(draw_dummy, method_texts, method_screenshots, font_desc)
    s3_h = _calc_event03_height(history_items)
    s4_h = _calc_event04_height(draw_dummy, intro_text, font_intro)

    section_total_h = s1_h + SECTION_GAP + s2_h + SECTION_GAP + s3_h + SECTION_GAP + s4_h
    canvas_h = kv_display_h + SECTION_GAP + section_total_h

    # ── Generate decor background ──
    decor_path = out_dir / "_email_decor_bg.png"
    try:
        decor_bg = _generate_decor_bg(canvas_h, theme, style_info, decor_path)
    except Exception as e:
        print(f"[邮件长图/装饰] 生成失败: {e}，使用纯色渐变兜底", flush=True)
        decor_bg = Image.new("RGB", (CANVAS_W, canvas_h), bg_page)

    # ── Canvas ──
    canvas = decor_bg.convert("RGBA")
    kv_rgba = kv_resized.convert("RGBA")
    canvas.paste(kv_rgba, (0, 0), kv_rgba)
    draw = ImageDraw.Draw(canvas)

    # ── KV title ──
    if main_title or sub_title:
        _draw_kv_title(draw, kv_display_h, main_title, sub_title,
                       font_title_big, _yahei(KV_SUBTITLE_SIZE))

    # ── Subdue overlay below KV ──
    overlay = Image.new("RGBA", (CANVAS_W, section_total_h), (0, 0, 0, 45))
    canvas.paste(overlay, (0, kv_display_h + SECTION_GAP), overlay)

    sy = kv_display_h + SECTION_GAP

    # ── EVENT01: 活动时间 ──
    badge_y, _ = _draw_event_badge(canvas, draw, sy, "EVENT01", "活动时间",
                                   font_enum_local, font_sec,
                                   accent, border_color, badge_text_color)
    cy = badge_y + BADGE_CONTENT_GAP
    if event_date.strip():
        cy = _draw_date_line(canvas, draw, cy, event_date, font_date,
                             accent, text_primary)
    if prizes:
        cy = _draw_circular_icon_grid(canvas, draw, cy, prizes, font_name,
                                      accent, bg_card_dark, border_color, text_secondary)
    sy += s1_h + SECTION_GAP

    # ── EVENT02: 参与方法 ──
    badge_y, _ = _draw_event_badge(canvas, draw, sy, "EVENT02", "参与方法",
                                   font_enum_local, font_sec,
                                   accent, border_color, badge_text_color)
    cy = badge_y + BADGE_CONTENT_GAP
    if method_texts:
        cy = _draw_method_section(canvas, draw, cy, method_texts,
                                  method_screenshots, font_desc,
                                  accent, bg_card_dark, border_color, text_secondary)
    sy += s2_h + SECTION_GAP

    # ── EVENT03: 往期中奖 ──
    badge_y, _ = _draw_event_badge(canvas, draw, sy, "EVENT03", "往期中奖",
                                   font_enum_local, font_sec,
                                   accent, border_color, badge_text_color)
    cy = badge_y + BADGE_CONTENT_GAP
    if history_items:
        cy = _draw_history_cards(canvas, draw, cy, history_items, font_name,
                                 accent, bg_card_dark, border_color, text_secondary)
    sy += s3_h + SECTION_GAP

    # ── EVENT04: 游戏介绍 ──
    badge_y, _ = _draw_event_badge(canvas, draw, sy, "EVENT04", "游戏介绍",
                                   font_enum_local, font_sec,
                                   accent, border_color, badge_text_color)
    cy = badge_y + BADGE_CONTENT_GAP
    if intro_text.strip():
        cy = _draw_intro_section(canvas, draw, cy, intro_text, font_intro,
                                 bg_card, border_color, text_secondary)

    # ── Save ──
    out_path = Path(output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"[邮件长图] 已保存: {out_path}", flush=True)
    return out_path
