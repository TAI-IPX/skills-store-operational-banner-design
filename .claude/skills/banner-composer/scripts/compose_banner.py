#!/usr/bin/env python3
"""
Compose a banner image: background + gradient overlay + main title + subtitle.
Follows spec from banner-spec (canvas, typography, positions, line breaks).
Requires Microsoft YaHei (微软雅黑) only; see references/install_font.md if missing.
"""

import argparse
import math
import os
import sys
from pathlib import Path

# 从 banner-spec 读取规范（PRESETS、布局 get_layout）
_script_dir = Path(__file__).resolve().parent
_spec_scripts = _script_dir.parent.parent / "banner-spec" / "scripts"
if _spec_scripts.is_dir():
    sys.path.insert(0, str(_spec_scripts))
import spec as _spec
PRESETS = _spec.PRESETS
get_layout = _spec.get_layout

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    print("Requires Pillow. Install: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def _create_rounded_mask(w, h, radius, supersample=8):
    sw, sh = w * supersample, h * supersample
    mask_hi = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask_hi).rounded_rectangle(
        [0, 0, sw, sh], radius=radius * supersample, fill=255)
    return mask_hi.resize((w, h), Image.Resampling.LANCZOS)


# Default canvas (spec)
DEFAULT_WIDTH = 1976
DEFAULT_HEIGHT = 464

GRADIENT_OPACITY = 0.3  # 蒙层整层不透明度（设计稿 30%）
TEXT_COLOR = (255, 255, 255)
DEFAULT_OUTPUT_DIR = "output"
SUPPORTED_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}

# Microsoft YaHei only (规范唯一合规字体). Supports .ttf and .ttc (e.g. MSYH.TTC / MSYHBD.TTC).
def _find_font_in_dir(dir_path: Path, base: str) -> Path | None:
    """In dir_path, find first existing file: base.ttf, base.ttc, or BASE.TTC (uppercase extension)."""
    names = [f"{base}.ttf", f"{base}.ttc", f"{base.upper()}.ttc", f"{base.upper()}.TTC"]
    for name in names:
        p = dir_path / name
        if p.is_file():
            return p
    return None


def _font_paths() -> tuple[str | None, str | None]:
    """Return (path_to_regular, path_to_bold) for 微软雅黑; accepts .ttf or .ttc (e.g. MSYH.TTC, MSYHBD.TTC)."""
    if sys.platform == "win32":
        windir = os.environ.get("SystemRoot", "C:\\Windows")
        fonts_dir = Path(windir) / "Fonts"
        r = _find_font_in_dir(fonts_dir, "msyh")
        b = _find_font_in_dir(fonts_dir, "msyhbd")
        return (str(r) if r else None, str(b) if b else None)
    dirs = [Path.home() / "Library" / "Fonts", Path("/Library/Fonts")]
    r = b = None
    for d in dirs:
        if not d.is_dir():
            continue
        if r is None:
            r = _find_font_in_dir(d, "msyh")
        if b is None:
            b = _find_font_in_dir(d, "msyhbd")
        if r and b:
            break
    return (str(r) if r else None, str(b) if b else None)

FONT_INSTALL_HINT = (
    "本 Skill 仅支持微软雅黑，未检测到安装。"
    "请参阅 references/install_font.md 安装说明（支持 Windows 与 macOS），"
    "或运行 scripts/install_font.py 进行检测与指引。"
)


def _break_lines(text: str, chars_per_line: int) -> list[str]:
    """Break text into lines by character count."""
    if not text or chars_per_line <= 0:
        return [text] if text else []
    return [text[i : i + chars_per_line] for i in range(0, len(text), chars_per_line)]


def _break_at_one(text: str, position: int | None) -> list[str]:
    """Break text into 2 lines at position (first line has position chars). If position invalid, return single line."""
    if not text or position is None or position <= 0 or position >= len(text):
        return [text] if text else []
    return [text[:position], text[position:]]


def _get_ai_line_breaks(main_title: str, subtitle: str) -> tuple[int | None, int | None]:
    """Get (main_break, sub_break) from Gemini; (None, None) on failure."""
    if not os.environ.get("GEMINI_API_KEY"):
        return (None, None)
    try:
        from gemini_linebreak import get_line_breaks
        return get_line_breaks(main_title, subtitle)
    except Exception:
        return (None, None)


def _load_yahei_font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
    """Load Microsoft YaHei at given size. Exits with install hint if not found."""
    path_regular, path_bold = _font_paths()
    path = path_bold if bold else path_regular
    if not path:
        print(f"Error: 未找到微软雅黑（{'Bold' if bold else 'Regular'}）。", file=sys.stderr)
        print(FONT_INSTALL_HINT, file=sys.stderr)
        sys.exit(1)
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError) as e:
        print(f"Error: 无法加载字体 {path}: {e}", file=sys.stderr)
        print(FONT_INSTALL_HINT, file=sys.stderr)
        sys.exit(1)


def _get_layout(width: int, height: int, preset: str | None = None) -> dict:
    """返回 (width, height) 对应的布局配置；来自 banner-spec get_layout（可选 preset 合并同画布多规格）。"""
    return get_layout(width, height, preset)


