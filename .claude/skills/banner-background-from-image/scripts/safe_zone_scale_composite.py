#!/usr/bin/env python3
"""
步骤 4：把上传图片缩放使主体 bbox 大小约为画布安全区的 85%，主体物 bbox 中心点和安全区中心点对齐；
多余部分不剪裁，直接保留在画布上，可超出画布安全区。空白区域不做任何填充（保持黑色），便于步骤 5 识别并填充。
"""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

from crop_to_target import get_safe_zone
from gemini_subject_detect import detect_subject_bbox


def scale_and_composite_to_canvas(
    image_path: str,
    output_path: str,
    width: int = 1976,
    height: int = 464,
    *,
    subject_bbox: tuple[float, float, float, float] | None = None,
    safe_zone_ratio: float = 0.85,
    context_prompt: str | None = None,
) -> Path:
    """
    主体 bbox 约为安全区 85%，等比缩放整图；主体 bbox 中心与安全区中心对齐；
    多余部分不剪裁，整图保留在画布上可超出安全区。空白区域不填充，保持黑色，供步骤 5 识别并填充。
    """
    safe = get_safe_zone(width, height)
    if safe is None:
        raise ValueError(f"画布 {width}×{height} 未配置安全区")
    x_min_safe, x_max_safe, y_min_safe, y_max_safe = safe
    safe_w = x_max_safe - x_min_safe
    safe_h = y_max_safe - y_min_safe
    safe_center_x = (x_min_safe + x_max_safe) / 2
    safe_center_y = (y_min_safe + y_max_safe) / 2

    bbox = subject_bbox if subject_bbox is not None else detect_subject_bbox(image_path, context_prompt=context_prompt)
    if bbox is None:
        raise RuntimeError("主体 bbox 检测失败，需 GEMINI_API_KEY 且 Gemini 可用")

    img = Image.open(image_path).convert("RGB")
    w0, h0 = img.size
    x_min, y_min, x_max, y_max = bbox
    # 若解析后横向宽于纵向，可能是模型返回了 (y_min, x_min, y_max, x_max)，交换 x 与 y
    if (x_max - x_min) > (y_max - y_min):
        x_min, y_min, x_max, y_max = y_min, x_min, y_max, x_max
        print("bbox 已按 y,x 顺序校正", flush=True)
    bw = (x_max - x_min) * w0
    bh = (y_max - y_min) * h0
    if bw < 1 or bh < 1:
        raise ValueError("主体 bbox 过小")
    target_w = safe_w * safe_zone_ratio
    target_h = safe_h * safe_zone_ratio
    scale = min(target_w / bw, target_h / bh)
    w1 = int(round(w0 * scale))
    h1 = int(round(h0 * scale))
    w1, h1 = max(1, w1), max(1, h1)
    img_scaled = img.resize((w1, h1), Image.Resampling.LANCZOS)

    cx_ratio = (x_min + x_max) / 2
    cy_ratio = (y_min + y_max) / 2
    cx = cx_ratio * w1
    cy = cy_ratio * h1
    x0 = int(round(safe_center_x - cx))
    y0 = int(round(safe_center_y - cy))
    # 调试：检查 bbox 中心与安全区中心对齐
    print(
        f"bbox={bbox} cx_ratio={cx_ratio:.4f} cy_ratio={cy_ratio:.4f} "
        f"w0={w0} h0={h0} w1={w1} h1={h1} cx={cx:.1f} cy={cy:.1f} "
        f"safe_center=({safe_center_x:.1f},{safe_center_y:.1f}) x0={x0} y0={y0}",
        flush=True,
    )

    # 专有填充色 (1,0,254)（近纯蓝偏紫，自然图片中极罕见），便于与画面内容精确区分、检测未填充
    canvas = Image.new("RGB", (width, height), (1, 0, 254))
    src_left = max(0, -x0)
    src_top = max(0, -y0)
    src_right = min(w1, width - x0)
    src_bottom = min(h1, height - y0)
    dest_left = max(0, x0)
    dest_top = max(0, y0)
    if src_right > src_left and src_bottom > src_top:
        patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
        canvas.paste(patch, (dest_left, dest_top))
    # 空白区域为专有色 (0,0,1)，便于步骤 5/7 识别并填充

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.suffix or out.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        out = out.with_suffix(".png")
    canvas.save(str(out), "PNG")
    return out


# A4 用：画布 2048×512（严格 4:1），主体 bbox 中心在画面水平 2/3 处，空白 (0,0,1) 供 Gemini 填充
FILL_CANVAS_W, FILL_CANVAS_H = 2048, 512


def composite_to_canvas_center(
    image_path: str,
    output_path: str,
    canvas_w: int = FILL_CANVAS_W,
    canvas_h: int = FILL_CANVAS_H,
    *,
    subject_bbox: tuple[float, float, float, float],
    subject_ratio: float = 0.75,
    center_x_ratio: float = 2 / 3,
    center_y_ratio: float = 0.5,
    fit_width_only: bool = False,
) -> Path:
    """
    将图片按 subject_bbox 贴到画布 (canvas_w, canvas_h)。
    主体 bbox 缩放后约占画布 subject_ratio；bbox 中心对齐到画布 (canvas_w*center_x_ratio, canvas_h*center_y_ratio)。
    默认 center_x_ratio=2/3 即 bbox 中心在画面水平 2/3 处（三分法）。空白为 (0,0,1)。
    """
    img = Image.open(image_path).convert("RGB")
    w0, h0 = img.size
    x_min, y_min, x_max, y_max = subject_bbox
    if (x_max - x_min) > (y_max - y_min):
        x_min, y_min, x_max, y_max = y_min, x_min, y_max, x_max
    bw = (x_max - x_min) * w0
    bh = (y_max - y_min) * h0
    if bw < 1 or bh < 1:
        raise ValueError("主体 bbox 过小")
    center_x = (x_min + x_max) / 2
    center_y = (y_min + y_max) / 2
    target_bw = canvas_w * subject_ratio
    target_bh = canvas_h * subject_ratio
    if fit_width_only:
        scale = target_bw / bw
    else:
        scale = min(target_bw / bw, target_bh / bh)
    w1 = max(1, int(round(w0 * scale)))
    h1 = max(1, int(round(h0 * scale)))
    img_scaled = img.resize((w1, h1), Image.Resampling.LANCZOS)
    cx = center_x * w1
    cy = center_y * h1
    # bbox 中心落在画布 (center_x_ratio, center_y_ratio) 处，默认水平 2/3、纵向居中
    canvas_target_x = canvas_w * center_x_ratio
    canvas_target_y = canvas_h * center_y_ratio
    x0 = int(round(canvas_target_x - cx))
    y0 = int(round(canvas_target_y - cy))
    canvas = Image.new("RGB", (canvas_w, canvas_h), (1, 0, 254))
    src_left = max(0, -x0)
    src_top = max(0, -y0)
    src_right = min(w1, canvas_w - x0)
    src_bottom = min(h1, canvas_h - y0)
    dest_left = max(0, x0)
    dest_top = max(0, y0)
    if src_right > src_left and src_bottom > src_top:
        patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
        canvas.paste(patch, (dest_left, dest_top))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out), "PNG")
    return out
