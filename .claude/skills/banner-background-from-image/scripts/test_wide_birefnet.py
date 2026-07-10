#!/usr/bin/env python3
"""
仅测试 3320×500 顶部条带 BiRefNet 抠图：将输入图做成 3320×500 画布，执行 A5b 条带合成并保存。
不依赖 Gemini，仅需 torch / transformers（BiRefNet）。
用法:
  python test_wide_birefnet.py -i <输入图> -o <输出 PNG>
  或使用指定 Python: D:\\cursor\\biyaozujian\\Python\\python.exe test_wide_birefnet.py -i 图 -o 出
  或双击 run_test_wide_birefnet.bat 并拖入图片。
"""

import argparse
import shutil
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from PIL import Image


def build_3320x500_canvas(image_path: str) -> Image.Image:
    """把输入图按「覆盖」方式裁成 3320×500。"""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    target_w, target_h = 3320, 500
    scale = max(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(h * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (nw - target_w) // 2
    y = (nh - target_h) // 2
    return img.crop((x, y, x + target_w, y + target_h))


def main():
    parser = argparse.ArgumentParser(description="测试 3320×500 顶部条带 BiRefNet 抠图")
    parser.add_argument("-i", "--input", required=True, help="输入图片路径")
    parser.add_argument("-o", "--output", default=None, help="输出 PNG 路径，默认 input_wide_birefnet.png")
    args = parser.parse_args()
    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"Error: 文件不存在 {in_path}", file=sys.stderr)
        sys.exit(1)
    out_path = Path(args.output) if args.output else in_path.parent / f"{in_path.stem}_wide_birefnet.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("构建 3320×500 画布...", flush=True)
    canvas = build_3320x500_canvas(str(in_path))
    tmp_path = out_path.parent / f"{out_path.stem}_canvas.png"
    canvas.save(tmp_path, "PNG")

    print("执行顶部条带 BiRefNet 抠图...", flush=True)
    from prepare_background import _composite_wide_top_strip_birefnet
    _composite_wide_top_strip_birefnet(str(tmp_path))
    shutil.copy2(tmp_path, out_path)
    tmp_path.unlink()
    print(f"已保存: {out_path}", flush=True)


if __name__ == "__main__":
    main()
