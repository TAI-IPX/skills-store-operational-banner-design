#!/usr/bin/env python3
"""
用 Lovart 生成图标并自动抠图，输出透明底 PNG。

用法：
    python scripts/generate_bubble_icon_lovart.py --prompt "课程3d图标..." --output input/course_icon.png
    python scripts/generate_bubble_icon_lovart.py --prompt "..." --output input/icon.png --no-remove-bg
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lovart_helper import generate_t2i


def remove_white_bg(input_path: str, output_path: str) -> None:
    """OpenCV 轮廓检测裁切 + 距离渐变去白底"""
    img_cv = cv2.imread(input_path)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

    # 找非白色区域轮廓
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("[remove_bg] 未找到轮廓，直接输出原图")
        Image.open(input_path).convert("RGBA").save(output_path, "PNG")
        return

    all_pts = np.concatenate(contours)
    x, y, w, h = cv2.boundingRect(all_pts)
    pad = 12
    h_img, w_img = img_cv.shape[:2]
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(w_img, x + w + pad)
    y2 = min(h_img, y + h + pad)
    print(f"[remove_bg] 裁切区域: ({x1},{y1})-({x2},{y2})  {x2-x1}×{y2-y1}")

    img_rgba = Image.open(input_path).convert("RGBA")
    cropped = img_rgba.crop((x1, y1, x2, y2))

    # 基于与白色距离的平滑 alpha
    data = np.array(cropped, dtype=np.float32)
    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]
    dist = np.sqrt((255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2)
    alpha = np.clip((dist - 15) / 45, 0, 1) * 255
    data[:, :, 3] = alpha

    result = Image.fromarray(data.astype(np.uint8))
    result.save(output_path, "PNG")
    print(f"[remove_bg] 已保存: {output_path}  {result.size}")


def main():
    parser = argparse.ArgumentParser(description="Lovart 生成图标 + 自动抠图")
    parser.add_argument("--prompt", "-p", required=True, help="图标生成提示词")
    parser.add_argument("--output", "-o", default="input/icon_transparent.png", help="输出透明底 PNG 路径")
    parser.add_argument("--raw", default=None, help="原始生成图保存路径（默认与 output 同名加 _raw）")
    parser.add_argument("--no-remove-bg", action="store_true", help="跳过抠图，直接输出原图")
    args = parser.parse_args()

    out_path = Path(args.output)
    raw_path = Path(args.raw) if args.raw else out_path.parent / (out_path.stem + "_raw.png")
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Lovart 文生图
    print(f"[lovart] 开始生成图标...")
    result = generate_t2i(args.prompt, str(raw_path))
    if not result:
        print("[lovart] 生成失败", file=sys.stderr)
        sys.exit(1)
    print(f"[lovart] 原始图已保存: {raw_path}")

    if args.no_remove_bg:
        Image.open(str(raw_path)).convert("RGBA").save(str(out_path), "PNG")
        print(f"[skip] 已直接输出: {out_path}")
        return

    # Step 2: 抠图
    remove_white_bg(str(raw_path), str(out_path))


if __name__ == "__main__":
    main()
