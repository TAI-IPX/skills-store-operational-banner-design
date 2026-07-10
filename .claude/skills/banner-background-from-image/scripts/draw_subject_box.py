#!/usr/bin/env python3
"""在图片上用红框标出 Gemini 检测到的主体边界框。需 GEMINI_API_KEY。"""
import os
import sys
from pathlib import Path

# 从项目根 .env 加载 GEMINI_API_KEY（若存在）
_root = Path(__file__).resolve().parent
for _ in range(6):
    _root = _root.parent
    _env = _root / ".env"
    if _env.is_file():
        with open(_env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY=") and "=" in line:
                    _, _, value = line.partition("=")
                    value = value.strip().strip("'\"")
                    if value:
                        os.environ["GEMINI_API_KEY"] = value
                    break
        break

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# 同目录下的主体检测
from gemini_subject_detect import detect_subject_bbox


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: draw_subject_box.py <image_path> [output_path]", file=sys.stderr)
        sys.exit(1)
    image_path = Path(sys.argv[1])
    if not image_path.is_file():
        print(f"未找到图片: {image_path}", file=sys.stderr)
        sys.exit(1)

    bbox = detect_subject_bbox(str(image_path))
    if bbox is None:
        print("主体边界框检测失败（请设置 GEMINI_API_KEY 或检查网络）。", file=sys.stderr)
        sys.exit(1)

    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    x_min, y_min, x_max, y_max = bbox
    left = int(x_min * w)
    top = int(y_min * h)
    right = int(x_max * w)
    bottom = int(y_max * h)
    left = max(0, min(left, w - 2))
    top = max(0, min(top, h - 2))
    right = max(left + 2, min(right, w))
    bottom = max(top + 2, min(bottom, h))

    draw = ImageDraw.Draw(img)
    draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=4)

    if len(sys.argv) >= 3:
        out_path = Path(sys.argv[2])
    else:
        out_path = image_path.parent / f"{image_path.stem}_subject_box{image_path.suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    print(f"已保存（红框标出主体）: {out_path}")


if __name__ == "__main__":
    main()
