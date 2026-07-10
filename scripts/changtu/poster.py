#!/usr/bin/env python3
"""
活动长图生成：1080 宽竖版，KV + 福利区 + 规则区。
色调从 KV 图自动提取，标题使用指定字体，正文使用微软雅黑。

编程调用：
    from activity_poster import make_poster
    make_poster(kv="kv.jpg", main_title="标题", ...)

CLI 调用：
    python -m activity_poster.poster --kv kv.jpg --font-title font.ttf ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .color_extract import extract_theme_from_kv

CANVAS_W = 1080

KV_TITLE_SIZE = 120
KV_SUBTITLE_SIZE = 48
KV_TITLE_SUB_GAP = 12

SECTION_GAP = 90
SECTION_PAD_LR = 40
SECTION_PAD_TOP = 55
SECTION_PAD_BOTTOM = 55
SECTION_TITLE_SIZE = 40
BADGE_PAD_X = 28
BADGE_PAD_Y = 10
BADGE_RADIUS = 10
BADGE_CONTENT_GAP = 70
DESC_PRIZE_GAP = 42
TEXT_BOX_PAD_X = 40
TEXT_BOX_PAD_Y = 40
TEXT_BOX_RADIUS = 12
TEXT_BOX_BG_ALPHA = 120
CARD_BG_ALPHA = 240
CARD_SEPARATOR_ALPHA = 60
FRAME_BORDER_WIDTH = 1

LINE_HEIGHT_RATIO = 1.6

EVENT_DATE_SIZE = 26
EVENT_DESC_SIZE = 24
EVENT_DATE_DESC_GAP = 30

CARD_GAP = 32
CARD_RADIUS = 12
CARD_NAME_SIZE = 20
CARD_NAME_H = 40

RULES_TITLE_SIZE = 24
RULES_BLOCK_GAP = 40

SHADOW_OFFSET = (5, 8)
SHADOW_BLUR = 6
SHADOW_ALPHA = 200

_YAHEI_FONT_PATH: str | None = None


def set_yahei_font(path: str | Path) -> None:
    global _YAHEI_FONT_PATH
    _YAHEI_FONT_PATH = str(Path(path).resolve())


def _check_fonts(font_title_path: str | Path, font_yahei_path: str | Path | None) -> None:
    title_path = Path(font_title_path)
    if not title_path.is_file():
        print(f"[长图/字体] 标题字体不存在: {title_path}", file=sys.stderr)
        print("  请使用 --font-title 指定有效的 .otf 或 .ttf 字体文件路径。", file=sys.stderr)
        sys.exit(1)

    if font_yahei_path:
        set_yahei_font(font_yahei_path)

    try:
        _yahei(24)
    except (RuntimeError, OSError) as e:
        print(f"[长图/字体] 微软雅黑加载失败: {e}", file=sys.stderr)
        print("  活动长图正文使用微软雅黑，请确保已安装。", file=sys.stderr)
        print("  或使用 --font-yahei 手动指定路径。", file=sys.stderr)
        sys.exit(1)


def _drop_shadow(canvas, draw,
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
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


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


def _wrap_text(draw, text: str, font: ImageFont.FreeTypeFont,
               max_w: int) -> list[str]:
    NO_LINE_START = set("\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a\u300d\u300f\u3015\u3011\u201d\u2014\u2026")
    lines = []
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


def _load_prizes(prize_dir: str,
                 order: list[str] | None = None) -> list[tuple[str, Image.Image]]:
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


def _round_img(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, img.size[0], img.size[1]], radius=radius, fill=255)
    if img.mode == "RGBA":
        return Image.composite(img, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask)
    return Image.composite(img.convert("RGBA"), Image.new("RGBA", img.size, (0, 0, 0, 0)), mask)


LIMIT_TAG_SIZE = 18


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


def _build_micu_prompt(theme: dict, *, kv_scene: str = "",
                       game_name: str = "活动", game_style: str = "") -> str:
    bg = theme.get("bg_page", "#1A1B1E")
    a1 = theme.get("accent_bright", "#FF44CA")
    a2 = theme.get("accent_bright_alt", "#2DFF3F")
    scene_part = f"场景：{kv_scene}。" if kv_scene else ""
    style_part = f"风格：{game_style}。" if game_style else ""
    return (
        f"为游戏「{game_name}」活动制作下半部分背景画布，从上方KV图自然延续。{scene_part}"
        f"主色调从{bg}过渡，点缀{a1}和{a2}的柔和光效。"
        f"{style_part}"
        f"细腻纹理。不要人物、不要文字、不要logo。活动风格，氛围与参考图一致。"
    )


def _generate_section_bg(height: int, theme: dict, kv_scene: str,
                         game_name: str, game_style: str,
                         output_path: Path) -> Image.Image:
    from .micu_image_gen import run_micu_t2i
    prompt = _build_micu_prompt(theme, kv_scene=kv_scene,
                                game_name=game_name, game_style=game_style)
    w16 = (CANVAS_W + 15) // 16 * 16
    h16 = (height + 15) // 16 * 16
    print(f"[T2I] generating section background {w16}x{h16}...", flush=True)
    result = run_micu_t2i(prompt, output_path, width=w16, height=h16)
    if result is None:
        raise RuntimeError("AI background generation failed")
    bg = Image.open(result).convert("RGB")
    if bg.size != (CANVAS_W, height):
        bg = bg.resize((CANVAS_W, height), Image.Resampling.LANCZOS)
    return bg


def make_poster(
    kv: str | Path,
    font_title: str | Path,
    *,
    font_yahei: str | Path | None = None,
    main_title: str = "",
    sub_title: str = "",
    section1: str = "福利活动",
    section2: str = "活动规则",
    event_date: str = "",
    event_desc: str = "",
    prize_dir: str = "",
    prize_order: list[str] | None = None,
    rules: list[str] | None = None,
    kv_scene: str = "",
    game_name: str = "活动",
    game_style: str = "",
    output: str | Path = "output/活动长图.jpg",
) -> Path:
    _check_fonts(font_title, font_yahei)
    if font_yahei:
        set_yahei_font(font_yahei)

    font_title_big = _load_font(font_title, KV_TITLE_SIZE)
    font_title_sec = _load_font(font_title, SECTION_TITLE_SIZE)
    font_sub = _yahei(KV_SUBTITLE_SIZE)
    font_date = _yahei(EVENT_DATE_SIZE)
    font_desc = _yahei(EVENT_DESC_SIZE)
    font_rules = _yahei(RULES_TITLE_SIZE)
    font_name = _yahei(CARD_NAME_SIZE)

    kv_path = Path(kv)
    if not kv_path.is_file():
        raise FileNotFoundError(f"KV file not found: {kv_path}")
    kv_img = Image.open(kv_path).convert("RGB")
    kv_scale = CANVAS_W / kv_img.width
    kv_h = int(kv_img.height * kv_scale)
    kv_resized = kv_img.resize((CANVAS_W, kv_h), Image.Resampling.LANCZOS)
    kv_display_h = kv_h

    print(f"[theme] extracting from {kv_path.name}...", flush=True)
    try:
        theme = extract_theme_from_kv(kv_path)
    except Exception as e:
        print(f"[warn] theme extraction failed: {e}")
        theme = {"bg_page": "#1A1A2E", "accent_bright": "#FF6B35",
                 "text_primary": "#FFFFFF", "text_secondary": "#AAAAAA",
                 "accent_primary": "#E85D04", "accent_bright_alt": "#4ECDC4"}
    for k, v in theme.items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")

    bg_page = _hex_rgb(theme.get("bg_page", "#1A1A2E"))
    accent = _hex_rgb(theme.get("accent_bright", "#FF6B35"))
    text_primary = _hex_rgb(theme.get("text_primary", "#FFFFFF"))
    text_secondary = _hex_rgb(theme.get("text_secondary", "#AAAAAA"))
    bg_card_dark = _hex_rgb(theme.get("bg_card_dark", "#37232B"))
    border_color = _hex_rgb(theme.get("accent_secondary", "#E755BE"))

    is_dark = _relative_luminance(bg_page) < 0.5
    accent_text_white = _contrast_ratio(accent, (255, 255, 255)) >= 3.0

    prizes = _load_prizes(prize_dir, prize_order) if prize_dir else []
    print(f"[prizes] loaded {len(prizes)} items", flush=True)
    if prize_order:
        print(f"  order: {[n for n, _ in prizes]}")

    rule_lines = rules or []

    section1_h = _calc_section1_height(
        font_title_sec, font_desc, font_name,
        event_date, event_desc, prizes)
    section2_h = _calc_section2_height(
        font_title_sec, font_rules, rule_lines)
    canvas_h = kv_display_h + SECTION_GAP + section1_h + SECTION_GAP + section2_h

    canvas = Image.new("RGB", (CANVAS_W, canvas_h), (30, 30, 35))
    draw = ImageDraw.Draw(canvas)

    out_path_resolved = Path(output)
    out_path_resolved.parent.mkdir(parents=True, exist_ok=True)
    micu_bg_path = out_path_resolved.parent / "_micu_full_bg.png"
    try:
        micu_full = _generate_section_bg(
            canvas_h, theme, kv_scene,
            game_name, game_style, micu_bg_path)
    except Exception as e:
        print(f"[WARN] AI background generation failed: {e}")
        if micu_bg_path.is_file():
            print("[WARN] reusing cached _micu_full_bg.png")
            micu_full = Image.open(micu_bg_path).convert("RGB")
            if micu_full.size[1] != canvas_h:
                micu_full = micu_full.resize((CANVAS_W, canvas_h), Image.Resampling.LANCZOS)
        else:
            print("[ERROR] no cached background available")
            sys.exit(1)
    canvas.paste(micu_full, (0, 0))

    canvas.paste(kv_resized, (0, 0))
    _draw_kv_title(draw, kv_display_h, main_title, sub_title,
                   font_title_big, font_sub)

    section_total_h = section1_h + SECTION_GAP + section2_h
    subdue = Image.new("RGBA", (CANVAS_W, section_total_h), (0, 0, 0, 45))
    canvas.paste(subdue, (0, kv_display_h + SECTION_GAP), subdue)

    y = kv_display_h + SECTION_GAP
    y = _draw_section(
        canvas, draw, y, section1,
        font_title_sec, font_date, font_desc, font_name,
        event_date, event_desc, prizes,
        bg_page, accent, accent_text_white,
        bg_card_dark, border_color,
        text_primary, text_secondary, is_dark,
        section1_h)

    y = _draw_rules_section(
        canvas, draw, y, section2,
        font_title_sec, font_rules,
        rule_lines, accent, accent_text_white,
        bg_page, border_color,
        text_secondary, section2_h)

    if out_path_resolved.suffix.lower() in (".jpg", ".jpeg"):
        canvas.convert("RGB").save(out_path_resolved, quality=95)
    else:
        canvas.save(out_path_resolved)
    print(f"\nDone: {out_path_resolved} ({canvas_h}px tall)", flush=True)
    return out_path_resolved


FRAME_BLUR_RADIUS = 12
FRAME_TINT_ALPHA = 80


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
        [x, y, x + w, y + h],
        radius=radius, outline=border_color, width=border_width)


def _draw_kv_title(draw, kv_display_h: int,
                   main_title: str, sub_title: str,
                   font_title, font_sub) -> None:
    sub_bottom = kv_display_h - 50
    text_y = sub_bottom - KV_SUBTITLE_SIZE - KV_TITLE_SUB_GAP - KV_TITLE_SIZE
    if main_title:
        fw = draw.textbbox((0, 0), main_title, font=font_title)[2]
        mx = (CANVAS_W - fw) // 2
        draw.text((mx, text_y), main_title, fill=(255, 255, 255), font=font_title)
    if sub_title:
        fw = draw.textbbox((0, 0), sub_title, font=font_sub)[2]
        sx = (CANVAS_W - fw) // 2
        sy = text_y + KV_TITLE_SIZE + KV_TITLE_SUB_GAP
        draw.text((sx, sy), sub_title, fill=(255, 255, 255), font=font_sub)


def _calc_section1_height(font_title_sec, font_desc, font_name,
                          event_date, event_desc, prizes) -> int:
    h = SECTION_PAD_TOP
    badge_fh = font_title_sec.getbbox("\u6d4b")[3]
    h += BADGE_PAD_Y * 2 + badge_fh
    h += BADGE_CONTENT_GAP
    lh_date = _line_height(font_desc)
    text_block_h = 0
    if event_date:
        text_block_h += lh_date + EVENT_DATE_DESC_GAP
    if event_desc:
        temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        text_max_w = CANVAS_W - SECTION_PAD_LR * 2 - TEXT_BOX_PAD_X * 2
        desc_lines = _wrap_text(temp_draw, event_desc, font_desc, text_max_w)
        text_block_h += len(desc_lines) * lh_date
    if text_block_h > 0:
        h += TEXT_BOX_PAD_Y * 2 + text_block_h
    if text_block_h > 0 and prizes:
        h += DESC_PRIZE_GAP
    if prizes:
        rows = _prize_rows(len(prizes))
        card_w = (CANVAS_W - SECTION_PAD_LR * 2
                  - (max(rows) - 1) * CARD_GAP) // max(rows)
        card_img_h = int(card_w * 0.65)
        h += len(rows) * (card_img_h + CARD_NAME_H + CARD_GAP)
    h += SECTION_PAD_BOTTOM
    return h


def _calc_section2_height(font_title_sec, font_rules, rule_lines) -> int:
    h = SECTION_PAD_TOP
    badge_fh = font_title_sec.getbbox("\u6d4b")[3]
    h += BADGE_PAD_Y * 2 + badge_fh
    h += BADGE_CONTENT_GAP
    lh = _line_height(font_rules)
    text_block_h = 0
    if rule_lines:
        temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        text_max_w = CANVAS_W - SECTION_PAD_LR * 2 - TEXT_BOX_PAD_X * 2
        for rule in rule_lines:
            wrapped = _wrap_text(temp_draw, rule, font_rules, text_max_w)
            text_block_h += len(wrapped) * lh
            text_block_h += RULES_BLOCK_GAP
        text_block_h -= RULES_BLOCK_GAP
    if text_block_h > 0:
        h += TEXT_BOX_PAD_Y * 2 + text_block_h
    h += SECTION_PAD_BOTTOM
    return h


def _draw_section(canvas, draw, y, section_title,
                  font_sec, font_date, font_desc, font_name,
                  event_date, event_desc, prizes,
                  bg_page, accent, accent_text_white,
                  bg_card_dark, border_color,
                  text_primary, text_secondary, is_dark,
                  section_h) -> int:
    sx = SECTION_PAD_LR
    sy = y + SECTION_PAD_TOP
    cw = CANVAS_W - SECTION_PAD_LR * 2
    bw = FRAME_BORDER_WIDTH

    badge_text = f"\u2605 {section_title}"
    bfw = draw.textbbox((0, 0), badge_text, font=font_sec)[2]
    bfh = draw.textbbox((0, 0), "\u6d4b", font=font_sec)[3]
    badge_w = bfw + BADGE_PAD_X * 2
    badge_h = bfh + BADGE_PAD_Y * 2
    badge_x = (CANVAS_W - badge_w) // 2
    _drop_shadow(canvas, draw, badge_x, sy, badge_w, badge_h,
                 BADGE_RADIUS, shadow_color=accent)
    draw.rounded_rectangle([badge_x, sy, badge_x + badge_w, sy + badge_h],
                           radius=BADGE_RADIUS, fill=accent,
                           outline=border_color, width=bw)
    tc = (255, 255, 255) if accent_text_white else (51, 51, 51)
    draw.text((badge_x + BADGE_PAD_X, sy + BADGE_PAD_Y),
              badge_text, fill=tc, font=font_sec)
    sy += badge_h + BADGE_CONTENT_GAP

    lh_date = _line_height(font_date)
    lh_desc = _line_height(font_desc)
    text_content_w = cw - TEXT_BOX_PAD_X * 2
    text_sy = sy
    text_block_h = 0
    if event_date:
        text_block_h += lh_date + EVENT_DATE_DESC_GAP
    _desc_lines = None
    if event_desc:
        _desc_lines = _wrap_text(draw, event_desc, font_desc, text_content_w)
        text_block_h += len(_desc_lines) * lh_desc
    has_text = text_block_h > 0
    if has_text:
        frame_x = sx
        frame_y = text_sy - TEXT_BOX_PAD_Y
        frame_w = cw
        frame_h = text_block_h + TEXT_BOX_PAD_Y * 2
        _frosted_frame(canvas, draw, frame_x, frame_y, frame_w, frame_h,
                       bg_page, border_color,
                       TEXT_BOX_RADIUS, bw)

    tx = sx + TEXT_BOX_PAD_X
    if event_date:
        tag_font = _yahei(LIMIT_TAG_SIZE)
        tag_text = "\u9650\u65f6"
        tw = draw.textbbox((0, 0), tag_text, font=tag_font)[2]
        th = draw.textbbox((0, 0), tag_text, font=tag_font)[3]
        tp = 6
        block_w = tw + tp * 2
        block_h = th + tp * 2
        tag_x = tx
        tag_y = text_sy + (lh_date - block_h) // 2
        draw.rounded_rectangle(
            [tag_x, tag_y, tag_x + block_w, tag_y + block_h],
            radius=3, fill=(255, 80, 80))
        tbox = draw.textbbox((0, 0), tag_text, font=tag_font)
        text_w = tbox[2] - tbox[0]
        text_h = tbox[3] - tbox[1]
        draw.text((tag_x + (block_w - text_w) // 2, tag_y + (block_h - text_h) // 2),
                  tag_text, fill=(255, 255, 255), font=tag_font)
        dt_x = tx + block_w + 8
        dt = f"\u6d3b\u52a8\u65f6\u95f4\uff1a{event_date}"
        draw.text((dt_x, text_sy), dt, fill=text_primary, font=font_date)
        text_sy += lh_date + EVENT_DATE_DESC_GAP

    if _desc_lines:
        for line in _desc_lines:
            draw.text((tx, text_sy), line, fill=text_secondary, font=font_desc)
            text_sy += lh_desc

    if has_text:
        sy = frame_y + frame_h
    else:
        sy = text_sy

    if has_text and prizes:
        sy += DESC_PRIZE_GAP

    if prizes:
        rows = _prize_rows(len(prizes))
        max_row = max(rows)
        card_w = (cw - (max_row - 1) * CARD_GAP) // max_row
        card_img_h = int(card_w * 0.65)
        idx = 0
        for row_items in rows:
            total_w = row_items * (card_w + CARD_GAP) - CARD_GAP
            rx = (CANVAS_W - total_w) // 2
            col = 0
            for _ in range(row_items):
                if idx >= len(prizes):
                    break
                name, pimg = prizes[idx]
                cx = rx + col * (card_w + CARD_GAP)
                ch = card_img_h + CARD_NAME_H + 8

                _drop_shadow(canvas, draw, cx, sy, card_w, ch, CARD_RADIUS,
                             shadow_color=border_color)
                card_fill = Image.new("RGBA", (card_w, ch),
                                      (*bg_page, CARD_BG_ALPHA))
                canvas.paste(card_fill, (cx, sy), card_fill)
                draw.rounded_rectangle(
                    [cx, sy, cx + card_w, sy + ch],
                    radius=CARD_RADIUS, outline=border_color, width=bw)

                img_pad = 24
                iw = card_w - img_pad * 2
                ih = card_img_h - img_pad * 2
                fitted = _fit_trimmed(pimg, iw, ih)
                px = cx + (card_w - iw) // 2
                py = sy + (card_img_h - ih) // 2
                canvas.paste(fitted, (px, py), fitted if fitted.mode == "RGBA" else None)

                n = name
                if draw.textbbox((0, 0), n, font=font_name)[2] > card_w - 8:
                    while n and draw.textbbox((0, 0), n + "\u2026", font=font_name)[2] > card_w - 8:
                        n = n[:-1]
                    n += "\u2026"
                tnw = draw.textbbox((0, 0), n, font=font_name)[2]
                nx = cx + (card_w - tnw) // 2
                ny = sy + card_img_h + 8

                bar_h = CARD_NAME_H
                bar = Image.new("RGBA", (card_w, bar_h), (0, 0, 0, 0))
                bp = bar.load()
                for by in range(bar_h):
                    t = by / max(bar_h - 1, 1)
                    a = int(200 * (1.0 - t))
                    for bx in range(card_w):
                        bp[bx, by] = (*accent, a)
                bar_y = sy + card_img_h + 8
                canvas.paste(bar, (cx, bar_y), bar)

                tnh = draw.textbbox((0, 0), n, font=font_name)[3]
                text_ny = bar_y + (bar_h - tnh) // 2
                draw.text((nx, text_ny), n, fill=text_primary, font=font_name)
                idx += 1
                col += 1
            sy += card_img_h + CARD_NAME_H + CARD_GAP

    return y + section_h


def _draw_rules_section(canvas, draw, y, section_title,
                        font_sec, font_rules,
                        rule_lines, accent, accent_text_white,
                        bg_page, border_color,
                        text_secondary, section_h) -> int:
    sx = SECTION_PAD_LR
    sy = y + SECTION_PAD_TOP
    cw = CANVAS_W - SECTION_PAD_LR * 2
    lh = _line_height(font_rules)
    bw = FRAME_BORDER_WIDTH

    badge_text = f"\u2605 {section_title}"
    bfw = draw.textbbox((0, 0), badge_text, font=font_sec)[2]
    bfh = draw.textbbox((0, 0), "\u6d4b", font=font_sec)[3]
    badge_w = bfw + BADGE_PAD_X * 2
    badge_h = bfh + BADGE_PAD_Y * 2
    badge_x = (CANVAS_W - badge_w) // 2
    _drop_shadow(canvas, draw, badge_x, sy, badge_w, badge_h,
                 BADGE_RADIUS, shadow_color=accent)
    draw.rounded_rectangle([badge_x, sy, badge_x + badge_w, sy + badge_h],
                           radius=BADGE_RADIUS, fill=accent,
                           outline=border_color, width=bw)
    tc = (255, 255, 255) if accent_text_white else (51, 51, 51)
    draw.text((badge_x + BADGE_PAD_X, sy + BADGE_PAD_Y),
              badge_text, fill=tc, font=font_sec)
    sy += badge_h + BADGE_CONTENT_GAP
    text_content_w = cw - TEXT_BOX_PAD_X * 2
    text_sy = sy
    text_block_h = 0
    text_lines_list: list[list[str]] = []
    if rule_lines:
        for rule in rule_lines:
            wrapped = _wrap_text(draw, rule, font_rules, text_content_w - 16)
            text_lines_list.append(wrapped)
            text_block_h += len(wrapped) * lh
            text_block_h += RULES_BLOCK_GAP
        text_block_h -= RULES_BLOCK_GAP
    has_text = text_block_h > 0
    if has_text:
        frame_x = sx
        frame_y = text_sy - TEXT_BOX_PAD_Y
        frame_w = cw
        frame_h = text_block_h + TEXT_BOX_PAD_Y * 2
        _frosted_frame(canvas, draw, frame_x, frame_y, frame_w, frame_h,
                       bg_page, border_color,
                       TEXT_BOX_RADIUS, bw)

    tx = sx + TEXT_BOX_PAD_X
    dot_r = 5
    for wrapped in text_lines_list:
        first = True
        for line in wrapped:
            if first:
                draw.ellipse([(tx, text_sy + lh // 2 - dot_r),
                              (tx + dot_r * 2, text_sy + lh // 2 + dot_r)],
                             fill=accent)
            draw.text((tx + 16, text_sy), line, fill=text_secondary, font=font_rules)
            text_sy += lh
            first = False
        text_sy += RULES_BLOCK_GAP

    if has_text:
        sy = frame_y + frame_h
    else:
        sy = text_sy

    return y + section_h


def main() -> None:
    ap = argparse.ArgumentParser(
        description="活动长图合成：1080 宽竖版，KV + 福利区 + 规则区"
    )
    ap.add_argument("--kv", required=True, help="KV 图路径")
    ap.add_argument("--font-title", required=True, help="标题字体路径")
    ap.add_argument("--font-yahei", default=None, help="微软雅黑字体路径（默认自动查找）")
    ap.add_argument("-m", "--main-title", default="", help="主标题")
    ap.add_argument("-s", "--sub-title", default="", help="副标题")
    ap.add_argument("--section1", default="福利活动", help="第一区块标题")
    ap.add_argument("--section2", default="活动规则", help="第二区块标题")
    ap.add_argument("--event-date", default="", help="活动日期")
    ap.add_argument("--event-desc", default="", help="参与方式描述")
    ap.add_argument("--prize-dir", default="", help="奖品图片目录")
    ap.add_argument("--prize-order", default="", help="奖品顺序，用 | 分隔文件名关键词")
    ap.add_argument("--rules", default="", help="规则文案，用 | 分隔多条")
    ap.add_argument("--kv-scene", default="", help="KV画面描述，用于MICU生成延续背景")
    ap.add_argument("--game-name", default="活动", help="游戏名称（用于MICU prompt）")
    ap.add_argument("--game-style", default="", help="游戏风格描述（用于MICU prompt）")
    ap.add_argument("-o", "--output", default="output/活动长图.jpg", help="输出路径")
    args = ap.parse_args()

    if args.font_yahei:
        set_yahei_font(args.font_yahei)

    prize_order = [s.strip() for s in args.prize_order.split("|") if s.strip()] if args.prize_order else None
    rules = [r.strip() for r in args.rules.split("|") if r.strip()]

    make_poster(
        kv=args.kv,
        font_title=args.font_title,
        main_title=args.main_title,
        sub_title=args.sub_title,
        section1=args.section1,
        section2=args.section2,
        event_date=args.event_date,
        event_desc=args.event_desc,
        prize_dir=args.prize_dir,
        prize_order=prize_order,
        rules=rules,
        kv_scene=args.kv_scene,
        game_name=args.game_name,
        game_style=args.game_style,
        output=args.output,
    )


if __name__ == "__main__":
    main()
