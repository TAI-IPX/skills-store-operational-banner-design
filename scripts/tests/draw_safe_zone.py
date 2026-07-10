#!/usr/bin/env python3
"""在 banner 图上用红色方框标出安全区 (1976×464: x=931～1457, y=0～464)。"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow: pip install Pillow", file=__import__("sys").stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_PATH = ROOT / "output" / "office_visual_banner.png"
OUTPUT_PATH = ROOT / "output" / "office_visual_banner_safe_zone.png"

# 安全区：画布 1976×464 固定值
X_MIN, X_MAX = 931, 1457
Y_MIN, Y_MAX = 0, 464

def main():
    if not INPUT_PATH.is_file():
        print(f"未找到图片: {INPUT_PATH}", file=__import__("sys").stderr)
        raise SystemExit(1)
    img = Image.open(INPUT_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)
    # 红色矩形框，线宽 4
    draw.rectangle([X_MIN, Y_MIN, X_MAX, Y_MAX], outline=(255, 0, 0), width=4)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT_PATH)
    print(f"已保存（红框标出安全区）: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