def _draw_gradient_overlay(
    canvas_w: int,
    canvas_h: int,
    *,
    gradient_rect: tuple[int, int] | None = None,
    gradient_rect_x: int | None = None,
    gradient_rect_y: int | None = None,
    gradient_diagonal: bool = False,
    gradient_vertical: bool = False,
    gradient_vertical_top_heavy: bool = False,
    gradient_opacity: float | None = None,
    gradient_blur_radius: float | None = None,
) -> Image.Image:
    """蒙层：gradient_rect 为 (gw,gh) 时仅该区域有渐变；gradient_rect_x/rect_y 为区域左上角（默认 0,0）。gradient_diagonal=左上→右下。gradient_vertical=上→下时：gradient_vertical_top_heavy=True 为上面最黑下面透明(1-t)，否则为下面最重上面透明(t)。gradient_opacity 未传时用 GRADIENT_OPACITY。"""
    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    gw = gradient_rect[0] if gradient_rect else canvas_w
    gh = gradient_rect[1] if gradient_rect else canvas_h
    gx = gradient_rect_x if gradient_rect_x is not None else 0
    gy = gradient_rect_y if gradient_rect_y is not None else 0
    opacity = gradient_opacity if gradient_opacity is not None else GRADIENT_OPACITY
    y_start = max(0, gy)
    y_end = min(canvas_h, gy + gh)
    x_start = max(0, gx)
    x_end = min(canvas_w, gx + gw)
    pixels = out.load()
    for py in range(y_start, y_end):
        for px in range(x_start, x_end):
            if gradient_diagonal:
                t = ((px - gx) * gw + (py - gy) * gh) / (gw * gw + gh * gh) if (gw * gw + gh * gh) else 0
            elif gradient_vertical:
                t = (py - gy) / gh if gh else 0
            else:
                t = (px - gx) / gw if gw else 0
            t = max(0, min(1, t))
            # 竖直渐变：top_heavy=上黑下透明(1-t)，否则下重上透明(t)；非竖直用 (1-t)
            if gradient_vertical:
                alpha = int(255 * opacity * (1 - t)) if gradient_vertical_top_heavy else int(255 * opacity * t)
            else:
                alpha = int(255 * opacity * (1 - t))
            pixels[px, py] = (0, 0, 0, alpha)
    if gradient_blur_radius is not None and gradient_blur_radius > 0:
        # 仅为柔和边缘过渡；允许轻微向外扩散
        out = out.filter(ImageFilter.GaussianBlur(radius=float(gradient_blur_radius)))
        # 模糊后清除 gradient_rect_y 以上的区域，防止模糊扩散到顶部保护区（如 3320×500 的 y=0-40）
        if gy > 0:
            pixels = out.load()
            for py in range(0, min(gy, canvas_h)):
                for px in range(canvas_w):
                    pixels[px, py] = (0, 0, 0, 0)
    return out


def _paste_background(
    canvas: Image.Image,
    bg_path: str,
    white_top_strip: int | None = None,
    white_top_strip_content_x: tuple[int, int] | None = None,
    subject_bbox: tuple[float, float, float, float] | None = None,
) -> None:
    """Resize/crop background to cover canvas and paste onto canvas (in-place).若 white_top_strip，则顶部该高度填白；white_top_strip_content_x=(x_min,x_max) 时仅左右两段填白，中间保留背景。若 subject_bbox (归一化 x_min,y_min,x_max,y_max)，则智能对齐安全区裁切。"""
    bg = Image.open(bg_path).convert("RGB")
    cw, ch = canvas.size
    bw, bh = bg.size
    r = max(cw / bw, ch / bh)
    nw, nh = math.ceil(bw * r), math.ceil(bh * r)
    bg = bg.resize((nw, nh), Image.Resampling.LANCZOS)

    if subject_bbox is not None and len(subject_bbox) == 4:
        safe_zone = _spec.get_safe_zone(cw, ch)
        if safe_zone is not None:
            sz_x_min, sz_x_max, sz_y_min, sz_y_max = safe_zone
            sz_cx = (sz_x_min + sz_x_max) / 2
            sz_cy = (sz_y_min + sz_y_max) / 2
            sub_cx = (subject_bbox[0] + subject_bbox[2]) / 2 * bw
            sub_cy = (subject_bbox[1] + subject_bbox[3]) / 2 * bh
            sub_scx = sub_cx * r
            sub_scy = sub_cy * r
            x = max(0, min(nw - cw, int(sub_scx - sz_cx)))
            y = max(0, min(nh - ch, int(sub_scy - sz_cy)))
        else:
            x = (nw - cw) // 2
            y = (nh - ch) // 2
    else:
        x = (nw - cw) // 2
        y = (nh - ch) // 2

    canvas.paste(bg.crop((x, y, x + cw, y + ch)), (0, 0))
    if white_top_strip and white_top_strip > 0:
        strip_h = min(white_top_strip, ch)
        draw = ImageDraw.Draw(canvas)
        x_min, x_max = white_top_strip_content_x if white_top_strip_content_x else (0, 0)
        if white_top_strip_content_x and x_min < x_max:
            # 仅左右两段填白，x_min～x_max 保留背景（允许画面元素伸入）
            if x_min > 0:
                draw.rectangle((0, 0, x_min, strip_h), fill=(255, 255, 255))
            if x_max < cw:
                draw.rectangle((x_max, 0, cw, strip_h), fill=(255, 255, 255))
        else:
            draw.rectangle((0, 0, cw, strip_h), fill=(255, 255, 255))


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    x: int,
    y: int,
    color: tuple[int, int, int],
    *,
    shadow_draw: ImageDraw.ImageDraw | None = None,
    shadow_offset: tuple[int, int] = (2, 2),
    shadow_color: tuple[int, int, int, int] | None = (0, 0, 0, 64),
) -> int:
    """Draw lines starting at (x, y). Return bottom y (for next block).
    If shadow_draw is provided, draws shadow text first with offset and shadow_color.
    """
    current_y = y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_h = bbox[3] - bbox[1]
        if shadow_draw is not None and shadow_color is not None:
            sx, sy = shadow_offset
            shadow_draw.text((x + sx, current_y + sy), line, font=font, fill=shadow_color)
        draw.text((x, current_y), line, font=font, fill=color)
        current_y += line_h
    return current_y


