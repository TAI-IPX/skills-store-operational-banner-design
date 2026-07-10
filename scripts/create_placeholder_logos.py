#!/usr/bin/env python3
"""创建联合 logo 占位图：assets/logo1.png、assets/logo2.png，供 combine_joint_logo 使用。"""
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要 Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "scripts" / "assets"
HEIGHT = 50


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    # 图1：可替换 logo 占位（简单几何块 + 文字 "Logo"）
    w1 = 80
    img1 = Image.new("RGBA", (w1, HEIGHT), (60, 60, 60, 255))
    d1 = ImageDraw.Draw(img1)
    d1.rectangle([8, 8, 32, HEIGHT - 8], outline=(255, 255, 255), width=2)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14) if sys.platform == "win32" else ImageFont.load_default()
    except OSError:
        f = ImageFont.load_default()
    d1.text((38, max(0, HEIGHT // 2 - 7)), "Logo", fill=(255, 255, 255), font=f)
    img1.save(ASSETS / "logo1.png")
    print(f"已创建: {ASSETS / 'logo1.png'}")

    # 图2：固定 logo 占位（LEGION ZONE 风格：深底 + 白字）
    w2 = 160
    img2 = Image.new("RGBA", (w2, HEIGHT), (20, 20, 20, 255))
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([6, 6, 28, HEIGHT - 6], outline=(255, 255, 255), width=1)
    try:
        f2 = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16) if sys.platform == "win32" else ImageFont.load_default()
    except OSError:
        f2 = ImageFont.load_default()
    d2.text((34, max(0, HEIGHT // 2 - 8)), "LEGION ZONE", fill=(255, 255, 255), font=f2)
    img2.save(ASSETS / "logo2.png")
    print(f"已创建: {ASSETS / 'logo2.png'}")
    return None


if __name__ == "__main__":
    main()
