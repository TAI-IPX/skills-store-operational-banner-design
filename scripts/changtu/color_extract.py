#!/usr/bin/env python3
"""从 KV 图像提取战报 theme Token 色值（Pillow + numpy，无 sklearn 依赖）。"""
from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

# 战报 theme 必填 Token（与 docs/战报规范.md 一致）
THEME_COLOR_KEYS = (
    "bg_page",
    "bg_card",
    "bg_card_dark",
    "accent_primary",
    "accent_secondary",
    "accent_bright",
    "accent_bright_alt",
    "text_primary",
    "text_secondary",
    "text_on_light",
    "stroke_decor",
)


# 暖色带：橙 / 珊瑚 / 玫红 —— KV 里常见且适合做出艳丽色块
WARM_VIVID_HUE_RANGES: tuple[tuple[float, float], ...] = (
    (6.0, 58.0),
    (278.0, 338.0),
)
COOL_VIVID_HUE_RANGE: tuple[float, float] = (165.0, 255.0)


@dataclass
class ExtractConfig:
    sample_max_side: int = 480
    k_accent: int = 8
    k_dark: int = 4
    min_saturation: float = 0.28
    min_value: float = 0.22
    max_value: float = 0.96
    min_hue_sep_deg: float = 28.0
    dark_value_cutoff: float = 0.28
    accent_min_saturation: float = 0.38
    bright_min_saturation: float = 0.42
    bright_min_value: float = 0.52
    hero_top_ratio: float = 0.55
    warm_min_saturation: float = 0.38
    warm_min_value: float = 0.36


def _rgb_to_hex(rgb: tuple[int, int, int], alpha: int | None = None) -> str:
    r, g, b = (int(np.clip(c, 0, 255)) for c in rgb)
    if alpha is None:
        return f"#{r:02X}{g:02X}{b:02X}"
    a = int(np.clip(alpha, 0, 255))
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 8:
        h = h[:6]
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1, l2 = _relative_luminance(c1), _relative_luminance(c2)
    lighter, darker = (max(l1, l2), min(l1, l2))
    return (lighter + 0.05) / (darker + 0.05)


