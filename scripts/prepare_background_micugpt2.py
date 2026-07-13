#!/usr/bin/env python3
"""
micugpt2 专用背景处理脚本。
与原 prepare_background.py 功能对等，但所有图编步骤（A1/A4/A6/S5/S6）全部走 micugpt2。
不修改任何现有文件，完全独立。

用法示例：
  py scripts/prepare_background_micugpt2.py input.png output.png --preset default --safe-zone-scale-outpaint
  py scripts/prepare_background_micugpt2.py --wide-from-fill tianchong.png output.png --bbox-file bbox.txt
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

_skill_scripts = str(Path(_script_dir).parent / ".claude" / "skills" / "banner-background-from-image" / "scripts")
if _skill_scripts not in sys.path:
    sys.path.insert(0, _skill_scripts)

from crop_to_target import PRESETS, get_safe_zone, get_safe_zone_center, crop_to_target

DEFAULT_OUTPUT_DIR = "output"

os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
BANNER_IMAGE_BACKEND = "micugpt2"


# ══════════════════════════════════════════════════════════════════════════════
# micugpt2 专用 Prompt 常量（可独立修改，无需动原文件）
# ══════════════════════════════════════════════════════════════════════════════

MICUGPT2_A1_REMOVE_TEXT_PROMPT = (
    "Remove every overlay on this image: text, logos, UI buttons, date labels, "
    "badges, color blocks, blur panels. Erase their shadows and halos too. "
    "Where an overlay covered the background, extend the same sky, wall, or "
    "environment seamlessly into that spot. Where an overlay covered skin or "
    "clothing, restore the body and fabric as if the overlay was never there. "
    "Fix any dark smudges or uneven shadows on the character's body. The "
    "result should look like a clean photograph with no graphics ever placed "
    "on it. Keep everything else pixel-perfect: colors, lighting, pose, "
    "composition stay the same. No new elements, no visible repair marks."
)

MICUGPT2_A4_FILL_PROMPT = (
    "This image has blank placeholder regions around a central subject. "
    "Fill the entire canvas to exactly 2048 by 512 pixels. "
    "The center subject must stay untouched. Extend the surrounding "
    "environment outward: more sky, more ground, more room, more of the "
    "same world. The result should look like a single wide-angle photo. "
    "Same art style, same lighting direction, same color warmth. Same "
    "camera angle and depth — the extension feels like panning the camera "
    "slightly, not zooming out or changing viewpoint. No visible seam or "
    "hard edge between original and extended zones. Each side feels equally "
    "detailed and busy, not one side empty and the other cluttered. Do not "
    "mirror, tile, or copy-paste any background element — each extended area "
    "is a unique natural continuation. Do not add people, characters, or text. "
    "One seamless image with no black bars, no empty edges."
)

MICUGPT2_A6_FILL_PROMPT = (
    "This image has unfilled near-black placeholder regions at the edges. "
    "Extend the adjacent background into those areas until the entire "
    "image is fully filled and looks like one continuous scene. "
    "The existing content stays unchanged. Fill only the empty areas. "
    "Match the lighting, color tone, and atmosphere of the surrounding "
    "scene exactly. The filled edges should blend invisibly — no dark "
    "borders, no visible patchwork. "
    "Do not add people, characters, or text. Do not copy the subject."
)

MICUGPT2_A6B_REPAIR_PROMPT = (
    "This wide banner image has visible seams, abrupt cut lines, or "
    "repeated background chunks that break the illusion of one scene. "
    "Blend everything into a single continuous environment. "
    "Extend and smooth the areas where different patches meet. Make "
    "transitions invisible. The final image should look like it was "
    "photographed or rendered as one wide shot — not assembled from "
    "separate pieces. "
    "Preserve the main subjects exactly as they are. Do not add people, "
    "characters, or text. Same pixel dimensions as the input."
)



# ══════════════════════════════════════════════════════════════════════════════
# wide (3320×500) 入口
# ══════════════════════════════════════════════════════════════════════════════

def _wide_a5b_alpha_threshold() -> float:
    """3320×500 A5b BiRefNet 条带 alpha 阈值，默认 0.5（更保守的二值化，减少边缘杂色）；可用 WIDE_A5B_ALPHA_THRESHOLD 覆盖。"""
    raw = os.environ.get("WIDE_A5B_ALPHA_THRESHOLD", "").strip()
    if not raw:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.5


def _wide_a5b_context_h() -> int:
    raw = os.environ.get("WIDE_A5B_CONTEXT_H", "").strip()
    if not raw:
        return 400
    try:
        return max(WIDE_STRIP_BIREFNET_Y_MAX, int(float(raw)))
    except ValueError:
        return 400


def _wide_a5b_min_component_area() -> int:
    """A5b 去装饰碎屑的连通域最小面积（像素），默认 3000；设 0 关闭过滤。"""
    raw = os.environ.get("WIDE_A5B_MIN_COMPONENT_AREA", "").strip()
    if not raw:
        return 3000
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 3000


def _wide_a5b_semantic_enabled() -> bool:
    v = os.environ.get("WIDE_A5B_SEMANTIC", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _wide_a5b_binarize() -> bool:
    v = os.environ.get("WIDE_A5B_NO_BINARIZE", "").strip().lower()
    return v not in ("1", "true", "yes", "on")


def _wide_a5b_no_gemini_fallback() -> bool:
    v = os.environ.get("WIDE_A5B_NO_GEMINI_FALLBACK", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _build_wide_a5b_keep_mask(img, x0: int, x1: int, y0: int, y1: int, context_prompt: str | None):
    from PIL import Image, ImageDraw
    import tempfile
    region = img.crop((x0, y0, x1, y1))
    rw, rh = region.size
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    boxes = None
    try:
        region.save(tmp, "PNG")
        from gemini_subject_detect import detect_foreground_objects_bboxes
        boxes = detect_foreground_objects_bboxes(tmp, context_prompt=context_prompt)
    except Exception as e:
        print(f"  A5b 语义前景检测异常（{e}），回退纯 BiRefNet", flush=True)
        boxes = None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    if boxes is None:
        print("  A5b 语义前景检测失败/无返回，回退纯 BiRefNet", flush=True)
        return None
    if not boxes:
        print("  A5b 语义前景检测：未发现前景物体，回退纯 BiRefNet 判定", flush=True)
        return None
    mask = Image.new("L", (rw, rh), 0)
    d = ImageDraw.Draw(mask)
    pad_x = max(2, int(rw * 0.01))
    pad_y = max(2, int(rh * 0.02))
    for (bx0, by0, bx1, by1) in boxes:
        px0 = max(0, int(bx0 * rw) - pad_x)
        py0 = max(0, int(by0 * rh) - pad_y)
        px1 = min(rw, int(bx1 * rw) + pad_x)
        py1 = min(rh, int(by1 * rh) + pad_y)
        if px1 > px0 and py1 > py0:
            d.rectangle((px0, py0, px1, py1), fill=255)
    print(f"  A5b 语义前景检测：{len(boxes)} 个前景框 → keep-mask", flush=True)
    return mask


def _composite_wide_top_strip_birefnet(canvas_path: str) -> None:
    """
    仅用于 3320×500（A5b）：
    1. 在裁切上下文区（x=1032-2464、y=0-context_h）上跑 BiRefNet 抠前景（pad 方形防失真）；
       WIDE_A5B_SEMANTIC=1 时叠 Gemini 前景物体 keep-mask（剔除环境/装饰），并去连通域碎屑；
    2. 铺整条 x=0-3320、y=0-40 #FFFFFF（规范顶部白条）；
    3. 将前景 RGBA 原位贴回；
    失败时回退到 Gemini 顶部条带伸入逻辑（仅 y=0-40）。
    """
    from PIL import Image, ImageDraw
    img = Image.open(canvas_path).convert("RGB")
    w, h = img.size
    if w != WIDE_CANVAS_SIZE[0] or h != WIDE_CANVAS_SIZE[1]:
        return
    strip_h = WIDE_TOP_STRIP_H
    x0 = WIDE_STRIP_BIREFNET_X_MIN
    x1 = WIDE_STRIP_BIREFNET_X_MAX
    mat_y_min = WIDE_STRIP_BIREFNET_Y_MIN
    mat_y_max = WIDE_STRIP_BIREFNET_Y_MAX
    context_h = min(_wide_a5b_context_h(), h - mat_y_min)
    ctx_prompt = None
    try:
        _pt = Path(canvas_path).parent / "prompt.txt"
        if _pt.is_file():
            ctx_prompt = _pt.read_text(encoding="utf-8").strip() or None
    except Exception:
        ctx_prompt = None
    try:
        from birefnet_matting import (
            load_birefnet_matting,
            composite_strip_with_matting,
        )
        model = load_birefnet_matting()

        keep_mask = None
        if _wide_a5b_semantic_enabled():
            keep_mask = _build_wide_a5b_keep_mask(
                img, x0, x1, mat_y_min, mat_y_min + context_h, ctx_prompt
            )

        strip_rgba, _ = composite_strip_with_matting(
            img,
            x0,
            x1,
            mat_y_min,
            mat_y_max,
            model=model,
            alpha_threshold=_wide_a5b_alpha_threshold(),
            keep_mask=keep_mask,
            min_component_area=_wide_a5b_min_component_area(),
            binarize=_wide_a5b_binarize(),
            context_h=context_h,
        )
        _mode = "BiRefNet+Gemini语义" if keep_mask is not None else "BiRefNet"

        # BiRefNet 在全景超宽图上常把上半主体漏判（strip 带内 alpha 近空），
        # 过少则用背景差异法兜底重建 strip alpha（与 prepare_background.py 同步）。
        if strip_rgba is not None:
            import numpy as _np
            _alpha_band = _np.asarray(strip_rgba)[:strip_h, :, 3]
            _opaque_cols = int((_alpha_band > 40).any(axis=0).sum())
            _band_w = strip_rgba.size[0]
            if _opaque_cols < max(20, int(_band_w * 0.02)):
                _fb = _content_strip_rgba(img, x0, x1, mat_y_min, strip_h, context_h)
                if _fb is not None:
                    strip_rgba = _fb
                    _mode += "+背景差异兜底"
                    print(
                        f"  A5b: BiRefNet strip 带 alpha 近空（不透明列 {_opaque_cols}），改用背景差异兜底",
                        flush=True,
                    )

        if strip_rgba is not None:
            # 白条精确 strip_h 像素（paste 半开区间，避免 rectangle 端点闭区间多铺 1px 接缝）
            img.paste((255, 255, 255), (0, 0, w, strip_h))
            img.paste(strip_rgba, (x0, mat_y_min), strip_rgba)
            img.save(canvas_path, "PNG")
            print(
                f"Step 5b / 3320×500 {_mode}: 全条 y=0-{strip_h} 铺白, 抠图区 x={x0}-{x1} context_h={context_h} 前景贴回 → {canvas_path}",
                flush=True,
            )
            return
    except Exception as e:
        if _wide_a5b_no_gemini_fallback():
            print(
                f"Step 5b BiRefNet 抠图失败，且 WIDE_A5B_NO_GEMINI_FALLBACK 已开启，终止（不回退 Gemini）: {e}",
                flush=True,
            )
            raise
        print(f"Step 5b BiRefNet 抠图失败，跳过顶部条带处理: {e}", flush=True)
        return


def _wide_side_fill_api_enabled() -> bool:
    """wide 两侧空隙是否走 sentinel API 延展填充（默认开）；设 WIDE_SIDE_FILL_API=0 回退纯 edge-pad。"""
    v = os.environ.get("WIDE_SIDE_FILL_API", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _wide_auto_top_poke_enabled() -> bool:
    """A5b 前是否自动探测主体顶部并上移使其探入白条（默认开）；设 WIDE_AUTO_TOP_POKE=0 关闭。
    仅当用户未显式设置 WIDE_TOP_EXTEND_PX（手动模式优先）时生效。"""
    if os.environ.get("WIDE_TOP_EXTEND_PX", "").strip() not in ("", "0"):
        return False
    v = os.environ.get("WIDE_AUTO_TOP_POKE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _detect_content_top_row(canvas_rgb, x0: int, x1: int, scan_h: int) -> int | None:
    """
    背景差异法检测主体真实顶行（不依赖 BiRefNet）。与 prepare_background.py 同步。
    从抠图区两侧极窄边列估计背景色，找首个与背景差异显著的行。
    """
    import numpy as np
    try:
        w, h = canvas_rgb.size
        x0 = max(0, min(x0, w - 1))
        x1 = max(x0 + 1, min(x1, w))
        scan_h = max(1, min(scan_h, h))
        reg = np.asarray(canvas_rgb.convert("RGB"), dtype=np.int16)[:scan_h, x0:x1]
        rw = reg.shape[1]
        edge = max(8, int(rw * 0.04))
        side = np.concatenate(
            [reg[:, :edge].reshape(-1, 3), reg[:, -edge:].reshape(-1, 3)], axis=0
        )
        bg = np.median(side, axis=0)
        dist = np.abs(reg - bg).max(axis=2)
        thr = int(os.environ.get("WIDE_TOP_POKE_BG_DIST", "45").strip() or "45")
        fg = dist > thr
        mn = reg.min(axis=2)
        fg = fg & (mn <= 235)
        rows = fg.sum(axis=1)
        min_cols = max(15, int(rw * 0.01))
        nz = np.where(rows > min_cols)[0]
        if len(nz) == 0:
            return None
        return int(nz[0])
    except Exception:
        return None


def _content_strip_rgba(img, x0: int, x1: int, y_min: int, strip_h: int, context_h: int):
    """
    A5b 背景差异兜底：BiRefNet 漏判上半主体时用背景差异法重建顶部白条前景 RGBA。
    与 prepare_background.py 同步。返回 (x1-x0)×strip_h 的 RGBA（PIL），无前景返回 None。
    """
    import numpy as np
    from PIL import Image
    try:
        reg = np.asarray(img.convert("RGB"), dtype=np.int16)[y_min:y_min + context_h, x0:x1]
        band = reg[:strip_h]
        rw = band.shape[1]
        edge = max(8, int(rw * 0.04))
        side = np.concatenate(
            [reg[:, :edge].reshape(-1, 3), reg[:, -edge:].reshape(-1, 3)], axis=0
        )
        bg = np.median(side, axis=0)
        thr = int(os.environ.get("WIDE_TOP_POKE_BG_DIST", "45").strip() or "45")
        dist = np.abs(band - bg).max(axis=2)
        mn = band.min(axis=2)
        fg = (dist > thr) & (mn <= 235)
        if fg.sum() < 10:
            return None
        alpha = (fg.astype(np.uint8)) * 255
        rgba = Image.new("RGBA", (rw, strip_h), (255, 255, 255, 0))
        rgb_src = Image.fromarray(band.astype(np.uint8), "RGB")
        rgba.paste(rgb_src, (0, 0))
        rgba.putalpha(Image.fromarray(alpha, "L"))
        return rgba
    except Exception:
        return None


def _wide_auto_top_poke(canvas_path: str) -> None:
    """
    A5b 前置：检测主体真实顶行，若够不到白条则整图上移使其探入（底部 edge 补齐）。
    顶行优先用背景差异法（对全景超宽图稳健），失败回退 BiRefNet。
    与 prepare_background.py 同步。
    """
    from PIL import Image
    import numpy as np

    try:
        img = Image.open(canvas_path).convert("RGB")
        w, h = img.size
        if (w, h) != WIDE_CANVAS_SIZE:
            return
        x0, x1 = WIDE_STRIP_BIREFNET_X_MIN, WIDE_STRIP_BIREFNET_X_MAX
        context_h = min(_wide_a5b_context_h(), h)
        top_row = _detect_content_top_row(img, x0, x1, context_h)
        _detect_src = "背景差异"
        if top_row is None:
            from birefnet_matting import load_birefnet_matting, _extract_alpha_region_padded
            model = load_birefnet_matting()
            crop = img.crop((x0, 0, x1, context_h))
            a = np.array(_extract_alpha_region_padded(crop, model=model), dtype=np.float32) / 255.0
            thr = _wide_a5b_alpha_threshold()
            rows = (a >= thr).sum(axis=1)
            nz = np.where(rows > 8)[0]
            if len(nz) == 0:
                print("  wide 自动探顶：抠图区未检出主体，跳过上移", flush=True)
                return
            top_row = int(nz[0])
            _detect_src = "BiRefNet"
        target = int(os.environ.get("WIDE_TOP_POKE_TARGET", "12").strip() or "12")
        if top_row <= target:
            print(f"  wide 自动探顶：主体顶行 y={top_row} 已探入白条，无需上移", flush=True)
            return
        shift = min(top_row - target, 120)
        arr = np.array(img)
        arr_shifted = np.pad(arr[shift:, :, :], ((0, shift), (0, 0), (0, 0)), mode="edge")
        Image.fromarray(arr_shifted).save(canvas_path, "PNG")
        print(f"  wide 自动探顶（{_detect_src}）：主体顶行 y={top_row} → 上移 {shift}px 使其探入白条（target≈{target}）", flush=True)
    except Exception as e:
        print(f"  wide 自动探顶失败（跳过）：{e}", file=sys.stderr, flush=True)


def _wide_fill_sides_via_api_micugpt2(img_scaled, paste_x: int, paste_y: int, target_w: int, target_h: int):
    """
    wide 两侧空隙用 sentinel API 延展填充（micugpt2 gpt-image-2），替代 edge-pad 拉伸。
    micugpt2 chat/completions 不支持像素级 mask，靠 sentinel 提示词延展；
    尺寸兜底 cover-scale + center-crop；sentinel 残留超阈值或异常时返回 None（回退 edge-pad）。
    成功返回 PIL.Image（target_w×target_h），失败返回 None。
    """
    from PIL import Image
    import numpy as np

    canvas = Image.new("RGB", (target_w, target_h), (1, 0, 254))
    sw, sh = img_scaled.size
    src_left = max(0, -paste_x)
    src_top = max(0, -paste_y)
    src_right = min(sw, target_w - paste_x)
    src_bottom = min(sh, target_h - paste_y)
    if src_right <= src_left or src_bottom <= src_top:
        return None
    patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
    canvas.paste(patch, (max(0, paste_x), max(0, paste_y)))

    fd, temp_canvas = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    fd2, temp_out = tempfile.mkstemp(suffix=".png")
    os.close(fd2)
    try:
        canvas.save(temp_canvas, "PNG")
        print("  wide_from_fill_micugpt2: 两侧 sentinel API 延展填充...", flush=True)
        _micugpt2_edit_image(temp_canvas, temp_out, MICUGPT2_A6_FILL_PROMPT, keep_returned_size=True)
        if not os.path.isfile(temp_out):
            return None
        out_img = Image.open(temp_out).convert("RGB")
        if out_img.size != (target_w, target_h):
            ow, oh = out_img.size
            scale = max(target_w / ow, target_h / oh)
            rw, rh = int(round(ow * scale)), int(round(oh * scale))
            out_img = out_img.resize((rw, rh), Image.Resampling.LANCZOS)
            cx0 = (rw - target_w) // 2
            cy0 = (rh - target_h) // 2
            out_img = out_img.crop((cx0, cy0, cx0 + target_w, cy0 + target_h))
            print(f"  wide_from_fill_micugpt2: API 返回 {ow}×{oh} → cover-crop 到 {target_w}×{target_h}", flush=True)
        arr = np.array(out_img)
        sentinel = (arr[:, :, 0] == 1) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 254)
        pct = float(sentinel.sum()) / float(arr.shape[0] * arr.shape[1])
        if pct > 0.02:
            print(f"  wide_from_fill_micugpt2: API 填充后 sentinel 残留 {pct*100:.1f}% > 2%，判定失败 → 回退 edge-pad", flush=True)
            return None
        return out_img
    except Exception as e:
        print(f"  wide_from_fill_micugpt2: 两侧 API 填充失败（{e}）→ 回退 edge-pad", file=sys.stderr, flush=True)
        return None
    finally:
        for _p in (temp_canvas, temp_out):
            if _p and os.path.isfile(_p):
                try:
                    os.unlink(_p)
                except OSError:
                    pass


def _safe_print_m(msg: str) -> None:
    """Windows GBK 控制台安全 print（micugpt2 孪生文件专用）。"""
    try:
        print(msg, flush=True)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            print(msg.encode("gbk", errors="replace").decode("gbk"), flush=True)
        except Exception:
            pass


def wide_from_fill_micugpt2(fill_image_path: str, output_path: str, bbox_file: str | None = None) -> None:
    """
    纯像素级 fit-to-safe-zone + edge-pad → A5b（与 prepare_background.py:wide_from_fill 同步，已验证）。
    """
    import numpy as np
    from PIL import Image

    target_w, target_h = WIDE_CANVAS_SIZE
    safe_x0, safe_x1, safe_y0, safe_y1 = (1470, 2464, 0, 500)
    safe_cx = (safe_x0 + safe_x1) / 2  # 1967
    safe_cy = (safe_y0 + safe_y1) / 2  # 250

    img = Image.open(fill_image_path).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError(f"无效填充图尺寸: {iw}×{ih}")

    # ── 读 bbox ──
    bbox = None
    if bbox_file and Path(bbox_file).is_file():
        try:
            parts = Path(bbox_file).read_text(encoding="utf-8").strip().split(",")
            if len(parts) == 4:
                bbox = tuple(float(v) for v in parts)
        except Exception:
            pass
    if bbox is None:
        # 无 bbox 时回退 cover + 图心对齐
        bbox = (0.0, 0.0, 1.0, 1.0)
        print("  wide_from_fill_micugpt2: 无 bbox，回退 cover+图心对齐", flush=True)

    x_min, y_min, x_max, y_max = bbox
    # bbox 退化守卫：Vision 返回近全帧框时，用 BiRefNet 在源图上复核收紧（与 prepare_background.py 共享）   
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".claude" / "skills" / "banner-background-from-image" / "scripts"))
    from prepare_background import _wide_refine_bbox_if_suspicious
    bbox = _wide_refine_bbox_if_suspicious(fill_image_path, bbox)
    x_min, y_min, x_max, y_max = bbox

    # ── fit-to-safe-zone 缩放 ──
    fit_ratio = float(os.environ.get("WIDE_FIT_RATIO", "0.9").strip() or "0.9")
    bbox_w_norm = x_max - x_min
    bbox_h_norm = y_max - y_min
    safe_w = safe_x1 - safe_x0
    safe_h = safe_y1 - safe_y0
    cover_scale = max(target_w / iw, target_h / ih)

    degenerate_bbox = bbox_w_norm >= 0.9 and bbox_h_norm >= 0.9
    if degenerate_bbox:
        fit_scale = cover_scale
        anchor_x_norm, anchor_y_norm = 0.5, 0.5
        align_cx, align_cy = target_w / 2.0, target_h / 2.0
        _safe_print_m(f"  wide_from_fill_micugpt2: [!] degenerate bbox {bbox} -> fallback cover + image-center align")
    else:
        scale_h = safe_h * fit_ratio / max(1e-6, bbox_h_norm * ih)
        scale_w = safe_w * fit_ratio / max(1e-6, bbox_w_norm * iw)
        fit_scale = scale_h
        bbox_w_s = bbox_w_norm * iw * fit_scale
        if bbox_w_s > safe_w * fit_ratio:
            fit_scale = scale_w
        # 保底：bbox 纵跨度<0.85 时才套 max(fit_scale, target_h/ih)，
        # 满高 bbox 不套保底（避免把主体重新撑出安全区）。
        if bbox_h_norm < 0.85:
            fit_scale = max(fit_scale, target_h / ih)
        anchor_x_norm, anchor_y_norm = (x_min + x_max) / 2, (y_min + y_max) / 2
        align_cx, align_cy = safe_cx, safe_cy

    # ── 缩放 ──
    scaled_w = int(round(iw * fit_scale))
    scaled_h = int(round(ih * fit_scale))
    img_scaled_raw = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    img.close()

    # ── anchor 对齐 ──
    anchor_cx_s = anchor_x_norm * scaled_w
    anchor_cy_s = anchor_y_norm * scaled_h
    paste_x = int(round(align_cx - anchor_cx_s))
    paste_y = int(round(align_cy - anchor_cy_s))

    _extend = int(os.environ.get("WIDE_TOP_EXTEND_PX", "0").strip())
    paste_y -= _extend

    # ── 两侧空隙填充：默认 sentinel API 延展，失败/关闭/无空隙/退化 bbox 回退 edge-pad ──
    pad_left = max(0, paste_x)
    pad_right = max(0, target_w - (paste_x + scaled_w))
    pad_top = max(0, paste_y)
    pad_bottom = max(0, target_h - (paste_y + scaled_h))
    has_gap = (pad_left + pad_right + pad_top + pad_bottom) > 0

    canvas = None
    if has_gap and not degenerate_bbox and _wide_side_fill_api_enabled():
        canvas = _wide_fill_sides_via_api_micugpt2(
            img_scaled_raw, paste_x, paste_y, target_w, target_h
        )

    if canvas is not None:
        _fill_tag = "API-fill"
    else:
        arr = np.array(img_scaled_raw)
        arr_pad = np.pad(
            arr,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            mode="edge",
        )
        crop_x = pad_left - paste_x
        crop_y = pad_top - paste_y
        canvas = Image.fromarray(
            arr_pad[crop_y:crop_y + target_h, crop_x:crop_x + target_w]
        )
        _fill_tag = "edge-pad"

    print(
        f"  wide_from_fill_micugpt2: {iw}×{ih} → fit {scaled_w}×{scaled_h} "
        f"(bbox中心→({align_cx},{align_cy})) paste=({paste_x},{paste_y}) "
        f"{_fill_tag} L{pad_left} R{pad_right} T{pad_top} B{pad_bottom}"
        f"{' extend +'+str(_extend) if _extend else ''}",
        flush=True,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"  wide_from_fill_micugpt2: {target_w}×{target_h} → {output_path}", flush=True)

    if _wide_auto_top_poke_enabled():
        _wide_auto_top_poke(output_path)

    _composite_wide_top_strip_birefnet(output_path)


# ══════════════════════════════════════════════════════════════════════════════
# 核心函数（micugpt2 API 调用 + 辅助）
# ══════════════════════════════════════════════════════════════════════════════

def _has_image_edit_key() -> bool:
    key = os.environ.get("MICUAPI_API_KEY", "").strip()
    return key.startswith("sk-")


def _micugpt2_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
) -> None:
    import json as _json
    import requests as _requests
    import base64 as _base64
    import re as _re
    import time as _time

    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("MICUAPI_API_KEY 未设置")

    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    from PIL import Image as _PILImage
    from io import BytesIO as _BytesIO

    ref_bytes = ref_path.read_bytes()
    im = _PILImage.open(_BytesIO(ref_bytes))
    im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
    orig_w, orig_h = im.size
    max_d = 2560
    if max(orig_w, orig_h) > max_d:
        scale = max_d / float(max(orig_w, orig_h))
        nw, nh = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
        im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        buf = _BytesIO()
        im.save(buf, format="PNG")
        ref_bytes = buf.getvalue()
        print(f"[micugpt2 edit] 参考图已缩放至 {nw}×{nh} (原 {orig_w}×{orig_h})", flush=True)
    ref_b64 = _base64.standard_b64encode(ref_bytes).decode("ascii")

    _proxies = None
    _no_proxy = os.environ.get("MICUGPT2_NO_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}

    prompt_with_size = prompt + f"\n\nOutput image must be exactly {orig_w}x{orig_h} pixels."
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = _json.dumps({
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt_with_size},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref_b64}"}},
        ]}],
    }).encode("utf-8")

    url = "https://www.micuapi.ai/v1/chat/completions"
    for _post_retry in range(3):
        try:
            resp = _requests.post(url, data=body, headers=headers, timeout=600, proxies=None)
            resp.raise_for_status()
            break
        except (_requests.exceptions.ConnectionError,
                _requests.exceptions.Timeout,
                _requests.exceptions.HTTPError,
                _requests.exceptions.RequestException) as _e:
            if _post_retry < 2:
                _delay = 2 ** (_post_retry + 1)
                print(f"[micugpt2 edit] API POST 异常 (尝试 {_post_retry + 1}/3，{_delay}s 后重试): {_e}", file=sys.stderr, flush=True)
                _time.sleep(_delay)
            else:
                raise RuntimeError(f"micugpt2 API POST 失败 (3次重试后): {_e}") from _e
    data = resp.json()

    img_url = ""
    for choice in data.get("choices", []):
        ct = choice.get("message", {}).get("content", "")
        if isinstance(ct, str):
            m = _re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', ct)
            if m:
                img_url = m.group(1)
                break
    if not img_url:
        raise RuntimeError(f"micugpt2 edits 无图片 URL: {_json.dumps(data, ensure_ascii=False)[:300]}")

    for _retry in range(3):
        try:
            dl = _requests.get(img_url, timeout=300, proxies=_proxies)
            dl.raise_for_status()
            break
        except (_requests.exceptions.ChunkedEncodingError,
                _requests.exceptions.ConnectionError,
                _requests.exceptions.Timeout,
                _requests.exceptions.RequestException) as _e:
            if _retry < 2:
                _delay = 2 ** (_retry + 1)
                print(f"[micugpt2 edit] CDN 下载异常 (尝试 {_retry + 1}/3，{_delay}s 后重试): {_e}", file=sys.stderr, flush=True)
                _time.sleep(_delay)
            else:
                raise RuntimeError(f"micugpt2 CDN 下载失败 (3次重试后): {_e}") from _e

    out_path_obj = Path(output_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_path_obj), "wb") as f:
        f.write(dl.content)

    # 尺寸兜底：micugpt2 返回尺寸可能不同于原始尺寸，cover-scale 修正
    result_img = _PILImage.open(_BytesIO(dl.content))
    pw, ph = result_img.size
    if (pw, ph) != (orig_w, orig_h):
        print(f"[micugpt2 edit] 返回 {pw}×{ph}，cover-scale 至 {orig_w}×{orig_h}...", flush=True)
        scale = max(orig_w / pw, orig_h / ph)
        nw, nh = max(1, int(pw * scale)), max(1, int(ph * scale))
        result_img = result_img.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        left = (nw - orig_w) // 2
        top = (nh - orig_h) // 2
        result_img = result_img.crop((left, top, left + orig_w, top + orig_h))
        result_img.save(str(out_path_obj), "PNG")
    else:
        out_sz = result_img.size
        print(f"[micugpt2 edit] 已保存: {out_path_obj} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _get_api_key() -> str:
    key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not key or not key.startswith("sk-"):
        raise RuntimeError("MICUAPI_API_KEY 未设置（需 sk- 开头）")
    return key


def _micugpt2_images_edit(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    size: str,
    mask_path: str | None = None,
    max_retries: int = 3,
) -> None:
    """使用 micuapi /v1/images/edits 端点进行图编。
    支持 size 参数精确控制输出尺寸，支持 mask 进行局部编辑。
    与 /v1/chat/completions 不同，此端点返回的图像尺寸与 size 参数一致。"""
    import micugpt2_images_api as _api
    import time as _time

    for retry in range(max_retries):
        try:
            result = _api.edit_image(
                image_path, prompt, output_path,
                mask_path=mask_path, size=size,
            )
            if result is not None:
                from PIL import Image as _PILImage
                sz = _PILImage.open(str(result)).size
                print(f"[micugpt2 images edit] 已保存: {result} ({sz[0]}×{sz[1]})", flush=True)
                return
        except Exception as e:
            if retry < max_retries - 1:
                delay = 2 ** (retry + 1)
                print(f"[micugpt2 images edit] 请求异常，{delay}s后重试 ({retry+1}/{max_retries}): {e}", file=sys.stderr, flush=True)
                _time.sleep(delay)
            else:
                raise RuntimeError(f"micugpt2 /v1/images/edits 失败 ({max_retries}次重试后): {e}") from e
    raise RuntimeError(f"micugpt2 /v1/images/edits 返回 None ({max_retries}次重试后)")


def _generate_unfilled_mask(image_path: str, threshold: int = 25) -> str:
    """对图像中近黑/未填充区域生成 RGBA mask（透明=可编辑，不透=保留）。
    返回 mask 临时文件路径。"""
    from PIL import Image
    import numpy as np

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    is_dark = np.max(arr, axis=-1) < threshold

    mask = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    mask[:, :, 3] = 255
    mask[is_dark, 3] = 0

    fd, mask_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.fromarray(mask, "RGBA").save(mask_path, "PNG")
    return mask_path


def _remove_text_micugpt2(image_path: str) -> Path | None:
    if not _has_image_edit_key():
        return None
    fd, out = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        _micugpt2_edit_image(image_path, out, MICUGPT2_A1_REMOVE_TEXT_PROMPT)
        return Path(out)
    except Exception as e:
        print(f"  micugpt2 去干扰失败: {e}", file=sys.stderr)
        if os.path.isfile(out):
            try:
                os.unlink(out)
            except OSError:
                pass
        return None


def _draw_bbox_and_save(image_path: str, bbox: tuple[float, float, float, float], out_path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    x_min, y_min, x_max, y_max = bbox
    left = max(0, min(int(x_min * w), w - 2))
    top = max(0, min(int(y_min * h), h - 2))
    right = max(left + 2, min(int(x_max * w), w))
    bottom = max(top + 2, min(int(y_max * h), h))
    draw = ImageDraw.Draw(img)
    draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))


def _crop_step5_to_canvas(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    preset: str | None = None,
    subject_bbox_norm: tuple[float, float, float, float] | None = None,
    context_prompt: str | None = None,
) -> None:
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    if (W, H) == (width, height):
        shutil.copy2(image_path, output_path)
        print(f"Step 5 裁切: 尺寸已为 {width}×{height}，复制 → {output_path}", flush=True)
        return

    from PIL import ImageDraw
    if subject_bbox_norm is not None:
        bbox = subject_bbox_norm
        print(f"Step 5 裁切: 使用共用 bbox {bbox}", flush=True)
    else:
        from gemini_subject_detect import detect_subject_bbox
        bbox = detect_subject_bbox(image_path, context_prompt=context_prompt)
        if bbox is None:
            raise RuntimeError("A5 主体 bbox 检测失败，无法继续")

    safe = get_safe_zone(width, height, preset)
    if safe is None:
        safe_cx, safe_cy = width / 2.0, height / 2.0
        safe_w, safe_h = float(width), float(height)
        x_min_s, x_max_s, y_min_s, y_max_s = 0, width, 0, height
    else:
        x_min_s, x_max_s, y_min_s, y_max_s = safe
        safe_cx = (x_min_s + x_max_s) / 2.0
        safe_cy = (y_min_s + y_max_s) / 2.0
        safe_w = x_max_s - x_min_s
        safe_h = y_max_s - y_min_s

    x_min, y_min, x_max, y_max = bbox
    bw = (x_max - x_min) * W
    bh = (y_max - y_min) * H
    if bw < 1 or bh < 1:
        bw, bh = 1.0, 1.0
    cx = (x_min + x_max) / 2 * W
    cy = (y_min + y_max) / 2 * H

    SAFE_ZONE_SCALE = 0.90
    target_bw = safe_w * SAFE_ZONE_SCALE
    target_bh = safe_h * SAFE_ZONE_SCALE
    scale = min(target_bw / bw, target_bh / bh)
    w1 = max(1, int(round(W * scale)))
    h1 = max(1, int(round(H * scale)))
    img_scaled = img.resize((w1, h1), Image.Resampling.LANCZOS)
    cx_scaled = cx * scale
    cy_scaled = cy * scale
    x0 = safe_cx - cx_scaled
    y0 = safe_cy - cy_scaled

    left_s = x_min * w1
    right_s = x_max * w1
    top_s = y_min * h1
    bottom_s = y_max * h1
    x0 = max(x_min_s - left_s, min(x_max_s - right_s, x0))
    y0 = max(y_min_s - top_s, min(y_max_s - bottom_s, y0))

    img_vis = img.copy()
    draw = ImageDraw.Draw(img_vis)
    left = max(0, min(int(x_min * W), W - 2))
    top = max(0, min(int(y_min * H), H - 2))
    right = max(left + 2, min(int(x_max * W), W))
    bottom = max(top + 2, min(int(y_max * H), H))
    draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=4)
    if safe is not None and scale > 0:
        left_s2 = int((x_min_s - safe_cx) / scale + cx)
        top_s2 = int((y_min_s - safe_cy) / scale + cy)
        right_s2 = int((x_max_s - safe_cx) / scale + cx)
        bottom_s2 = int((y_max_s - safe_cy) / scale + cy)
        draw.rectangle([max(0, left_s2), max(0, top_s2), min(W, right_s2), min(H, bottom_s2)], outline=(0, 0, 255), width=3)
    out_preview = Path(output_path).parent / "a5_bbox_preview.png"
    out_preview.parent.mkdir(parents=True, exist_ok=True)
    img_vis.save(str(out_preview), "PNG")
    print(f"Step 5 裁切前主体识别区域（红框=主体，蓝框=安全区）→ {out_preview}", flush=True)

    rx0 = round(x0)
    ry0 = round(y0)
    dest_left = max(0, rx0)
    dest_top = max(0, ry0)
    src_left = max(0, -rx0)
    src_top = max(0, -ry0)
    avail_w = width - dest_left
    avail_h = height - dest_top
    src_right = min(w1, src_left + avail_w)
    src_bottom = min(h1, src_top + avail_h)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    if src_right > src_left and src_bottom > src_top:
        patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
        canvas.paste(patch, (dest_left, dest_top))
    canvas.save(output_path, "PNG")
    print(
        f"Step 5 裁切: 主体 bbox 缩放至安全区 90%，bbox 严格落安全区内，中心 ({cx_scaled:.0f},{cy_scaled:.0f}) 对齐安全区 ({safe_cx:.0f},{safe_cy:.0f})，空白由 Step 6 填充",
        flush=True,
    )
    print(f"Step 5 产出: {W}×{H} → 缩放 {w1}×{h1} → 贴图 {width}×{height} → {output_path}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# 规格常量
# ══════════════════════════════════════════════════════════════════════════════

WIDE_CANVAS_SIZE = (3320, 500)
WIDE_TOP_STRIP_H = 40
WIDE_TOP_STRIP_X_MIN = 1470
WIDE_TOP_STRIP_X_MAX = 2464
WIDE_STRIP_BIREFNET_X_MIN = 1032
WIDE_STRIP_BIREFNET_X_MAX = 2464
WIDE_STRIP_BIREFNET_Y_MIN = 0
WIDE_STRIP_BIREFNET_Y_MAX = 200

SHOP_TOPIC_HEADER_SIZE = (1740, 220)
A6B_MAX_REPAIR_ROUNDS = 2


# ══════════════════════════════════════════════════════════════════════════════
# 主流程：_safe_zone_outpaint_micugpt2 — 与原始 _safe_zone_scale_outpaint 对等
# 区别：A4 走 _micugpt2_edit_image 而非 edit_image (Gemini)
# ══════════════════════════════════════════════════════════════════════════════

def _safe_zone_outpaint_micugpt2(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    skip_a4_outpaint: bool = False,
    remove_text: bool = True,
    preset: str | None = None,
    context_prompt: str | None = None,
) -> Path:
    if get_safe_zone(width, height, preset) is None:
        raise ValueError(f"画布 {width}×{height} 未配置安全区，无法使用 safe_zone_scale_outpaint")
    if not _has_image_edit_key():
        print(
            "Error: safe_zone_scale_outpaint 需设置 MICUAPI_API_KEY（以 sk- 开头）。",
            file=sys.stderr,
        )
        sys.exit(1)

    from gemini_image_edit import image_has_black_bars, image_has_black_bars_full_image
    from gemini_subject_detect import (
        detect_subject_bbox,
        image_a4_need_refill_unfilled,
        image_a4_need_refill_seams,
        image_a6b_shop_header_need_repair,
        image_has_unfilled_blanks,
    )
    from safe_zone_scale_composite import composite_to_canvas_center

    out_dir = Path(output_path).parent
    current_input = image_path
    cleaned_path = None

    # A1) 去干扰
    if remove_text:
        print("Step 1 / 去干扰 (micugpt2 remove-text)...", flush=True)
        _cleaned = _remove_text_micugpt2(image_path)
        if _cleaned is not None:
            cleaned_path = _cleaned
            current_input = str(cleaned_path)
    else:
        print("Step 1 / 跳过去干扰（--remove-text 未传）", flush=True)

    # A2) 主体 bbox 检测（_call_vision_get_text 会自动走 micugpt2 Vision 因为 BANNER_IMAGE_BACKEND=micugpt2）
    print("Step 2 / 主体 bbox 检测 (micugpt2 Vision)...", flush=True)
    bbox = detect_subject_bbox(current_input, context_prompt=context_prompt)
    if bbox is None:
        raise RuntimeError("主体 bbox 检测失败，无法继续")

    # A3) 标注保存
    zhuti_path = out_dir / "zhuti.png"
    _draw_bbox_and_save(current_input, bbox, zhuti_path)
    print(f"Step 3 / 标注保存 → {zhuti_path}", flush=True)

    # 所有预设走标准 A4→A5→A6→A6b 流程
    tianchong_path = out_dir / "tianchong.png"
    if not skip_a4_outpaint:
        # A4) micugpt2 延展填充（替代 Gemini edit_image）
        fd, temp_canvas = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            composite_to_canvas_center(
                current_input,
                temp_canvas,
                subject_bbox=bbox,
                subject_ratio=0.85,
                center_x_ratio=0.5,
                center_y_ratio=0.5,
            )
            max_fill_rounds = 4
            fill_input = temp_canvas
            for r in range(max_fill_rounds):
                print(f"Step 4 / 填充画面 (micugpt2 延展填满 2048×512) 第 {r + 1}/{max_fill_rounds} 轮...", flush=True)
                try:
                    _micugpt2_edit_image(
                        fill_input,
                        str(tianchong_path),
                        MICUGPT2_A4_FILL_PROMPT,
                    )
                except Exception as e:
                    print(
                        f"  A4 图编失败，改用本地画布继续（可能未填充）: {e}",
                        file=sys.stderr,
                        flush=True,
                    )
                    try:
                        shutil.copy2(temp_canvas, str(tianchong_path))
                    except Exception:
                        pass
                    break

                need_refill_unfilled = image_a4_need_refill_unfilled(str(tianchong_path))
                if need_refill_unfilled is None:
                    need_refill_unfilled = image_has_black_bars_full_image(str(tianchong_path)) or image_has_black_bars(str(tianchong_path))
                need_refill_seams = image_a4_need_refill_seams(str(tianchong_path))
                need_refill = need_refill_unfilled or (need_refill_seams if need_refill_seams is not None else True)
                if need_refill:
                    if r < max_fill_rounds - 1:
                        which = []
                        if need_refill_unfilled:
                            which.append("未填满")
                        if need_refill_seams:
                            which.append("接缝/割裂")
                        elif need_refill_seams is None and not need_refill_unfilled:
                            which.append("接缝/割裂(检测未返回)")
                        print(f"  A4 检测不通过（{' + '.join(which)}），重新填充...", flush=True)
                    fill_input = temp_canvas
                    continue
                break
            print(f"Step 4 产出 → {tianchong_path}", flush=True)
            try:
                from PIL import Image
                with Image.open(str(tianchong_path)) as img:
                    w, h = img.size
                    if (w, h) != (2048, 512):
                        print(f"tianchong.png 实际尺寸: {w}×{h}（非规定 2048×512）", flush=True)
            except Exception:
                pass
        finally:
            if os.path.isfile(temp_canvas):
                try:
                    os.unlink(temp_canvas)
                except OSError:
                    pass
    else:
        print("Step 4 / 跳过（--skip-a4-outpaint：文生图/有参考图流程，不生成 tianchong.png）", flush=True)

    # A5) 按画布裁切
    image_for_a5 = current_input if skip_a4_outpaint else str(tianchong_path)
    print("Step 5 / 按画布裁切（主体与安全区中心对齐）...", flush=True)
    _crop_step5_to_canvas(image_for_a5, output_path, width, height, preset=preset, context_prompt=context_prompt)

    # A5b) 仅 3320×500
    if (width, height) == WIDE_CANVAS_SIZE:
        _composite_wide_top_strip_birefnet(output_path)

    # A6) 画面检测 + 补填（micugpt2 /v1/images/edits，mask 精确控制）
    print("Step 6 / 画面检测（Vision 是否未填充完整）...", flush=True)
    has_unfilled = image_has_unfilled_blanks(output_path)
    if has_unfilled is None:
        has_unfilled = image_has_black_bars_full_image(output_path) or image_has_black_bars(output_path)
    if has_unfilled:
        print("  检测到未填充区域，使用 micugpt2 /v1/images/edits 填充...", flush=True)
        _mask_path = None
        try:
            _mask_path = _generate_unfilled_mask(output_path)
            _micugpt2_images_edit(
                output_path, output_path, MICUGPT2_A6_FILL_PROMPT,
                size=f"{width}x{height}", mask_path=_mask_path,
            )
        except Exception as e:
            print(f"  A6 填充失败（保留 A5 产出）: {e}", file=sys.stderr)
        finally:
            if _mask_path and os.path.isfile(_mask_path):
                try:
                    os.unlink(_mask_path)
                except OSError:
                    pass
    else:
        print("  无未填充区域，跳过填充。", flush=True)

    # A6b) 仅 1740×220，固定运行修复
    if (width, height) == SHOP_TOPIC_HEADER_SIZE:
        print(
            "Step 6b / 专题头图 1740×220 画质修复（固定运行，micugpt2 延展融补）...",
            flush=True,
        )
        for round_idx in range(1, A6B_MAX_REPAIR_ROUNDS + 1):
            print(
                f"  A6b 第 {round_idx}/{A6B_MAX_REPAIR_ROUNDS} 次修复（micugpt2 延展融补）...",
                flush=True,
            )
            try:
                _micugpt2_images_edit(
                    output_path, output_path, MICUGPT2_A6B_REPAIR_PROMPT,
                    size=f"{width}x{height}",
                )
            except Exception as e:
                print(f"  A6b 第 {round_idx} 次修复失败（保留当前产出）: {e}", file=sys.stderr)
                break
            if round_idx < A6B_MAX_REPAIR_ROUNDS:
                print("  A6b 复检（割裂/重复拼接）...", flush=True)
                need_a6b = image_a6b_shop_header_need_repair(output_path)
                if need_a6b is False:
                    print("  A6b：复检通过，停止修复。", flush=True)
                    break
                if need_a6b is None:
                    pass
        if round_idx == A6B_MAX_REPAIR_ROUNDS:
            need_final = image_a6b_shop_header_need_repair(output_path)
            if need_final is True:
                print(
                    f"  A6b：已完成 {A6B_MAX_REPAIR_ROUNDS} 次修复，末检仍建议继续处理（可人工或过片）。",
                    flush=True,
                )
            elif need_final is False:
                print("  A6b：末检通过。", flush=True)
            else:
                print("  A6b：末检未返回明确结果。", flush=True)

    if cleaned_path is not None and cleaned_path.is_file():
        try:
            cleaned_path.unlink()
        except OSError:
            pass
    return Path(output_path)


# ══════════════════════════════════════════════════════════════════════════════
# prepare_background 入口函数（与原文件接口兼容）
# ══════════════════════════════════════════════════════════════════════════════

def prepare_background(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    subject_center_y_ratio: float | None = None,
    subject_center_x_ratio: float | None = None,
    force_crop_only: bool = True,
    remove_text: bool = False,
    auto_subject: bool = True,
    align_image_center_to_safe_zone: bool = True,
    safe_zone_scale_outpaint: bool = False,
    skip_a4_outpaint: bool = False,
    preset: str | None = None,
    context_prompt: str | None = None,
) -> Path:
    from PIL import Image

    current_input = image_path
    cleaned_path = None
    if remove_text and not safe_zone_scale_outpaint:
        cleaned_path = _remove_text_micugpt2(image_path)
        if cleaned_path is not None:
            current_input = str(cleaned_path)

    if safe_zone_scale_outpaint:
        out = _safe_zone_outpaint_micugpt2(
            current_input,
            output_path,
            width,
            height,
            skip_a4_outpaint=skip_a4_outpaint,
            remove_text=remove_text,
            preset=preset,
            context_prompt=context_prompt,
        )
        if cleaned_path and cleaned_path.is_file():
            try:
                cleaned_path.unlink()
            except OSError:
                pass
        return out

    if not align_image_center_to_safe_zone:
        subject_x = subject_center_x_ratio
        subject_y = subject_center_y_ratio
        from gemini_subject_detect import detect_subject_xy_ratio
        if auto_subject and (subject_x is None or subject_y is None):
            xy = detect_subject_xy_ratio(current_input)
            if subject_x is None:
                subject_x = xy[0]
            if subject_y is None:
                subject_y = xy[1]
        if subject_x is None or subject_y is None:
            print("Warning: 无法检测主体位置，回退到居中裁切", file=sys.stderr)
            subject_x, subject_y = 0.5, 0.5

        return crop_to_target(
            current_input,
            output_path,
            width,
            height,
            subject_x=subject_x,
            subject_y=subject_y,
            force_crop_only=force_crop_only,
            preset=preset,
        )
    else:
        return crop_to_target(
            current_input,
            output_path,
            width,
            height,
            align_image_center_to_safe_zone=True,
            force_crop_only=force_crop_only,
            preset=preset,
        )


# ══════════════════════════════════════════════════════════════════════════════
# argparse 入口 — 与原 prepare_background.py 参数完全兼容
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="micugpt2 专用背景处理 — 与原 prepare_background.py 参数兼容，A4 改用 micugpt2"
    )
    parser.add_argument(
        "--wide-from-fill",
        nargs=2,
        metavar=("FILL_IMAGE", "OUTPUT_PATH"),
        help="复用填充图：将 FILL_IMAGE 按 cover 缩放到 3320×500 并做顶部条带，输出到 OUTPUT_PATH",
    )
    parser.add_argument(
        "--crop-from-image",
        nargs=2,
        metavar=("IMAGE", "OUTPUT"),
        dest="crop_from_image",
        help="仅 A5：从 IMAGE 做主体 bbox 检测，缩放到安全区 90%% 中心对齐裁切到目标尺寸",
    )
    parser.add_argument("input", nargs="?", default=None, help="Source image path")
    parser.add_argument("output", nargs="?", default=None, help="Output path or filename")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS.keys()), default="default")
    group.add_argument("--width", "-W", type=int)
    parser.add_argument("--height", "-H", type=int)
    parser.add_argument("--subject-y", type=float, metavar="RATIO")
    parser.add_argument("--subject-x", type=float, metavar="RATIO")
    parser.add_argument("--try-expand", dest="crop_only", action="store_false")
    parser.add_argument("--remove-text", action="store_true")
    parser.add_argument("--no-auto-subject", action="store_true")
    parser.add_argument("--no-align-image-center", action="store_true")
    parser.add_argument("--safe-zone-scale-outpaint", action="store_true")
    parser.add_argument("--skip-a4-outpaint", action="store_true")
    parser.add_argument("--outpaint-after-crop", action="store_true", dest="outpaint_after_crop")
    parser.add_argument(
        "--subject-bbox-norm",
        nargs=4,
        type=float,
        metavar=("X_MIN", "Y_MIN", "X_MAX", "Y_MAX"),
    )
    parser.add_argument("--bbox-file", type=str, metavar="BBOX_FILE")
    parser.add_argument("--context-prompt", type=str, metavar="PROMPT_FILE")
    args = parser.parse_args()

    # wide_from_fill 模式
    if args.wide_from_fill:
        fill_image, output_path = args.wide_from_fill
        if not Path(fill_image).is_file():
            print(f"Error: 填充图不存在: {fill_image}", file=sys.stderr)
            sys.exit(1)
        wide_from_fill_micugpt2(fill_image, output_path, bbox_file=args.bbox_file or None)
        return

    # crop_from_image 模式
    if args.crop_from_image:
        crop_image, output_path = args.crop_from_image
        if not Path(crop_image).is_file():
            print(f"Error: 图片不存在: {crop_image}", file=sys.stderr)
            sys.exit(1)
        preset = args.preset
        w, h = args.width or PRESETS[preset][0], args.height or PRESETS[preset][1]
        ctx_prompt = None
        if args.context_prompt and Path(args.context_prompt).is_file():
            ctx_prompt = Path(args.context_prompt).read_text(encoding="utf-8").strip()
        subject_bbox_norm = None
        if args.subject_bbox_norm:
            subject_bbox_norm = tuple(args.subject_bbox_norm)
        _crop_step5_to_canvas(
            crop_image, output_path, w, h,
            preset=preset,
            subject_bbox_norm=subject_bbox_norm,
            context_prompt=ctx_prompt,
        )
        if args.outpaint_after_crop and Path(output_path).is_file():
            from gemini_image_edit import image_has_black_bars_full_image, image_has_black_bars
            has_black = image_has_black_bars_full_image(output_path) or image_has_black_bars(output_path)
            if has_black:
                print("crop_from_image: 检测到黑边，使用 micugpt2 补齐...", flush=True)
                try:
                    _micugpt2_edit_image(output_path, output_path, MICUGPT2_A6_FILL_PROMPT)
                except Exception as e:
                    print(f"  outpaint_after_crop 失败: {e}", file=sys.stderr)
        return

    if not args.input or not args.output:
        print("Error: 请提供 input 和 output 参数", file=sys.stderr)
        sys.exit(1)

    input_path = args.input
    output_path = args.output
    preset = args.preset
    if args.width and args.height:
        w, h = args.width, args.height
    else:
        w, h = PRESETS[preset]

    ctx_prompt = None
    if args.context_prompt and Path(args.context_prompt).is_file():
        ctx_prompt = Path(args.context_prompt).read_text(encoding="utf-8").strip()

    prepare_background(
        input_path,
        output_path,
        w,
        h,
        subject_center_y_ratio=args.subject_y,
        subject_center_x_ratio=args.subject_x,
        force_crop_only=getattr(args, "crop_only", True),
        remove_text=args.remove_text,
        auto_subject=not args.no_auto_subject,
        align_image_center_to_safe_zone=not args.no_align_image_center,
        safe_zone_scale_outpaint=args.safe_zone_scale_outpaint,
        skip_a4_outpaint=args.skip_a4_outpaint,
        preset=preset,
        context_prompt=ctx_prompt,
    )


if __name__ == "__main__":
    main()