def _text_xy_centered_in_rect(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    x: int,
    y: int,
    w: int,
    h: int,
) -> tuple[int, int]:
    """矩形内文字视觉居中。textbbox 的 left/top 常非 0，需扣减否则 draw.text 会偏左上或垂直不均。"""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x + (w - tw) // 2 - bbox[0]
    ty = y + (h - th) // 2 - bbox[1]
    return tx, ty


def _draw_button(canvas: Image.Image, layout: dict) -> None:
    """按 layout 配置绘制按钮。支持透明填充/描边（button_fill_rgba/button_stroke_rgba）或旧版深色底白字。圆角可用 button_radius 指定（如 39.5）。"""
    x = layout["button_x"]
    y = layout["button_y"]
    w = layout["button_w"]
    h = layout["button_h"]
    text = layout["button_text"]
    radius = layout.get("button_radius")
    if radius is None:
        radius = min(w, h) // 2
    fill_rgba = layout.get("button_fill_rgba")
    stroke_rgba = layout.get("button_stroke_rgba")
    stroke_width = layout.get("button_stroke_width", 1)
    text_x = layout.get("button_text_x")
    text_y = layout.get("button_text_y")
    font_size = layout.get("button_font_size", 24)

    if fill_rgba is not None or stroke_rgba is not None:
        # 描边居中画在矩形边界上时，左右/上下会各有一半线宽落在框外；图层若刚好 w×h 会裁掉左侧与上侧描边。
        # 有描边时扩大图层并在层内缩进绘制，再 paste 到 (x-pad, y-pad)，视觉位置与规范仍对齐 (x,y) 的 w×h。
        sw = max(1, int(round(stroke_width))) if stroke_rgba is not None else 0
        pad = max(1, sw) if stroke_rgba is not None else 0
        layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        draw_layer = ImageDraw.Draw(layer)
        bx0, by0, bx1, by1 = pad, pad, pad + w, pad + h
        if fill_rgba is not None:
            draw_layer.rounded_rectangle([bx0, by0, bx1, by1], radius=radius, fill=fill_rgba, outline=None)
        if stroke_rgba is not None:
            draw_layer.rounded_rectangle(
                [bx0, by0, bx1, by1], radius=radius, fill=None, outline=stroke_rgba, width=sw
            )
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(layer, (x - pad, y - pad), layer)
        draw = ImageDraw.Draw(canvas_rgba)
        font = _load_yahei_font(font_size, bold=False)
        if text_x is not None and text_y is not None:
            tx, ty = text_x, text_y
        else:
            tx, ty = _text_xy_centered_in_rect(draw, text, font, x, y, w, h)
        shadow_dy = layout.get("button_shadow_dy")
        shadow_rgba = layout.get("button_shadow_rgba")
        shadow_blur = layout.get("button_shadow_blur_radius", 0)
        if shadow_dy is not None and shadow_rgba is not None:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad = max(shadow_blur * 2, 4)
            lw = int(tw + pad * 2)
            lh = int(th + abs(shadow_dy) + pad * 2)
            shadow_layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            shadow_draw.text((pad, pad + shadow_dy), text, font=font, fill=shadow_rgba)
            if shadow_blur > 0:
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
            canvas_rgba.paste(shadow_layer, (tx - pad, ty - pad), shadow_layer)
        draw = ImageDraw.Draw(canvas_rgba)
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255))
        canvas_final = canvas_rgba.convert("RGB")
        canvas.paste(canvas_final, (0, 0))
        return
    draw = ImageDraw.Draw(canvas)
    fill_color = (55, 55, 55)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill_color, outline=None)
    font = _load_yahei_font(font_size, bold=False)
    if text_x is not None and text_y is not None:
        tx, ty = text_x, text_y
    else:
        tx, ty = _text_xy_centered_in_rect(draw, text, font, x, y, w, h)
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255))


