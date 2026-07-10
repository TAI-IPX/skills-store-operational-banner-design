#!/usr/bin/env python3
"""
HD 产线 Stage 3：合成画面。

流程：
  1. 根据 Stage 1 判断，对需要抠图的图跑 BiRefNet，免抠的直接复制
  2. background_prompt → t2i → bg_final.jpg
  3. 角色与背景光效统一 + 边缘融合（保留原始特征）
  4. 艺术字生成
  5. 合成终稿
"""
from __future__ import annotations

import subprocess
import sys
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACT_SCRIPT = ROOT / "scripts" / "extract_subject_birefnet.py"
GEMINI_SCRIPTS_DIR = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
CANVAS_W, CANVAS_H = 3840, 1200


def _is_already_cutout(src: Path) -> tuple[bool, float]:
    """
    本地检测图片是否已经是抠好的透明背景图。
    返回 (is_cutout, transparent_ratio)。

    判定规则（优先级从高到低）：
      1. 非 RGBA 模式 → 一定不是抠图 (False)
      2. 真实透明像素（alpha ≤ 10）占比 > 5% → 已是抠图 (True)
      3. 其余情况 → 不确定，返回 False，交给 BiRefNet 处理
    """
    from PIL import Image
    import numpy as np

    try:
        im = Image.open(src)
        if im.mode != "RGBA":
            return False, 0.0
        alpha = np.array(im.split()[3], dtype=np.uint8)
        ratio = float((alpha <= 10).sum()) / max(1, alpha.size)
        return ratio > 0.05, ratio
    except Exception:
        return False, 0.0


def _run_cutouts(
    stage1_result: dict,
    image_paths: list[Path],
    out_dir: Path,
) -> list[Path]:
    """
    抠图流程（优先级从高到低）：
      1. 本地检测：RGBA 且真实透明像素 > 5% → 已抠图，直接复制，跳过 BiRefNet
      2. Stage 1 needs_matting=False → fallback 三维验证，通过则免抠
      3. 其余 → BiRefNet 抠图

    返回 cutout 路径列表（顺序与 image_paths 一致）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    images = {img["index"]: img for img in stage1_result["images"]}
    cutout_paths: list[Path] = []

    for i, src in enumerate(image_paths):
        co = out_dir / f"hd_cutout_{i:02d}.png"

        if not src.is_file():
            print(f"[stage3] 跳过：文件不存在 {src}", file=sys.stderr)
            continue

        # ── 优先：本地透明通道检测 ──
        already_cut, ratio = _is_already_cutout(src)
        if already_cut:
            from PIL import Image
            im = Image.open(src).convert("RGBA")
            im.save(str(co), "PNG")
            print(f"[stage3] 已抠图(透明{ratio*100:.1f}%): {src.name} → {co.name}", flush=True)
            cutout_paths.append(co)
            continue

        # ── 回退：Stage 1 判断 + BiRefNet ──
        img_info = images.get(i, {"needs_matting": True})
        needs_matting = img_info.get("needs_matting", True)

        if not needs_matting:
            if _needs_matting_fallback(src, co):
                _bi_refnet_cutout(src, co, i)
            else:
                from PIL import Image
                im = Image.open(src)
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                im.save(str(co), "PNG")
                print(f"[stage3] 免抠: {src.name} → {co.name}", flush=True)
        else:
            _bi_refnet_cutout(src, co, i)
        cutout_paths.append(co)

    return cutout_paths


def _needs_matting_fallback(src: Path, out_path: Path) -> bool:
    """
    验证免抠判定是否正确。不符合免抠条件时返回 True，需回退 BiRefNet。

    RGBA 三维交叉验证：
      维1 透明占比 — 真正完全透明的像素占比 > 5% → 真抠图，通过
      维2 边缘厚度 — 最多腐蚀几层后透明区域消失 → ≤5px 说明只有抗锯齿，需抠图
      维3 中心均匀 — 不透明中心 RGB 标准差 < 25 → 纯色底，需抠图

    RGB 多区采样：
      四角 8×8 + 四边 4px 条 + 中心 10% 区域，三区均值/标准差交叉检验
    """
    from PIL import Image, ImageFilter
    import numpy as np

    im = Image.open(src)

    if im.mode == "RGBA":
        alpha = np.array(im.split()[3], dtype=np.uint8)
        h, w = alpha.shape

        # 维1: 真正完全透明的像素占比 (alpha ≤ 10)
        truly_clear = (alpha <= 10).sum() / max(1, alpha.size)
        if truly_clear > 0.05:
            return False

        # 维2: 透明边缘厚度 — 腐蚀 alpha 看透明区域多久消失
        body = alpha > 10
        edge_thickness = 0
        eroded = body.copy()
        for depth in range(1, 21):
            eroded_img = Image.fromarray((eroded.astype(np.uint8)) * 255, mode="L")
            eroded_img = eroded_img.filter(ImageFilter.MinFilter(3))
            eroded = np.array(eroded_img, dtype=bool)
            if eroded.sum() == 0:
                break
            if (alpha <= 10).sum() == 0:
                edge_thickness = depth
                break
            # 模拟 alpha erosion: 取当前腐蚀后的 body 外的区域
            clear_now = ~eroded & (alpha <= 10)
            if clear_now.sum() == 0:
                edge_thickness = depth
                break

        if edge_thickness <= 5:
            print(f"[stage3] {src.name}: 透明边缘仅{edge_thickness}px（抗锯齿），回退抠图", flush=True)
            return True

        # 维3: 不透明中心区域 RGB 是否均匀
        rgb = np.array(im.convert("RGB"))
        ch, cw = h // 3, w // 3
        center = rgb[ch:2*ch, cw:2*cw]
        center_std = float(center.std(axis=(0, 1)).mean())
        if center_std < 25:
            print(f"[stage3] {src.name}: 中心区域单调（std={center_std:.0f}），纯色底，回退抠图", flush=True)
            return True

        print(f"[stage3] {src.name}: 透明{truly_clear*100:.1f}% 边缘{edge_thickness}px 中心std={center_std:.0f}，免抠通过", flush=True)
        return False

    # RGB 模式：三区采样交叉验证
    arr = np.array(im.convert("RGB"))
    h, w = arr.shape[:2]

    corners = np.concatenate([
        arr[:8, :8].reshape(-1, 3),
        arr[:8, -8:].reshape(-1, 3),
        arr[-8:, :8].reshape(-1, 3),
        arr[-8:, -8:].reshape(-1, 3),
    ])
    edge_strips = np.concatenate([
        arr[:4, :].reshape(-1, 3), arr[-4:, :].reshape(-1, 3),
        arr[:, :4].reshape(-1, 3), arr[:, -4:].reshape(-1, 3),
    ])
    ch, cw = max(1, h // 10), max(1, w // 10)
    center = arr[h//2-ch:h//2+ch, w//2-cw:w//2+cw]

    corner_mean = corners.mean()
    edge_mean = edge_strips.mean()
    center_mean = center.mean()
    center_std = float(center.std())

    is_extreme = corner_mean > 220 or corner_mean < 30
    edge_match = abs(edge_mean - corner_mean) < 30
    center_diff = abs(center_mean - edge_mean) > 50 or center_std < 30

    if is_extreme and edge_match and center_diff:
        print(f"[stage3] {src.name}: RGB 纯色底（角{corner_mean:.0f} 边{edge_mean:.0f} 心std={center_std:.0f}），回退抠图", flush=True)
        return True
    return False


def _bi_refnet_cutout(src: Path, co: Path, idx: int) -> None:
    from PIL import Image
    import numpy as np

    im = Image.open(src)
    iw, ih = im.size

    arr = np.array(im.convert("RGB"))
    corners = np.concatenate([
        arr[:8, :8].reshape(-1, 3), arr[:8, -8:].reshape(-1, 3),
        arr[-8:, :8].reshape(-1, 3), arr[-8:, -8:].reshape(-1, 3),
    ])
    corner_mean = corners.mean()
    pre_white_strip = corner_mean > 220
    pre_stripped = co.parent / f"hd_pre_{idx:02d}.png"

    if pre_white_strip:
        print(f"[stage3] 检测到白底（四角均值{corner_mean:.0f}），先去白底", flush=True)
        _remove_white_bg(src, pre_stripped)
        src_for_birefnet = pre_stripped
    else:
        src_for_birefnet = src

    if str(GEMINI_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(GEMINI_SCRIPTS_DIR))
    import gemini_subject_detect as gsd

    bbox = gsd.detect_subject_bbox(str(src), strict=True, max_retries=3)
    if bbox is None:
        x1, y1, x2, y2 = 0, 0, iw, ih
    else:
        x0, y0, x1n, y1n = bbox
        bw, bh = max(1e-6, x1n - x0), max(1e-6, y1n - y0)
        mx, my = bw * 0.06, bh * 0.06
        x0n = max(0.0, x0 - mx)
        y0n = max(0.0, y0 - my)
        x1n = min(1.0, x1n + mx)
        y1n = min(1.0, y1n + my)
        import math
        x1 = max(0, min(iw - 1, math.floor(x0n * iw)))
        y1 = max(0, min(ih - 1, math.floor(y0n * ih)))
        x2 = min(iw, max(x1 + 1, math.ceil(x1n * iw)))
        y2 = min(ih, max(y1 + 1, math.ceil(y1n * ih)))
        if x2 <= x1 or y2 <= y1:
            x1, y1, x2, y2 = 0, 0, iw, ih

    cmd = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        str(src_for_birefnet),
        "--output", str(co),
        "--crop", str(x1), str(y1), str(x2), str(y2),
    ]
    print(f"[stage3] 抠图: {src.name} → {co.name}", flush=True)
    subprocess.run(cmd, check=True)


def _remove_white_bg(input_path: Path, output_path: Path):
    from PIL import Image
    import numpy as np
    im = Image.open(input_path).convert("RGBA")
    arr = np.array(im, dtype=np.uint8)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    white_mask = (r > 240) & (g > 240) & (b > 240)
    arr[white_mask, 3] = 0
    out = Image.fromarray(arr, "RGBA")
    out.save(str(output_path), "PNG")


# ─── 完整性检测 + 补齐 + 光源统一 ───

_INTEGRITY_PROMPT = """Analyze this character cutout image. Check if the following body parts are COMPLETE and VISIBLE:
1. HEAD (including hair, top of head)
2. FACE (eyes, nose, mouth visible)
3. HANDS (both hands, fingers)
4. BODY (torso, clothing)
5. OVERALL completeness

