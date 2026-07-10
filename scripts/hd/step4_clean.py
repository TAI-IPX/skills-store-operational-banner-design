#!/usr/bin/env python3
"""
HD 生产线 Step 4：去干扰
4a: Gemini inpaint 去除生成背景图中的文字/水印
4b: 人物抠图边缘精修（形态学腐蚀去毛边）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE_EDIT_SCRIPTS = (
    ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
)
if str(IMAGE_EDIT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(IMAGE_EDIT_SCRIPTS))

REMOVE_TEXT_PROMPT = (
    "Remove all overlaid text, watermarks, logos, UI elements, badges, and promotional copy from this image. "
    "Fill removed areas naturally using the surrounding background content. "
    "Do not change any part of the image that was not covered by text or overlays. "
    "Output the same size as input."
)


def clean_background(bg_path: Path, out_path: Path) -> Path:
    """4a: 用 Gemini inpaint 去除背景图中的文字/水印。"""
    try:
        from gemini_image_edit import edit_image

        print("[step4a] Gemini 去文字/水印...", flush=True)
        result = edit_image(str(bg_path), str(out_path), REMOVE_TEXT_PROMPT)
        if result and Path(result).is_file():
            print(f"[step4a] 完成: {out_path.name}", flush=True)
            return Path(result)
    except Exception as e:
        print(f"[step4a] 去文字失败（跳过）: {e}", flush=True)
    # 失败时直接复制原图
    import shutil

    shutil.copy2(bg_path, out_path)
    return out_path


def refine_character_edge(
    char_path: Path,
    out_path: Path,
    erode_px: int = 2,
    feather_px: int = 3,
) -> Path:
    """
    4b: 人物抠图边缘精修。
    erode_px: 腐蚀像素数（去毛边）
    feather_px: 羽化半径（柔化边缘）
    """
    from PIL import Image, ImageFilter
    import numpy as np

    img = Image.open(char_path).convert("RGBA")
    r, g, b, a = img.split()
    a_arr = np.array(a, dtype=np.uint8)

    # 形态学腐蚀：去除边缘毛刺
    if erode_px > 0:
        from PIL import ImageFilter as IF

        a_img = Image.fromarray(a_arr, mode="L")
        for _ in range(erode_px):
            a_img = a_img.filter(IF.MinFilter(3))
        a_arr = np.array(a_img, dtype=np.uint8)

    # 羽化：高斯模糊 alpha 通道边缘
    if feather_px > 0:
        a_img = Image.fromarray(a_arr, mode="L")
        a_blurred = a_img.filter(ImageFilter.GaussianBlur(radius=feather_px))
        # 只在边缘区域应用羽化（保留内部实心区域）
        a_orig = np.array(a_img, dtype=np.float32)
        a_blur = np.array(a_blurred, dtype=np.float32)
        # 内部（alpha>200）保持原值，边缘区域用模糊值
        mask = a_orig > 200
        a_final = np.where(mask, a_orig, a_blur).astype(np.uint8)
        a_arr = a_final

    result = Image.merge("RGBA", (r, g, b, Image.fromarray(a_arr, mode="L")))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(out_path))
    print(f"[step4b] 边缘精修完成: {out_path.name}", flush=True)
    return out_path


def run_step4(
    bg_path: Path,
    char_paths: dict[str, Path],
    out_dir: Path,
) -> tuple[Path, dict[str, Path]]:
    """
    去干扰全流程。
    返回 (cleaned_bg_path, refined_char_paths)
    """
    # 4a: 背景去文字
    cleaned_bg = out_dir / "bg_cleaned.png"
    clean_background(bg_path, cleaned_bg)

    # 4b: 人物边缘精修
    refined: dict[str, Path] = {}
    for key, path in char_paths.items():
        if key.startswith("char_") and path.is_file():
            out = out_dir / f"{key}_refined.png"
            refine_character_edge(path, out)
            refined[key] = out
        else:
            refined[key] = path  # logo/title_art 不做边缘精修

    return cleaned_bg, refined
