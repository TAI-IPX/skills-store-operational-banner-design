#!/usr/bin/env python3
"""
将 LZ 顶栏艺术字素材规范为透明底 PNG，固定尺寸等于规范 title_art_rect 的宽×高（当前 1080×328）。

**推荐（独立大字图／即梦直出）：** `--crop-mode full` — **不截取**画布上的 `title_art_rect`、也不按字面 bbox 裁块；
整幅素材抠背后，将全部可见字与构图 **按比例缩小并居中装入** 1080×328（letterbox／contain）。
避免先把图硬拉到 3840×1200 再当作「LZ 底板」截取一片导致像截图。

流程（顺序固定：**先选定工作图（整块或裁一块），再抠图**）：
1）裁切策略：
   `full`：**整幅**参与抠背与缩放入 1080×328（主推独立艺术字）。
   若为完整 LZ 底板 ≥3840×1200（允许 ±2px）：`auto` — 先试规范 `title_art_rect`；
   若该区内亮字过少则改整幅 **字面 bbox**；`rect`：仅规范区；`smart`：仅整幅字面 bbox。
2）对 **上一步得到的子图** 去背（默认 --matte-mode auto）：
   - **auto**：若四边条带多为近黑像素（常见即梦「亮字 + 纯黑/近黑底」），**先近黑底抠除**；
     否则 **BiRefNet**；BiRefNet 前景像素过少时再试近黑底；再失败则「近白底阈值」；
   - 四角已近似透明 → 视为已抠图，跳过去背；
   - **dark**：仅近黑底抠除（适合深色纯色底霓虹/金属字）；
   - **birefnet**：仅 BiRefNet，不可用则报错；
   - **rembg**：用 rembg 库抠图（需 `pip install rembg`，另需模型权重）；
   - **white**：仅白底阈值（快、无_torch）；
3）按非透明 bbox 缩放居中放入画布 × title_art_fit_scale。

用法：
  python scripts/normalize_lz_title_art.py title_sheet.png -o out.png --crop-mode full --matte-mode hybrid
  python scripts/normalize_lz_title_art.py title_sheet.png -o out.png --matte-mode dark --dark-matte-threshold 58 --defringe-max-rgb 80
  python scripts/normalize_lz_title_art.py banner3840.png -o out.png --crop-mode auto
  python scripts/normalize_lz_title_art.py in3840.png -o out.png --crop-mode smart --matte-mode dark
  python scripts/normalize_lz_title_art.py in.png -o out.png --matte-mode white --matte-threshold 245
  python scripts/normalize_lz_title_art.py in.png -o out.png --matte-mode birefnet
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
_BIREFNET_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if _SPEC.is_dir() and str(_SPEC) not in sys.path:
    sys.path.insert(0, str(_SPEC))
if _BIREFNET_SCRIPTS.is_dir() and str(_BIREFNET_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BIREFNET_SCRIPTS))
import spec as _spec  # noqa: E402


def _sig_frac_bright_rgb(rgb_np, lum: int = 52) -> float:
    import numpy as np

    if rgb_np.size == 0:
        return 0.0
    return float((rgb_np.max(axis=2) > lum).mean())


def _tight_bbox_non_dark(
    rgb,
    *,
    lum: int = 48,
    pad: int = 20,
    min_fg_pixels: int = 600,
) :
    """亮于 lum 的像素 tight bbox；（left, top, right, bottom）为 PIL crop（右下为开区间）。"""
    import numpy as np

    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    m = rgb[:, :, :3].max(axis=2) > lum
    ys, xs = np.where(m)
    if ys.size < min_fg_pixels:
        return None
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    h, w = rgb.shape[0], rgb.shape[1]
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1_ex = min(w, x1 + 1 + pad)
    y1_ex = min(h, y1 + 1 + pad)
    if x1_ex <= x0 or y1_ex <= y0:
        return None
    return (x0, y0, x1_ex, y1_ex)


def _pick_working_patch_rgba(
    img_rgba,
    *,
    canvas_w: int,
    canvas_h: int,
    title_rect: tuple[int, int, int, int],
    crop_mode: str,
    rect_min_bright_frac: float = 0.0028,
    bbox_lum: int = 46,
    bbox_pad: int = 22,
):
    """从整图挑出一片 **仅用于后续抠背** 的子区域（先裁再走 BiRefNet/阈值等）。
    auto/smart 时可能在整幅上读 RGB 只做亮度 bbox，不会去背。"""
    from PIL import Image

    xmn, xmx, ymn, ymx = title_rect
    img = img_rgba.copy()
    w, h = img.size
    matched = abs(w - canvas_w) <= 2 and abs(h - canvas_h) <= 2

    def rect_patch(im: Image.Image) -> Image.Image:
        return im.crop((xmn, ymn, xmx, ymx)).convert("RGBA")

    cm = crop_mode.strip().lower()
    if cm not in ("auto", "rect", "smart", "full"):
        raise ValueError(f"未知 crop_mode: {crop_mode!r}")

    if cm == "full":
        print(
            "[normalize_lz_title_art] crop_mode=full：整幅图抠背并按可见内容缩放装入 1080×328（不裁 title_art_rect / 字面 bbox）",
            flush=True,
        )
        return img.convert("RGBA")

    if not matched:
        print(
            f"[normalize_lz_title_art] 输入非 {canvas_w}×{canvas_h}（实为 {w}×{h}），整块参与抠背",
            flush=True,
        )
        return img

    if img.size != (canvas_w, canvas_h):
        img = img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)

    def rect_only():
        return rect_patch(img)

    if cm == "rect":
        return rect_only()

    import numpy as np

    rgb_full = np.asarray(img.convert("RGB"))
    if cm == "smart":
        bb = _tight_bbox_non_dark(rgb_full, lum=bbox_lum, pad=bbox_pad)
        if bb:
            print("[normalize_lz_title_art] crop_mode=smart，整幅字面 bbox:", bb, flush=True)
            return img.crop(bb).convert("RGBA")
        print("[normalize_lz_title_art] crop_mode=smart 未检出足够前景，回退 title_art_rect", flush=True)
        return rect_only()

    # auto — 先看规范区信息量
    rp = rgb_full[ymn:ymx, xmn:xmx]
    frac_rect = _sig_frac_bright_rgb(rp, lum=54)
    if frac_rect >= rect_min_bright_frac:
        print(
            f"[normalize_lz_title_art] auto：规范区内亮像素占比 {frac_rect:.4f} ≥ {rect_min_bright_frac:.4f}，用 title_art_rect",
            flush=True,
        )
        return rect_only()

    bb = _tight_bbox_non_dark(rgb_full, lum=bbox_lum, pad=bbox_pad)
    if bb:
        x0, y0, xe, ye = bb
        inner = rgb_full[y0:ye, x0:xe]
        if inner.size > 0 and _sig_frac_bright_rgb(inner, lum=bbox_lum) >= rect_min_bright_frac * 0.25:
            print(
                f"[normalize_lz_title_art] auto：规范区过空（占比 {frac_rect:.4f}），改用整幅 bbox {bb}",
                flush=True,
            )
            return img.crop(bb).convert("RGBA")

    print(
        "[normalize_lz_title_art] auto：整幅也未检出大块前景，回退规范区裁切（请检查素材或换 crop-mode smart）",
        flush=True,
    )
    return rect_only()


def _corners_mostly_transparent(img_rgba, alpha_max: int = 48) -> bool:
    """四角 alpha 均较低时认为已是透明底素材，不必再跑模型/阈值。"""
    w, h = img_rgba.size
    if w < 2 or h < 2:
        return False
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if img_rgba.getpixel(xy)[3] > alpha_max:
            return False
    return True

def _apply_white_matte_rgba(img_rgba, threshold: int = 240):
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgba.convert("RGBA"))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    white_mask = (r >= threshold) & (g >= threshold) & (b >= threshold)
    arr[:, :, 3][white_mask] = 0
    return Image.fromarray(arr).convert("RGBA")


def _apply_dark_matte_rgba(
    img_rgba,
    threshold: int,
    *,
    soft_span: int = 32,
    hard: bool = False,
):
    """
    近黑/纯黑底抠除。默认 soft：按 max(R,G,B) 软过渡 alpha，减轻金属字边缘锯齿与灰边。
    hard=True 时恢复旧逻辑（三通道均≤T 即全透明，易留黑边或吃字）。
    """
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgba.convert("RGBA"))
    if hard:
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        dark = (r <= threshold) & (g <= threshold) & (b <= threshold)
        arr[:, :, 3] = np.where(dark, 0, 255)
        return Image.fromarray(arr, "RGBA")

    mx = arr[:, :, :3].max(axis=2).astype(np.float32)
    t0 = float(threshold)
    t1 = t0 + max(4, int(soft_span))
    alpha = (mx - t0) / (t1 - t0) * 255.0
    arr[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _defringe_dark_rgba(img_rgba, *, max_rgb: int = 72, edge_rgb: int = 88) -> "Image.Image":
    """去掉仍带 alpha 的近黑/灰边像素，减轻「抠不干净」的黑底残留。"""
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgba.convert("RGBA"))
    mx = arr[:, :, :3].max(axis=2)
    a = arr[:, :, 3].astype(np.float32)
    # 明显是底色的不透明/半透明像素 → 全透明
    kill = (a > 6) & (mx <= max_rgb)
    arr[kill, 3] = 0
    # 边缘半透明且偏暗 → 按亮度压低 alpha
    edge = (arr[:, :, 3] > 0) & (arr[:, :, 3] < 252) & (mx <= edge_rgb)
    if edge.any():
        scale = np.clip(mx[edge].astype(np.float32) / float(edge_rgb + 1), 0, 1)
        arr[edge, 3] = np.minimum(arr[edge, 3], (scale * 255).astype(np.uint8))
    return Image.fromarray(arr, "RGBA")


def _defringe_title_edge_only(
    img_rgba,
    *,
    max_rgb: int = 24,
    edge_rgb: int = 40,
    edge_band: int = 4,
) -> "Image.Image":
    """艺术字透明底：仅清外缘/轮廓带内的近黑残留，保留字芯深色填充。"""
    import numpy as np
    from PIL import Image, ImageFilter

    arr = np.array(img_rgba.convert("RGBA"))
    fg = arr[:, :, 3] > 32
    if not fg.any():
        return img_rgba

    band = max(2, int(edge_band))
    k = band * 2 + 1
    fg_u8 = (fg.astype(np.uint8) * 255)
    pil_fg = Image.fromarray(fg_u8, mode="L")
    dilated = np.array(pil_fg.filter(ImageFilter.MaxFilter(k))) > 127
    eroded = np.array(pil_fg.filter(ImageFilter.MinFilter(k))) > 127
    edge_zone = dilated & ~eroded
    outer = dilated & ~fg

    mx = arr[:, :, :3].max(axis=2)
    kill = (outer | edge_zone) & (arr[:, :, 3] > 6) & (mx <= max_rgb)
    arr[kill, 3] = 0

    fringe = edge_zone & (arr[:, :, 3] > 0) & (arr[:, :, 3] < 252) & (mx <= edge_rgb)
    if fringe.any():
        scale = np.clip(mx[fringe].astype(np.float32) / float(edge_rgb + 1), 0, 1)
        arr[fringe, 3] = np.minimum(arr[fringe, 3], (scale * 255).astype(np.uint8))

    return Image.fromarray(arr, "RGBA")


def _repair_hollow_title_glyphs(img_rgba, *, split_ratio: float | None = None) -> "Image.Image":
    """主标题带内：形态学闭运算填小孔，避免 MICU/defringe 造成的字芯镂空。"""
    import cv2
    import numpy as np
    from PIL import Image

    from scripts.hd.title_art_fx import _split_main_subtitle_masks

    if split_ratio is None:
        try:
            split_ratio = float(os.environ.get("LZ_MICU_TITLE_SUB_SPLIT", "0.62"))
        except ValueError:
            split_ratio = 0.62

    arr = np.array(img_rgba.convert("RGBA"))
    alpha = arr[:, :, 3].astype(np.float32)
    main_mask, _ = _split_main_subtitle_masks(alpha, split_ratio=split_ratio)
    if main_mask is None or not main_mask.any():
        return img_rgba

    fg = main_mask & (alpha > 40)
    if int(fg.sum()) < 32:
        return img_rgba

    fg_u8 = fg.astype(np.uint8) * 255
    closed = cv2.morphologyEx(fg_u8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    holes = (closed > 127) & ~fg & main_mask
    if not int(holes.sum()):
        return img_rgba

    rgb = arr[:, :, :3].astype(np.float32)
    dilated = cv2.dilate(fg_u8, np.ones((7, 7), np.uint8)) > 127
    ring = dilated & ~fg & main_mask
    if ring.any():
        med = np.median(rgb[ring], axis=0)
    else:
        med = np.median(rgb[fg], axis=0)

    arr[holes, :3] = np.clip(med, 0, 255).astype(np.uint8)
    arr[holes, 3] = 255
    print(f"[lz_micu/title] 镂空修复: 填充 {int(holes.sum())} px", flush=True)
    return Image.fromarray(arr, "RGBA")


def _title_matte_bg_margin() -> int:
    return _title_matte_env_int("LZ_MICU_TITLE_MATTE_BG_MARGIN", 0)


def _title_matte_br_fg_min() -> int:
    return _title_matte_env_int("LZ_MICU_TITLE_MATTE_BR_FG_MIN", 32)


def matte_hollow_repair_enabled() -> bool:
    return os.environ.get("LZ_MICU_TITLE_MATTE_HOLLOW_REPAIR", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _merge_dark_and_birefnet_alpha(
    img_rgb,
    dark_rgba,
    birefnet_rgba,
    *,
    dark_threshold: int,
    bg_margin: int | None = None,
    br_fg_min: int | None = None,
):
    """黑底艺术字：近黑软抠与 BiRefNet 取 max；仅清 BiRefNet 也判背景的真黑底，保留字内 3D 阴影。"""
    import numpy as np
    from PIL import Image

    if bg_margin is None:
        bg_margin = _title_matte_bg_margin()
    if br_fg_min is None:
        br_fg_min = _title_matte_br_fg_min()

    mx = np.array(img_rgb.convert("RGB")).max(axis=2)
    ad = np.array(dark_rgba.split()[-1], dtype=np.float32)
    ab = np.array(birefnet_rgba.split()[-1], dtype=np.float32)
    merged = np.maximum(ad, ab)
    near_black = mx <= (dark_threshold + bg_margin)
    kill = near_black & (ab < float(br_fg_min))
    kept_dark_fg = int((near_black & (ab >= float(br_fg_min)) & (merged > 0)).sum())
    cleared_bg = int(kill.sum())
    merged[kill] = 0
    print(
        f"[normalize_lz_title_art] hybrid 合并: 保留 BiRefNet 暗前景≈{kept_dark_fg}px "
        f"清除真黑底≈{cleared_bg}px (T={dark_threshold}+margin={bg_margin}, br_fg≥{br_fg_min})",
        flush=True,
    )
    out = img_rgb.convert("RGBA")
    out.putalpha(Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8), mode="L"))
    return out


def _apply_light_matte_rgba(
    img_rgba,
    threshold: int = 240,
    *,
    soft_span: int = 28,
    hard: bool = False,
):
    """白/近白底抠除，保留深色字形（白底黑字）。"""
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgba.convert("RGBA"))
    mx = arr[:, :, :3].max(axis=2).astype(np.float32)
    if hard:
        bright = mx >= float(threshold)
        arr[:, :, 3] = np.where(bright, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, "RGBA")

    t1 = float(threshold)
    t0 = t1 - max(4, int(soft_span))
    alpha = (t1 - mx) / max(1.0, t1 - t0) * 255.0
    arr[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _defringe_light_rgba(img_rgba, *, min_rgb: int = 200, edge_rgb: int = 185) -> "Image.Image":
    """去掉仍带 alpha 的近白底残留（白底黑字抠图后）。"""
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgba.convert("RGBA"))
    mx = arr[:, :, :3].max(axis=2)
    a = arr[:, :, 3].astype(np.float32)
    kill = (a > 6) & (mx >= min_rgb)
    arr[kill, 3] = 0
    edge = (arr[:, :, 3] > 0) & (arr[:, :, 3] < 252) & (mx >= edge_rgb)
    if edge.any():
        scale = np.clip((255.0 - mx[edge].astype(np.float32)) / float(255 - edge_rgb + 1), 0, 1)
        arr[edge, 3] = np.minimum(arr[edge, 3], (scale * 255).astype(np.uint8))
    return Image.fromarray(arr, "RGBA")


def _merge_white_and_birefnet_alpha(
    img_rgb,
    light_rgba,
    birefnet_rgba,
    *,
    light_threshold: int = 240,
    bg_margin: int = 8,
):
    """白底艺术字：亮部强制透明，暗部取 light 与 BiRefNet alpha 的较大值。"""
    import numpy as np
    from PIL import Image

    mx = np.array(img_rgb.convert("RGB")).max(axis=2)
    al = np.array(light_rgba.split()[-1], dtype=np.float32)
    ab = np.array(birefnet_rgba.split()[-1], dtype=np.float32)
    merged = np.maximum(al, ab)
    bg = mx >= (light_threshold - bg_margin)
    merged[bg] = 0
    out = img_rgb.convert("RGBA")
    out.putalpha(Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8), mode="L"))
    return out


def _detect_title_plate_type(img_rgb) -> str:
    """dark=黑底白字/light=白底黑字/unknown。"""
    border_dark = _border_dark_fraction(img_rgb)
    border_bright = _border_bright_fraction(img_rgb)
    if border_dark >= 0.42 and border_dark >= border_bright + 0.12:
        return "dark"
    if border_bright >= 0.42 and border_bright >= border_dark + 0.12:
        return "light"
    if border_dark >= 0.55:
        return "dark"
    if border_bright >= 0.55:
        return "light"
    return "unknown"


def _score_title_matte_result(
    out_rgba,
    *,
    plate: str,
    canvas_w: int,
    canvas_h: int,
    min_fg: int,
) -> float:
    """抠字质量评分：前景量 + 覆盖合理 + 明度符合底稿类型。"""
    import numpy as np

    n = _foreground_pixel_count(out_rgba)
    if n < max(64, min_fg // 4):
        return -1.0
    bbox = _alpha_bbox(out_rgba)
    if not bbox:
        return -1.0
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    cover = (bw * bh) / max(1, canvas_w * canvas_h)
    if cover > 0.94 or cover < 0.015:
        return -1.0

    arr = np.array(out_rgba.convert("RGBA"))
    fg = arr[:, :, 3] > 32
    if not fg.any():
        return -1.0
    lum = float(arr[fg, :3].max(axis=1).mean())

    base = float(n)
    if plate == "dark":
        if lum < 72:
            return base * 0.25
        return base * (0.55 + 0.45 * min(1.0, lum / 220.0))
    if plate == "light":
        if lum > 210:
            return base * 0.25
        return base * (0.55 + 0.45 * min(1.0, (200.0 - lum) / 180.0))
    contrast = abs(lum - 128.0) / 128.0
    return base * (0.45 + 0.55 * contrast)


def _foreground_pixel_count(img_rgba, alpha_min: int = 8) -> int:
    import numpy as np

    a = np.array(img_rgba.split()[-1], dtype=np.uint8)
    return int((a > alpha_min).sum())


def _border_dark_fraction(img_rgb, *, strip_px: int = 4, dark_rgb_max: int = 48) -> float:
    """四边窄条里 max(R,G,B)≤dark_rgb_max 的像素占比；高表示多为纯黑/近黑边（标题区裁切后常见）。"""
    import numpy as np
    from PIL import Image

    arr = np.array(img_rgb.convert("RGB"))
    h, w = arr.shape[:2]
    sp = max(1, min(strip_px, w // 8, h // 8))
    top = arr[:sp, :].reshape(-1, 3)
    bot = arr[-sp:, :].reshape(-1, 3)
    mid_r = arr[sp : h - sp, :]
    left = mid_r[:, :sp].reshape(-1, 3)
    right = mid_r[:, -sp:].reshape(-1, 3)
    px = np.concatenate([top, bot, left, right], axis=0)
    if px.size == 0:
        return 0.0
    mx = px.max(axis=1)
    return float((mx <= dark_rgb_max).mean())


def _apply_birefnet_matte(img_rgb, *, alpha_threshold: float | None = None):
    """
    BiRefNet-matting 自动识别前景，输出 RGBA。
    alpha_threshold：None 保留柔和连续 alpha；0~1 时二值化（更干净边缘，可能锯齿）。
    """
    import numpy as np
    from PIL import Image

    from birefnet_matting import load_birefnet_matting, extract_alpha_pil

    model = load_birefnet_matting()
    alpha = extract_alpha_pil(img_rgb.convert("RGB"), model=model)

    if alpha_threshold is not None:
        thr = float(alpha_threshold)
        a_arr = np.array(alpha, dtype=np.float32) / 255.0
        a_arr = (a_arr >= thr).astype(np.uint8) * 255
        alpha = Image.fromarray(a_arr, mode="L")

    out = img_rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _apply_rembg_matte(img_rgba):
    from io import BytesIO

    try:
        from rembg import remove  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "未安装 rembg。请执行: pip install rembg"
        ) from e
    from PIL import Image

    buf = BytesIO()
    img_rgba.convert("RGB").save(buf, format="PNG")
    raw = remove(buf.getvalue())
    return Image.open(BytesIO(raw)).convert("RGBA")


def _title_matte_defringe_mode() -> str:
    """off=关, full=全局 defringe, edge=仅外缘去黑边（保字芯深色）。"""
    raw = os.environ.get("LZ_MICU_TITLE_DEFRINGE", "edge").strip().lower()
    if raw in ("0", "false", "no", "off", "none"):
        return "off"
    if raw in ("1", "true", "yes", "on", "full", "global"):
        return "full"
    return "edge"


def _title_matte_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _title_matte_env_float_or_none(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _finish_matte(
    img_rgba,
    *,
    defringe: bool,
    defringe_max_rgb: int,
    defringe_mode: str = "full",
    label: str = "",
) :
    if not defringe or defringe_mode == "off":
        return img_rgba
    if defringe_mode == "edge":
        edge_rgb = min(255, defringe_max_rgb + 12)
        img_rgba = _defringe_title_edge_only(
            img_rgba, max_rgb=defringe_max_rgb, edge_rgb=edge_rgb
        )
        tag = f"{label} " if label else ""
        print(
            f"[normalize_lz_title_art] {tag}defringe=edge-only（max_rgb≤{defringe_max_rgb}）",
            flush=True,
        )
    else:
        img_rgba = _defringe_dark_rgba(img_rgba, max_rgb=defringe_max_rgb)
        if label:
            print(
                f"[normalize_lz_title_art] {label} 已做去黑边/灰边（defringe≤{defringe_max_rgb}）",
                flush=True,
            )
    return img_rgba


def _remove_background(
    img_rgba,
    *,
    matte_mode: str,
    matte_threshold: int,
    dark_matte_threshold: int,
    dark_matte_soft_span: int,
    defringe: bool,
    defringe_max_rgb: int,
    defringe_mode: str = "full",
    dark_matte_hard: bool,
    skip_matte: bool,
    birefnet_alpha_threshold: float | None,
) :
    """返回处理后的 RGBA。"""
    from PIL import Image

    if skip_matte:
        return img_rgba

    if matte_mode not in ("auto", "hybrid", "hybrid_white", "birefnet", "white", "dark", "rembg"):
        raise ValueError(f"未知 matte_mode: {matte_mode!r}")

    if _corners_mostly_transparent(img_rgba):
        print("[normalize_lz_title_art] 检测到透明四角，跳过自动抠背", flush=True)
        return img_rgba

    rgb = img_rgba.convert("RGB")
    border_dark = _border_dark_fraction(rgb)
    border_bright = _border_bright_fraction(rgb)

    if matte_mode == "white":
        out = _apply_white_matte_rgba(img_rgba, matte_threshold)
        return _finish_matte(out, defringe=False, defringe_max_rgb=defringe_max_rgb)

    if matte_mode == "dark":
        print(
            f"[normalize_lz_title_art] 近黑底软抠（T={dark_matte_threshold}, soft={dark_matte_soft_span}）...",
            flush=True,
        )
        out = _apply_dark_matte_rgba(
            img_rgba,
            dark_matte_threshold,
            soft_span=dark_matte_soft_span,
            hard=dark_matte_hard,
        )
        return _finish_matte(
            out, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )

    if matte_mode == "hybrid":
        print(
            f"[normalize_lz_title_art] hybrid：近黑软抠 + defringe + BiRefNet 合并（T={dark_matte_threshold}）...",
            flush=True,
        )
        dm = _apply_dark_matte_rgba(
            img_rgba,
            dark_matte_threshold,
            soft_span=dark_matte_soft_span,
            hard=dark_matte_hard,
        )
        dm = _finish_matte(
            dm, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )
        try:
            br = _apply_birefnet_matte(rgb, alpha_threshold=birefnet_alpha_threshold)
            out = _merge_dark_and_birefnet_alpha(
                rgb, dm, br, dark_threshold=dark_matte_threshold
            )
            return _finish_matte(
                out,
                defringe=defringe,
                defringe_max_rgb=defringe_max_rgb,
                defringe_mode=defringe_mode,
                label="",
            )
        except Exception as e:
            msg = str(e).split("\n")[0][:160]
            print(f"[normalize_lz_title_art] hybrid BiRefNet 不可用，仅用近黑软抠: {msg}", flush=True)
            return dm

    if matte_mode == "hybrid_white":
        light_thr = max(200, int(matte_threshold))
        print(
            f"[normalize_lz_title_art] hybrid_white：近白软抠 + BiRefNet 合并（T={light_thr}）...",
            flush=True,
        )
        lm = _apply_light_matte_rgba(img_rgba, light_thr, soft_span=dark_matte_soft_span)
        lm = _defringe_light_rgba(lm)
        try:
            br = _apply_birefnet_matte(rgb, alpha_threshold=birefnet_alpha_threshold)
            out = _merge_white_and_birefnet_alpha(
                rgb, lm, br, light_threshold=light_thr
            )
            return _defringe_light_rgba(out)
        except Exception as e:
            msg = str(e).split("\n")[0][:160]
            print(f"[normalize_lz_title_art] hybrid_white BiRefNet 不可用，仅用近白软抠: {msg}", flush=True)
            return lm

    if matte_mode == "birefnet":
        print("[normalize_lz_title_art] BiRefNet 语义抠图...", flush=True)
        out = _apply_birefnet_matte(rgb, alpha_threshold=birefnet_alpha_threshold)
        return _finish_matte(
            out, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )

    if matte_mode == "rembg":
        print("[normalize_lz_title_art] rembg 抠图...", flush=True)
        out = _apply_rembg_matte(img_rgba)
        return _finish_matte(
            out, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )

    # ----- auto -----
    min_fg = max(400, int(0.0008 * rgb.size[0] * rgb.size[1]))

    def _try_dark(label: str) -> tuple:
        dm = _apply_dark_matte_rgba(
            img_rgba,
            dark_matte_threshold,
            soft_span=dark_matte_soft_span,
            hard=dark_matte_hard,
        )
        dm = _finish_matte(
            dm, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )
        n = _foreground_pixel_count(dm)
        print(
            f"[normalize_lz_title_art] {label} 近黑底软抠，前景像素≈{n}（边带暗占比 {border_dark:.2f}）",
            flush=True,
        )
        return dm, n

    best_img = None
    best_n = -1

    if border_dark >= 0.78:
        dm, n = _try_dark("优先")
        if n >= min_fg:
            return dm
        best_img, best_n = dm, n

    try:
        print("[normalize_lz_title_art] BiRefNet 语义抠图（auto）...", flush=True)
        br = _apply_birefnet_matte(rgb, alpha_threshold=birefnet_alpha_threshold)
        if border_dark >= 0.55:
            dm, _ = _try_dark("auto 合并前")
            br = _merge_dark_and_birefnet_alpha(
                rgb, dm, br, dark_threshold=dark_matte_threshold
            )
        br = _finish_matte(
            br, defringe=defringe, defringe_max_rgb=defringe_max_rgb, defringe_mode=defringe_mode
        )
        n_br = _foreground_pixel_count(br)
        print(f"[normalize_lz_title_art] BiRefNet 前景像素≈{n_br}", flush=True)
        if n_br >= min_fg and n_br >= best_n:
            return br
        if n_br < min_fg and border_dark >= 0.55:
            dm, n_dm = _try_dark("BiRefNet 前景不足，试近黑底")
            if n_dm > n_br and (n_dm >= min_fg or n_dm > max(n_br, best_n)):
                return dm
        if border_dark >= 0.72:
            dm, n_dm = _try_dark("BiRefNet 前景不足，二次近黑底")
            if n_dm >= min_fg or n_dm > n_br:
                return dm
        if best_img is not None and best_n > n_br:
            return best_img
        if n_br < min_fg:
            wm = _apply_white_matte_rgba(img_rgba, matte_threshold)
            n_wm = _foreground_pixel_count(wm)
            if n_wm > n_br:
                print("[normalize_lz_title_art] BiRefNet 过空，改用白底阈值兜底", flush=True)
                return wm
        return br
    except Exception as e:
        msg = str(e).split("\n")[0][:200]
        print(
            f"[normalize_lz_title_art] BiRefNet 不可用: {msg}",
            flush=True,
        )
        if border_dark >= 0.55:
            dm, n_dm = _try_dark("BiRefNet 异常后")
            if n_dm >= min_fg or best_img is None:
                return dm
        if best_img is not None:
            print("[normalize_lz_title_art] 使用先前近黑底结果", flush=True)
            return best_img
        print("[normalize_lz_title_art] 改用白底阈值", flush=True)
        return _apply_white_matte_rgba(img_rgba, matte_threshold)


def _alpha_bbox(img_rgba):
    a = img_rgba.split()[-1]
    return a.getbbox()


def _fit_alpha_threshold() -> int:
    raw = os.environ.get("LZ_TITLE_ART_FIT_ALPHA", "16").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 16


def _fit_safe_margin_px() -> int:
    raw = os.environ.get("LZ_TITLE_ART_FIT_MARGIN_PX", "0").strip()
    try:
        return max(0, min(24, int(raw)))
    except ValueError:
        return 0


def _dilate_bool_mask(mask) -> "np.ndarray":
    """1px 膨胀，纳入火焰/霓虹尖角。"""
    import numpy as np

    m = np.asarray(mask, dtype=bool)
    h, w = m.shape
    padded = np.pad(m, 1, mode="constant", constant_values=False)
    out = np.zeros((h, w), dtype=bool)
    for dy in range(3):
        for dx in range(3):
            out |= padded[dy : dy + h, dx : dx + w]
    return out


def _fit_alpha_bbox(img_rgba, min_alpha: int | None = None) -> tuple[int, int, int, int] | None:
    """fit 用 bbox；默认 alpha>=16 含 glow，轻度膨胀后取框。"""
    if min_alpha is None:
        min_alpha = _fit_alpha_threshold()
    if min_alpha <= 0:
        return _alpha_bbox(img_rgba)
    import numpy as np

    a = np.array(img_rgba.split()[-1])
    core = a >= min_alpha
    if not core.any():
        return _alpha_bbox(img_rgba)
    mask = _dilate_bool_mask(core)
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _log_fit_result(
    *,
    bb: tuple[int, int, int, int],
    scale: float,
    content_w: int,
    content_h: int,
    canvas_w: int,
    canvas_h: int,
    paste_x: int,
    paste_y: int,
    fit_scale: float,
) -> None:
    bbox_w = bb[2] - bb[0]
    bbox_h = bb[3] - bb[1]
    min_alpha = _fit_alpha_threshold()
    bbox_label = "decor_bbox" if min_alpha > 0 else "bbox"
    margin_t = paste_y
    margin_b = canvas_h - content_h - paste_y
    margin_l = paste_x
    margin_r = canvas_w - content_w - paste_x
    safe_m = _fit_safe_margin_px()
    print(
        f"[fit] {bbox_label}={bbox_w}×{bbox_h} scale={scale:.3f} → "
        f"content={content_w}×{content_h} fit_scale={fit_scale:.2f} "
        f"safe_margin={safe_m}px margins T={margin_t} B={margin_b} L={margin_l} R={margin_r}",
        flush=True,
    )


def normalize_lz_title_art_png(
    src: Path | str,
    dst: Path | str,
    *,
    preset: str = "legend_top_banner_3840",
    crop_mode: str = "full",
    matte_mode: str = "hybrid",
    matte_threshold: int = 240,
    dark_matte_threshold: int = 52,
    dark_matte_soft_span: int = 32,
    defringe: bool = True,
    defringe_max_rgb: int = 72,
    dark_matte_hard: bool = False,
    skip_matte: bool = False,
    birefnet_alpha_threshold: float | None = None,
    fit_scale_override: float | None = None,
) -> Path:
    """
    读出 src：**① 选工作图（full=整幅）→ ② 抠背** → ③ 可见内容 contain 缩放居中写入 1080×328，写入 dst。
    """
    from PIL import Image

    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise FileNotFoundError(src)

    cw, ch = _spec.PRESETS[preset]
    layout = _spec.get_layout(cw, ch, preset)
    rect = layout.get("title_art_rect")
    if not rect:
        raise ValueError(f"preset {preset!r} 无 title_art_rect")
    x_min, x_max, y_min, y_max = rect
    tw = max(1, x_max - x_min)
    th = max(1, y_max - y_min)
    fit_scale = float(fit_scale_override if fit_scale_override is not None else layout.get("title_art_fit_scale", 1.0))
    fit_scale = max(0.5, min(1.0, fit_scale))
    max_w = max(1, int(round(tw * fit_scale)))
    max_h = max(1, int(round(th * fit_scale)))

    img_full = Image.open(src).convert("RGBA")
    img = _pick_working_patch_rgba(
        img_full,
        canvas_w=cw,
        canvas_h=ch,
        title_rect=(x_min, x_max, y_min, y_max),
        crop_mode=crop_mode,
    )
    cw0, ch0 = img.size
    step1 = (
        f"工作图 {cw0}×{ch0}（crop_mode=full，无裁切）"
        if crop_mode.strip().lower() == "full"
        else f"裁切完成 {cw0}×{ch0}"
    )
    print(
        f"[normalize_lz_title_art] 步骤① {step1} → 步骤② 抠背（matte_mode={matte_mode}）",
        flush=True,
    )

    img = _remove_background(
        img,
        matte_mode=matte_mode,
        matte_threshold=matte_threshold,
        dark_matte_threshold=dark_matte_threshold,
        dark_matte_soft_span=dark_matte_soft_span,
        defringe=defringe,
        defringe_max_rgb=defringe_max_rgb,
        dark_matte_hard=dark_matte_hard,
        skip_matte=skip_matte,
        birefnet_alpha_threshold=birefnet_alpha_threshold,
    )

    bb = _fit_alpha_bbox(img)
    if not bb:
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(dst), "PNG")
        print(f"[normalize_lz_title_art] 无可见内容，已写入空画布: {dst} {tw}×{th}", flush=True)
        return dst

    patch = img.crop(bb)
    pw, ph = patch.size
    scale = min(max_w / pw, max_h / ph)
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    patch = patch.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    px = (tw - nw) // 2
    py = (th - nh) // 2
    canvas.paste(patch, (px, py), patch)
    _log_fit_result(
        bb=bb,
        scale=scale,
        content_w=nw,
        content_h=nh,
        canvas_w=tw,
        canvas_h=th,
        paste_x=px,
        paste_y=py,
        fit_scale=fit_scale,
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(dst), "PNG")
    print(
        f"[normalize_lz_title_art] {src.name} → {dst.name} {tw}×{th} "
        f"content={nw}×{nh} fit_scale={fit_scale:.2f} "
        f"(crop_mode={crop_mode}, matte_mode={matte_mode})",
        flush=True,
    )
    return dst


def _title_matte_min_fg(w: int, h: int) -> int:
    return max(400, int(0.0008 * w * h))


def _pick_title_matte_mode(img_rgb, requested: str | None) -> str:
    """auto（默认）自动识别黑底/白底；也可强制 hybrid / hybrid_white / birefnet 等。"""
    import os

    mode = (requested or os.environ.get("LZ_MICU_TITLE_MATTE_MODE", "auto")).strip().lower()
    valid = ("auto", "hybrid", "hybrid_white", "dark", "birefnet", "white")
    if mode not in valid:
        mode = "auto"
    if mode != "auto":
        return mode

    plate = _detect_title_plate_type(img_rgb)
    if plate == "dark":
        return "hybrid"
    if plate == "light":
        return "hybrid_white"
    return "auto"


def _title_matte_candidate_modes(plate: str, primary: str) -> list[str]:
    """按底稿类型排列抠字模式尝试顺序。"""
    if primary != "auto":
        if plate == "dark":
            pool = [primary, "hybrid", "dark", "auto", "birefnet"]
        elif plate == "light":
            pool = [primary, "hybrid_white", "birefnet", "white", "auto"]
        else:
            pool = [primary, "hybrid", "hybrid_white", "birefnet", "dark", "white", "auto"]
    elif plate == "dark":
        pool = ["hybrid", "dark", "auto", "birefnet", "hybrid_white"]
    elif plate == "light":
        pool = ["hybrid_white", "birefnet", "white", "auto", "hybrid"]
    else:
        pool = ["hybrid", "hybrid_white", "birefnet", "auto", "dark", "white"]
    out: list[str] = []
    for m in pool:
        if m not in out:
            out.append(m)
    return out


def _border_bright_fraction(img_rgb, *, strip_px: int = 4, bright_rgb_min: int = 210) -> float:
    """四边窄条里 max(R,G,B)≥bright_rgb_min 的像素占比；高表示多为白底。"""
    import numpy as np

    arr = np.array(img_rgb.convert("RGB"))
    h, w = arr.shape[:2]
    sp = max(1, min(strip_px, w // 8, h // 8))
    top = arr[:sp, :].reshape(-1, 3)
    bot = arr[-sp:, :].reshape(-1, 3)
    mid_r = arr[sp : h - sp, :]
    left = mid_r[:, :sp].reshape(-1, 3)
    right = mid_r[:, -sp:].reshape(-1, 3)
    px = np.concatenate([top, bot, left, right], axis=0)
    if px.size == 0:
        return 0.0
    mx = px.max(axis=1)
    return float((mx >= bright_rgb_min).mean())


def _matte_edge_soften(img_rgba):
    """抠字后柔化 alpha 外缘，减轻 BiRefNet 锯齿。"""
    try:
        from scripts.hd.title_art_fx import soften_title_rgba_edges

        return soften_title_rgba_edges(img_rgba)
    except Exception:
        return img_rgba


def normalize_glyph_rgba(img_rgba, *, alpha_threshold: int = 32):
    """
    glyph Step1 后处理：保留艺术 alpha 轮廓，RGB 规范为纯黑/深灰。
    透明底直读，跳过 BiRefNet。
    """
    from PIL import Image
    import numpy as np

    from scripts.hd.title_art_fx import _split_main_subtitle_masks

    if not isinstance(img_rgba, Image.Image):
        img_rgba = Image.open(img_rgba).convert("RGBA")
    else:
        img_rgba = img_rgba.convert("RGBA")

    if _corners_mostly_transparent(img_rgba):
        print("[normalize_lz_title_art] glyph 透明底直读，规范 RGB 为纯黑", flush=True)
    else:
        print("[normalize_lz_title_art] glyph 无透明四角，仍规范 RGB（保留 alpha）", flush=True)

    arr = np.array(img_rgba, dtype=np.uint8)
    alpha = arr[:, :, 3].astype(np.float32)
    fg = alpha > alpha_threshold
    if not fg.any():
        return img_rgba

    try:
        split_ratio = float(os.environ.get("LZ_MICU_TITLE_SUB_SPLIT", "0.62"))
    except ValueError:
        split_ratio = 0.62
    main_mask, sub_mask = _split_main_subtitle_masks(alpha, split_ratio=split_ratio)
    if sub_mask is None or not sub_mask.any():
        sub_mask = np.zeros_like(fg, dtype=bool)

    arr[fg, 0] = 0
    arr[fg, 1] = 0
    arr[fg, 2] = 0
    if sub_mask.any():
        arr[sub_mask, 0] = 51
        arr[sub_mask, 1] = 51
        arr[sub_mask, 2] = 51

    out = Image.fromarray(arr, "RGBA")
    return _matte_edge_soften(out)


def title_art_matte_rgba(
    img_rgba,
    *,
    matte_mode: str | None = None,
    defringe: bool = True,
    defringe_max_rgb: int = 72,
    dark_matte_threshold: int = 58,
    dark_matte_soft_span: int = 32,
    birefnet_alpha_threshold: float | None = None,
):
    """
    Step 2：艺术字抠字（黑底白字 / 白底黑字自适应）。
    - 黑底：hybrid（近黑软抠 + BiRefNet）
    - 白底：hybrid_white（近白软抠 + BiRefNet）
    - 多模式评分，确保字形抠出
    """
    from PIL import Image

    dark_matte_threshold = _title_matte_env_int(
        "LZ_MICU_TITLE_DARK_MATTE_THRESHOLD", dark_matte_threshold
    )
    dark_matte_soft_span = _title_matte_env_int(
        "LZ_MICU_TITLE_DARK_MATTE_SOFT_SPAN", dark_matte_soft_span
    )
    defringe_mode = _title_matte_defringe_mode()
    defringe = defringe and defringe_mode != "off"
    defringe_max_rgb = _title_matte_env_int(
        "LZ_MICU_TITLE_DEFRINGE_MAX_RGB",
        28 if defringe_max_rgb == 72 else defringe_max_rgb,
    )
    env_biref_thr = _title_matte_env_float_or_none("LZ_MICU_TITLE_BIREFNET_ALPHA_THRESHOLD")
    if env_biref_thr is not None:
        birefnet_alpha_threshold = env_biref_thr

    if not isinstance(img_rgba, Image.Image):
        img_rgba = Image.open(img_rgba).convert("RGBA")
    else:
        img_rgba = img_rgba.convert("RGBA")

    if _corners_mostly_transparent(img_rgba):
        print("[normalize_lz_title_art] 四角已透明，跳过抠字", flush=True)
        return _matte_edge_soften(img_rgba)

    rgb = img_rgba.convert("RGB")
    w, h = rgb.size
    min_fg = _title_matte_min_fg(w, h)
    plate = _detect_title_plate_type(rgb)
    plate_label = {"dark": "黑底白字", "light": "白底黑字", "unknown": "未知底稿"}.get(plate, plate)
    primary = _pick_title_matte_mode(rgb, matte_mode)
    modes = _title_matte_candidate_modes(plate, primary)

    print(
        f"[normalize_lz_title_art] 艺术字抠字 底稿={plate_label} primary={primary} "
        f"尝试={','.join(modes)}",
        flush=True,
    )

    best = img_rgba
    best_score = -1.0
    best_mode = ""
    best_n = 0

    for mode in modes:
        print(f"[normalize_lz_title_art] 艺术字抠字 mode={mode}...", flush=True)
        try:
            out = _remove_background(
                img_rgba,
                matte_mode=mode,
                matte_threshold=240,
                dark_matte_threshold=dark_matte_threshold,
                dark_matte_soft_span=dark_matte_soft_span,
                defringe=defringe,
                defringe_max_rgb=defringe_max_rgb,
                defringe_mode=defringe_mode,
                dark_matte_hard=False,
                skip_matte=False,
                birefnet_alpha_threshold=birefnet_alpha_threshold,
            )
        except Exception as e:
            print(f"[normalize_lz_title_art] mode={mode} 失败: {e}", flush=True)
            continue

        n = _foreground_pixel_count(out)
        score = _score_title_matte_result(
            out, plate=plate, canvas_w=w, canvas_h=h, min_fg=min_fg
        )
        print(
            f"[normalize_lz_title_art] mode={mode} 前景≈{n} 评分={score:.0f}（需≥{min_fg}）",
            flush=True,
        )
        if score > best_score or (score == best_score and n > best_n):
            best, best_score, best_mode, best_n = out, score, mode, n
        if score > 0 and n >= min_fg:
            print(f"[normalize_lz_title_art] 抠字选用 mode={mode} 前景≈{n}", flush=True)
            return _finalize_title_matte(out)

    if best_n < min_fg or best_score <= 0:
        raise RuntimeError(
            f"艺术字抠字失败：黑底/白底各模式均未得到有效字形（最佳 mode={best_mode or '?'} "
            f"前景≈{best_n}，需≥{min_fg}）。请检查 Step1 是否为高对比纯色底稿。"
        )
    print(
        f"[normalize_lz_title_art] 抠字回退选用 mode={best_mode} 前景≈{best_n} 评分={best_score:.0f}",
        flush=True,
    )
    return _finalize_title_matte(best)


def _finalize_title_matte(out_rgba):
    """抠字后：可选镂空修复 + 外缘柔化。"""
    if matte_hollow_repair_enabled():
        out_rgba = _repair_hollow_title_glyphs(out_rgba)
    return _matte_edge_soften(out_rgba)


def invert_title_rgba_for_micu_edit(rgba) -> "Image.Image":
    """
    白底黑字 BiRefNet 抠字后 → 黑字透明底；反色为白/浅灰字透明底，供 MICU 黑底图编。
    保留副标题与主标题的明度层次（#333 → #CCC）。
    """
    from PIL import Image
    import numpy as np

    if not isinstance(rgba, Image.Image):
        rgba = Image.open(rgba).convert("RGBA")
    arr = np.array(rgba.convert("RGBA"), dtype=np.uint8)
    fg = arr[:, :, 3] > 32
    if not fg.any():
        return rgba
    arr[fg, 0] = (255 - arr[fg, 0].astype(np.int16)).astype(np.uint8)
    arr[fg, 1] = (255 - arr[fg, 1].astype(np.int16)).astype(np.uint8)
    arr[fg, 2] = (255 - arr[fg, 2].astype(np.int16)).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def birefnet_matte_rgba(
    img_rgba,
    *,
    defringe: bool = True,
    defringe_max_rgb: int = 80,
    birefnet_alpha_threshold: float | None = None,
):
    """Step 2：仅 BiRefNet（黑底白字易抠没，艺术字产线请用 title_art_matte_rgba）。"""
    from PIL import Image

    if not isinstance(img_rgba, Image.Image):
        img_rgba = Image.open(img_rgba).convert("RGBA")
    return _remove_background(
        img_rgba,
        matte_mode="birefnet",
        matte_threshold=240,
        dark_matte_threshold=58,
        dark_matte_soft_span=32,
        defringe=defringe,
        defringe_max_rgb=defringe_max_rgb,
        dark_matte_hard=False,
        skip_matte=False,
        birefnet_alpha_threshold=birefnet_alpha_threshold,
    )



def _gen_upscale_enabled() -> bool:
    return os.environ.get("LZ_MICU_TITLE_GEN_UPSCALE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _gen_max_w_ratio() -> float:
    try:
        return max(0.5, min(0.98, float(os.environ.get("LZ_MICU_TITLE_GEN_MAX_W_RATIO", "0.92"))))
    except ValueError:
        return 0.92


def _gen_max_h_ratio() -> float:
    try:
        return max(0.35, min(0.75, float(os.environ.get("LZ_MICU_TITLE_GEN_MAX_H_RATIO", "0.58"))))
    except ValueError:
        return 0.58


def upscale_main_title_on_gen_canvas(
    img_rgba,
    *,
    gen_w: int = 1968,
    gen_h: int = 656,
    split_ratio: float | None = None,
):
    """Step1 后：主标题 alpha bbox 放大并水平居中到 gen_w×gen_h（为 SVG 副标题留底）。"""
    from PIL import Image

    if not _gen_upscale_enabled():
        return img_rgba.convert("RGBA")

    import numpy as np
    from scripts.hd.title_art_style_ref import _main_title_crop_box

    src = img_rgba.convert("RGBA")
    if src.size != (gen_w, gen_h):
        src = src.resize((gen_w, gen_h), Image.Resampling.LANCZOS)

    arr = np.array(src)
    alpha = arr[:, :, 3]
    bb = _main_title_crop_box(alpha, split_ratio=split_ratio)
    if bb is None:
        bb = _fit_alpha_bbox(src)
    if not bb:
        return src

    patch = src.crop(bb)
    pw, ph = patch.size
    target_w = gen_w * _gen_max_w_ratio()
    target_h = gen_h * _gen_max_h_ratio()
    scale = min(target_w / max(1, pw), target_h / max(1, ph))
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    if (nw, nh) != (pw, ph):
        patch = patch.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (gen_w, gen_h), (0, 0, 0, 0))
    px = (gen_w - patch.size[0]) // 2
    py = max(8, (gen_h // 2 - patch.size[1]) // 2)
    canvas.paste(patch, (px, py), patch)
    print(
        f"[lz_micu/title/upscale] gen={gen_w}×{gen_h} bbox={bb} scale={scale:.3f} "
        f"patch={patch.size[0]}×{patch.size[1]} @ ({px},{py})",
        flush=True,
    )
    return canvas



def _fit_use_full_frame() -> bool:
    """整图等比 contain 缩进画布，不按 alpha 裁 decor_bbox（不丢副标题/光晕/装饰）。"""
    raw = os.environ.get("LZ_MICU_TITLE_FIT_BBOX", "").strip().lower()
    if raw in ("full", "frame", "whole", "整图", "全画幅"):
        return True
    if raw in ("alpha", "decor", "trim"):
        return False
    try:
        from scripts.hd.title_art_style import (
            hero_pure_enabled,
            step1_solid_background,
            title_step1_mode,
        )

        if hero_pure_enabled() or title_step1_mode() == "hero_flat":
            return False
        if title_step1_mode() == "transparent_styled":
            return True
        return step1_solid_background()
    except ImportError:
        return False


def fit_rgba_to_title_canvas(
    img_rgba,
    *,
    canvas_w: int = 1080,
    canvas_h: int = 328,
    fit_scale: float = 1.0,
    bottom_reserve_px: int = 0,
    use_full_frame: bool | None = None,
):
    """Step 4：可见字图 contain 等比缩放居中装入 canvas_w×canvas_h 透明画布。

    use_full_frame=True：整图等比缩进画布（实心底/综艺装饰板）；False：按 alpha decor_bbox。
    bottom_reserve_px：底部预留高度（如 svg 副标题条），内容在上部区域垂直居中。
    """
    from PIL import Image

    if use_full_frame is None:
        use_full_frame = _fit_use_full_frame()

    fit_scale = max(0.5, min(1.0, float(fit_scale)))
    margin = _fit_safe_margin_px()
    reserve = max(0, int(bottom_reserve_px))
    max_w = max(1, int(round(canvas_w * fit_scale)) - 2 * margin)
    max_h = max(1, int(round(canvas_h * fit_scale)) - 2 * margin - reserve)

    src = img_rgba.convert("RGBA")
    if use_full_frame:
        pw, ph = src.size
        bb = (0, 0, pw, ph)
        patch = src
    else:
        bb = _fit_alpha_bbox(src)
        if not bb:
            return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        patch = src.crop(bb)
        pw, ph = patch.size

    scale = min(max_w / pw, max_h / ph)
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    patch = patch.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    px = (canvas_w - nw) // 2
    avail_h = max(1, canvas_h - reserve)
    py = max(margin, (avail_h - nh) // 2)
    canvas.paste(patch, (px, py), patch)
    bbox_label = "full_frame" if use_full_frame else ("decor_bbox" if _fit_alpha_threshold() > 0 else "bbox")
    print(
        f"[fit] {bbox_label}={pw}×{ph} scale={scale:.3f} → "
        f"content={nw}×{nh} fit_scale={fit_scale:.2f} "
        f"safe_margin={margin}px margins T={py} B={canvas_h - nh - py} "
        f"L={px} R={canvas_w - nw - px}",
        flush=True,
    )
    if reserve > 0:
        print(
            f"[lz_micu/title/fit] bottom_reserve={reserve}px paste_y={py} content={nw}×{nh}",
            flush=True,
        )
    return canvas


def main() -> None:
    p = argparse.ArgumentParser(description="LZ 标题：选定工作图后在子图/整图上抠背，导出 1080×328 PNG")
    p.add_argument("input", help="输入 PNG/JPG（推荐独立大字图任意比例；或与底板同尺 3840×1200 见 --crop-mode）")
    p.add_argument("-o", "--output", required=True, help="输出 PNG 路径")
    p.add_argument("-p", "--preset", default="legend_top_banner_3840", choices=list(_spec.PRESETS))
    p.add_argument(
        "--crop-mode",
        choices=("full", "auto", "rect", "smart"),
        default="full",
        help="full（默认）= 整幅图抠背再装入 1080×328，不截取规范区；3840 LZ 底板时可选 auto/rect/smart",
    )
    p.add_argument(
        "--matte-mode",
        choices=("auto", "hybrid", "hybrid_white", "birefnet", "white", "dark", "rembg"),
        default="hybrid",
        help="hybrid（默认）= 近黑软抠+去黑边+BiRefNet 合并；hybrid_white=近白软抠+BiRefNet合并（白底文字镂空修复）；rembg/birefnet/auto 见上文",
    )
    p.add_argument("--matte-threshold", type=int, default=240, help="white 模式：RGB≥此值视作透明（默认 240）")
    p.add_argument(
        "--dark-matte-threshold",
        type=int,
        default=52,
        metavar="T",
        help="近黑底：max(R,G,B)≤T 起算透明（默认 52；底抠不净可调到 58–68；字被吃空则降到 42–48）",
    )
    p.add_argument(
        "--dark-matte-soft-span",
        type=int,
        default=32,
        metavar="N",
        help="近黑软抠过渡宽度（默认 32，越大边缘越柔、底越干净）",
    )
    p.add_argument(
        "--defringe-max-rgb",
        type=int,
        default=72,
        metavar="N",
        help="去黑边：仍带 alpha 且 max(RGB)≤N 的像素清掉（默认 72；黑边多可调到 80–90）",
    )
    p.add_argument(
        "--no-defringe",
        action="store_true",
        help="关闭去黑边/灰边后处理",
    )
    p.add_argument(
        "--dark-matte-hard",
        action="store_true",
        help="近黑抠使用旧版硬阈值（不推荐，易留锯齿/黑边）",
    )
    p.add_argument(
        "--birefnet-alpha-threshold",
        type=float,
        default=None,
        metavar="T",
        help="BiRefNet 输出二值化阈值 0~1（默认不设，保留柔和半透明边）",
    )
    p.add_argument(
        "--skip-matte",
        action="store_true",
        help="完全跳过去背（仅裁切/缩放/入画布，适合成品透明 PNG）",
    )
    p.add_argument(
        "--fit-scale",
        type=float,
        default=None,
        metavar="S",
        help="可见字图 contain 缩放上限（相对 1080×328，默认读 spec title_art_fit_scale=0.95）",
    )
    args = p.parse_args()
    try:
        normalize_lz_title_art_png(
            args.input,
            args.output,
            preset=args.preset,
            crop_mode=args.crop_mode,
            matte_mode=args.matte_mode,
            matte_threshold=args.matte_threshold,
            dark_matte_threshold=args.dark_matte_threshold,
            dark_matte_soft_span=args.dark_matte_soft_span,
            defringe=not args.no_defringe,
            defringe_max_rgb=args.defringe_max_rgb,
            dark_matte_hard=args.dark_matte_hard,
            skip_matte=args.skip_matte,
            birefnet_alpha_threshold=args.birefnet_alpha_threshold,
            fit_scale_override=args.fit_scale,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
