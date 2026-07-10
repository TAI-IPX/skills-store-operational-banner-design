#!/usr/bin/env python3
"""
HD 生产线 Step 4：背景生成
4a. 用 prompt 生成 4128×1024 背景图（Gemini/Packy）
4b. Gemini Vision 检查背景是否匹配主体物的风格/色调/光源
4c. 不匹配则重新生成（最多 3 次）
4d. 裁切/缩放到 3840×1200
"""
from __future__ import annotations
import base64, io, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

from _env import load_env
load_env()

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"
IMAGE_MODELS_DEFAULT = "gemini-3-pro-image-preview,gemini-3.1-flash-image-preview,gemini-2.5-flash-image"


def _get_image_models() -> list[str]:
    """动态读取图像模型列表（支持运行时环境变量覆盖）。"""
    raw = os.environ.get("GEMINI_MODEL", IMAGE_MODELS_DEFAULT)
    return [m.strip() for m in raw.split(",") if m.strip()]
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview"]

BG_GEN_PROMPT_TEMPLATE = """Generate a high-quality game banner background image.

Creative brief:
\"\"\"{user_prompt}\"\"\"

Requirements:
- Ultra-wide horizontal format (4:1 ratio)
- Rich, detailed environment/scene matching the brief
- NO characters, NO people, NO text, NO watermarks, NO UI elements, NO logos
- Left area (leftmost 30%) should be slightly simpler/darker to accommodate logo and title overlay
- Cinematic quality, vibrant colors, high production value
- The scene should feel like a natural environment where game characters would exist

Generate ONLY the background scene."""

BG_CHECK_PROMPT = """Compare these two images:
Image 1: Character cutouts (the game characters)
Image 2: A generated background scene

Check if the background is COMPATIBLE with the characters:
1. Art style consistency (both 3D cartoon? both realistic? etc.)
2. Color palette harmony (do the colors complement each other?)
3. Lighting direction consistency (does the light in the background match the characters?)
4. Overall visual coherence (would these characters look natural in this background?)

Reply with ONLY a JSON object:
{"compatible": true/false, "issues": "brief description of issues or 'none'", "score": 1-10}
Output ONLY the JSON, no markdown."""

MAX_RETRIES = 3
TARGET_W, TARGET_H = 3840, 1200


def _get_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def _headers(key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        h["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        h["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return h


def _url(model: str, key: str) -> str:
    u = f"{API_BASE}/{model}:generateContent"
    return u if key.startswith("sk-") else f"{u}?key={key}"


def _encode(path: Path) -> tuple[str, str]:
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return b64, mime


def _generate_bg(prompt: str) -> bytes | None:
    """调用 Gemini 文生图，返回图片 bytes。"""
    key = _get_key()
    if not key:
        return None
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }).encode()
    for model in _get_image_models():
        print(f"[step4] 生图 model={model} ...", flush=True)
        req = urllib.request.Request(_url(model, key), data=body, headers=_headers(key), method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts:
                    if "inlineData" in p:
                        return base64.b64decode(p["inlineData"]["data"])
                print(f"[step4] model={model} 无图片响应", flush=True)
                break
            except urllib.error.HTTPError as e:
                err = (e.read().decode("utf-8", errors="replace") if e.fp else "")[:200]
                print(f"[step4] HTTP {e.code} model={model}: {err}", flush=True)
                if e.code in (403, 404):
                    break
                if e.code in (500, 503) and attempt < 2:
                    wait = 10 * (attempt + 1)
                    print(f"[step4] 重试 {attempt+1}/3，等待 {wait}s...", flush=True)
                    time.sleep(wait)
                    continue
                break
            except Exception as e:
                print(f"[step4] 异常: {e}", flush=True)
                if attempt < 2:
                    time.sleep(5)
    return None


def _check_bg_compatibility(char_path: Path, bg_path: Path) -> dict:
    """Gemini Vision 检查背景与人物的兼容性。"""
    key = _get_key()
    if not key:
        return {"compatible": True, "issues": "skip", "score": 7}
    b64_char, mime_char = _encode(char_path)
    b64_bg, mime_bg = _encode(bg_path)
    body = json.dumps({
        "contents": [{"parts": [
            {"text": BG_CHECK_PROMPT},
            {"inline_data": {"mime_type": mime_char, "data": b64_char}},
            {"inline_data": {"mime_type": mime_bg, "data": b64_bg}},
        ]}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    for model in VISION_MODELS:
        req = urllib.request.Request(_url(model, key), data=body, headers=_headers(key), method="POST")
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts:
                    if "text" in p:
                        text = p["text"]
                        start = text.find("{")
                        if start >= 0:
                            depth = 0
                            for i, c in enumerate(text[start:], start):
                                if c == "{":
                                    depth += 1
                                elif c == "}":
                                    depth -= 1
                                    if depth == 0:
                                        try:
                                            return json.loads(text[start:i+1])
                                        except Exception:
                                            break
            except Exception:
                if attempt < 1:
                    time.sleep(3)
    return {"compatible": True, "issues": "check failed", "score": 6}


def run_step4(user_prompt: str, char_ref_path: Path, out_dir: Path) -> Path:
    """
    生成背景图，检查兼容性，不合格则重试。
    返回最终 3840×1200 背景图路径。
    """
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    full_prompt = BG_GEN_PROMPT_TEMPLATE.format(user_prompt=user_prompt.strip() or "game banner epic scene")

    best_bg: Path | None = None
    best_score = 0

    for attempt in range(MAX_RETRIES):
        print(f"\n[step4] 背景生成 第 {attempt+1}/{MAX_RETRIES} 次...", flush=True)
        img_bytes = _generate_bg(full_prompt)
        if not img_bytes:
            print(f"[step4] 生图失败，跳过本次", flush=True)
            continue

        raw_path = out_dir / f"bg_raw_{attempt}.png"
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.save(str(raw_path))
        print(f"[step4] 原始背景: {img.size}", flush=True)

        # 检查兼容性
        print(f"[step4] 检查背景兼容性...", flush=True)
        check = _check_bg_compatibility(char_ref_path, raw_path)
        score = int(check.get("score", 5))
        compatible = check.get("compatible", True)
        print(f"[step4] 兼容性: compatible={compatible} score={score} issues={check.get('issues','')}", flush=True)

        if score > best_score:
            best_score = score
            best_bg = raw_path

        if compatible and score >= 6:
            print(f"[step4] 背景通过检查 (score={score})", flush=True)
            break
        else:
            print(f"[step4] 背景不合格，重新生成...", flush=True)

    if best_bg is None:
        raise RuntimeError("[step4] 所有背景生成均失败")

    # 缩放到 3840×1200
    final_path = out_dir / "bg_final.png"
    img = Image.open(best_bg).convert("RGB")
    if img.size != (TARGET_W, TARGET_H):
        # 等比缩放后居中裁切
        w, h = img.size
        scale = max(TARGET_W / w, TARGET_H / h)
        nw, nh = int(w * scale), int(h * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        x = (nw - TARGET_W) // 2
        y = (nh - TARGET_H) // 2
        img = img.crop((x, y, x + TARGET_W, y + TARGET_H))
        print(f"[step4] 缩放裁切: {img.size}", flush=True)
    img.save(str(final_path))
    print(f"[step4] 背景完成: {final_path}", flush=True)
    return final_path