def _remove_background(img: "Image.Image") -> "Image.Image":
    """尝试用 BiRefNet 抠图去除背景；失败则直接返回原图（不中断流程）。"""
    try:
        import tempfile
        import subprocess
        _script_dir_local = Path(__file__).resolve().parent
        birefnet_script = _script_dir_local.parent.parent.parent / "scripts" / "extract_subject_birefnet.py"
        if not birefnet_script.is_file():
            return img
        tmp_in_path = tmp_out_path = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_in:
            tmp_in_path = tmp_in.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
        try:
            img.save(tmp_in_path)
            result = subprocess.run(
                [sys.executable, str(birefnet_script), tmp_in_path, "--output", tmp_out_path],
                capture_output=True, timeout=60,
            )
            if result.returncode == 0 and Path(tmp_out_path).is_file():
                from PIL import Image as _Image
                return _Image.open(tmp_out_path).copy()
        finally:
            for p in (tmp_in_path, tmp_out_path):
                if p is not None:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    except Exception as e:
        print(f"Warning: 抠图失败，直接使用原图: {e}", file=sys.stderr)
    return img


def _paste_logo(
    canvas: Image.Image,
    logo_path: str,
    logo_rect: tuple[int, int, int, int],
    *,
    logo_align: str = "center",
    logo_scale: str = "fit",
    logo_fit_scale: float = 1.0,
) -> None:
    """将 logo 图等比缩放贴到 logo_rect (x, y, w, h)。支持透明 PNG；无透明通道则按不透明贴。
    logo_align: center=矩形内居中，top_left=左上角对齐。
    logo_scale: fit=缩放进矩形内，max_width=按矩形宽度等比缩放（高度可小于矩形）。
    logo_fit_scale: 在 fit/max_width 之后再乘以该系数（如 0.95 表示相对最大可放入尺寸缩放至 95%）。"""
    lx, ly, lw, lh = logo_rect
    if lw <= 0 or lh <= 0:
        return
    try:
        logo = Image.open(logo_path)
        # 检测是否有透明通道：PNG 含 alpha 直接用；否则尝试 BiRefNet 抠图
        has_alpha = logo.mode in ("RGBA", "LA") or (logo.mode == "P" and "transparency" in logo.info)
        if not has_alpha:
            logo = _remove_background(logo)
        if logo.mode != "RGBA":
            logo = logo.convert("RGBA")
        iw, ih = logo.size
        if iw <= 0 or ih <= 0:
            return
        if logo_scale == "max_width":
            scale = lw / iw
            nw = lw
            nh = max(1, int(round(ih * scale)))
        elif logo_scale == "max_height":
            # 按 logo_rect 高度等比缩放；若缩放后宽度超过 logo_rect 宽度则改按宽度缩放
            scale = lh / ih
            nw = max(1, int(round(iw * scale)))
            nh = lh
            if nw > lw:
                scale = lw / iw
                nw = lw
                nh = max(1, int(round(ih * scale)))
        else:
            scale = min(lw / iw, lh / ih, 1.0)
            nw = max(1, int(round(iw * scale)))
            nh = max(1, int(round(ih * scale)))
        fk = float(logo_fit_scale)
        if fk > 0 and fk != 1.0:
            nw = max(1, int(round(nw * fk)))
            nh = max(1, int(round(nh * fk)))
        logo = logo.resize((nw, nh), Image.Resampling.LANCZOS)
        if logo_align == "top_left":
            paste_x, paste_y = lx, ly
        else:
            paste_x = lx + (lw - nw) // 2
            paste_y = ly + (lh - nh) // 2
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(logo, (paste_x, paste_y), logo)
        canvas_new = canvas_rgba.convert("RGB")
        canvas.paste(canvas_new, (0, 0))
    except Exception:
        pass


def _paste_subject(
    canvas: Image.Image,
    subject_path: str,
    subject_rect: tuple[int, int, int, int],
    *,
    subject_align: str = "center",
    subject_scale: str = "fit",
) -> None:
    """将主体物图等比缩放贴到 subject_rect (x, y, w, h)。主体物应为透明PNG。
    subject_align: center=矩形内居中，top_left=左上角对齐。
    subject_scale: fit=缩放进矩形内（保持比例）。"""
    sx, sy, sw, sh = subject_rect
    if sw <= 0 or sh <= 0:
        return
    try:
        subject = Image.open(subject_path)
        if subject.mode != "RGBA":
            subject = subject.convert("RGBA")
        iw, ih = subject.size
        if iw <= 0 or ih <= 0:
            return
        # 等比缩放 fit 进区域
        if subject_scale == "fit":
            scale = min(sw / iw, sh / ih, 1.0)
        else:
            scale = 1.0
        nw = max(1, int(round(iw * scale)))
        nh = max(1, int(round(ih * scale)))
        subject = subject.resize((nw, nh), Image.Resampling.LANCZOS)
        if subject_align == "top_left":
            paste_x, paste_y = sx, sy
        else:
            paste_x = sx + (sw - nw) // 2
            paste_y = sy + (sh - nh) // 2
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(subject, (paste_x, paste_y), subject)
        canvas_new = canvas_rgba.convert("RGB")
        canvas.paste(canvas_new, (0, 0))
    except Exception as e:
        print(f"Warning: 贴主体物失败: {e}", file=sys.stderr)


