#!/usr/bin/env python3
"""
HD 产线 Stage 1：一次 Gemini Vision 综合分析 3 张人物图。

输出 JSON:
{
  "images": [
    {"index": 0, "needs_matting": true},
    {"index": 1, "needs_matting": false},
    {"index": 2, "needs_matting": true}
  ],
  "quality_order": [1, 0, 2],
  "center_index": 1,
  "style": {
    "art_style": "...",
    "rendering": "...",
    "palette": "...",
    "costume_colors": "...",
    "accent_colors": "...",
    "lighting": "...",
    "world_setting": "...",
    "environment": "...",
    "mood": "...",
    "bg_prompt_addendum": "..."
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_STAGE1_PROMPT = """You are given {n} character images (indexed 0 to {hi}). Analyze ALL images together in ONE response.

## 1. Matting Detection (per image)
For each image: does it need background removal (BiRefNet matting)?
- TRUE = complex scene/card background / photograph with environment
- FALSE = already transparent / clean solid studio bg / existing cutout asset

## 2. Quality Ranking
Rank images from BEST to WORST by: visual quality, sharpness, detail, completeness (full body visible, no parts cut off), visual weight.

## 3. Center Candidate
Which image is best for CENTER position in a wide triple banner?
- Index of the most FRONTAL pose (facing camera squarely)
- Most COMPACT silhouette (arms/legs close to body)
- Avoid strong profile / extreme 3/4 turn / wide-reaching limbs for center

## 4. Per-character Style (for each image)
For each image, write ONE short sentence describing its distinct visual style (art_style, main colors, world type).
Example: "anime cel-shade with pink hair, street fashion, bright pastels"

## 5. Combined Background Style
Analyze ALL {n} images TOGETHER. The banner will place all {n} characters on ONE shared background.
Find the COMMON ground:
- If all characters are stylized 3D → use stylized 3D
- If styles conflict (e.g. one realistic + one cartoon) → pick a neutral middle-ground environment that doesn't favor any single character
- palette: identify colors that APPEAR IN MULTIPLE characters, or neutral tones that work with all
- environment: choose a setting that makes sense for ALL characters (e.g. "neutral urban plaza" is safer than "ancient temple" if characters are mixed genres)
- lighting: soft directional ambient that works across all character lighting styles
- bg_prompt_addendum: 2-3 English sentences describing a unified background that ALL characters would look natural in. NO people, NO text. Mention the shared lighting direction and palette.

Do NOT invent cyberpunk neon city unless clearly visible on MULTIPLE characters.

IMPORTANT: Reply as TEXT, NOT as an image. Do NOT generate a picture.
Reply with ONLY a JSON object (text only, no markdown, no image):
{{
  "images": [{{"index": 0, "needs_matting": true/false, "style_note": "one short sentence"}}, ...],
  "quality_order": [best_idx, ..., worst_idx],
  "center_index": <int>,
  "style": {{
    "art_style": "...",
    "rendering": "...",
    "palette": "...",
    "costume_colors": "...",
    "accent_colors": "...",
    "lighting": "...",
    "world_setting": "...",
    "environment": "...",
    "mood": "...",
    "bg_prompt_addendum": "..."
  }}
}}"""

_STYLE_FIELDS = (
    "art_style",
    "rendering",
    "palette",
    "costume_colors",
    "accent_colors",
    "lighting",
    "world_setting",
    "environment",
    "mood",
    "bg_prompt_addendum",
)


def run_stage1(image_paths: list[Path]) -> dict:
    """
    Stage 1：一次 Gemini Vision 综合分析（失败重试 3 次）。
    Args:
        image_paths: 3 张原始图片路径
    Returns:
        分析结果 dict（见文件头注释）
    Raises:
        RuntimeError: Vision 失败或响应无法解析
    """
    from scripts.hd.hd_vision import call_hd_vision_multi
    import time

    n = len(image_paths)
    prompt = _STAGE1_PROMPT.format(n=n, hi=n - 1)

    for attempt in range(1, 4):
        text = call_hd_vision_multi(prompt, image_paths, timeout=90)
        if text:
            data = _parse_stage1_json(text, n)
            if data is not None:
                _validate_stage1(data, n)
                _log_stage1(data)
                return data
            print(f"[stage1] 第 {attempt}/3 次 JSON 解析失败", flush=True)
        else:
            print(f"[stage1] 第 {attempt}/3 次无响应", flush=True)
        if attempt < 3:
            wait = 5 * attempt
            print(f"[stage1] 等待 {wait}s 后重试...", flush=True)
            time.sleep(wait)

    raise RuntimeError("[stage1] Gemini Vision 综合分析重试 3 次均失败")


def _parse_stage1_json(text: str, n: int) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except (json.JSONDecodeError, TypeError, ValueError):
                    return None
    return None


def _validate_stage1(data: dict, n: int) -> None:
    images = data.get("images")
    if not isinstance(images, list) or len(images) != n:
        raise RuntimeError(f"[stage1] images 字段无效: 期望 {n} 条")
    for img in images:
        idx = img.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= n:
            raise RuntimeError(f"[stage1] image index 无效: {idx}")

    qo = data.get("quality_order")
    if not isinstance(qo, list) or len(qo) != n:
        raise RuntimeError(f"[stage1] quality_order 无效")

    ci = data.get("center_index")
    if not isinstance(ci, int) or ci < 0 or ci >= n:
        raise RuntimeError(f"[stage1] center_index 无效: {ci}")

    style = data.get("style")
    if not isinstance(style, dict):
        raise RuntimeError("[stage1] style 字段无效")
    for f in _STYLE_FIELDS:
        style.setdefault(f, "")


def _log_stage1(data: dict) -> None:
    images = data["images"]
    for img in images:
        flag = "抠" if img.get("needs_matting", True) else "免"
        note = img.get("style_note", "")
        line = f"[stage1] 图{img['index']}: {flag}抠"
        if note:
            line += f" — {note[:80]}"
        print(line, flush=True)

    qo = data["quality_order"]
    print(f"[stage1] 质量排序: {qo}", flush=True)

    ci = data["center_index"]
    print(f"[stage1] 中槽: 图{ci}", flush=True)

    s = data["style"]
    print(
        f"[stage1] 风格: {s.get('art_style', '?')[:60]} · "
        f"{s.get('palette', '?')[:40]} · "
        f"{s.get('environment', '?')[:40]}",
        flush=True,
    )
