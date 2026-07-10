#!/usr/bin/env python3
"""
生成气泡装饰图标（bubble_icon），并合成气泡预览图。

用法：
    python scripts/generate_bubble_icon.py --icon input/icon.png --text "今天星期五了"
    python scripts/generate_bubble_icon.py --icon input/icon.png --text "文案" --theme pink
    python scripts/generate_bubble_icon.py --icon input/icon.png --text "文案" --output-dir output/my_bubble

流程：
    1. 将输入 icon（透明底 PNG）缩放到 38×38px，输出 bubble_icon_Nx.png
    2. 生成气泡背景图（调用 make_bubble）
    3. 将 icon 叠加在气泡左上角（x=0, y=0），输出合成预览图 bubble_preview_Nx.png
"""

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

# 引入气泡背景生成函数
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from generate_bubble import make_bubble, SCALES

# ── icon 规范 ────────────────────────────────────────────────────
ICON_SIZE = 38   # 1x 基准尺寸（正方形）

# 5套主题：背景渐变色 + 对应文字颜色
THEMES = {
    "pink":   {"grad": (254, 166, 166), "text": (130, 20,  77)},   # #FEA6A6 / #82144D
    "yellow": {"grad": (255, 229, 125), "text": (124, 55,  32)},   # #FFE57D / #7C3720
    "green":  {"grad": (74,  208, 147), "text": (56,  110, 66)},   # #4AD093 / #386E42
    "blue":   {"grad": (104, 164, 255), "text": (38,  49,  95)},   # #68A4FF / #26315F
    "purple": {"grad": (202, 148, 255), "text": (105, 5,   126)},  # #CA94FF / #69057E
}


def make_icon(icon_img: Image.Image, scale: float) -> Image.Image:
    """将 icon 缩放到目标尺寸，保留透明通道"""
    size = round(ICON_SIZE * scale)
    return icon_img.resize((size, size), Image.LANCZOS)


def make_preview(bubble_img: Image.Image, icon_img: Image.Image, scale: float) -> Image.Image:
    """将 icon 叠加在气泡左上角 (x=0, y=0)，输出合成预览图"""
    # 画布大小：取气泡和 icon 的最大范围
    canvas_w = max(bubble_img.width, icon_img.width)
    canvas_h = max(bubble_img.height, icon_img.height)
    preview = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # 先贴气泡背景
    preview.alpha_composite(bubble_img, (0, 0))
    # 再叠 icon（x=0, y=0，允许溢出）
    preview.alpha_composite(icon_img, (0, 0))
    return preview


def main():
    parser = argparse.ArgumentParser(description="生成气泡 icon 及合成预览图")
    parser.add_argument("--icon", required=True, help="透明底 icon PNG 路径（BiRefNet 抠图输出）")
    parser.add_argument("--text", required=True, help="气泡内显示的文字")
    parser.add_argument(
        "--theme",
        default="blue",
        choices=list(THEMES.keys()),
        help="主题色（pink/yellow/green/blue/purple），默认 blue",
    )
    parser.add_argument("--output-dir", default=None, help="输出目录（默认 output/bubble_icon_YYYYMMDD_HHMMSS）")
    args = parser.parse_args()

    # 加载 icon
    icon_path = Path(args.icon)
    if not icon_path.exists():
        print(f"错误：找不到 icon 文件 {icon_path}")
        sys.exit(1)
    icon_src = Image.open(icon_path).convert("RGBA")

    # 输出目录
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else Path(f"output/bubble_icon_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 切换主题色和文字颜色
    import generate_bubble as gb
    theme = THEMES[args.theme]
    gb.GRAD_LEFT = theme["grad"]
    text_color = theme["text"]

    scale_names = {1: "1x", 1.5: "1.5x", 2: "2x", 3: "3x"}
    for scale in SCALES:
        name = scale_names[scale]

        # 1. icon 缩放输出
        icon_scaled = make_icon(icon_src, scale)
        icon_path_out = out_dir / f"bubble_icon_{name}.png"
        icon_scaled.save(icon_path_out, "PNG")
        print(f"icon    {name}: {icon_scaled.width}x{icon_scaled.height} -> {icon_path_out.name}")

        # 2. 气泡背景（带关闭按钮，使用主题对应文字颜色）
        bubble = make_bubble(args.text, scale, text_color=text_color)

        # 3. 合成预览图
        preview = make_preview(bubble, icon_scaled, scale)
        preview_path_out = out_dir / f"bubble_preview_{name}.png"
        preview.save(preview_path_out, "PNG")
        print(f"preview {name}: {preview.width}x{preview.height} -> {preview_path_out.name}")

    print(f"\n输出目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