def _paste_text_art(
    canvas: Image.Image,
    text_art_path: str,
    text_art_rect: tuple[int, int, int, int],
    *,
    text_art_align: str = "center",
    text_art_scale: str = "fit",
) -> None:
    """将文字艺术字图等比缩放贴到 text_art_rect (x, y, w, h)。支持透明 PNG；无透明通道则自动 BiRefNet 抠图。"""
    tx, ty, tw, th = text_art_rect
    if tw <= 0 or th <= 0:
        return
    try:
        art = Image.open(text_art_path)
        has_alpha = art.mode in ("RGBA", "LA") or (art.mode == "P" and "transparency" in art.info)
        if not has_alpha:
            # 亮度蒙版：自动检测底色深浅，保留文字部分
            import numpy as _np2
            art_rgba = art.convert("RGBA")
            gray = art_rgba.convert("L")
            avg = _np2.array(gray).mean()
            alpha = gray.point(lambda x: 255 - x) if avg > 128 else gray.point(lambda x: x)
            art_rgba.putalpha(alpha)
            art = art_rgba
        if art.mode != "RGBA":
            art = art.convert("RGBA")
        iw, ih = art.size
        if iw <= 0 or ih <= 0:
            return
        if text_art_scale == "fit":
            scale = min(tw / iw, th / ih, 1.0)
        else:
            scale = 1.0
        nw = max(1, int(round(iw * scale)))
        nh = max(1, int(round(ih * scale)))
        art = art.resize((nw, nh), Image.Resampling.LANCZOS)
        if text_art_align == "top_left":
            paste_x, paste_y = tx, ty
        else:
            paste_x = tx + (tw - nw) // 2
            paste_y = ty + (th - nh) // 2
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(art, (paste_x, paste_y), art)
        canvas_new = canvas_rgba.convert("RGB")
        canvas.paste(canvas_new, (0, 0))
    except Exception as e:
        print(f"Warning: 贴文字艺术字失败: {e}", file=sys.stderr)


def _paste_dialog(
    canvas: Image.Image,
    dialog_path: str,
    dialog_rect: tuple[int, int, int, int],
    *,
    dialog_align: str = "center",
    dialog_scale: str = "fit",
) -> None:
    """将对话框容器图等比缩放贴到 dialog_rect (x, y, w, h)。
    对话框作为文字容器保留背景色，不做抠图，直接 cover 缩放粘贴。"""
    dx, dy, dw, dh = dialog_rect
    if dw <= 0 or dh <= 0:
        return
    try:
        dialog = Image.open(dialog_path).convert("RGBA")
        iw, ih = dialog.size
        if iw <= 0 or ih <= 0:
            return
        # cover 缩放：填满 dialog_rect，不留白边
        scale = max(dw / iw, dh / ih)
        nw = max(1, int(round(iw * scale)))
        nh = max(1, int(round(ih * scale)))
        dialog_s = dialog.resize((nw, nh), Image.Resampling.LANCZOS)
        # 居中裁切到目标尺寸
        cx = (nw - dw) // 2
        cy = (nh - dh) // 2
        dialog_s = dialog_s.crop((cx, cy, cx + dw, cy + dh))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(dialog_s, (dx, dy), dialog_s)
        canvas_new = canvas_rgba.convert("RGB")
        canvas.paste(canvas_new, (0, 0))
    except Exception as e:
        print(f"Warning: 贴对话框失败: {e}", file=sys.stderr)


def _resolve_output_path(output_path: str, add_timestamp: bool = True) -> tuple[Path, str]:
    """Resolve output path (default dir ./output/) and format from extension. Returns (path, PIL format).
    If add_timestamp=True (default), inserts a timestamp suffix before the extension to avoid overwriting."""
    import datetime
    p = Path(output_path)
    ext = p.suffix.lower().lstrip(".") if p.suffix else ""
    if ext not in SUPPORTED_FORMATS:
        p = p.with_suffix(".png")
        ext = "png"
    if not p.parent or p.parent == Path("."):
        p = Path(DEFAULT_OUTPUT_DIR) / p.name
    if add_timestamp:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        p = p.with_name(f"{p.stem}_{ts}{p.suffix}")
    pil_fmt = SUPPORTED_FORMATS.get(ext, "PNG")
    return (p, pil_fmt)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Hex color string to RGB tuple, e.g. '#6AF4EA' -> (106, 244, 234)."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _draw_fixed_gradient(
    width: int,
    height: int,
    colors: tuple[str, str],
    direction: str = "diagonal",
    corner_radius: int = 0,
) -> Image.Image:
    """绘制固定渐变背景（左上→右下），支持圆角。返回 RGBA 图片。"""
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    c1 = _hex_to_rgb(colors[0])
    c2 = _hex_to_rgb(colors[1])
    pixels = canvas.load()
    for py in range(height):
        for px in range(width):
            if direction == "diagonal":
                t = (px + py) / (width + height)
            else:
                t = px / width if width > 0 else 0
            t = max(0, min(1, t))
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            pixels[px, py] = (r, g, b, 255)

    if corner_radius > 0:
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, width, height], radius=corner_radius, fill=255)
        canvas.putalpha(mask)

    return canvas


