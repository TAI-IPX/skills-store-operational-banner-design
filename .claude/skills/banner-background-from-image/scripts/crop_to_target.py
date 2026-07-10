#!/usr/bin/env python3
"""
Crop (and optionally scale) a source image to target W×H for use as a banner background.
Respects shared safe zone from banner-spec. See banner-spec references/spec.md.
"""

import argparse
import sys
from pathlib import Path

# 从 banner-spec 读取规范（PRESETS、安全区、图例区）
_script_dir = Path(__file__).resolve().parent
_spec_scripts = _script_dir.parent.parent / "banner-spec" / "scripts"
if _spec_scripts.is_dir():
    sys.path.insert(0, str(_spec_scripts))
import spec as _spec
PRESETS = _spec.PRESETS
get_safe_zone = _spec.get_safe_zone
get_safe_zone_center = _spec.get_safe_zone_center
get_legend_zone = _spec.get_legend_zone

try:
    from PIL import Image
except ImportError:
    print("Requires Pillow. Install: pip install Pillow", file=sys.stderr)
    sys.exit(1)

DEFAULT_OUTPUT_DIR = "output"
SUPPORTED_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}

# 主体在安全区内的纵向目标比例：0.7 表示主体中心放在安全区内自上而下 70% 处
SAFE_ZONE_TARGET_RATIO = 0.7


def crop_to_target(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    subject_center_y_ratio: float | None = None,
    subject_center_x_ratio: float | None = None,
    align_image_center_to_safe_zone: bool = False,
    preset: str | None = None,
) -> Path:
    """
    Crop (and scale) source image to exactly width×height.
    When align_image_center_to_safe_zone: place image geometric center at safe zone center.
    Otherwise: require subject_center_x/y (from Gemini) and safe zone; place subject at safe zone center. No center-crop fallback.
    Returns path to saved file.
    """
    img = Image.open(image_path).convert("RGB")
    w0, h0 = img.size
    scale = max(width / w0, height / h0)
    w1 = max(width, int(round(w0 * scale)))
    h1 = max(height, int(round(h0 * scale)))
    img_scaled = img.resize((w1, h1), Image.Resampling.LANCZOS)

    # Crop window (W×H) position
    safe = get_safe_zone(width, height, preset)
    if align_image_center_to_safe_zone:
        # 上传画面中心 = 画布安全区中心（无安全区时用画布中心）
        center = get_safe_zone_center(width, height, preset)
        if center is not None:
            x_target, y_target = center
        else:
            x_target, y_target = width / 2, height / 2
        # 缩放图上图片中心为 (w1/2, h1/2)，要落在输出 (x_target, y_target) => x0 = w1/2 - x_target
        x0_candidate = w1 / 2 - x_target
        y0_candidate = h1 / 2 - y_target
        x0 = max(0, min(w1 - width, int(round(x0_candidate))))
        y0 = max(0, min(h1 - height, int(round(y0_candidate))))
    else:
        # 强制主体 + 安全区：禁止居中裁切回退
        if subject_center_y_ratio is None or subject_center_x_ratio is None:
            print("Error: 按主体落安全区裁切必须提供主体位置（Gemini 主体检测）。未提供 subject_center_x/y 时禁止使用居中裁切。", file=sys.stderr)
            sys.exit(1)
        if safe is None:
            print(f"Error: 画布 {width}×{height} 未配置安全区，无法按主体落安全区裁切。", file=sys.stderr)
            sys.exit(1)
        x_min, x_max, y_min, y_max = safe
        # 主体中心落在安全区：横向安全区中心，纵向 70%
        x_target = (x_min + x_max) / 2
        y_target = y_min + SAFE_ZONE_TARGET_RATIO * (y_max - y_min)
        y_sub_scaled = h1 * subject_center_y_ratio
        x_sub_scaled = w1 * subject_center_x_ratio
        x0_candidate = x_sub_scaled - x_target
        y0_candidate = y_sub_scaled - y_target
        x0 = max(0, min(w1 - width, int(round(x0_candidate))))
        y0 = max(0, min(h1 - height, int(round(y0_candidate))))

    cropped = img_scaled.crop((x0, y0, x0 + width, y0 + height))
    if cropped.size != (width, height):
        cropped = cropped.resize((width, height), Image.Resampling.LANCZOS)

    out_path = Path(output_path)
    if not out_path.suffix or out_path.suffix.lower().lstrip(".") not in SUPPORTED_FORMATS:
        out_path = out_path.with_suffix(".png")
    if not out_path.parent or out_path.parent == Path("."):
        out_path = Path(DEFAULT_OUTPUT_DIR) / out_path.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ext = out_path.suffix.lower().lstrip(".")
    save_kw = {"quality": 90} if ext in ("jpg", "jpeg") else {}
    cropped.save(str(out_path), SUPPORTED_FORMATS.get(ext, "PNG"), **save_kw)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crop image to target W×H for banner background (shared safe zone). Output default: output/."
    )
    parser.add_argument("input", help="Source image path")
    parser.add_argument("output", help="Output path or filename (default dir: output/; .png or .jpg)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS), default="default")
    group.add_argument("--width", "-W", type=int, help="Target width (use with --height)")
    parser.add_argument("--height", "-H", type=int, help="Target height")
    parser.add_argument(
        "--subject-y",
        type=float,
        metavar="RATIO",
        help="Subject center Y in source image as ratio 0..1 (optional)",
    )
    parser.add_argument(
        "--subject-x",
        type=float,
        metavar="RATIO",
        help="Subject center X in source image as ratio 0..1 (optional; with Y keeps subject in frame)",
    )
    parser.add_argument(
        "--align-image-center",
        action="store_true",
        help="Place image geometric center at safe zone center (ignores subject position)",
    )
    args = parser.parse_args()

    if args.width is not None and args.height is not None:
        width, height = args.width, args.height
    else:
        width, height = PRESETS[args.preset]

    preset = args.preset if args.width is None or args.height is None else None
    out = crop_to_target(
        args.input,
        args.output,
        width,
        height,
        subject_center_y_ratio=args.subject_y,
        subject_center_x_ratio=getattr(args, "subject_x", None),
        align_image_center_to_safe_zone=getattr(args, "align_image_center", False),
        preset=preset,
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
