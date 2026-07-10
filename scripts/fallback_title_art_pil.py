#!/usr/bin/env python3
"""
当文生图 API 不可用时，用系统字体生成简易透明底艺术字 PNG（非书法效果，仅保证流水线可合成预览）。
主文案默认「前程似锦」置于 title_art_rect 内；落款「Sunrise Ai」在画布底部居中。
"""
import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Requires Pillow.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
_SPEC = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC.is_dir():
    sys.path.insert(0, str(_SPEC))
import spec as _spec


def _yahei_bold(size: int) -> ImageFont.FreeTypeFont:
    if sys.platform == "win32":
        fonts = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts"
        for name in ("msyhbd.ttc", "MSYHBD.TTC", "msyhbd.ttf"):
            p = fonts / name
            if p.is_file():
                return ImageFont.truetype(str(p), size)
    for d in (Path.home() / "Library" / "Fonts", Path("/Library/Fonts")):
        if d.is_dir():
            for name in ("msyhbd.ttc", "msyhbd.ttf"):
                p = d / name
                if p.is_file():
                    return ImageFont.truetype(str(p), size)
    raise RuntimeError("未找到微软雅黑 Bold，将使用默认字体（可能无法显示中文）")


def _fit_font_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_loader,
    max_w: int,
    max_h: int,
    size_min: int = 24,
    size_max: int = 400,
) -> ImageFont.FreeTypeFont:
    lo, hi = size_min, size_max
    best = font_loader(size_min)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = font_loader(mid)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= max_w and th <= max_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description="简易透明字层回退（PIL）")
    parser.add_argument("--main", default="前程似锦", dest="main_text", help="主文案")
    parser.add_argument("--footer", default="Sunrise Ai", help="底部落款英文")
    parser.add_argument("--output", "-o", required=True, help="输出 PNG 路径")
    parser.add_argument("--preset", "-p", default="legend_top_banner_3840", help="读取 title_art_rect 的 preset")
    args = parser.parse_args()

    w, h = _spec.PRESETS[args.preset]
    layout = _spec.get_layout(w, h, args.preset)
    rect = layout.get("title_art_rect")
    if not rect:
        print("Error: layout 无 title_art_rect", file=sys.stderr)
        sys.exit(1)
    x_min, x_max, y_min, y_max = rect
    rw = x_max - x_min
    rh = y_max - y_min
    fit_scale = float(layout.get("title_art_fit_scale", 1.0))
    inner_w = max(1, int(rw * fit_scale))
    inner_h = max(1, int(rh * fit_scale))
    ox = x_min + (rw - inner_w) // 2
    oy = y_min + (rh - inner_h) // 2

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def load_bold(sz: int) -> ImageFont.FreeTypeFont:
        try:
            return _yahei_bold(sz)
        except RuntimeError:
            return ImageFont.load_default()

    tmp = Image.new("RGBA", (1, 1))
    tmp_draw = ImageDraw.Draw(tmp)
    main_font = _fit_font_size(
        tmp_draw, args.main_text, load_bold, inner_w - 8, inner_h - 8, 40, 320
    )
    mb = draw.textbbox((0, 0), args.main_text, font=main_font)
    mw, mh = mb[2] - mb[0], mb[3] - mb[1]
    mx = ox + (inner_w - mw) // 2
    my = oy + (inner_h - mh) // 2
    draw.text((mx, my), args.main_text, font=main_font, fill=(0, 0, 0, 255))

    footer_size = max(18, min(36, w // 120))
    try:
        foot_font = _yahei_bold(footer_size)
    except RuntimeError:
        foot_font = ImageFont.load_default()
    fb = draw.textbbox((0, 0), args.footer, font=foot_font)
    fw, fh = fb[2] - fb[0], fb[3] - fb[1]
    fx = (w - fw) // 2
    fy = h - fh - 36
    draw.text((fx, fy), args.footer, font=foot_font, fill=(0, 0, 0, 230))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), "PNG")
    print(f"[fallback_title_art_pil] 已写入: {out}")


if __name__ == "__main__":
    main()
