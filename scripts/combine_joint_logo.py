#!/usr/bin/env python3
"""联合 logo 合成：图1（可替换）— 20px — 22×22 白色 X 按钮 — 20px — 图2（固定 logo），整体高度 50px。"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
HEIGHT = 50
GAP_PX = 20
X_BUTTON_SIZE = 22
X_BUTTON_COLOR = "#FFFFFF"  # X 线条颜色，无背景
X_STROKE_WIDTH = 2


def load_and_scale_to_height(path: Path, height: int) -> Image.Image:
    """加载图片并按高度等比缩放，保持宽高比。"""
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    if h <= 0:
        return img
    scale = height / h
    nw = max(1, int(w * scale))
    nh = height
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def draw_x_button(size: int, stroke_color: str, stroke_width: int) -> Image.Image:
    """绘制 22×22 X 按钮：无背景，仅 X 线条 #FFFFFF，上下左右对称（中心交点，四臂等长）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = size // 2  # 中心
    half_arm = (size - 1) // 2 - 2  # 从中心到端点的半臂长，留约 2px 边距
    half_arm = max(2, half_arm)
    # 两条对角线，交点 (cx,cx)，四端点与中心等距
    draw.line([(cx - half_arm, cx - half_arm), (cx + half_arm, cx + half_arm)], fill=stroke_color, width=stroke_width)
    draw.line([(cx + half_arm, cx - half_arm), (cx - half_arm, cx + half_arm)], fill=stroke_color, width=stroke_width)
    return img


def combine_joint_logo(
    logo1_path: Path,
    logo2_path: Path,
    output_path: Path,
    height: int = HEIGHT,
    gap: int = GAP_PX,
    x_size: int = X_BUTTON_SIZE,
) -> None:
    """合成联合 logo：logo1 | gap | X按钮 | gap | logo2，整体高度 height。"""
    logo1 = load_and_scale_to_height(logo1_path, height)
    logo2 = load_and_scale_to_height(logo2_path, height)
    x_btn = draw_x_button(x_size, X_BUTTON_COLOR, X_STROKE_WIDTH)

    w1, _ = logo1.size
    w2, _ = logo2.size
    total_w = w1 + gap + x_size + gap + w2

    out = Image.new("RGBA", (total_w, height), (0, 0, 0, 0))
    x_pos = 0
    out.paste(logo1, (x_pos, 0), logo1 if logo1.mode == "RGBA" else None)
    x_pos += w1 + gap
    # X 按钮在高度内居中
    y_btn = (height - x_size) // 2
    out.paste(x_btn, (x_pos, y_btn), x_btn)
    x_pos += x_size + gap
    out.paste(logo2, (x_pos, 0), logo2 if logo2.mode == "RGBA" else None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(output_path), "PNG")
    print(f"已保存: {output_path}")


def main() -> None:
    default_logo1 = ROOT / "scripts" / "assets" / "logo1.png"
    default_logo2 = ROOT / "scripts" / "assets" / "logo2.png"
    parser = argparse.ArgumentParser(
        description="联合 logo：图1 — 20px — 22×22 白色 X 按钮 — 20px — 图2，高度 50px"
    )
    parser.add_argument("--logo1", "-1", default=None, help="前面可替换 logo（图1），不传则用 assets/logo1.png")
    parser.add_argument("--logo2", "-2", default=None, help="后面固定 logo（图2），不传则用 assets/logo2.png")
    parser.add_argument("--output", "-o", default=None, help="输出路径，默认 output/joint_logo.png")
    parser.add_argument("--height", type=int, default=HEIGHT, help=f"整体高度，默认 {HEIGHT}")
    args = parser.parse_args()

    logo1 = Path(args.logo1 or default_logo1).resolve()
    logo2 = Path(args.logo2 or default_logo2).resolve()
    if not logo1.is_file():
        print(f"Error: 未找到图1: {logo1}", file=sys.stderr)
        print("请将可替换 logo 放到 assets/logo1.png 或使用 --logo1 指定路径。", file=sys.stderr)
        sys.exit(1)
    if not logo2.is_file():
        print(f"Error: 未找到图2: {logo2}", file=sys.stderr)
        print("请将固定 logo 放到 assets/logo2.png 或使用 --logo2 指定路径。", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output).resolve() if args.output else OUTPUT_DIR / "joint_logo.png"
    combine_joint_logo(logo1, logo2, out_path, height=args.height)
    return None


if __name__ == "__main__":
    main()
