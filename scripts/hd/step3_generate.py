#!/usr/bin/env python3
"""
HD 生产线 Step 3：Gemini i2i 生图
以 layout_ref.png 为参考图，结合用户 prompt，调用 Gemini（Packy）生成 3840×1200 完整背景。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

from _env import load_env
load_env()

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = (
    f"{_gemini_base}/v1beta/models"
    if _gemini_base
    else "https://generativelanguage.googleapis.com/v1beta/models"
)

IMAGE_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODEL",
        "gemini-3-pro-image-preview,gemini-3.1-flash-image-preview,gemini-2.5-flash-image",
    ).split(",")
    if m.strip()
]

HD_GENERATE_PROMPT_TEMPLATE = """You are generating a high-quality game banner background image (3840×1200, ultra-wide horizontal format).

User's creative brief:
\"\"\"{user_prompt}\"\"\"

The reference image shows the character layout arrangement. Use it as a COMPOSITION GUIDE ONLY — understand where the characters are positioned, then generate a complete, seamless scene that:
1. Matches the mood, color palette, and atmosphere described in the brief
2. Places characters naturally within the environment (they are already positioned in the reference)
3. Creates a rich, detailed background that extends behind and around the characters
4. Left area (x=0 to x=1200) should have slightly simpler/darker background to accommodate logo and title text overlay
5. NO text, NO watermarks, NO UI elements, NO logos in the generated image
6. Ultra-wide cinematic composition, high production quality

Generate a complete banner scene — not just a background, but a full environment where the characters exist."""


def _get_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def _gemini_headers(key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        h["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        h["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return h


def _gemini_url(model: str, key: str) -> str:
    url = f"{API_BASE}/{model}:generateContent"
    return url if key.startswith("sk-") else f"{url}?key={key}"


def _encode_image(path: Path) -> tuple[str, str]:
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return b64, mime


def _call_gemini_image(layout_ref: Path, prompt: str, model: str) -> bytes | None:
    """调用 Gemini 图像生成，返回图片 bytes 或 None。"""
    key = _get_key()
    if not key:
        return None
    b64, mime = _encode_image(layout_ref)
    body = json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
    ).encode()
    url = _gemini_url(model, key)
    req = urllib.request.Request(
        url, data=body, headers=_gemini_headers(key), method="POST"
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for p in parts:
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"])
            return None
        except urllib.error.HTTPError as e:
            err = (e.read().decode("utf-8", errors="replace") if e.fp else "")[:200]
            print(f"[step3] HTTP {e.code} model={model}: {err}", flush=True)
            if e.code in (403, 404):
                return None
            if e.code in (500, 503) and attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"[step3] 重试 {attempt + 1}/3，等待 {wait}s...", flush=True)
                time.sleep(wait)
                continue
            return None
        except Exception as e:
            print(f"[step3] 异常: {e}", flush=True)
            if attempt < 2:
                time.sleep(5)
            continue
    return None


def run_step3(
    layout_ref: Path,
    user_prompt: str,
    out_dir: Path,
) -> Path:
    """
    以 layout_ref 为参考图生成完整背景，输出 generated_bg.png。
    """
    from PIL import Image
    import io

    prompt = HD_GENERATE_PROMPT_TEMPLATE.format(
        user_prompt=user_prompt.strip() or "game banner, epic scene"
    )
    out_path = out_dir / "generated_bg.png"
    out_dir.mkdir(parents=True, exist_ok=True)

    img_bytes = None
    for model in IMAGE_MODELS:
        print(f"[step3] 生图 model={model} ...", flush=True)
        img_bytes = _call_gemini_image(layout_ref, prompt, model)
        if img_bytes:
            print(f"[step3] 生图成功 model={model}", flush=True)
            break
        print(f"[step3] model={model} 失败，尝试下一个", flush=True)

    if not img_bytes:
        raise RuntimeError("[step3] 所有模型均失败，无法生成背景图")

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    # 缩放到目标尺寸
    if img.size != (3840, 1200):
        print(f"[step3] 缩放 {img.size} → (3840, 1200)", flush=True)
        img = img.resize((3840, 1200), Image.Resampling.LANCZOS)

    img.save(str(out_path))
    print(f"[step3] 背景图已保存: {out_path}", flush=True)
    return out_path
