#!/usr/bin/env python3
"""
BiRefNet 抠图：用于商店专题长图顶部条带主体抠图。
依赖: torch, torchvision, transformers（可选，未安装时调用方需回退）。
"""

from __future__ import annotations

import os
from pathlib import Path

# BiRefNet-matting 为固定分辨率，使用 1024×1024 推理后再缩放回原图尺寸
BIREFNET_INFER_SIZE = 1024
# 顶部条带 matting 使用的源区高度（像素），比条带高一些以利抠图、主体更干净
STRIP_SOURCE_HEIGHT = 120

_model_cache = None


def _get_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def load_birefnet_matting(device: str | None = None):
    """加载 BiRefNet-matting，返回 model。首次会从 HuggingFace 下载。"""
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    # 分别导入，避免把 transformers 内部依赖（如 regex）错误误报成「未装 torch」
    try:
        import torch
    except ImportError as e:
        raise RuntimeError(
            "BiRefNet 需要 PyTorch。任选其一：\n"
            "  1) 项目根: pip install -e \".[birefnet]\"\n"
            "  2) Windows CPU: scripts/install_birefnet_deps.bat\n"
            "  3) pip install torch torchvision"
        ) from e
    try:
        from transformers import AutoModelForImageSegmentation
    except ImportError as e:
        raise RuntimeError(
            "BiRefNet 需要 transformers。请执行: pip install \"transformers>=4.38\" huggingface_hub\n"
            "若仍报错，可尝试: pip install --force-reinstall regex"
        ) from e
    dev = device or _get_device()
    try:
        model = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet-matting",
            trust_remote_code=True,
        )
    except Exception as e:
        raise RuntimeError(
            "BiRefNet 从 HuggingFace 加载失败（需联网首次下载 ZhengPeng7/BiRefNet-matting）。"
            f" 详情: {e}"
        ) from e
    model.to(dev)
    model.eval()
    if dev == "cuda":
        model.half()
    _model_cache = model
    return model


def extract_alpha_pil(
    image_pil,
    model=None,
    device: str | None = None,
    infer_size: int = BIREFNET_INFER_SIZE,
):
    """
    对整图做 BiRefNet 推理，得到与 image_pil 同尺寸的 alpha（PIL 单通道 L）。
    使用固定 1024×1024 推理后缩放回原图，以兼容 BiRefNet-matting 固定分辨率。
    """
    try:
        import torch
        from torchvision import transforms
    except ImportError as e:
        raise RuntimeError("需要 torch、torchvision") from e
    from PIL import Image

    if model is None:
        model = load_birefnet_matting(device)
    dev = device or _get_device()
    w, h = image_pil.size
    rw = rh = infer_size
    infer_img = image_pil.resize((rw, rh), Image.Resampling.LANCZOS)

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    x = transform(infer_img.convert("RGB")).unsqueeze(0)
    x = x.to(dev)
    if dev == "cuda":
        x = x.half()

    with torch.no_grad():
        out = model(x)
        if isinstance(out, (list, tuple)):
            pred = out[-1].sigmoid().cpu().float().numpy()
        else:
            pred = out.sigmoid().cpu().float().numpy()
    pred = pred[0, 0]
    if pred.ndim == 3:
        pred = pred[0]
    pred = (pred * 255).clip(0, 255).astype("uint8")
    alpha_pil = Image.fromarray(pred, mode="L")
    if (rw, rh) != (w, h):
        alpha_pil = alpha_pil.resize((w, h), Image.Resampling.LANCZOS)
    return alpha_pil


def _extract_alpha_region_padded(region_pil, model=None, device: str | None = None):
    """
    在【区域图】上跑 BiRefNet，先 pad 成方形再推理，避免长宽比失真（超宽条带被压成 1024×1024 会崩）。
    返回与 region 同尺寸的 alpha（PIL 'L'）。

    padding 用【边缘镜像延展】而非纯黑填充：纯黑色块几何规整、与真实内容对比度极高，
    BiRefNet 会把这块黑色 padding 本身误判成显著前景物体（已实测：100% 高置信度像素落在纯黑
    padding 区，真实内容区反而判成背景）。镜像延展的像素统计特征与原图连续，不会引入这种伪前景。
    """
    import numpy as np
    from PIL import Image
    w, h = region_pil.size
    side = max(w, h)
    if (w, h) != (side, side):
        arr = np.array(region_pil.convert("RGB"))
        pad_bottom = side - h
        pad_right = side - w
        # reflect 模式：镜像延展边缘内容，避免引入人工高对比度色块
        padded_arr = np.pad(
            arr, ((0, pad_bottom), (0, pad_right), (0, 0)), mode="reflect"
        )
        padded = Image.fromarray(padded_arr, mode="RGB")
        alpha_sq = extract_alpha_pil(padded, model=model, device=device)
        return alpha_sq.crop((0, 0, w, h))
    return extract_alpha_pil(region_pil, model=model, device=device)