def _rgb_to_hsv_deg(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (x / 255.0 for x in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def _hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _hue_in_ranges(h: float, ranges: tuple[tuple[float, float], ...]) -> bool:
    return any(lo <= h <= hi for lo, hi in ranges)


def _is_warm_vivid_hue(h: float) -> bool:
    return _hue_in_ranges(h, WARM_VIVID_HUE_RANGES)


def _is_cool_vivid_hue(h: float) -> bool:
    lo, hi = COOL_VIVID_HUE_RANGE
    return lo <= h <= hi


def _rgb_near(a: tuple[int, int, int], b: tuple[int, int, int], *, thresh: int = 32) -> bool:
    return sum((x - y) ** 2 for x, y in zip(a, b)) < thresh * thresh


def _lively_palette_multiplier(stat: dict[str, Any]) -> float:
    """艳丽倾向：KV 橙/珊瑚/玫红等暖高光加权，避免只落到大面积绿/蓝。"""
    h, s, v = stat["hue"], stat["saturation"], stat["value"]
    if _is_warm_vivid_hue(h) and s >= 0.4:
        return 1.5 + min(max(s - 0.4, 0.0), 0.45) * 1.1 + min(max(v - 0.45, 0.0), 0.4) * 0.5
    if _is_cool_vivid_hue(h) and s >= 0.48:
        return 1.18
    if 52.0 <= h <= 145.0 and s >= 0.5:
        return 1.1
    return 1.0


def _kmeans(pixels: np.ndarray, k: int, seed: int = 42, max_iter: int = 40) -> np.ndarray:
    """pixels: (n, 3) float RGB 0-255. Returns centroids (k, 3)."""
    n = len(pixels)
    if n == 0:
        return np.zeros((k, 3))
    k = min(k, n)
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, k, replace=False)
    centroids = pixels[idx].astype(np.float64)
    for _ in range(max_iter):
        dists = ((pixels[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        labels = dists.argmin(axis=1)
        new_centroids = np.zeros_like(centroids)
        for i in range(k):
            mask = labels == i
            if mask.any():
                new_centroids[i] = pixels[mask].mean(axis=0)
            else:
                new_centroids[i] = pixels[rng.integers(0, n)]
        if np.allclose(new_centroids, centroids, atol=1.0):
            break
        centroids = new_centroids
    return centroids


def _load_image_array(path: Path, max_side: int) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return np.array(im, dtype=np.float64)


def _load_sample_pixels(path: Path, max_side: int) -> np.ndarray:
    return _load_image_array(path, max_side).reshape(-1, 3)


def _hero_accent_pixels(arr: np.ndarray, hero_top_ratio: float) -> np.ndarray:
    h, w, _ = arr.shape
    top = max(1, int(h * hero_top_ratio))
    return arr[:top, :, :].reshape(-1, 3)


def _cluster_stats(centroids: np.ndarray, pixels: np.ndarray) -> list[dict[str, Any]]:
    dists = ((pixels[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
    labels = dists.argmin(axis=1)
    out: list[dict[str, Any]] = []
    for i, c in enumerate(centroids):
        mask = labels == i
        count = int(mask.sum())
        rgb = tuple(int(round(x)) for x in c)
        h, s, v = _rgb_to_hsv_deg(rgb)
        out.append(
            {
                "rgb": rgb,
                "count": count,
                "weight": count / max(len(pixels), 1),
                "hue": h,
                "saturation": s,
                "value": v,
                "score_accent": (s**2) * (count / max(len(pixels), 1)) * (0.25 + v * 0.75),
                "score_bright": (s * v) * (count / max(len(pixels), 1)),
            }
        )
    return out


def _pick_bg_page(dark_stats: list[dict[str, Any]], cfg: ExtractConfig) -> tuple[int, int, int]:
    candidates = [s for s in dark_stats if s["value"] <= cfg.dark_value_cutoff + 0.08]
    if not candidates:
        candidates = sorted(dark_stats, key=lambda s: s["value"])[:2]
    best = min(candidates or dark_stats, key=lambda s: s["value"])
    r, g, b = best["rgb"]
    # 略压暗，避免与截图融在一起
    factor = 0.88
    return tuple(int(round(x * factor)) for x in (r, g, b))


def _pick_accents(accent_stats: list[dict[str, Any]], cfg: ExtractConfig) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    vivid = [s for s in accent_stats if s["saturation"] >= cfg.accent_min_saturation]
    ranked = sorted(vivid or accent_stats, key=lambda s: s["score_accent"], reverse=True)
    if not ranked:
        return (255, 45, 154), (0, 229, 255)

    primary = ranked[0]["rgb"]
    secondary: tuple[int, int, int] | None = None
    for s in ranked[1:]:
        if _hue_distance(ranked[0]["hue"], s["hue"]) >= cfg.min_hue_sep_deg:
            secondary = s["rgb"]
            break
    if secondary is None and len(ranked) > 1:
        secondary = ranked[1]["rgb"]
    elif secondary is None:
        h, sat, val = _rgb_to_hsv_deg(primary)
        h2 = (h + 150.0) % 360.0
        r, g, b = colorsys.hsv_to_rgb(h2 / 360.0, min(1.0, sat * 0.95), min(1.0, val * 1.05))
        secondary = tuple(int(round(x * 255)) for x in (r, g, b))

    return primary, secondary


def _boost_vivid(rgb: tuple[int, int, int], *, sat_mul: float = 1.08, val_mul: float = 1.1) -> tuple[int, int, int]:
    r, g, b = (x / 255.0 for x in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, max(s * sat_mul, 0.55))
    v = min(1.0, v * val_mul)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return tuple(int(round(x * 255)) for x in (r2, g2, b2))


def _boost_warm_vivid(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """橙/珊瑚：略向纯橙收束并拉高饱和，贴近 KV 里的鲜亮暖色。"""
    h, s, v = _rgb_to_hsv_deg(rgb)
    if _is_warm_vivid_hue(h) and 6.0 <= h <= 58.0:
        h = float(np.clip(h, 22.0, 42.0))
        s = min(1.0, max(s * 1.18, 0.72))
        v = min(1.0, max(v * 1.14, 0.62))
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
        return tuple(int(round(x * 255)) for x in (r, g, b))
    return _boost_vivid(rgb, sat_mul=1.16, val_mul=1.14)


def _mine_warm_vivid_accent(arr: np.ndarray, cfg: ExtractConfig) -> dict[str, Any] | None:
    """全图挖掘 KV 橙/珊瑚高光（面积小但饱和高，专供艳丽色块）。"""
    pixels = arr.reshape(-1, 3)
    hsv = np.array([_rgb_to_hsv_deg(tuple(int(x) for x in p)) for p in pixels])
    warm_mask = np.zeros(len(pixels), dtype=bool)
    for lo, hi in WARM_VIVID_HUE_RANGES:
        warm_mask |= (hsv[:, 0] >= lo) & (hsv[:, 0] <= hi)
    warm_mask &= (hsv[:, 1] >= cfg.warm_min_saturation) & (hsv[:, 2] >= cfg.warm_min_value)
    warm_pixels = pixels[warm_mask]
    if len(warm_pixels) < 24:
        return None
    k = min(5, max(2, len(warm_pixels) // 180))
    centroids = _kmeans(warm_pixels, k)
    stats = _cluster_stats(centroids, warm_pixels)
    ranked = sorted(
        stats,
        key=lambda s: (s["saturation"] ** 2) * s["value"] * _lively_palette_multiplier(s),
        reverse=True,
    )
    best = ranked[0]
    if best["saturation"] < 0.4:
        return None
    return best


def _merge_accent_stat(accent_stats: list[dict[str, Any]], extra: dict[str, Any] | None) -> list[dict[str, Any]]:
    if extra is None:
        return accent_stats
    if any(_rgb_near(s["rgb"], extra["rgb"]) for s in accent_stats):
        return accent_stats
    return accent_stats + [extra]


def _complementary_vivid(
    rgb: tuple[int, int, int],
    *,
    secondary_hint: tuple[int, int, int] | None = None,
    hue_shift: float = 168.0,
) -> tuple[int, int, int]:
    """KV 对比色 / 互补色：用于色块第二色，与主色拉开色相。"""
    h, s, v = _rgb_to_hsv_deg(rgb)
    h2 = (h + hue_shift) % 360.0
    s2 = min(1.0, max(s, 0.68) * 1.08)
    v2 = min(1.0, max(v * 1.1, 0.58))
    r, g, b = colorsys.hsv_to_rgb(h2 / 360.0, s2, v2)
    comp = tuple(int(round(x * 255)) for x in (r, g, b))
    if secondary_hint is not None:
        if _hue_distance(h, _rgb_to_hsv_deg(secondary_hint)[0]) >= 28.0 and _contrast_ratio(
            rgb, secondary_hint
        ) >= _contrast_ratio(rgb, comp):
            return secondary_hint
    return comp


def _block_pop_score(stat: dict[str, Any], bg_page: tuple[int, int, int]) -> float:
    """色块/边框用色：饱和 + 明度 + 与暗底反差 + 艳丽暖色加权。"""
    rgb = stat["rgb"]
    cr_bg = min(_contrast_ratio(rgb, bg_page), 8.0)
    base = (
        (stat["saturation"] ** 1.65)
        * (stat["value"] ** 0.9)
        * (0.3 + stat["weight"])
        * (0.45 + cr_bg / 3.2)
    )
    return base * _lively_palette_multiplier(stat)


def _pair_block_highlight_quality(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    bg_page: tuple[int, int, int],
) -> float:
    return (
        min(_contrast_ratio(a, bg_page), _contrast_ratio(b, bg_page))
        * _contrast_ratio(a, b)
        * (_relative_luminance(a) + _relative_luminance(b) + 0.08)
    )


def _pick_max_contrast_vivid_pair(
    accent_stats: list[dict[str, Any]],
    bg_page: tuple[int, int, int],
    *,
    min_saturation: float = 0.32,
) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    """在 KV 色簇中找反差最大的一对（相近色 / 对比色均可）。"""
    pool = [s for s in accent_stats if s["saturation"] >= min_saturation]
    if len(pool) < 2:
        pool = sorted(accent_stats, key=lambda s: s["score_accent"], reverse=True)[:8]
    if len(pool) < 2:
        return None
    best: tuple[dict[str, Any], dict[str, Any], float] | None = None
    for i, sa in enumerate(pool):
        for sb in pool[i + 1 :]:
            cr = _contrast_ratio(sa["rgb"], sb["rgb"])
            hd = _hue_distance(sa["hue"], sb["hue"])
            if cr < 2.1 and hd < 22.0:
                continue
            pop = _block_pop_score(sa, bg_page) + _block_pop_score(sb, bg_page)
            sc = pop * cr * (1.0 + hd / 95.0)
            if best is None or sc > best[2]:
                best = (sa, sb, sc)
    if best is None:
        return None
    return best[0]["rgb"], best[1]["rgb"]


def _pick_bright_alt_for_block(
    anchor: dict[str, Any],
    ranked: list[dict[str, Any]],
    bg_page: tuple[int, int, int],
    *,
    secondary_hint: tuple[int, int, int],
    min_hue_sep_deg: float,
) -> tuple[int, int, int]:
    """第二色：优先 KV 内高反差 / 色相分离簇，否则用对比色推导。"""
    best_rgb: tuple[int, int, int] | None = None
    best_sc = -1.0
    for s in ranked[1:12]:
        if s["rgb"] == anchor["rgb"]:
            continue
        hd = _hue_distance(anchor["hue"], s["hue"])
        cr_pair = _contrast_ratio(anchor["rgb"], s["rgb"])
        sc = _block_pop_score(s, bg_page) * (1.0 + hd / 70.0) * (0.8 + min(cr_pair, 5.5) / 2.2)
        if sc > best_sc:
            best_sc = sc
            best_rgb = s["rgb"]
    if best_rgb is not None and _contrast_ratio(anchor["rgb"], best_rgb) >= 2.15:
        return best_rgb
    if _hue_distance(anchor["hue"], _rgb_to_hsv_deg(secondary_hint)[0]) >= min_hue_sep_deg * 0.75:
        return secondary_hint
    return _complementary_vivid(anchor["rgb"], secondary_hint=secondary_hint)


def _pick_lively_block_anchor(
    ranked: list[dict[str, Any]],
    bg_page: tuple[int, int, int],
) -> dict[str, Any]:
    """主色：综合分最高；若 KV 有鲜亮暖色（如橙）且够饱和，优先作色块主色。"""
    anchor = ranked[0]
    warm_candidates = [
        s
        for s in ranked
        if _is_warm_vivid_hue(s["hue"]) and s["saturation"] >= 0.44 and s["value"] >= 0.48
    ]
    if not warm_candidates:
        return anchor
    best_warm = warm_candidates[0]
    warm_sc = _block_pop_score(best_warm, bg_page)
    top_sc = _block_pop_score(anchor, bg_page)
    if warm_sc >= top_sc * 0.52 or not _is_warm_vivid_hue(anchor["hue"]):
        return best_warm
    return anchor


def _pick_lively_block_alt(
    anchor: dict[str, Any],
    ranked: list[dict[str, Any]],
    bg_page: tuple[int, int, int],
    *,
    secondary_hint: tuple[int, int, int],
    min_hue_sep_deg: float,
) -> tuple[int, int, int]:
    """副色：主暖则配冷青/蓝，主冷则配 KV 橙珊瑚，整体更艳丽。"""
    others = [s for s in ranked if not _rgb_near(s["rgb"], anchor["rgb"])]
    if _is_warm_vivid_hue(anchor["hue"]):
        cyan_blue = [s for s in others if _is_cool_vivid_hue(s["hue"])]
        if cyan_blue:
            return max(cyan_blue, key=lambda s: _block_pop_score(s, bg_page))["rgb"]
        brand_green = [
            s for s in others if 72.0 <= s["hue"] <= 128.0 and s["saturation"] >= 0.48
        ]
        if brand_green:
            return brand_green[0]["rgb"]
    else:
        warm = [s for s in others if _is_warm_vivid_hue(s["hue"]) and s["saturation"] >= 0.42]
        if warm:
            return warm[0]["rgb"]
    return _pick_bright_alt_for_block(
        anchor,
        ranked,
        bg_page,
        secondary_hint=secondary_hint,
        min_hue_sep_deg=min_hue_sep_deg,
    )


def _finalize_block_vivid_rgb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    h, _, _ = _rgb_to_hsv_deg(rgb)
    if _is_warm_vivid_hue(h):
        return _boost_warm_vivid(rgb)
    return _boost_vivid(rgb, sat_mul=1.12, val_mul=1.14)


def _order_warm_primary(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """色块主色优先 KV 暖橙/珊瑚，副色配冷色。"""
    if _is_warm_vivid_hue(_rgb_to_hsv_deg(b)[0]) and not _is_warm_vivid_hue(_rgb_to_hsv_deg(a)[0]):
        return b, a
    return a, b


def _pick_bright_accents(
    accent_stats: list[dict[str, Any]],
    cfg: ExtractConfig,
    *,
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    bg_page: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """UI 色块/边框：艳丽思维 = KV 暖橙 + 冷色对比，而非仅面积最大的绿/蓝。"""
    pool = [
        s
        for s in accent_stats
        if s["saturation"] >= cfg.bright_min_saturation and s["value"] >= cfg.bright_min_value
    ]
    ranked = sorted(pool or accent_stats, key=lambda s: _block_pop_score(s, bg_page), reverse=True)
    if not ranked:
        return _order_warm_primary(
            _boost_vivid(primary, sat_mul=1.12, val_mul=1.12),
            _boost_vivid(secondary, sat_mul=1.12, val_mul=1.12),
        )

    anchor = _pick_lively_block_anchor(ranked, bg_page)
    alt_rgb = _pick_lively_block_alt(
        anchor,
        ranked,
        bg_page,
        secondary_hint=secondary,
        min_hue_sep_deg=cfg.min_hue_sep_deg,
    )
    pop_a = _finalize_block_vivid_rgb(anchor["rgb"])
    pop_b = _finalize_block_vivid_rgb(alt_rgb)

    contrast_pair = _pick_max_contrast_vivid_pair(accent_stats, bg_page)
    if contrast_pair:
        cp_a = _finalize_block_vivid_rgb(contrast_pair[0])
        cp_b = _finalize_block_vivid_rgb(contrast_pair[1])
        has_warm = _is_warm_vivid_hue(_rgb_to_hsv_deg(cp_a)[0]) or _is_warm_vivid_hue(_rgb_to_hsv_deg(cp_b)[0])
        if has_warm and _pair_block_highlight_quality(cp_a, cp_b, bg_page) > _pair_block_highlight_quality(
            pop_a, pop_b, bg_page
        ) * 0.82:
            return _order_warm_primary(cp_a, cp_b)
        if not has_warm and _pair_block_highlight_quality(cp_a, cp_b, bg_page) > _pair_block_highlight_quality(
            pop_a, pop_b, bg_page
        ) * 0.92:
            pop_a, pop_b = cp_a, cp_b

    return _order_warm_primary(pop_a, pop_b)


def _ensure_contrast_text(bg: tuple[int, int, int]) -> tuple[str, str, str]:
    white = (255, 255, 255)
    dark = (51, 51, 51)
    if _contrast_ratio(bg, white) >= _contrast_ratio(bg, dark):
        return (
            _rgb_to_hex(white),
            "#FFFFFFCC",
            _rgb_to_hex(dark),
        )
    return (_rgb_to_hex(dark), "#333333CC", _rgb_to_hex(dark))


def _shift_rgb(rgb: tuple[int, int, int], delta: int) -> tuple[int, int, int]:
    return tuple(int(np.clip(c + delta, 0, 255)) for c in rgb)


def extract_theme_from_pixels(
    pixels: np.ndarray,
    cfg: ExtractConfig | None = None,
    accent_pixels_override: np.ndarray | None = None,
    warm_accent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or ExtractConfig()
    hsv = np.array([_rgb_to_hsv_deg(tuple(int(x) for x in p)) for p in pixels])

    dark_mask = hsv[:, 2] <= cfg.dark_value_cutoff
    dark_pixels = pixels[dark_mask]
    if len(dark_pixels) < 50:
        dark_pixels = pixels[hsv[:, 2] <= np.percentile(hsv[:, 2], 25)]

    accent_source = accent_pixels_override if accent_pixels_override is not None else pixels
    accent_hsv = np.array([_rgb_to_hsv_deg(tuple(int(x) for x in p)) for p in accent_source])
    accent_mask = (
        (accent_hsv[:, 1] >= cfg.min_saturation)
        & (accent_hsv[:, 2] >= cfg.min_value)
        & (accent_hsv[:, 2] <= cfg.max_value)
    )
    accent_pixels = accent_source[accent_mask]
    if len(accent_pixels) < 80:
        accent_pixels = accent_source[accent_hsv[:, 1] >= cfg.min_saturation * 0.65]

    dark_centroids = _kmeans(dark_pixels, cfg.k_dark) if len(dark_pixels) else _kmeans(pixels, 2)
    accent_centroids = (
        _kmeans(accent_pixels, cfg.k_accent) if len(accent_pixels) else _kmeans(accent_source, cfg.k_accent)
    )

    dark_stats = _cluster_stats(dark_centroids, dark_pixels if len(dark_pixels) else pixels)
    accent_stats = _merge_accent_stat(
        _cluster_stats(
            accent_centroids,
            accent_pixels if len(accent_pixels) else accent_source,
        ),
        warm_accent,
    )

    bg_page = _pick_bg_page(dark_stats, cfg)
    accent_primary, accent_secondary = _pick_accents(accent_stats, cfg)
    accent_bright, accent_bright_alt = _pick_bright_accents(
        accent_stats,
        cfg,
        primary=accent_primary,
        secondary=accent_secondary,
        bg_page=bg_page,
    )
    text_primary, text_secondary, text_on_light = _ensure_contrast_text(bg_page)

    bg_card = (242, 242, 242)
    bg_card_dark = _shift_rgb(bg_page, 24)

    stroke_rgb = accent_bright_alt
    stroke_decor = _rgb_to_hex(stroke_rgb, alpha=int(255 * 0.72))

    return {
        "bg_page": _rgb_to_hex(bg_page),
        "bg_card": _rgb_to_hex(bg_card),
        "bg_card_dark": _rgb_to_hex(bg_card_dark),
        "accent_primary": _rgb_to_hex(accent_primary),
        "accent_secondary": _rgb_to_hex(accent_secondary),
        "accent_bright": _rgb_to_hex(accent_bright),
        "accent_bright_alt": _rgb_to_hex(accent_bright_alt),
        "text_primary": text_primary,
        "text_secondary": text_secondary,
        "text_on_light": text_on_light,
        "stroke_decor": stroke_decor,
        "_meta": {
            "accent_candidates": [
                {"hex": _rgb_to_hex(s["rgb"]), "hue": round(s["hue"], 1), "sat": round(s["saturation"], 3)}
                for s in sorted(accent_stats, key=lambda x: x["score_accent"], reverse=True)[:6]
            ],
            "dark_candidates": [
                {"hex": _rgb_to_hex(s["rgb"]), "value": round(s["value"], 3)}
                for s in sorted(dark_stats, key=lambda x: x["value"])[:4]
            ],
            "warm_accent": (
                {
                    "hex": _rgb_to_hex(warm_accent["rgb"]),
                    "hue": round(warm_accent["hue"], 1),
                    "sat": round(warm_accent["saturation"], 3),
                }
                if warm_accent
                else None
            ),
        },
    }


def extract_theme_from_kv(path: Path, cfg: ExtractConfig | None = None) -> dict[str, Any]:
    cfg = cfg or ExtractConfig()
    arr = _load_image_array(path, cfg.sample_max_side)
    all_pixels = arr.reshape(-1, 3)
    hero_pixels = _hero_accent_pixels(arr, cfg.hero_top_ratio)
    warm_accent = _mine_warm_vivid_accent(arr, cfg)
    return extract_theme_from_pixels(
        all_pixels,
        cfg,
        accent_pixels_override=hero_pixels,
        warm_accent=warm_accent,
    )


def build_theme_json(
    kv_path: Path,
    theme_id: str,
    style_id: str | None = None,
    cfg: ExtractConfig | None = None,
) -> dict[str, Any]:
    extracted = extract_theme_from_kv(kv_path, cfg)
    meta = extracted.pop("_meta", {})
    theme = {
        "theme_id": theme_id,
        "style_id": style_id or theme_id,
        "style_source": "hero_kv",
        "source_kv": str(kv_path.resolve()),
        "description": f"由 KV 自动取色生成：{kv_path.name}",
        **{k: extracted[k] for k in THEME_COLOR_KEYS},
        "extract_meta": meta,
    }
    return theme


def write_palette_preview(theme: dict[str, Any], out_path: Path, swatch_h: int = 64) -> None:
    keys = [k for k in THEME_COLOR_KEYS if k in theme]
    w = 180
    gap = 8
    img_h = len(keys) * (swatch_h + gap) + gap
    img = Image.new("RGB", (w + 220, img_h), (30, 30, 32))
    from .fonts import load_font

    draw = ImageDraw.Draw(img)
    font = load_font("body_regular", 14)

    y = gap
    for key in keys:
        hex_c = theme[key]
        rgb = _hex_to_rgb(hex_c)
        if len(hex_c) == 9:
            a = int(hex_c[7:9], 16)
            base = Image.new("RGB", (w, swatch_h), (200, 200, 200))
            fg = Image.new("RGB", (w, swatch_h), rgb)
            mask = Image.new("L", (w, swatch_h), a)
            swatch = Image.composite(fg, base, mask)
        else:
            swatch = Image.new("RGB", (w, swatch_h), rgb)
        img.paste(swatch, (gap, y))
        draw.text((w + gap * 2, y + swatch_h // 2 - 8), f"{key}\n{hex_c}", fill=(240, 240, 240), font=font)
        y += swatch_h + gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def save_theme(theme: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in theme.items() if not k.startswith("_")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
