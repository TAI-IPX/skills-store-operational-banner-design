#!/usr/bin/env python3
"""
程序化绘制六边形横幅底托（对标线上 SVG 素材）。

形状：M30,0 H478 L508,24 L478,48 H30 L0,24 Z
  - 主体矩形 + 左右箭头端点
  - 内阴影（颜色自动推导）
  - 描边（颜色自动推导）2px

颜色来源：
  1. --color <hex>  直接指定填充色（描边/阴影自动推导）
  2. --bg <path> --region x1 y1 x2 y2  从背景图区域提取主色，三色全部自动推导

用法：
  py scripts/generate_dialog_banner.py --color "#9D2626" --output output/dialog.png
  py scripts/generate_dialog_banner.py --bg output/bg.png --region 516 363 1021 410 --output output/dialog.png
"""

import argparse
import colorsys
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    print("Requires Pillow. Install: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# SVG 原始尺寸
SVG_W = 508
SVG_H = 48
ARROW_INDENT = 30   # 左右箭头缩进量
STROKE_WIDTH = 2
INNER_SHADOW_DY = 3
INNER_SHADOW_BLUR = 3


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """相对亮度（WCAG）。"""
    def _c(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _c(rgb[0]) + 0.7152 * _c(rgb[1]) + 0.0722 * _c(rgb[2])


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1 = _luminance(fg) + 0.05
    l2 = _luminance(bg) + 0.05
    return max(l1, l2) / min(l1, l2)


def _derive_stroke_color(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    """从底色推导描边色：
    - 取底色色相，提高亮度到 90%+，降低饱和度到 30% 以下，得到接近白/米色的高亮色
    - 若底色本身极亮（v>0.85），则用底色压暗 40% 作为描边
    """
    r, g, b = fill
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v > 0.85:
        # 亮色底：描边用压暗色
        stroke_v = max(0.0, v - 0.4)
        stroke_s = min(1.0, s * 1.2)
        sr, sg, sb = [int(x * 255) for x in colorsys.hsv_to_rgb(h, stroke_s, stroke_v)]
    else:
        # 暗/中色底：描边用同色相高亮米色（v→0.95, s→0.15）
        sr, sg, sb = [int(x * 255) for x in colorsys.hsv_to_rgb(h, 0.15, 0.95)]
    return (sr, sg, sb)


def _derive_shadow_color(fill: tuple[int, int, int]) -> tuple[tuple[int, int, int], float]:
    """从底色推导内阴影色和不透明度：
    - 暗色底（v<0.4）：用白色阴影，opacity 0.15（提亮内部）
    - 中色底（0.4~0.7）：用黑色阴影，opacity 0.20
    - 亮色底（v>0.7）：用黑色阴影，opacity 0.30
    """
    r, g, b = fill
    _, _, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.4:
        return (255, 255, 255), 0.15
    elif v < 0.7:
        return (0, 0, 0), 0.20
    else:
        return (0, 0, 0), 0.30


def _extract_dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """从图像提取主色调（PIL quantize 取最多像素的颜色）。"""
    small = img.convert("RGB").resize((64, 64), Image.Resampling.LANCZOS)
    quantized = small.quantize(colors=8, method=Image.Quantize.FASTOCTREE)
    palette = quantized.getpalette()
    hist = quantized.histogram()
    best_idx = max(range(8), key=lambda i: hist[i])
    return (palette[best_idx * 3], palette[best_idx * 3 + 1], palette[best_idx * 3 + 2])


def _ensure_contrast(color: tuple[int, int, int], min_ratio: float = 4.5) -> tuple[int, int, int]:
    """压暗颜色直到白色文字对比度 >= min_ratio。"""
    white = (255, 255, 255)
    r, g, b = color
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    # 先增强饱和度
    s = min(1.0, s * 1.3)
    for _ in range(50):
        if _contrast_ratio(white, (int(r), int(g), int(b))) >= min_ratio:
            break
        v = max(0.0, v - 0.03)
        r, g, b = [x * 255 for x in colorsys.hsv_to_rgb(h, s, v)]
    return (int(r), int(g), int(b))


def _make_gradient_fill(w: int, h: int, color: tuple[int, int, int]) -> Image.Image:
    """生成左深右浅的渐变填充（主色 → 主色亮化 20%）。"""
    hr, hg, hb = color
    hh, hs, hv = colorsys.rgb_to_hsv(hr / 255, hg / 255, hb / 255)
    # 右侧亮化
    light_v = min(1.0, hv * 1.25)
    light_r, light_g, light_b = [int(x * 255) for x in colorsys.hsv_to_rgb(hh, max(0, hs * 0.85), light_v)]

    grad = Image.new("RGB", (w, h))
    pixels = grad.load()
    for px in range(w):
        t = px / max(w - 1, 1)
        pr = int(hr * (1 - t) + light_r * t)
        pg = int(hg * (1 - t) + light_g * t)
        pb = int(hb * (1 - t) + light_b * t)
        for py in range(h):
            pixels[px, py] = (pr, pg, pb)
    return grad


def _hexagon_points(w: int, h: int) -> list[tuple[float, float]]:
    """按目标尺寸缩放 SVG 六边形顶点。"""
    sx = w / SVG_W
    sy = h / SVG_H
    mid_y = h / 2
    return [
        (ARROW_INDENT * sx, 0),
        (w - ARROW_INDENT * sx, 0),
        (w, mid_y),
        (w - ARROW_INDENT * sx, h),
        (ARROW_INDENT * sx, h),
        (0, mid_y),
    ]


def draw_banner(
    color: tuple[int, int, int],
    width: int = SVG_W,
    height: int = SVG_H,
    *,
    stroke_color: tuple[int, int, int] | None = None,
    shadow_color: tuple[int, int, int] | None = None,
    shadow_opacity: float | None = None,
) -> Image.Image:
    """绘制六边形横幅，返回 RGBA Image。
    stroke_color / shadow_color / shadow_opacity 未传时自动从 color 推导。
    """
    if stroke_color is None:
        stroke_color = _derive_stroke_color(color)
    if shadow_color is None or shadow_opacity is None:
        _sc, _so = _derive_shadow_color(color)
        if shadow_color is None:
            shadow_color = _sc
        if shadow_opacity is None:
            shadow_opacity = _so
    # 超采样 3x 提升边缘质量
    SS = 3
    cw, ch = width * SS, height * SS
    pts = _hexagon_points(cw, ch)

    # 1. 渐变填充层
    grad = _make_gradient_fill(cw, ch, color)

    # 2. 六边形遮罩
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)

    # 3. 合成填充
    base = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    grad_rgba = grad.convert("RGBA")
    base.paste(grad_rgba, mask=mask)

    # 4. 内阴影：底部叠加推导阴影色
    shadow_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.polygon(pts, fill=(*shadow_color, int(255 * shadow_opacity)))
    dy_scaled = int(INNER_SHADOW_DY * SS)
    blur_scaled = INNER_SHADOW_BLUR * SS
    # 向下偏移后模糊
    shifted = Image.new("RGBA", (cw, ch + dy_scaled), (0, 0, 0, 0))
    shifted.paste(shadow_layer, (0, dy_scaled))
    shifted = shifted.filter(ImageFilter.GaussianBlur(radius=blur_scaled))
    shifted = shifted.crop((0, 0, cw, ch))
    # 只保留形状内部（用 mask 限制）
    inner_mask_img = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(inner_mask_img).polygon(pts, fill=255)
    # 将 shifted 的 alpha 与 inner_mask 相乘
    shifted_arr = shifted.split()  # R,G,B,A
    import PIL.ImageChops as _chops
    clipped_alpha = _chops.multiply(shifted_arr[3], inner_mask_img)
    shifted.putalpha(clipped_alpha)
    base = Image.alpha_composite(base, shifted)

    # 5. 描边（推导色）
    stroke_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    stroke_draw = ImageDraw.Draw(stroke_layer)
    sw = STROKE_WIDTH * SS
    stroke_draw.polygon(pts, outline=(*stroke_color, 255), width=sw)
    base = Image.alpha_composite(base, stroke_layer)

    # 6. 缩小到目标尺寸
    result = base.resize((width, height), Image.Resampling.LANCZOS)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="生成六边形横幅底托（程序化，颜色自动匹配背景）")
    parser.add_argument("--color", default=None, help="填充色 hex，如 #9D2626")
    parser.add_argument("--bg", default=None, help="背景图路径（与 --region 配合提取主色）")
    parser.add_argument("--region", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"),
                        default=None, help="从背景图提取颜色的区域坐标")
    parser.add_argument("--width", type=int, default=SVG_W, help=f"输出宽度（默认 {SVG_W}）")
    parser.add_argument("--height", type=int, default=SVG_H, help=f"输出高度（默认 {SVG_H}）")
    parser.add_argument("--output", "-o", required=True, help="输出 PNG 路径")
    parser.add_argument("--min-contrast", type=float, default=4.5,
                        help="白色文字最低对比度（WCAG AA=4.5，默认 4.5）")
    args = parser.parse_args()

    if args.color:
        color = _hex_to_rgb(args.color)
    elif args.bg and args.region:
        bg = Image.open(args.bg).convert("RGB")
        x1, y1, x2, y2 = args.region
        region = bg.crop((x1, y1, x2, y2))
        color = _extract_dominant_color(region)
        print(f"提取主色: {_rgb_to_hex(color)} {color}", flush=True)
    else:
        print("Error: 需要 --color 或 --bg + --region", file=sys.stderr)
        sys.exit(1)

    color = _ensure_contrast(color, min_ratio=args.min_contrast)
    stroke_color = _derive_stroke_color(color)
    shadow_color, shadow_opacity = _derive_shadow_color(color)
    print(f"底色:   {_rgb_to_hex(color)} {color}", flush=True)
    print(f"描边色: {_rgb_to_hex(stroke_color)} {stroke_color}", flush=True)
    print(f"阴影色: {_rgb_to_hex(shadow_color)} opacity={shadow_opacity:.2f}", flush=True)

    banner = draw_banner(
        color, width=args.width, height=args.height,
        stroke_color=stroke_color,
        shadow_color=shadow_color,
        shadow_opacity=shadow_opacity,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    banner.save(str(out), "PNG")
    print(f"已保存: {out}", flush=True)


if __name__ == "__main__":
    main()
