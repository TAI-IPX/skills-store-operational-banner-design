#!/usr/bin/env python3
"""
对图像某一区域做 BiRefNet 抠图并输出 RGBA PNG。
海报等多主体时建议先裁剪再抠，使目标成为显著前景。

示例（左下角，默认取宽 50%×高 55%）：
  python birefnet_extract_region.py -i poster.png -o cat_cutout.png --preset bottom-left

显式裁剪框（左、上、右、下，像素）：
  python birefnet_extract_region.py -i poster.png -o out.png --box 0 1200 900 2400

洛克王国类竖幅（约 576×1024）左下蓝猫：先框住角色再抠；左侧小角色用 --strip-left 只保留蓝像素；
  --box 0 265 536 1012 --strip-left 108 --keep-largest-cc --open-kernel 0
大字与角色在模型里粘连时，可再调 --alpha-threshold 或用笔刷修边。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _crop_bottom_left(im, width_frac: float, height_frac: float):
    """返回 (crop_pil, box) box=(l,t,r,b)"""
    w, h = im.size
    l = 0
    t = max(0, int(round(h * (1.0 - height_frac))))
    r = max(1, int(round(w * width_frac)))
    b = h
    return im.crop((l, t, r, b)), (l, t, r, b)


def _refine_alpha_largest_cc(
    alpha_u8: "np.ndarray",
    _rgb: "np.ndarray",
    *,
    open_kernel: int = 3,
) -> "np.ndarray":
    """
    保留最大连通前景，去掉与主体分离的小块（如白字、碎块）。
    可选形态学开运算，减弱字与角色之间细连接（需已安装 opencv-python）。
    """
    import numpy as np

    import cv2

    m = (alpha_u8 > 127).astype(np.uint8) * 255
    if open_kernel >= 3:
        k = open_kernel // 2 * 2 + 1
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, ker)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return alpha_u8
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    keep = (labels == largest).astype(np.uint8) * 255
    out = (alpha_u8.astype(np.float32) * (keep > 0).astype(np.float32)).clip(0, 255).astype(np.uint8)
    return out


def _refine_alpha_near_blue_body(
    rgb: "np.ndarray",
    alpha_u8: "np.ndarray",
    *,
    dilate_px: int = 100,
    min_blue_x: int = 0,
) -> "np.ndarray":
    """
    用原图「蓝色皮毛」区域膨胀得到角色大致范围，抑制远离该范围但仍带 alpha 的浅色大字/杂边
    （BiRefNet 常把字与头连成一块，仅靠最大连通域去不掉）。
    min_blue_x：仅使用该列以右的蓝色像素作种子，避免把海报左侧其它小角色也膨胀进掩膜。
    """
    import cv2
    import numpy as np

    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    h, w = alpha_u8.shape
    xs = np.arange(w, dtype=np.int32)[np.newaxis, :].repeat(h, axis=0)
    blue = (
        (b.astype(np.int16) > r + 14)
        & (b.astype(np.int16) > g + 8)
        & (b > 65)
        & (xs >= int(min_blue_x))
    )
    m = np.uint8(blue) * 255
    k = max(3, int(dilate_px) * 2 + 1)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    m = cv2.dilate(m, ker)
    keep = (m > 0).astype(np.float32)
    a = alpha_u8.astype(np.float32) * keep
    return a.clip(0, 255).astype(np.uint8)


def _strip_left_columns_keep_blue_only(
    rgb: "np.ndarray",
    alpha_u8: "np.ndarray",
    *,
    max_x: int = 96,
) -> "np.ndarray":
    """左侧 max_x 列内：仅保留明显蓝色皮毛像素（去掉黑白小角色等）。"""
    import numpy as np

    h, w = alpha_u8.shape
    mx = min(int(max_x), w)
    if mx <= 0:
        return alpha_u8
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    sl = slice(0, mx)
    bl = (
        (b[:, sl].astype(np.int16) > r[:, sl] + 18)
        & (b[:, sl].astype(np.int16) > g[:, sl] + 10)
        & (b[:, sl] > 72)
    )
    out = alpha_u8.copy()
    out[:, sl] = np.where(bl, out[:, sl], 0)
    return out


def _drop_top_neutral_bright(
    alpha_u8: "np.ndarray",
    rgb: "np.ndarray",
    *,
    top_frac: float = 0.45,
    max_alpha_keep: int = 235,
) -> "np.ndarray":
    """
    裁剪区上方条带内：高亮且接近中性灰白的像素多为背景大字，压低 alpha（保留不透明角色像素）。
    """
    import numpy as np

    h, w = alpha_u8.shape
    top = max(1, int(round(h * top_frac)))
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    neutral = (np.abs(r.astype(np.int16) - g) < 22) & (np.abs(g.astype(np.int16) - b) < 22)
    bright = (r.astype(np.int32) + g + b) > 700
    band = np.zeros_like(alpha_u8, dtype=bool)
    band[:top, :] = True
    kill = band & neutral & bright & (alpha_u8 < max_alpha_keep)
    out = alpha_u8.copy()
    out[kill] = 0
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="BiRefNet 区域抠图 → RGBA PNG")
    parser.add_argument("-i", "--input", required=True, help="输入图片路径")
    parser.add_argument("-o", "--output", required=True, help="输出 PNG（带透明通道）")
    parser.add_argument(
        "--preset",
        choices=("bottom-left", "full"),
        default="bottom-left",
        help="bottom-left：左下角区域（适合左下角的猫/角色）；full：整图（多主体时易混）",
    )
    parser.add_argument(
        "--width-frac",
        type=float,
        default=0.52,
        help="preset=bottom-left 时，从左侧取的宽度比例（默认 0.52）",
    )
    parser.add_argument(
        "--height-frac",
        type=float,
        default=0.58,
        help="preset=bottom-left 时，从底部取的高度比例（默认 0.58）",
    )
    parser.add_argument(
        "--box",
        type=int,
        nargs=4,
        metavar=("L", "T", "R", "B"),
        default=None,
        help="可选：显式裁剪框 左 上 右 下（像素），覆盖 preset",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=float,
        default=0.35,
        help="alpha 低于该值（0~1）置透明，略低于 0.5 可多去蓝底杂边（默认 0.35）",
    )
    parser.add_argument(
        "--keep-largest-cc",
        action="store_true",
        help="二值化后保留最大连通域，去掉分离的白字/碎块（推荐海报）",
    )
    parser.add_argument(
        "--open-kernel",
        type=int,
        default=3,
        help="与 --keep-largest-cc 联用：形态学开运算核大小（奇数，默认 3；0 表示不做开运算）",
    )
    parser.add_argument(
        "--drop-top-white",
        action="store_true",
        help="裁剪区上约 45%% 高度内，弱化高亮中性白（常见大字残边）",
    )
    parser.add_argument(
        "--drop-top-max-alpha",
        type=int,
        default=235,
        help="与 --drop-top-white 联用：仅当 alpha 低于该值（0~255）时才清除中性高亮（默认 235，略调低如 228 更激进）",
    )
    parser.add_argument(
        "--near-blue-dilate",
        type=int,
        default=0,
        help=">0 时启用：按原图蓝色身体膨胀该像素数，裁掉远离身体的浅色大字（默认 0 关闭）",
    )
    parser.add_argument(
        "--near-blue-min-x",
        type=int,
        default=0,
        help="与 --near-blue-dilate 联用：仅用 x≥该值的蓝色像素作膨胀种子（默认 0；左有杂角色时可设 70~110）",
    )
    parser.add_argument(
        "--strip-left",
        type=int,
        default=0,
        help=">0 时：在左侧该宽度（列数）内仅保留蓝色像素，去掉左上角杂角色（默认 0 关闭）",
    )
    args = parser.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.is_file():
        print(f"Error: 输入文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    from PIL import Image
    import numpy as np

    im = Image.open(in_path).convert("RGB")
    if args.box is not None:
        l, t, r, b = args.box
        crop = im.crop((l, t, r, b))
        box = (l, t, r, b)
    elif args.preset == "bottom-left":
        crop, box = _crop_bottom_left(im, args.width_frac, args.height_frac)
    else:
        crop = im
        box = (0, 0, im.size[0], im.size[1])

    print(f"[BiRefNet] 裁剪区域 (L,T,R,B)={box}，尺寸 {crop.size}", flush=True)

    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from birefnet_matting import extract_alpha_pil, load_birefnet_matting

    model = load_birefnet_matting()
    alpha = extract_alpha_pil(crop, model=model)

    a = np.array(alpha, dtype=np.float32) / 255.0
    thr = max(0.0, min(1.0, args.alpha_threshold))
    a = np.where(a >= thr, a, 0.0)
    alpha_u8 = (a * 255.0).clip(0, 255).astype("uint8")
    rgb = np.array(crop)
    if args.strip_left > 0:
        alpha_u8 = _strip_left_columns_keep_blue_only(rgb, alpha_u8, max_x=args.strip_left)
    if args.near_blue_dilate > 0:
        alpha_u8 = _refine_alpha_near_blue_body(
            rgb,
            alpha_u8,
            dilate_px=args.near_blue_dilate,
            min_blue_x=args.near_blue_min_x,
        )
    if args.drop_top_white:
        alpha_u8 = _drop_top_neutral_bright(
            alpha_u8, rgb, max_alpha_keep=max(0, min(255, args.drop_top_max_alpha))
        )
    if args.keep_largest_cc:
        ok = max(0, args.open_kernel)
        alpha_u8 = _refine_alpha_largest_cc(alpha_u8, rgb, open_kernel=ok)
    alpha = Image.fromarray(alpha_u8, mode="L")

    rgba = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    rgba.paste(crop, (0, 0))
    rgba.putalpha(alpha)

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(out_path, "PNG")
    print(f"[BiRefNet] 已保存: {out_path}", flush=True)


if __name__ == "__main__":
    main()