def compose(
    background_path: str,
    output_path: str,
    main_title: str,
    subtitle: str = "",
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    use_ai_linebreak: bool = True,
    logo_path: str | None = None,
    preset: str | None = None,
    font_path: str | None = None,
    font_path_regular: str | None = None,
    gradient_variant: int = 1,
    subject_path: str | None = None,
    text_art_path: str | None = None,
    dialog_path: str | None = None,
    subject_bbox: tuple[float, float, float, float] | None = None,
) -> str:
    """
    Compose banner and save to output_path.
    Canvas size = (width, height). Background is scaled to cover. Gradient and text per LAYOUT_BY_CANVAS or default spec.
    If preset is given and found in PRESETS, its canvas size overrides width/height.
    If layout has logo_rect and logo_path is set, paste logo (transparent PNG or opaque) scaled to fit.
    If layout has subject_rect and subject_path is set, paste subject (transparent PNG) scaled to fit.
    If subject_bbox (归一化 x_min,y_min,x_max,y_max) is set, paste_background aligns subject with canvas safe zone instead of center-crop.
    If use_ai_linebreak and GEMINI_API_KEY set, uses Gemini for main title line break.
    """
    # 若 preset 在 PRESETS 中有明确画布定义，自动覆盖 width/height
    if preset and preset in _spec.PRESETS:
        width, height = _spec.PRESETS[preset]
    layout = _get_layout(width, height, preset)
    main_x = layout["main_x"]
    main_y = layout["main_y"]
    main_size = layout["main_size"]
    sub_x = layout["sub_x"]
    sub_size = layout["sub_size"]
    sub_opacity = layout["sub_opacity"]
    subtitle_gap = layout["subtitle_gap"]
    main_break_chars = layout["main_break_chars"]
    sub_break_chars = layout["sub_break_chars"]
    grad_rect = layout.get("gradient_rect")
    grad_rect_x = layout.get("gradient_rect_x")
    grad_rect_y = layout.get("gradient_rect_y")
    grad_diagonal = layout.get("gradient_diagonal", False)
    grad_vertical = layout.get("gradient_vertical", False)
    grad_vertical_top_heavy = layout.get("gradient_vertical_top_heavy", False)
    grad_opacity = layout.get("gradient_opacity")
    grad_blur = layout.get("gradient_blur_radius")
    white_top_strip = layout.get("white_top_strip")
    white_top_strip_content_x = layout.get("white_top_strip_content_x")
    no_text = layout.get("no_text", False)

    # 固定渐变背景（4种方案）或普通背景图
    fixed_gradient = layout.get("fixed_gradient", False)
    transparent = layout.get("transparent", False)
    corner_radius = layout.get("corner_radius", 0)
    if fixed_gradient:
        gradient_colors = layout.get("fixed_gradient_colors", [])
        if gradient_colors and 1 <= gradient_variant <= len(gradient_colors):
            colors = gradient_colors[gradient_variant - 1]
        else:
            colors = gradient_colors[0] if gradient_colors else ("#6AF4EA", "#0471FE")
        direction = layout.get("fixed_gradient_direction", "diagonal")
        canvas = _draw_fixed_gradient(width, height, colors, direction, 0)
        canvas = canvas.convert("RGB")
    elif transparent:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        _paste_background(canvas, background_path, white_top_strip=white_top_strip, white_top_strip_content_x=white_top_strip_content_x, subject_bbox=subject_bbox)
    else:
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        _paste_background(canvas, background_path, white_top_strip=white_top_strip, white_top_strip_content_x=white_top_strip_content_x, subject_bbox=subject_bbox)

    # 规范里写了遮罩（gradient_rect 非 None）时才添加渐变遮罩；未写则不加
    if grad_rect is not None:
        overlay = _draw_gradient_overlay(
            width, height,
            gradient_rect=grad_rect,
            gradient_rect_x=grad_rect_x,
            gradient_rect_y=grad_rect_y,
            gradient_diagonal=grad_diagonal,
            gradient_vertical=grad_vertical,
            gradient_vertical_top_heavy=grad_vertical_top_heavy,
            gradient_opacity=grad_opacity,
            gradient_blur_radius=grad_blur,
        )
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba = Image.alpha_composite(canvas_rgba, overlay)
        canvas = canvas_rgba.convert("RGB")

    if not no_text:
        main_max = layout.get("main_max_chars")
        sub_max = layout.get("sub_max_chars")
        main_effective = (main_title[:main_max] if main_max is not None else main_title) if main_title else ""
        sub_effective = (subtitle[:sub_max] if sub_max is not None else subtitle) if subtitle else ""
        main_break, _ = (None, None)
        # 规范字数内不换行：该尺寸有 main_max_chars 时一律不换行；仅当未设字数上限且主标题≥main_break_chars 字时才请求 AI 换行（规范：≥10 字按语义断行）
        if use_ai_linebreak and main_effective and main_max is None and len(main_effective) >= main_break_chars:
            main_break, _ = _get_ai_line_breaks(main_effective, "")
        lines_main = _break_at_one(main_effective, main_break) if main_break is not None else _break_lines(main_effective, main_break_chars)
        if not lines_main:
            lines_main = [main_effective] if main_effective else []

        draw = ImageDraw.Draw(canvas)
        # 字体加载：优先使用调用方传入的本地字体路径；未传则回退微软雅黑
        if font_path:
            try:
                font_main = ImageFont.truetype(font_path, main_size)
            except (OSError, IOError) as e:
                print(f"Warning: 无法加载字体 {font_path}: {e}，回退微软雅黑", file=sys.stderr)
                font_main = _load_yahei_font(main_size, bold=layout.get("main_bold", True))
        else:
            font_main = _load_yahei_font(main_size, bold=layout.get("main_bold", True))

        font_regular_path = font_path_regular or font_path
        if font_regular_path:
            try:
                font_sub = ImageFont.truetype(font_regular_path, sub_size)
            except (OSError, IOError) as e:
                print(f"Warning: 无法加载字体 {font_regular_path}: {e}，回退微软雅黑", file=sys.stderr)
                font_sub = _load_yahei_font(sub_size, bold=False)
        else:
            font_sub = _load_yahei_font(sub_size, bold=False)
        # 文字居中处理：如果配置了 main_align=center，则居中对齐
        if layout.get("main_align") == "center":
            if lines_main:
                text_width = int(draw.textlength(lines_main[0], font=font_main))
                main_x = (width - text_width) // 2

        # 主标题投影：右下方 2px 黑色 25% 不透明
        if lines_main:
            main_shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            main_shadow_draw = ImageDraw.Draw(main_shadow)
            _draw_text_block(main_shadow_draw, lines_main, font_main,
                             main_x + 2, main_y + 2, (0, 0, 0, 64))
            canvas = canvas.convert("RGBA")
            canvas = Image.alpha_composite(canvas, main_shadow)
            draw = ImageDraw.Draw(canvas)

        main_bottom = _draw_text_block(draw, lines_main, font_main, main_x, main_y, TEXT_COLOR)

        if sub_effective:
            lines_sub = _break_lines(sub_effective, sub_break_chars)
            if not lines_sub:
                lines_sub = [sub_effective]
            if layout.get("sub_y_follow_main_if_wrap") and len(lines_main) > 1:
                sub_top_y = main_bottom + subtitle_gap
            else:
                sub_top_y = layout["sub_y"] if "sub_y" in layout else (main_bottom + subtitle_gap)
            sub_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            sub_draw = ImageDraw.Draw(sub_layer)
            _draw_text_block(sub_draw, lines_sub, font_sub, sub_x + 2, sub_top_y + 2, (0, 0, 0, 64))
            _draw_text_block(sub_draw, lines_sub, font_sub, sub_x, sub_top_y, (*TEXT_COLOR, 255))
            sub_layer_pixels = sub_layer.load()
            for py in range(height):
                for px in range(width):
                    r, g, b, a = sub_layer_pixels[px, py]
                    sub_layer_pixels[px, py] = (r, g, b, int(a * sub_opacity))
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba = Image.alpha_composite(canvas_rgba, sub_layer)
            canvas = canvas_rgba.convert("RGB")

        # 3320×500 等布局可配置副标题下方固定按钮（如「了解更多」）
        if layout.get("button_text") and layout.get("button_x") is not None:
            _draw_button(canvas, layout)

    # 若规范有 logo_rect 且传入了 logo_path，贴 logo（等比缩放入框；可选左上角对齐+按最大宽度缩放）
    if logo_path and layout.get("logo_rect"):
        _paste_logo(
            canvas,
            logo_path,
            layout["logo_rect"],
            logo_align=layout.get("logo_align", "center"),
            logo_scale=layout.get("logo_scale", "fit"),
            logo_fit_scale=float(layout.get("logo_fit_scale", 1.0)),
        )

    # 若规范有 subject_rect 且传入了 subject_path，贴主体物（等比缩放fit进安全区）
    if subject_path and layout.get("subject_rect"):
        _paste_subject(
            canvas,
            subject_path,
            layout["subject_rect"],
            subject_align=layout.get("subject_align", "center"),
            subject_scale=layout.get("subject_scale", "fit"),
        )

    # 若规范有 text_art_rect 且传入了 text_art_path，贴文字艺术字（等比缩放，无透明通道时自动 BiRefNet 抠图）
    if text_art_path and layout.get("text_art_rect"):
        # 可选底衬：半透明暗色矩形增强艺术字可读性
        if layout.get("text_art_backdrop"):
            _bx, _by, _bw, _bh = layout["text_art_rect"]
            from PIL import Image as _PILImg
            _backdrop = _PILImg.new("RGBA", (_bw, _bh), (0, 0, 0, 80))
            _canvas_rgba = canvas.convert("RGBA")
            _canvas_rgba.paste(_backdrop, (_bx, _by), _backdrop)
            canvas.paste(_canvas_rgba.convert("RGB"), (0, 0))
        _paste_text_art(
            canvas,
            text_art_path,
            layout["text_art_rect"],
            text_art_align="center",
            text_art_scale="fit",
        )

    # 若规范有 dialog_rect 且传入了 dialog_path，贴对话框（等比缩放，无透明通道时自动 BiRefNet 抠图）
    if dialog_path and layout.get("dialog_rect"):
        _paste_dialog(
            canvas,
            dialog_path,
            layout["dialog_rect"],
            dialog_align="center",
            dialog_scale="fit",
        )

    # 圆角：最后施加遮罩，避免中间步骤丢失 alpha
    if corner_radius > 0:
        canvas_rgba = canvas.convert("RGBA")
        mask = _create_rounded_mask(width, height, corner_radius)
        canvas_rgba.putalpha(mask)
        canvas = canvas_rgba

    out_path, pil_fmt = _resolve_output_path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_kw = {"quality": 90} if pil_fmt == "JPEG" else {}
    canvas.save(str(out_path), pil_fmt, **save_kw)

    # 多倍率输出（multi_scale）：layout.multi_scale 为 [(倍率, 文件名, 圆角半径), ...]，跳过 1.0x 版本
    multi_scale = layout.get("multi_scale")
    if multi_scale:
        out_dir = out_path.parent
        for scale, scale_filename, scale_corner in multi_scale:
            if scale == 1.0:
                continue
            sw = int(width * scale)
            sh = int(height * scale)
            scale_canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            bg = Image.open(background_path).convert("RGB")
            bw, bh = bg.size
            r = max(sw / bw, sh / bh)
            nw, nh = math.ceil(bw * r), math.ceil(bh * r)
            bg = bg.resize((nw, nh), Image.Resampling.LANCZOS)
            x = (nw - sw) // 2
            y = (nh - sh) // 2
            scale_canvas.paste(bg.crop((x, y, x + sw, y + sh)), (0, 0))
            if scale_corner > 0:
                mask = _create_rounded_mask(sw, sh, scale_corner)
                scale_canvas.putalpha(mask)
            scale_path = out_dir / scale_filename
            scale_canvas.save(str(scale_path), "PNG")

    return str(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compose a banner from background image, main title, and subtitle (spec: references/spec.md). Output default dir: ./output/; format: .png (default) or .jpg."
    )
    parser.add_argument("background", help="Path to background image")
    parser.add_argument("output", help="Output path or filename (default dir: output/; format: .png or .jpg)")
    parser.add_argument("--main-title", "-m", required=True, help="Main title text (AI line break or 8-char fallback)")
    parser.add_argument("--subtitle", "-s", default="", help="Subtitle text (single line, no line-break rule)")
    parser.add_argument("--no-ai-linebreak", action="store_true", help="Main title: use fixed 8-char break instead of Gemini")
    parser.add_argument("--logo", default=None, help="Path to logo image (paste to logo_rect when layout has it)")
    parser.add_argument("--font", default=None, help="Path to main title font file (e.g. C:/Windows/Fonts/msyhbd.ttc); defaults to Microsoft YaHei Bold")
    parser.add_argument("--font-regular", default=None, dest="font_regular", help="Path to subtitle font file; defaults to --font value (or Microsoft YaHei Regular)")
    parser.add_argument("--variant", "-v", type=int, default=1, help="Gradient variant (1-4) for fixed gradient backgrounds")
    parser.add_argument("--subject", "-S", default=None, help="Path to subject image (transparent PNG) to paste at subject_rect")
    parser.add_argument("--text-art", default=None, dest="text_art", help="Path to text art image (transparent PNG) to paste at text_art_rect")
    parser.add_argument("--dialog", default=None, dest="dialog", help="Path to dialog image (transparent PNG) to paste at dialog_rect")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS), default="default", help="Canvas preset (default: default)")
    group.add_argument("--width", "-W", type=int, help="Canvas width (use with --height)")
    parser.add_argument("--height", "-H", type=int, help="Canvas height (use with --width)")
    args = parser.parse_args()

    if args.width is not None and args.height is not None:
        width, height = args.width, args.height
        preset_arg = None
    else:
        width, height = PRESETS[args.preset]
        preset_arg = args.preset

    saved = compose(
        args.background,
        args.output,
        args.main_title,
        args.subtitle,
        width=width,
        height=height,
        use_ai_linebreak=not getattr(args, "no_ai_linebreak", False),
        logo_path=getattr(args, "logo", None),
        preset=preset_arg,
        font_path=getattr(args, "font", None),
        font_path_regular=getattr(args, "font_regular", None),
        gradient_variant=getattr(args, "variant", 1),
        subject_path=getattr(args, "subject", None),
        text_art_path=getattr(args, "text_art", None),
        dialog_path=getattr(args, "dialog", None),
    )
    print(f"Saved: {saved}")


if __name__ == "__main__":
    main()