Reply with ONLY a JSON object:
{"head": true/false, "face": true/false, "hands": true/false, "body": true/false, "complete": true/false, "missing": "brief description of what is missing or 'nothing'", "direction": "left/right/top/bottom/none — which side of the character is the missing part on"}

Output ONLY the JSON, no markdown."""

_INPAINT_PROMPT = """This is a character cutout with transparent background.
The character is missing: {missing_parts}.

ONLY extend/draw the missing parts in the TRANSPARENT area indicated by the mask.
Do NOT modify, redraw, or repaint any existing pixels of the character.
The character's existing body, face, clothing, and colors must remain exactly as-is.
Use the mask as your strict edit boundary — only draw where the mask allows.
Keep the transparent background.

Output the completed character with the same transparent background."""

_UNIFY_LIGHT_PROMPT = """This character cutout needs its lighting adjusted to match a scene with light coming from the upper-left direction. Adjust the highlights and shadows subtly to be consistent with upper-left lighting. Keep the art style and colors the same. Keep the transparent background."""


def _check_cutout_integrity(cutout_path: Path) -> dict:
    """3a: Gemini Vision 检测抠图完整性。失败假设完整。"""
    from scripts.hd.hd_vision import call_hd_vision
    import json

    print(f"  [step3/3a] 完整性检测: {cutout_path.name}", flush=True)
    try:
        text = call_hd_vision(cutout_path, _INTEGRITY_PROMPT, timeout=45)
        if text:
            start = text.find("{")
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == "{": depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            obj = json.loads(text[start:i+1])
                            print(f"  [step3/3a] → complete={obj.get('complete')}", flush=True)
                            return obj
    except Exception as e:
        print(f"  [step3/3a] Vision 失败: {e}", flush=True)
    return {"head": True, "face": True, "hands": True, "body": True, "complete": True, "missing": "nothing"}


def _build_inpaint_mask(alpha_arr: "np.ndarray", missing_desc: str) -> "np.ndarray":
    """
    构建约束遮罩：仅缺失方向上的 alpha 边界外围可编辑，角色其余部分严格保护。

    alpha=0   → 透明，不可编辑（除非在缺失方向的膨胀带内）
    alpha>0   → 角色核心，严格保护（不可编辑）

    方向检测：从 missing_desc 中提取 left/right/top/bottom 关键词，
    仅在该方向区域膨胀 alpha 边界，实现局部补全而非全身编辑。
    无明确方向时回退到全局膨胀（兼容旧逻辑）。
    """
    from PIL import Image, ImageFilter
    import numpy as np

    h, w = alpha_arr.shape
    missing_lower = missing_desc.lower()
    body_mask = alpha_arr > 0

    # 找出角色前景的包围盒
    rows = np.any(body_mask, axis=1)
    cols = np.any(body_mask, axis=0)
    has_body = rows.any() and cols.any()

    if not has_body:
        # 无前景像素，无法确定方向，回退全局膨胀
        body = Image.fromarray(alpha_arr.astype(np.uint8), mode="L").point(lambda x: 255 if x > 0 else 0)
        dilated = body.filter(ImageFilter.MaxFilter(61))
        dilated_arr = np.array(dilated, dtype=np.uint8)
        band = (dilated_arr > 0) & (alpha_arr == 0)
        mask_rgba = np.zeros((h, w, 4), dtype=np.uint8)
        mask_rgba[..., 3] = np.where(band, 255, 0).astype(np.uint8)
        return mask_rgba

    y_min, y_max = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
    x_min, x_max = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
    bbox_h = y_max - y_min
    bbox_w = x_max - x_min

    # ── 方向判定 ──
    has_left = any(kw in missing_lower for kw in ("left", "左侧", "左边"))
    has_right = any(kw in missing_lower for kw in ("right", "右侧", "右边"))
    has_top = any(kw in missing_lower for kw in ("top", "head", "hair", "forehead", "crown", "头顶", "头部", "上方"))
    has_bottom = any(kw in missing_lower for kw in ("bottom", "foot", "feet", "leg", "ankle", "shoe", "calves", "knee", "脚", "腿", "底部", "下方"))
    has_hand_arm = any(kw in missing_lower for kw in ("hand", "arm", "finger", "shoulder", "elbow", "wrist", "手", "胳膊", "手臂", "肩膀"))

    is_large = any(kw in missing_lower for kw in ("large", "big", "wide", "whole", "half", "most", "extensive"))

    directions = set()
    if has_hand_arm and has_left:
        directions.add("left")
    elif has_hand_arm and has_right:
        directions.add("right")
    elif has_hand_arm:
        # 手/胳膊无明确左右 → 两侧都做
        directions.add("left")
        directions.add("right")
    if has_left:
        directions.add("left")
    if has_right:
        directions.add("right")
    if has_top:
        directions.add("top")
    if has_bottom:
        directions.add("bottom")

    # 无方向 → 回退全局膨胀
    if not directions:
        base_radius = 60 if is_large else 30
        body = Image.fromarray(alpha_arr.astype(np.uint8), mode="L").point(lambda x: 255 if x > 0 else 0)
        dilated = body.filter(ImageFilter.MaxFilter(base_radius * 2 + 1))
        dilated_arr = np.array(dilated, dtype=np.uint8)
        band = (dilated_arr > 0) & (alpha_arr == 0)
        mask_rgba = np.zeros((h, w, 4), dtype=np.uint8)
        mask_rgba[..., 3] = np.where(band, 255, 0).astype(np.uint8)
        pct = band.sum() / max(1, h * w) * 100
        print(f"  [step3/3b] mask(全局回退): r={base_radius} editable={pct:.1f}%", flush=True)
        return mask_rgba

    # ── 按方向构建局部可编辑带 ──
    expand_px = 80 if is_large else 40  # 向外膨胀像素数
    margin = 0.33  # 方向区域占 bbox 的比例

    mask_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    band_accum = np.zeros((h, w), dtype=bool)

    for direction in directions:
        # 定义该方向的源区域（角色 bbox 内靠近该方向的部分）
        if direction == "top":
            y_cut = y_min + max(1, int(bbox_h * margin))
            y_cut = min(y_cut, y_max)  # 确保不越界
            source = body_mask & (np.arange(h)[:, None] <= y_cut)
            # 向外膨胀（仅向上方向）
            yy, xx = np.where(source)
            if len(yy) == 0:
                continue
            for dy in range(1, expand_px + 1):
                ny = yy - dy
                valid = (ny >= 0)
                if not valid.any():
                    break
                ny_valid = ny[valid]
                nx_valid = xx[valid]
                band_accum[ny_valid, nx_valid] = True

        elif direction == "bottom":
            y_cut = y_max - max(1, int(bbox_h * margin))
            y_cut = max(y_cut, y_min)
            source = body_mask & (np.arange(h)[:, None] >= y_cut)
            yy, xx = np.where(source)
            if len(yy) == 0:
                continue
            for dy in range(1, expand_px + 1):
                ny = yy + dy
                valid = (ny < h)
                if not valid.any():
                    break
                ny_valid = ny[valid]
                nx_valid = xx[valid]
                band_accum[ny_valid, nx_valid] = True

        elif direction == "left":
            x_cut = x_min + max(1, int(bbox_w * margin))
            x_cut = min(x_cut, x_max)
            source = body_mask & (np.arange(w)[None, :] <= x_cut)
            yy, xx = np.where(source)
            if len(yy) == 0:
                continue
            for dx in range(1, expand_px + 1):
                nx = xx - dx
                valid = (nx >= 0)
                if not valid.any():
                    break
                ny_valid = yy[valid]
                nx_valid = nx[valid]
                band_accum[ny_valid, nx_valid] = True

        elif direction == "right":
            x_cut = x_max - max(1, int(bbox_w * margin))
            x_cut = max(x_cut, x_min)
            source = body_mask & (np.arange(w)[None, :] >= x_cut)
            yy, xx = np.where(source)
            if len(yy) == 0:
                continue
            for dx in range(1, expand_px + 1):
                nx = xx + dx
                valid = (nx < w)
                if not valid.any():
                    break
                ny_valid = yy[valid]
                nx_valid = nx[valid]
                band_accum[ny_valid, nx_valid] = True

    # 可编辑区域 = 膨胀带中真正透明的位置（保护角色核心 alpha>0）
    band = band_accum & (alpha_arr == 0)
    mask_rgba[..., 3] = np.where(band, 255, 0).astype(np.uint8)

    pct = band.sum() / max(1, h * w) * 100
    print(f"  [step3/3b] mask(局部): dirs={directions} expand={expand_px}px "
          f"editable={pct:.1f}% body=({x_min},{y_min})-({x_max},{y_max})", flush=True)

    return mask_rgba


def _merge_alpha_union(img_path: Path, orig_alpha: "np.ndarray") -> None:
    """
    BiRefNet 新 alpha 与原始 alpha 取并集后写回 img_path。
    原始 alpha 保留旧内容；BiRefNet alpha 捕捉新补全内容（手指、腿脚等）。
    BiRefNet 失败时自动回退纯 orig_alpha。
    """
    from PIL import Image
    import numpy as np

    im = Image.open(img_path).convert("RGBA")
    arr = np.array(im, dtype=np.uint8)
    h, w = arr.shape[:2]

    # 缩放 orig_alpha 到当前尺寸
    a_old = orig_alpha
    if a_old.shape != (h, w):
        a_old = np.array(
            Image.fromarray(a_old, "L").resize((w, h), Image.Resampling.LANCZOS),
            dtype=np.uint8,
        )

    # ── BiRefNet 生成新 alpha ──
    tmp_br = img_path.parent / f"_br_{img_path.stem}.png"
    a_new = None
    try:
        import subprocess as _sp
        r = _sp.run(
            [sys.executable, str(EXTRACT_SCRIPT),
             str(img_path), "--output", str(tmp_br),
             "--alpha-threshold", "0.45", "--no-binarize"],
            capture_output=True, timeout=120,
        )
        if r.returncode == 0 and tmp_br.is_file():
            br = Image.open(tmp_br).convert("RGBA")
            a_br = np.array(br.split()[3], dtype=np.uint8)
            a_new = a_br
    except Exception:
        a_new = None
    finally:
        try: tmp_br.unlink(missing_ok=True)
        except: pass

    # ── 取并集 ──
    if a_new is not None:
        if a_new.shape != (h, w):
            a_new = np.array(
                Image.fromarray(a_new, "L").resize((w, h), Image.Resampling.LANCZOS),
                dtype=np.uint8,
            )
        merged = np.maximum(a_old, a_new)
        union_extra = float(((merged > 10) & (a_old <= 10)).sum()) / max(1, merged.size)
        print(
            f"  [stage3/alpha] {img_path.name}: orig+BiRefNet union，"
            f"新增区域 {union_extra*100:.1f}%",
            flush=True,
        )
    else:
        merged = a_old
        print(
            f"  [stage3/alpha] {img_path.name}: BiRefNet 不可用，回退纯 orig_alpha",
            flush=True,
        )

    arr[:, :, 3] = merged
    Image.fromarray(arr, "RGBA").save(str(img_path), "PNG")


def _ensure_transparent_bg(img_path: Path) -> None:
    """
    原地修复：若图片实际上是白底（透明像素 < 5%），做感知去白底处理并覆写。
    Gemini edit_image 有时会把透明背景改成白底，此函数在每次 Gemini 编辑后调用。
    """
    from PIL import Image
    import numpy as np

    try:
        im = Image.open(img_path).convert("RGBA")
        arr = np.array(im, dtype=np.uint8)
        alpha = arr[:, :, 3]
        transparent_ratio = float((alpha <= 10).sum()) / max(1, alpha.size)

        if transparent_ratio > 0.05:
            # 已有足够透明区域，无需处理
            return

        # 白底判定：亮度高 + 饱和度低的像素设为透明
        r = arr[:, :, 0].astype(np.float32)
        g = arr[:, :, 1].astype(np.float32)
        b = arr[:, :, 2].astype(np.float32)
        brightness = 0.299 * r + 0.587 * g + 0.114 * b
        saturation = (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b))

        lo, hi = 220.0, 245.0
        white_ratio = np.clip((brightness - lo) / (hi - lo), 0.0, 1.0)
        sat_factor  = np.clip(1.0 - saturation / 40.0, 0.0, 1.0)
        alpha_new = np.clip(255.0 * (1.0 - white_ratio * sat_factor), 0, 255).astype(np.uint8)

        arr[:, :, 3] = alpha_new
        result = Image.fromarray(arr, "RGBA")

        # tight crop
        bbox = result.getbbox()
        if bbox:
            result = result.crop(bbox)

        removed = float((alpha_new <= 10).sum()) / max(1, alpha_new.size)
        print(f"  [stage3/fix-bg] {img_path.name}: 去白底后透明 {removed*100:.1f}%", flush=True)
        result.save(str(img_path), "PNG")
    except Exception as e:
        print(f"  [stage3/fix-bg] 去白底失败 ({img_path.name}): {e}", flush=True)


def _inpaint_cutout(cutout_path: Path, missing_desc: str, out_path: Path) -> Path:
    """3b: Gemini 编辑补齐缺失部位（支持 mask）。失败返回原图。"""
    from PIL import Image
    import numpy as np

    print(f"  [step3/3b] 补齐 (Gemini): {missing_desc[:60]}", flush=True)

    char = Image.open(cutout_path).convert("RGBA")
    alpha = np.array(char.split()[3], dtype=np.uint8)
    orig_alpha = alpha.copy()   # 保存原始 alpha，编辑后恢复
    mask = _build_inpaint_mask(alpha, missing_desc)

    tmp_mask = out_path.parent / "_inpaint_mask.png"
    Image.fromarray(mask, "RGBA").save(str(tmp_mask), "PNG")

    prompt = _INPAINT_PROMPT.format(missing_parts=missing_desc)

    try:
        if str(GEMINI_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(GEMINI_SCRIPTS_DIR))
        import gemini_image_edit as gie
        gie.edit_image(
            str(cutout_path),
            str(out_path),
            prompt,
            mask_path=str(tmp_mask),
        )
        # Mask 硬约束：非编辑区逐像素还原为原始图，防 Gemini 白底/重绘
        edited = np.array(Image.open(out_path).convert("RGBA"))
        original = np.array(Image.open(cutout_path).convert("RGBA"))
        mask_arr = np.array(Image.open(tmp_mask).convert("RGBA"))
        protected = mask_arr[:, :, 3] == 0
        edited[protected] = original[protected]
        Image.fromarray(edited, "RGBA").save(str(out_path), "PNG")

        if out_path.is_file():
            _merge_alpha_union(out_path, orig_alpha)
            _ensure_transparent_bg(out_path)
            # 四重保障 #4：透明区 RGB 强制归零
            result = Image.open(out_path).convert("RGBA")
            r_arr = np.array(result, dtype=np.uint8)
            r_arr[r_arr[:,:,3] <= 10, :3] = 0
            Image.fromarray(r_arr, "RGBA").save(str(out_path), "PNG")
        print(f"  [step3/3b] 补齐完成: {out_path.name}", flush=True)
        return out_path
    except Exception as e:
        print(f"  [step3/3b] 补齐失败: {e}", flush=True)
    finally:
        try: tmp_mask.unlink(missing_ok=True)
        except: pass

    return cutout_path


def _unify_cutout_lighting(cutout_path: Path, out_path: Path) -> Path:
    """3c: Gemini 编辑统一到左上光。失败回退原图。"""
    from PIL import Image
    import numpy as np

    print(f"  [step3/3c] 统一光源 (Gemini): {cutout_path.name}", flush=True)

    char = Image.open(cutout_path).convert("RGBA")
    alpha = np.array(char.split()[3], dtype=np.uint8)
    orig_alpha = alpha.copy()   # 保存原始 alpha，编辑后恢复

    # 仅边缘可编辑（腐蚀核心保护），避免 Gemini 重绘整个角色
    from PIL import ImageFilter
    eroded = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(5))
    core = np.array(eroded) > 0
    body = alpha > 0
    edge = body & ~core

    mask = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    mask[edge, 3] = 255

    tmp_mask = out_path.parent / "_unify_mask.png"
    Image.fromarray(mask, "RGBA").save(str(tmp_mask), "PNG")

    try:
        if str(GEMINI_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(GEMINI_SCRIPTS_DIR))
        import gemini_image_edit as gie
        gie.edit_image(
            str(cutout_path),
            str(out_path),
            _UNIFY_LIGHT_PROMPT,
            mask_path=str(tmp_mask),
        )
        # Mask 硬约束：非编辑区逐像素还原为原始图，防 Gemini 白底/重绘
        edited = np.array(Image.open(out_path).convert("RGBA"))
        original = np.array(Image.open(cutout_path).convert("RGBA"))
        mask_arr = np.array(Image.open(tmp_mask).convert("RGBA"))
        protected = mask_arr[:, :, 3] == 0
        edited[protected] = original[protected]
        Image.fromarray(edited, "RGBA").save(str(out_path), "PNG")

        if out_path.is_file():
            _merge_alpha_union(out_path, orig_alpha)
            _ensure_transparent_bg(out_path)
            # 四重保障 #4：透明区 RGB 强制归零
            result = Image.open(out_path).convert("RGBA")
            r_arr = np.array(result, dtype=np.uint8)
            r_arr[r_arr[:,:,3] <= 10, :3] = 0
            Image.fromarray(r_arr, "RGBA").save(str(out_path), "PNG")
        print(f"  [step3/3c] 光源统一完成: {out_path.name}", flush=True)
        return out_path
    except Exception as e:
        print(f"  [step3/3c] 统一失败: {e}", flush=True)
    finally:
        try: tmp_mask.unlink(missing_ok=True)
        except: pass

    return cutout_path


def _check_and_complete_cutouts(cutout_paths: list[Path], out_dir: Path) -> list[Path]:
    """遍历所有抠图：3a 完整性检测 → 3b 补全 → 3c 光源统一。"""
    results = []
    for i, path in enumerate(cutout_paths):
        if not path.is_file():
            results.append(path)
            continue
        current = path

        integrity = _check_cutout_integrity(current)
        if not integrity.get("complete", True):
            missing = integrity.get("missing", "unknown parts")
            direction = integrity.get("direction", "")
            if direction and direction not in ("none", ""):
                missing = f"{missing} ({direction})"
            inpaint_out = out_dir / f"hd_inpaint_{i:02d}.png"
            current = _inpaint_cutout(current, missing, inpaint_out)

        light_out = out_dir / f"hd_unified_{i:02d}.png"
        current = _unify_cutout_lighting(current, light_out)

        results.append(current)
    return results


def _run_hd_image_t2i(prompt: str, output_path: Path, width: int, height: int) -> Path:
    """gpt-image-2 / Gemini t2i via /v1/images/generations (OpenAI-compat)，自包含。"""
    import base64, json, os, urllib.request, urllib.error
    from io import BytesIO
    from PIL import Image

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("[stage3] 未配置 OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://www.micuapi.ai").strip().rstrip("/")
    url = base + "/v1/images/generations"
    model = os.environ.get("OPENAI_MODEL", "gpt-image-2").strip()

    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    print(f"[stage3] MICU t2i ({model} {width}×{height})...", flush=True)
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=360) as resp:
                data = json.loads(resp.read())
            break
        except Exception as e:
            print(f"[stage3] MICU t2i 第 {attempt}/3 次失败: {e}", flush=True)
            if attempt < 3:
                import time
                time.sleep(10 * attempt)
            else:
                raise RuntimeError(f"[stage3] MICU t2i 重试 3 次均失败: {e}")

    item = (data.get("data") or [{}])[0]
    b64 = item.get("b64_json")
    if b64:
        raw = base64.b64decode(b64)
    elif item.get("url"):
        img_req = urllib.request.Request(
            item["url"], headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(img_req, timeout=120) as r:
            raw = r.read()
    else:
        raise RuntimeError(f"[stage3] MICU 响应无 b64_json 或 url: {str(data)[:300]}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(BytesIO(raw)).convert("RGB")
    img.save(str(output_path), "PNG")
    print(f"[stage3] MICU 已保存: {output_path.name} ({img.size[0]}×{img.size[1]})", flush=True)
    return output_path


def _generate_background(background_prompt: str, out_dir: Path) -> Path:
    """t2i 背景生图 → cover crop 到 3840×1200。读 BANNER_IMAGE_BACKEND 标准变量。"""
    import os as _os
    from PIL import Image

    bg_final = out_dir / "bg_final.jpg"
    img_backend = _os.environ.get("BANNER_IMAGE_BACKEND", "gemini")

    if img_backend in ("packy", "gemini", "xingchengemini"):
        bg_native = out_dir / "bg_native.png"
        _run_gemini_t2i(background_prompt, bg_native, 3840, 1280)
    else:
        bg_native = out_dir / "bg_native.png"
        _run_hd_image_t2i(background_prompt, bg_native, 4096, 1024)

    img = Image.open(bg_native).convert("RGB")
    sw, sh = img.size
    scale = max(CANVAS_W / sw, CANVAS_H / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - CANVAS_W) // 2, (nh - CANVAS_H) // 2
    cropped = resized.crop((left, top, left + CANVAS_W, top + CANVAS_H))
    cropped.save(str(bg_final), "JPEG", quality=95)
    try:
        bg_native.unlink(missing_ok=True)
    except Exception:
        pass
    print(f"[stage3] 背景: {bg_final.name} {CANVAS_W}×{CANVAS_H}", flush=True)
    return bg_final


def _run_gemini_t2i(prompt: str, output_path: Path, width: int, height: int) -> Path:
    """Gemini t2i via Packy proxy."""
    import base64, json, os, urllib.error, urllib.request
    from io import BytesIO
    from PIL import Image

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("[stage3] 未配置 GEMINI_API_KEY")
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
    api_base = f"{base}/v1beta/models" if base else "https://generativelanguage.googleapis.com/v1beta/models"
    models_raw = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["Text", "Image"]},
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        headers["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in base:
        headers["User-Agent"] = "Mozilla/5.0"

    for model in models:
        url = f"{api_base}/{model}:generateContent"
        if not key.startswith("sk-"):
            url = f"{url}?key={key}"
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
            for candidate in result.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "inlineData" in part:
                        img_data = base64.b64decode(part["inlineData"]["data"])
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                        img.save(str(output_path), "PNG")
                        return output_path
        except Exception:
            continue
    raise RuntimeError("[stage3] Gemini 背景生图失败")


def _run_gpt_image_t2i(prompt: str, output_path: Path, backend: str) -> Path:
    """gpt-image-2 t2i via OpenAI compatible API (xingchengpt / packygpt)."""
    import base64, json, os as _os, time, urllib.error, urllib.request
    from io import BytesIO
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)

    api_key = _os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"[stage3] 未配置 OPENAI_API_KEY ({backend})")
    api_base = _os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not api_base:
        api_base = "https://www.packyapi.com"
    model = _os.environ.get("OPENAI_MODEL", "gpt-image-2").strip()

    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "4096x1024",
        "quality": "auto",
    }).encode()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{api_base}/v1/images/generations"
    print(f"[stage3] {backend} 生图 ({model})...", flush=True)

    max_retries = int(_os.environ.get("HD_GPT_IMAGE_T2I_RETRIES", "3"))
    retry_wait_base = int(_os.environ.get("HD_GPT_IMAGE_T2I_RETRY_WAIT", "15"))
    result = None
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=450) as resp:
                result = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            last_err = e
            retryable = e.code in (429, 500, 502, 503, 504)
            if retryable and attempt < max_retries:
                wait = retry_wait_base * (attempt + 1)
                print(f"[stage3] {backend} 生图 HTTP {e.code}，{wait}s 后重试 ({attempt + 1}/{max_retries})...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"[stage3] {backend} 生图请求失败: HTTP {e.code} {e.reason}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt < max_retries:
                wait = retry_wait_base * (attempt + 1)
                print(f"[stage3] {backend} 生图网络/超时错误: {e}，{wait}s 后重试 ({attempt + 1}/{max_retries})...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"[stage3] {backend} 生图请求失败: {e}")
        except Exception as e:
            raise RuntimeError(f"[stage3] {backend} 生图请求失败: {e}")
    if result is None:
        raise RuntimeError(f"[stage3] {backend} 生图请求失败（重试用尽）: {last_err}")

    data_list = result.get("data", [])
    if not data_list:
        raise RuntimeError(f"[stage3] {backend} 未返回图片数据。响应: {json.dumps(result, ensure_ascii=False)[:500]}")

    b64 = None
    for item in data_list:
        b64 = item.get("b64_json") or item.get("b64")
        if b64:
            break
        img_url = item.get("url")
        if img_url:
            try:
                img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(img_req, timeout=120) as img_resp:
                    img = Image.open(BytesIO(img_resp.read())).convert("RGB")
                    img.save(str(output_path), "PNG")
                    print(f"[stage3] {backend} 已保存: {output_path.name} ({img.size[0]}x{img.size[1]})", flush=True)
                    return output_path
            except Exception:
                continue

    if b64:
        img_data = base64.b64decode(b64)
        img = Image.open(BytesIO(img_data)).convert("RGB")
        img.save(str(output_path), "PNG")
        print(f"[stage3] {backend} 已保存: {output_path.name} ({img.size[0]}x{img.size[1]})", flush=True)
        return output_path

    raise RuntimeError(f"[stage3] {backend} 无法解析图片数据")


def _relight_char_via_gpt_edits(
    cutout_path: Path,
    bg_path: Path,
    lp: dict,
    style_block: str,
    out_dir: Path,
) -> Path | None:
    """
    gpt-image-2 /v1/images/edits：用 mask 保护角色核心，编辑边缘/阴影以匹配背景。
    API 格式：multipart/form-data (image, mask, prompt, model, n, size)
    """
    import base64, json, os, urllib.request, urllib.error
    from io import BytesIO
    from PIL import Image, ImageFilter
    import numpy as np

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not key or not base:
        return None

    try:
        char = Image.open(cutout_path).convert("RGBA")
        bg = Image.open(bg_path).convert("RGB")
    except Exception:
        return None

    # Match character to a standard size (max 1024)
    cw, ch = char.size
    scale = min(1.0, 1024.0 / max(cw, ch))
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    char = char.resize((nw, nh), Image.Resampling.LANCZOS)

    # Mask: RGBA where alpha channel controls edit area (OpenAI /v1/images/edits spec)
    # alpha=0 → preserve (do not edit)
    # alpha=255 → can edit
    alpha = np.array(char.split()[3], dtype=np.uint8)
    eroded = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(5))
    core  = np.array(eroded) > 0   # inner core = preserve
    body  = alpha > 0              # full character
    edge  = body & ~core           # outer edge = edit zone

    mask_rgba = np.zeros((nh, nw, 4), dtype=np.uint8)
    mask_rgba[edge, 3] = 255       # edge: alpha=255 = AI can edit
    mask_img = Image.fromarray(mask_rgba, "RGBA")

    # Save temp files for multipart
    tmp_char = out_dir / "_relight_char.png"
    tmp_mask = out_dir / "_relight_mask.png"
    char.save(str(tmp_char), "PNG")
    mask_img.save(str(tmp_mask), "PNG")

    instruction = (
        f"Adjust the character's EDGES and SHADOWS to match this scene lighting. "
        f"Scene: {style_block[:300]}. "
        f"Darken shadows on the side away from light. Keep character core intact."
    )

    # Multipart form
    boundary = "----HDRElightBoundary"
    body = b""
    for field_name, fpath, fname in [
        ("image", str(tmp_char), "char.png"),
        ("mask", str(tmp_mask), "mask.png"),
    ]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{field_name}"; filename="{fname}"\r\n'.encode()
        body += b"Content-Type: image/png\r\n\r\n"
        body += open(fpath, "rb").read()
        body += b"\r\n"
    for field_name, value in [
        ("prompt", instruction), ("model", "gpt-image-2"), ("n", "1"), ("size", f"{nw}x{nh}"),
    ]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode()
        body += value.encode()
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    url = f"{base}/v1/images/edits"

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200] if e.fp else str(e)
        print(f"[stage3/relight] gpt-image-2 edits HTTP {e.code}: {detail}", flush=True)
        for p in (tmp_char, tmp_mask):
            try: p.unlink(missing_ok=True)
            except: pass
        return None
    except Exception as e:
        print(f"[stage3/relight] edits 请求失败: {e}", flush=True)
        for p in (tmp_char, tmp_mask):
            try: p.unlink(missing_ok=True)
            except: pass
        return None

    b64 = None
    for item in (result.get("data") or []):
        b64 = item.get("b64_json")
        if b64: break
    if not b64:
        print("[stage3/relight] edits 响应无图片", flush=True)
        return None

    img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGBA")
    if img.size != (cw, ch):
        img = img.resize((cw, ch), Image.Resampling.LANCZOS)
    # 恢复原图透明背景（API 可能填充透明区域）
    orig_rgba = Image.open(cutout_path).convert("RGBA")
    orig_alpha = orig_rgba.split()[3]
    if img.size != orig_alpha.size:
        orig_alpha = orig_rgba.resize(img.size, Image.Resampling.LANCZOS).split()[3]
    img.putalpha(orig_alpha)
    # 透明区域 RGB 归零，避免 API 残留脏色
    arr = np.array(img, dtype=np.uint8)
    arr[arr[:,:,3] == 0, :3] = 0
    img = Image.fromarray(arr, "RGBA")
    role = lp.get("role", "unknown")
    out = out_dir / f"relit_{role}.png"
    img.save(str(out), "PNG")
    for p in (tmp_char, tmp_mask):
        try: p.unlink(missing_ok=True)
        except: pass
    print(f"[stage3/relight] {role}: API图编 → {out.name}", flush=True)
    return out


def _relight_characters(
    cutout_paths: list[Path],
    layout_params: list[dict],
    bg_path: Path,
    out_dir: Path,
    style_block: str = "",
) -> list[dict]:
    """
    角色光效统一：优先 gpt-image-2 /v1/images/edits API，失败回退程序化染色。
    """
    from PIL import Image

    bg_img = Image.open(bg_path).convert("RGB")
    if bg_img.size != (CANVAS_W, CANVAS_H):
        bg_img = bg_img.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)
    bg_arr = np.array(bg_img, dtype=np.float32)

    for lp in layout_params:
        role = lp.get("role", "?")
        ci   = lp.get("cutout_index", 0)
        if ci >= len(cutout_paths):
            continue

        src_path = cutout_paths[ci]
        if not src_path.is_file():
            continue

        tone_path = out_dir / f"tone_{role}.png"
        lp["path"]        = str(src_path)
        lp["cutout_path"] = str(src_path)

        # ── 优先 API 图编 ──
        api_result = _relight_char_via_gpt_edits(src_path, bg_path, lp, style_block, out_dir)
        if api_result and api_result.is_file():
            img = Image.open(api_result).convert("RGBA")
            print(f"[stage3] 光效统一 {role}: API图编 → {tone_path.name}", flush=True)
        else:
            # ── 回退程序化染色：先确保透明背景正确 ──
            char = Image.open(src_path).convert("RGBA")
            import numpy as _np
            _alpha = _np.array(char.split()[3], dtype=_np.uint8)
            _transparent_ratio = float((_alpha <= 10).sum()) / max(1, _alpha.size)
            if _transparent_ratio < 0.05:
                # 白底图：先去白底再染色
                print(f"[stage3] 光效统一 {role}: 检测到白底(透明{_transparent_ratio*100:.1f}%)，先去白底", flush=True)
                _ensure_transparent_bg(src_path)
                char = Image.open(src_path).convert("RGBA")
            img  = _tone_character(char, lp, bg_arr, out_dir)
            print(f"[stage3] 光效统一 {role}: 程序化回退 → {tone_path.name}", flush=True)

        # 透明区域 RGB 归零（兜底）
        arr = np.array(img, dtype=np.uint8)
        arr[arr[:,:,3] == 0, :3] = 0
        img = Image.fromarray(arr, "RGBA")
        img.save(str(tone_path), "PNG")
        lp["path"]       = str(tone_path)
        lp["rgba_image"] = img

    return layout_params


def _tone_character(
    char_rgba,
    lp: dict,
    bg_arr: np.ndarray,
    out_dir: Path,
):
    """对单个角色做阴影环境色染色 + 边缘融合."""
    from PIL import Image, ImageFilter
    import numpy as np

    src = char_rgba.convert("RGBA")
    arr = np.array(src.convert("RGB"), dtype=np.float32) / 255.0
    alpha = np.array(src.split()[3], dtype=np.float32)
    m = alpha > 48
    if not m.any():
        return src

    h, w = bg_arr.shape[:2]
    cx = int(lp["x_center"])
    y_bot = int(lp["y_bottom"])
    ch = int(lp["height"])
    half_w = max(24, ch // 2)
    y_top = max(0, y_bot - ch)
    y_bot2 = min(h, y_bot)
    x0 = max(0, cx - half_w)
    x1 = min(w, cx + half_w)
    if y_bot2 > y_top and x1 > x0:
        region = bg_arr[y_top:y_bot2, x0:x1].reshape(-1, 3).mean(axis=0) / 255.0
    else:
        region = bg_arr.reshape(-1, 3).mean(axis=0) / 255.0

    shadow = region * np.array([0.82, 0.88, 1.08], dtype=np.float32)

    lab = _rgb_to_lab(arr)
    L = lab[..., 0]
    med = float(np.median(L[m]))
    shadow_mask = m & (L <= med - 4)

    out = arr.copy()
    strength = 0.18
    for c in range(3):
        ch_arr = out[..., c]
        ch_arr[shadow_mask] = ch_arr[shadow_mask] * (1.0 - strength) + shadow[c] * strength
        out[..., c] = ch_arr

    edge = _edge_mask(alpha)
    if edge.any():
        edge_w = 0.12 * np.clip(alpha[edge] / 255.0, 0.15, 0.6)
        for c in range(3):
            ch_arr = out[..., c]
            ch_arr[edge] = ch_arr[edge] * (1.0 - edge_w) + region[c] * edge_w
            out[..., c] = ch_arr

    rgb_u8 = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    result = Image.merge("RGBA", (*Image.fromarray(rgb_u8).split(), src.split()[3]))
    # 透明区域 RGB 归零
    r_arr = np.array(result, dtype=np.uint8)
    r_arr[r_arr[:,:,3] == 0, :3] = 0
    return Image.fromarray(r_arr, "RGBA")


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    import numpy as np
    arr = np.clip(rgb, 0, 1)
    t = (arr > 0.04045).astype(np.float32)
    arr_l = arr / 12.92
    arr_g = ((arr + 0.055) / 1.055) ** 2.4
    arr = arr_l * (1 - t) + arr_g * t

    xyz_mat = np.array([[0.4124, 0.3576, 0.1805],
                         [0.2126, 0.7152, 0.0722],
                         [0.0193, 0.1192, 0.9505]], dtype=np.float32)
    xyz = np.dot(arr, xyz_mat.T)
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)

    t2 = xyz > 0.008856
    f = np.where(t2, xyz ** (1.0 / 3.0), 7.787 * xyz + 16.0 / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b_arr = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b_arr], axis=-1)


def _edge_mask(alpha: np.ndarray) -> np.ndarray:
    from PIL import Image, ImageFilter
    a_u8 = alpha.astype(np.uint8)
    a_blur = np.array(
        Image.fromarray(a_u8).filter(ImageFilter.GaussianBlur(radius=1.6)),
        dtype=np.float32,
    )
    return (alpha > 36) & (alpha < 252) & (np.abs(alpha - a_blur) > 5)


def _birefnet_extract_text(img_path: Path) -> None:
    """
    对艺术字图运行通用 BiRefNet 抠图，原地覆写。
    使用 --no-binarize 保留柔和笔划边缘；--threshold 0.3 比默认宽松。
    BiRefNet 失败时保留原图（不中断流程）。
    """
    tmp_br = img_path.parent / f"_br_title_{img_path.stem}.png"
    try:
        import subprocess as _sp
        print(f"  [stage3/title] BiRefNet 抠字: {img_path.name}", flush=True)
        r = _sp.run(
            [sys.executable, str(EXTRACT_SCRIPT),
             str(img_path), "--output", str(tmp_br),
             "--alpha-threshold", "0.3",
             "--no-binarize"],
            capture_output=True, timeout=120,
        )
        if r.returncode == 0 and tmp_br.is_file():
            import shutil
            shutil.move(str(tmp_br), str(img_path))
            from PIL import Image
            s = Image.open(img_path).size
            print(f"  [stage3/title] BiRefNet 完成: {img_path.name} {s[0]}×{s[1]}", flush=True)
        else:
            print(
                f"  [stage3/title] BiRefNet 失败(rc={r.returncode})，保留原图",
                flush=True,
            )
    except Exception as e:
        print(f"  [stage3/title] BiRefNet 异常({e})，保留原图", flush=True)
    finally:
        try: tmp_br.unlink(missing_ok=True)
        except: pass


def _prepare_logo(logo_path: Path, out_dir: Path) -> Path | None:
    """
    处理 logo 图：确保 RGBA 透明背景 → 等比缩放 fit 450×120 → 输出独立透明 PNG。
    1. 若已有透明区 (>5%) → 直接用
    2. 白底 → 感知去白底
    3. 复杂背景 → BiRefNet 抠图
    """
    from PIL import Image
    import numpy as np

    try:
        img = Image.open(logo_path).convert("RGBA")
        alpha = np.array(img.split()[3], dtype=np.uint8)
        ratio = float((alpha <= 10).sum()) / max(1, alpha.size)
        if ratio < 0.05:
            print(f"  [stage3/logo] 无透明区(透明{ratio*100:.1f}%)，尝试去白底", flush=True)
            img = _remove_white_bg_title(img)
            alpha2 = np.array(img.split()[3], dtype=np.uint8)
            ratio2 = float((alpha2 <= 10).sum()) / max(1, alpha2.size)
            if ratio2 < 0.05:
                print(f"  [stage3/logo] 去白底后仍不透明(透明{ratio2*100:.1f}%)，走 BiRefNet", flush=True)
                tmp = out_dir / "_logo_pre_br.png"
                img.save(str(tmp), "PNG")
                _birefnet_extract_text(tmp)
                img = Image.open(tmp).convert("RGBA")
                try: tmp.unlink(missing_ok=True)
                except: pass

        # 等比缩放 fit 450×120
        LOGO_RECT_W, LOGO_RECT_H = 450, 120
        lw, lh = img.size
        scale = min(1.0, LOGO_RECT_W * 0.95 / lw, LOGO_RECT_H * 0.95 / lh)
        nw, nh = max(1, int(lw * scale)), max(1, int(lh * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)

        # 透明区域 RGB 归零
        arr = np.array(img, dtype=np.uint8)
        arr[arr[:,:,3] == 0, :3] = 0
        img = Image.fromarray(arr, "RGBA")

        out = out_dir / "logo_final.png"
        img.save(str(out), "PNG")
        print(f"  [stage3/logo] 已处理: {out.name} {nw}×{nh}", flush=True)
        return out
    except Exception as e:
        print(f"  [stage3/logo] 处理失败: {e}", flush=True)
        return None


def _remove_white_bg_title(img):
    """
    艺术字去白底：RGB 三通道均 >= 230 的像素设为透明。
    使用渐变阈值，避免边缘锯齿：220~240 区间线性过渡。
    """
    import numpy as np
    from PIL import Image

    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    # 亮度（感知加权）
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    # 色彩饱和度：最大通道 - 最小通道
    saturation = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)

    # 白底判定：高亮度 + 低饱和度
    lo, hi = 220.0, 245.0
    white_ratio = np.clip((brightness - lo) / (hi - lo), 0.0, 1.0)
    # 饱和度高的像素不算白底（彩色艺术字笔划保留）
    sat_factor = np.clip(1.0 - saturation / 40.0, 0.0, 1.0)
    alpha_reduce = white_ratio * sat_factor

    orig_a = arr[:, :, 3]
    arr[:, :, 3] = np.clip(orig_a * (1.0 - alpha_reduce), 0, 255).astype(np.float32)

    result = Image.fromarray(arr.astype(np.uint8), "RGBA")

    # tight crop 去掉四周透明边距
    bbox = result.getbbox()
    if bbox:
        result = result.crop(bbox)

    removed = float((arr[:, :, 3] < 10).sum()) / max(1, arr[:, :, 3].size)
    print(f"  [stage3/title] 去白底: 透明化 {removed*100:.1f}% 像素", flush=True)
    return result


def _generate_title_art_gpt(
    title_prompt: str,
    out_dir: Path,
) -> Path:
    """gpt-image-2 直出完整艺术字（风格化的中文标题），失败重试 3 次，仍失败则报错。"""
    import base64, json, os, time, urllib.request, urllib.error
    from io import BytesIO
    from PIL import Image

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not key or not base:
        raise RuntimeError(
            f"[stage3] 艺术字 GPT 无法执行: "
            f"OPENAI_API_KEY={'已设置' if key else '未设置'}, "
            f"OPENAI_BASE_URL={'已设置' if base else '未设置'}"
        )

    model = os.environ.get("OPENAI_MODEL", "gpt-image-2").strip()
    MAX_RETRIES = 3
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[stage3] 艺术字 GPT 生图 ({model}) 第 {attempt}/{MAX_RETRIES} 次 base={base[:40]}...", flush=True)
        try:
            body = json.dumps({
                "model": model,
                "prompt": title_prompt,
                "n": 1,
                "size": "1792x1024",
                "quality": "auto",
                "response_format": "b64_json",
            }).encode()
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            url = f"{base}/v1/images/generations"

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())

            b64 = None
            for item in (result.get("data") or []):
                b64 = item.get("b64_json")
                if b64:
                    break
                img_url = item.get("url")
                if img_url:
                    try:
                        img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(img_req, timeout=120) as r:
                            b64 = base64.standard_b64encode(r.read()).decode("ascii")
                        break
                    except Exception as e:
                        print(f"[stage3] 艺术字 GPT URL 下载失败: {e}", flush=True)

            if not b64:
                raise RuntimeError(f"响应无图片数据: {str(result)[:200]}")

            img = Image.open(BytesIO(base64.b64decode(b64)))
            print(f"  [stage3/title] 原始图片: {img.size} mode={img.mode}", flush=True)

            # BiRefNet 在完整白底图上抠字（白底RGB → alpha），
            # 不再调用 _remove_white_bg_title，避免亮度阈值误将文字内部白色区域镂空
            tmp_br = out_dir / "_title_pre_br.png"
            img.convert("RGB").save(str(tmp_br), "PNG")  # 以白底 RGB 传给 BiRefNet
            _birefnet_extract_text(tmp_br)
            img = Image.open(tmp_br).convert("RGBA")
            try: tmp_br.unlink(missing_ok=True)
            except: pass

            # 裁边：切掉四周透明区域
            bbox = img.split()[3].getbbox()
            if bbox:
                img = img.crop(bbox)
                print(f"  [stage3/title] 裁边后: {img.size}", flush=True)

            # 等比缩放 fit 1080×328，居中到透明画布
            SPEC_W, SPEC_H = 1080, 328
            if img.size[0] > 0 and img.size[1] > 0:
                scale = min(SPEC_W / img.size[0], SPEC_H / img.size[1])
                nw, nh = max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale))
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (SPEC_W, SPEC_H), (0, 0, 0, 0))
                canvas.paste(img, ((SPEC_W - nw) // 2, (SPEC_H - nh) // 2), img)
                img = canvas

            out = out_dir / "title_art.png"
            img.save(str(out), "PNG")
            print(f"[stage3] 艺术字 (GPT): {out.name} {img.size}", flush=True)
            return out

        except Exception as e:
            last_error = str(e)
            print(f"[stage3] 艺术字 GPT 第 {attempt}/{MAX_RETRIES} 次失败: {last_error}", flush=True)
            if attempt < MAX_RETRIES:
                wait = 5 * attempt
                print(f"[stage3] 等待 {wait}s 后重试...", flush=True)
                time.sleep(wait)

    raise RuntimeError(f"[stage3] 艺术字 GPT 重试 {MAX_RETRIES} 次全部失败: {last_error}")



def _generate_title_art(
    style: dict,
    main_title: str,
    subtitle: str,
    title_prompt: str,
    out_dir: Path,
) -> Path | None:
    """GPT 直出艺术字，失败即报错。"""
    if not main_title.strip():
        return None

    if not title_prompt:
        raise RuntimeError(
            f"[stage3] 艺术字 title_prompt 为空，无法生成"
        )

    return _generate_title_art_gpt(title_prompt, out_dir)


def _composite(
    bg_path: Path,
    layout_params: list[dict],
    title_path: Path | None,
    out_dir: Path,
) -> tuple[Path, Path]:
    """合成含文案 + 无文案两版终稿."""
    from PIL import Image

    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (CANVAS_W, CANVAS_H):
        bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)

    for lp in sorted(layout_params, key=lambda x: x["z_order"], reverse=True):
        rgba = lp.get("rgba_image")
        if rgba is None:
            p = lp.get("path")
            if p and Path(p).is_file():
                rgba = Image.open(p).convert("RGBA")
        if rgba is None:
            continue
        _paste_char(bg, rgba, lp)

    title_rgba = None
    if title_path and title_path.is_file():
        title_rgba = Image.open(title_path).convert("RGBA")

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 先存无文案版 ──
    final_nc = out_dir / "LZ顶部banner 3840x1200_无文案.jpg"
    bg_no_text = bg.copy()
    bg_no_text.convert("RGB").save(str(final_nc), "JPEG", quality=95)

    if title_rgba is not None:
        # ── banner-spec legend_top_banner_3840 文字填充区 ──
        TITLE_RECT = (1380, 2460, 607, 935)  # x_min, x_max, y_min, y_max
        TITLE_SCALE = 0.95
        rect_w = TITLE_RECT[1] - TITLE_RECT[0]
        rect_h = TITLE_RECT[3] - TITLE_RECT[2]
        tw, th = title_rgba.size
        if tw > 0 and th > 0:
            scale = min(1.0, rect_w * TITLE_SCALE / tw, rect_h * TITLE_SCALE / th)
            nw, nh = max(1, int(tw * scale)), max(1, int(th * scale))
            resized = title_rgba.resize((nw, nh), Image.Resampling.LANCZOS)
            tx = TITLE_RECT[0] + (rect_w - nw) // 2
            ty = TITLE_RECT[2] + (rect_h - nh) // 2
            print(f"[stage3/title] 贴图: x={tx} y={ty} size={nw}×{nh} rect={TITLE_RECT}", flush=True)
            bg.paste(resized, (tx, ty), resized)

    # ── 含文案版 ──
    final = out_dir / "LZ顶部banner 3840x1200.jpg"
    bg.convert("RGB").save(str(final), "JPEG", quality=95)

    composite = out_dir / "composite_0.png"
    bg.save(str(composite), "PNG")

    print(f"[stage3] 终稿: {final.name}", flush=True)
    return final, final_nc


def _paste_char(canvas, char_rgba, lp: dict):
    from PIL import Image

    cw, ch = char_rgba.size
    target_h = lp["height"]
    if ch < 1:
        return

    # alpha 紧裁：用实际人物高度做缩放基准，排除透明 padding
    bbox = char_rgba.split()[3].getbbox()
    if bbox:
        left, top, right, bottom = bbox
        char_cw = right - left
        char_ch = bottom - top
        if char_ch > 0:
            scale = target_h / float(char_ch)
            # 按 bbox 中心对齐
            char_center_x = (left + right) / 2.0
            char_bottom_y = float(bottom)
        else:
            scale = target_h / float(ch)
            char_center_x = cw / 2.0
            char_bottom_y = float(ch)
    else:
        scale = target_h / float(ch)
        char_center_x = cw / 2.0
        char_bottom_y = float(ch)

    for _ in range(14):
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        resized = char_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 按紧裁后的中心/底部对齐
        if lp.get("head_align_canvas_x") is not None:
            from scripts.hd.stage2_layout_prompt import VISUAL_CENTER_X
            cx = VISUAL_CENTER_X - char_center_x * scale + new_w // 2
            x = int(round(cx - new_w // 2))
        else:
            x = int(round(lp["x_center"] - char_center_x * scale))
        y = int(round(lp["y_bottom"] - char_bottom_y * scale))

        if x >= 0 and y >= 0 and x + new_w <= CANVAS_W and y + new_h <= CANVAS_H:
            canvas.paste(resized, (x, y), resized)
            return
        scale *= 0.995

    new_w = max(1, int(round(cw * scale)))
    new_h = max(1, int(round(ch * scale)))
    resized = char_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = int(round(lp["x_center"] - char_center_x * scale))
    y = int(round(lp["y_bottom"] - char_bottom_y * scale))
    src_x = max(0, -x)
    src_y = max(0, -y)
    dst_x = max(0, x)
    dst_y = max(0, y)
    src_w = min(new_w - src_x, CANVAS_W - dst_x)
    src_h = min(new_h - src_y, CANVAS_H - dst_y)
    if src_w > 0 and src_h > 0:
        patch = resized.crop((src_x, src_y, src_x + src_w, src_y + src_h))
        canvas.paste(patch, (dst_x, dst_y), patch)


def run_stage3(
    stage1_result: dict,
    stage2_result: dict,
    image_paths: list[Path],
    out_dir: Path,
    *,
    skip_cutout: bool = False,
    logo_path: Path | None = None,
) -> dict:
    """
    Stage 3：合成画面。后端配置从标准环境变量读取（BANNER_IMAGE_BACKEND / GEMINI_API_KEY / OPENAI_API_KEY）。

    Args:
        stage1_result: Stage 1 分析结果
        stage2_result: Stage 2 排版 + prompt
        image_paths: 原始输入图片
        out_dir: 输出目录
        logo_path: 可选 logo 图片路径，粘贴到 LOGO_RECT (1160,240) 450×120

    Returns:
        {"final": Path, "final_nc": Path, "background": Path}
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if skip_cutout:
        print("\n[stage3] === 跳过抠图（--skip-cutout），直接使用原图 ===", flush=True)
        cutouts = list(image_paths)
        print("\n[stage3] === 完整性检测+补齐 ===", flush=True)
        cutouts = _check_and_complete_cutouts(cutouts, out_dir)
    else:
        # 1. 抠图 / 免抠
        print("\n[stage3] === 抠图 ===", flush=True)
        cutouts = _run_cutouts(stage1_result, image_paths, out_dir)

        # 1b. 完整性检测 + 补齐 + 光源统一
        print("\n[stage3] === 完整性检测+补齐 ===", flush=True)
        cutouts = _check_and_complete_cutouts(cutouts, out_dir)

    # 2. 把 cutout 路径写入 layout_params
    for lp in stage2_result["layout_params"]:
        ci = lp["cutout_index"]
        if ci < len(cutouts):
            lp["path"] = str(cutouts[ci])
            lp["cutout_path"] = str(cutouts[ci])

    # 3. 背景生图
    print("\n[stage3] === 背景生图 ===", flush=True)
    bg_path = _generate_background(stage2_result["background_prompt"], out_dir)

    # 4. 光效统一
    print("\n[stage3] === 光效统一 ===", flush=True)
    style_block = stage2_result.get("style_block", "")
    layout_params = _relight_characters(cutouts, stage2_result["layout_params"], bg_path, out_dir, style_block)

    # 5. 艺术字
    title_path = None
    main_title = stage2_result.get("main_title", "")
    if main_title.strip():
        print("\n[stage3] === 艺术字 ===", flush=True)
        title_path = _generate_title_art(
            stage1_result["style"],
            main_title,
            stage2_result.get("subtitle", ""),
            stage2_result.get("title_art_prompt", ""),
            out_dir,
        )

    # 5.5 Logo 处理
    logo_ready = None
    if logo_path and logo_path.is_file():
        print("\n[stage3] === Logo ===", flush=True)
        logo_ready = _prepare_logo(logo_path, out_dir)

    # 6. 合成
    print("\n[stage3] === 合成 ===", flush=True)
    final, final_nc = _composite(bg_path, layout_params, title_path, out_dir)

    return {
        "final": final,
        "final_nc": final_nc,
        "bg_path": bg_path,
        "layout_params": layout_params,
    }
