#!/usr/bin/env python3
"""
用 BiRefNet 抠出图片中指定区域的主体，输出带透明通道的 PNG。
用法:
  python scripts/extract_subject_birefnet.py <input_image> [--crop x1 y1 x2 y2] [--output output.png]

  --crop: 可选，先裁切指定区域再抠图（像素坐标，左上到右下）
          若不指定则对全图做 BiRefNet
  --output: 输出路径，默认 output/extracted_subject.png
  --alpha-threshold: alpha 二值化阈值 0~1，默认 0.7（与 --no-binarize 互斥）
  --no-binarize: 保留 BiRefNet 连续 alpha，发丝/半透明边缘更柔和
"""

import argparse
import os
import sys
from pathlib import Path

# 使用镜像站点解决 HuggingFace 连接超时
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_OFFLINE', '0')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".claude/skills/banner-background-from-image/scripts"))


def _get_alpha_threshold() -> float:
    """从环境变量 BIREFNET_ALPHA_THRESHOLD 读取，若未设置则返回 0.7（边缘更干净）"""
    env_val = os.environ.get("BIREFNET_ALPHA_THRESHOLD")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return 0.7


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="输入图片路径")
    parser.add_argument(
        "--crop",
        nargs=4,
        type=int,
        metavar=("X1", "Y1", "X2", "Y2"),
        help="裁切区域（像素），左上角到右下角",
    )
    parser.add_argument("--output", default="output/subject_rgba.png")
    parser.add_argument("--alpha-threshold", type=float, default=None,
                        help=f"alpha 二值化阈值 0~1，默认从环境变量 BIREFNET_ALPHA_THRESHOLD 读取（当前：{_get_alpha_threshold()}），或 0.7")
    parser.add_argument(
        "--no-binarize",
        action="store_true",
        help="不做 alpha 二值化，保留模型输出的柔和边缘",
    )
    args = parser.parse_args()

    # 若未显式指定，则从环境变量读取
    alpha_threshold = args.alpha_threshold if args.alpha_threshold is not None else _get_alpha_threshold()

    from PIL import Image
    import numpy as np

    img = Image.open(args.input).convert("RGB")
    w, h = img.size
    print(f"[info] 原图尺寸: {w}x{h}")

    if args.crop:
        x1, y1, x2, y2 = args.crop
        region = img.crop((x1, y1, x2, y2))
        print(f"[info] 裁切区域: ({x1},{y1}) -> ({x2},{y2})，尺寸 {region.size}")
    else:
        region = img
        x1, y1 = 0, 0

    # 导入 BiRefNet
    from birefnet_matting import load_birefnet_matting, extract_alpha_pil

    print("[info] 加载 BiRefNet 模型（首次运行会从 HuggingFace 下载）...")
    model = load_birefnet_matting()
    print("[info] 推理中...")
    alpha = extract_alpha_pil(region, model=model)

    if args.no_binarize:
        alpha_use = alpha
    else:
        a_arr = np.array(alpha, dtype=np.float32) / 255.0
        a_arr = (a_arr >= alpha_threshold).astype(np.uint8) * 255
        alpha_use = Image.fromarray(a_arr, mode="L")

    result = region.convert("RGBA")
    result.putalpha(alpha_use)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(out_path))
    print(f"[output] Saved to: {out_path}")
    print(f"[done] 已保存: {out_path}  尺寸: {result.size}")


if __name__ == "__main__":
    main()
