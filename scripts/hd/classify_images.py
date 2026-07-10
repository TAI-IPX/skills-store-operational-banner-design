#!/usr/bin/env python3
"""
HD 生产线 Step 0：图片分类
从 OpenCode 缓存提取 5 张图，用 Gemini Vision 判断每张图的类型：
  - character: 人物/角色图（3张），并按主体质量排序（主角=最高分）
  - logo: 游戏 logo（1张）
  - title_art: 标题艺术字（1张）
返回 ClassifyResult(characters=[主角,左配角,右配角], logo=path, title_art=path)
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = ROOT / ".claude" / "skills"
VISION_SCRIPTS = SKILLS_DIR / "banner-background-from-image" / "scripts"
if str(VISION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VISION_SCRIPTS))

# 加载 .env
_env_file = ROOT / ".env"
if _env_file.is_file():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                if _k not in os.environ:
                    os.environ[_k] = _v.strip().strip("\"'")

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = (
    f"{_gemini_base}/v1beta/models"
    if _gemini_base
    else "https://generativelanguage.googleapis.com/v1beta/models"
)
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3-pro-preview"]

CLASSIFY_PROMPT = """Analyze this image and classify it into exactly ONE of these categories:

1. CHARACTER - The image contains a game character, person, or creature as the main subject. The character is clearly visible and takes up significant space.
2. LOGO - The image is a game logo, brand mark, or icon. It typically has a simple/transparent background with text and/or a symbol.
3. TITLE_ART - The image is title artwork, stylized text, or a title card. It's primarily decorative text/calligraphy used as a game title.

Also rate the image quality for banner use (1-10):
- For CHARACTER: rate based on clarity, composition, subject size, and visual appeal
- For LOGO/TITLE_ART: rate based on clarity and transparency/clean background

Reply with ONLY a JSON object, no markdown:
{"type": "CHARACTER" or "LOGO" or "TITLE_ART", "quality_score": <1-10>, "reason": "<one short sentence in Chinese>"}"""


@dataclass
class ClassifyResult:
    characters: list[Path]  # [主角, 左配角, 右配角]
    logo: Path | None
    title_art: Path | None


def _get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def _encode_image(path: Path) -> tuple[str, str]:
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return b64, mime


def _gemini_headers(key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        h["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        h["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return h


def _gemini_url(model: str, key: str) -> str:
    url = f"{API_BASE}/{model}:generateContent"
    if key.startswith("sk-"):
        return url
    return f"{url}?key={key}"


def _call_vision(image_path: Path, prompt: str) -> str | None:
    import urllib.request, urllib.error

    key = _get_api_key()
    if not key:
        return None
    b64, mime = _encode_image(image_path)
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
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
    ).encode()
    for model in VISION_MODELS:
        url = _gemini_url(model, key)
        req = urllib.request.Request(
            url, data=body, headers=_gemini_headers(key), method="POST"
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                parts = (
                    data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                )
                for p in parts:
                    if "text" in p:
                        return p["text"]
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                if e.code in (500, 503) and attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                break
            except Exception:
                if attempt < 2:
                    time.sleep(3)
                continue
    return None


def _parse_classify(text: str) -> dict | None:
    if not text:
        return None
    # extract JSON object
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return None
    return None


def classify_images(image_paths: list[Path], verbose: bool = True) -> ClassifyResult:
    """
    对 image_paths 中每张图调用 Gemini Vision 分类。
    返回 ClassifyResult(characters=[主角,左配角,右配角], logo, title_art)。
    """
    results: list[dict] = []
    for p in image_paths:
        if verbose:
            print(f"[classify] 分析: {p.name} ...", flush=True)
        text = _call_vision(p, CLASSIFY_PROMPT)
        parsed = _parse_classify(text) if text else None
        if parsed is None:
            # 兜底：按文件名猜测
            name = p.stem.lower()
            if any(k in name for k in ("logo",)):
                parsed = {"type": "LOGO", "quality_score": 5, "reason": "文件名推断"}
            elif any(k in name for k in ("title", "art", "text")):
                parsed = {
                    "type": "TITLE_ART",
                    "quality_score": 5,
                    "reason": "文件名推断",
                }
            else:
                parsed = {"type": "CHARACTER", "quality_score": 5, "reason": "默认推断"}
        img_type = parsed.get("type", "CHARACTER").upper()
        score = float(parsed.get("quality_score", 5))
        reason = parsed.get("reason", "")
        if verbose:
            print(f"  → type={img_type} score={score} reason={reason}", flush=True)
        results.append({"path": p, "type": img_type, "score": score})

    characters = sorted(
        [r for r in results if r["type"] == "CHARACTER"],
        key=lambda x: x["score"],
        reverse=True,
    )
    logos = [r for r in results if r["type"] == "LOGO"]
    title_arts = [r for r in results if r["type"] == "TITLE_ART"]

    # 若分类结果不足，按数量补充（优先保证3个人物）
    non_char = [r for r in results if r["type"] != "CHARACTER"]
    if len(characters) < 3 and non_char:
        # 把多余的非人物图按分数补入人物
        extra = sorted(non_char, key=lambda x: x["score"], reverse=True)
        while len(characters) < 3 and extra:
            characters.append(extra.pop(0))

    char_paths = [r["path"] for r in characters[:3]]
    # 补齐到3个（极端情况）
    while len(char_paths) < min(3, len(image_paths)):
        char_paths.append(image_paths[len(char_paths)])

    logo_path = logos[0]["path"] if logos else None
    title_art_path = title_arts[0]["path"] if title_arts else None

    if verbose:
        print(
            f"[classify] 主角: {char_paths[0].name if char_paths else '-'}", flush=True
        )
        if len(char_paths) > 1:
            print(f"[classify] 左配角: {char_paths[1].name}", flush=True)
        if len(char_paths) > 2:
            print(f"[classify] 右配角: {char_paths[2].name}", flush=True)
        print(f"[classify] logo: {logo_path.name if logo_path else '-'}", flush=True)
        print(
            f"[classify] title_art: {title_art_path.name if title_art_path else '-'}",
            flush=True,
        )

    return ClassifyResult(
        characters=char_paths,
        logo=logo_path,
        title_art=title_art_path,
    )