def _filter_small_components(a_float, min_area: int):
    """
    a_float: HxW ∈ [0,1]。去掉面积 < min_area 的前景连通块（清理光斑/粒子等装饰碎屑）。
    需要 cv2；不可用时原样返回。
    """
    import numpy as np
    if not min_area or min_area <= 0:
        return a_float
    binm = (a_float > 0.05).astype(np.uint8)
    if binm.sum() == 0:
        return a_float
    try:
        import cv2
    except Exception:
        return a_float
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binm, connectivity=8)
    keep = np.zeros_like(a_float, dtype=np.float32)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[labels == i] = 1.0
    return a_float * keep


def composite_strip_with_matting(
    canvas_rgb,
    strip_x_min: int,
    strip_x_max: int,
    strip_y_min: int,
    strip_y_max: int,
    model=None,
    device: str | None = None,
    alpha_threshold: float = 0.5,
    keep_mask=None,
    min_component_area: int = 0,
    binarize: bool = True,
    context_h: int | None = None,
):
    """
    在 canvas 上取条带区域，用 BiRefNet 抠图得到 RGBA 块，返回 (strip_rgba_pil, alpha_pil_crop)。

    - 在【裁切区域】而非整张画布上跑 BiRefNet（pad 成方形），避免超宽画布被压成 1024×1024 导致失真、抠不出前景。
    - context_h：用更高的上下文源区做推理（利于识别前景），仅贴回最上 strip_h 像素。
    - keep_mask：可选 PIL 'L'（区域尺寸），框内=保留、框外=剔除（语义前景约束，用于剔除环境/装饰）。
    - binarize=True：alpha≥threshold 置 1、否则 0；False：低于 threshold 归零、其余保留柔和边缘。
    - min_component_area：去掉面积过小的前景连通块（清理光斑/粒子装饰碎屑）。
    """
    from PIL import Image
    import numpy as np
    w, h = canvas_rgb.size
    strip_w = strip_x_max - strip_x_min
    strip_h = strip_y_max - strip_y_min
    if strip_w <= 0 or strip_h <= 0:
        return None, None
    want_h = context_h if (context_h and context_h > 0) else STRIP_SOURCE_HEIGHT
    source_h = max(strip_h, min(want_h, h - strip_y_min))
    source_y_max = strip_y_min + source_h
    crop = canvas_rgb.crop((strip_x_min, strip_y_min, strip_x_max, source_y_max))

    alpha_region = _extract_alpha_region_padded(crop, model=model, device=device)
    a = np.array(alpha_region, dtype=np.float32) / 255.0
    if binarize:
        a = (a >= alpha_threshold).astype(np.float32)
    else:
        a = np.clip((a - alpha_threshold) / max(1e-6, 1.0 - alpha_threshold), 0.0, 1.0)

    if keep_mask is not None:
        km = keep_mask if keep_mask.size == crop.size else keep_mask.resize(crop.size, Image.Resampling.LANCZOS)
        kmn = np.array(km.convert("L"), dtype=np.float32) / 255.0
        a = a * kmn

    a = _filter_small_components(a, min_component_area)

    alpha_region = Image.fromarray((a * 255.0).clip(0, 255).astype(np.uint8), mode="L")
    strip_rgba = Image.new("RGBA", (strip_w, strip_h), (255, 255, 255, 0))
    src_rgb = crop.crop((0, 0, strip_w, strip_h))
    src_alpha = alpha_region.crop((0, 0, strip_w, strip_h))
    strip_rgba.paste(src_rgb, (0, 0))
    strip_rgba.putalpha(src_alpha)
    return strip_rgba, alpha_region
