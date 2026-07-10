#!/usr/bin/env python3
"""
战报 Vision：截图排序、AI 数据区排版等，走 MICU OpenAI 兼容 chat/completions。

环境变量：
  MICU_API_KEY
  MICU_API_BASE_URL  默认由 MICU_API_URL 推导为 https://www.micuapi.ai/v1
  MICU_VISION_MODEL   默认 gpt-4o（须支持识图）
  BATTLE_REPORT_VISION_BACKEND=micu|gemini  默认 micu（有 MICU_API_KEY 时）
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path

import requests

from scripts.battle_report.env_setup import load_dotenv

# MICU 账号若仅开通生图分组，chat/completions 会 model_not_found；同进程内跳过后续重试
_micu_vision_blocked = False


def micu_vision_available() -> bool:
    load_dotenv()
    return bool(os.environ.get("MICU_API_KEY", "").strip())


def vision_backend() -> str:
    global _micu_vision_blocked
    explicit = os.environ.get("BATTLE_REPORT_VISION_BACKEND", "").strip().lower()
    if explicit in ("gemini", "packy"):
        return "gemini"
    if explicit in ("micu", "micuapi"):
        return "micu"
    if _micu_vision_blocked:
        return "gemini"
    if micu_vision_available():
        return "micu"
    return "gemini"


def mark_micu_vision_blocked(reason: str = "") -> None:
    global _micu_vision_blocked
    if not _micu_vision_blocked:
        _micu_vision_blocked = True
        msg = "[战报] MICU 账号未开通识图模型，本进程内改用 Gemini Vision"
        if reason:
            msg += f"（{reason[:80]}）"
        print(msg, flush=True)


def micu_api_base() -> str:
    base = os.environ.get("MICU_API_BASE_URL", "").strip().rstrip("/")
    if base:
        return base
    url = os.environ.get("MICU_API_URL", "").strip()
    if "/images/" in url:
        return url.split("/images/", 1)[0].rstrip("/")
    if url.endswith("/v1"):
        return url.rstrip("/")
    if url:
        return url.rstrip("/")
    return "https://www.micuapi.ai/v1"


def micu_vision_models() -> list[str]:
    for key in ("MICU_VISION_MODEL", "MICU_CHAT_MODEL"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return [m.strip() for m in raw.split(",") if m.strip()]
    return ["gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"]


def _encode_image_jpeg(path: Path, *, max_side: int = 0) -> str | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            if max_side > 0:
                w, h = im.size
                scale = min(1.0, max_side / max(w, h))
                if scale < 1.0:
                    im = im.resize(
                        (max(1, int(w * scale)), max(1, int(h * scale))),
                        Image.Resampling.LANCZOS,
                    )
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
            return base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except OSError:
        return None


def call_micu_vision_with_images(
    prompt: str,
    image_paths: list[Path],
    *,
    thumb_max: int = 0,
    timeout: int = 120,
) -> str | None:
    """MICU 多图识图 + 文本回复。"""
    global _micu_vision_blocked
    load_dotenv()
    if _micu_vision_blocked:
        return None
    key = os.environ.get("MICU_API_KEY", "").strip()
    if not key:
        return None

    content: list[dict] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        b64 = _encode_image_jpeg(p, max_side=thumb_max)
        if b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
            )
    if len(content) <= 1:
        return None

    url = f"{micu_api_base()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    for model in micu_vision_models():
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
        }
        for attempt in range(2):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    break
                message = choices[0].get("message") or {}
                text = message.get("content")
                if isinstance(text, str) and text.strip():
                    if model != micu_vision_models()[0]:
                        print(f"[战报/MICU Vision] 使用模型 {model}", flush=True)
                    return text
                break
            except requests.RequestException as exc:
                detail = ""
                if hasattr(exc, "response") and exc.response is not None:
                    try:
                        detail = exc.response.text[:400]
                    except Exception:
                        pass
                print(f"[战报/MICU Vision] 请求失败({model}): {exc} {detail}", flush=True)
                if "model_not_found" in detail or "vip_2_image" in detail:
                    mark_micu_vision_blocked("model_not_found")
                    return None
                if attempt == 0:
                    time.sleep(2)
    return None


def call_micu_vision_single(
    prompt: str,
    image_path: Path,
    *,
    timeout: int = 60,
) -> str | None:
    return call_micu_vision_with_images(prompt, [image_path], timeout=timeout)
