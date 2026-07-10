#!/usr/bin/env python3
"""
HD 生产线 Vision：默认 MICU（OpenAI 兼容 chat/completions）。

环境变量：
  HD_VISION_BACKEND=micu|gemini  默认 micu（有 MICU_API_KEY 时）
  HD_VISION_GEMINI_FALLBACK=1    仅当显式开启时，MICU 失败后回退 Gemini
  MICU_API_KEY / MICU_VISION_MODEL  见 scripts/battle_report/micu_vision.py
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.is_file():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k not in os.environ:
                        os.environ[k] = v.strip().strip("\"'")


def hd_vision_backend() -> str:
    _load_env()
    explicit = os.environ.get("HD_VISION_BACKEND", "").strip().lower()
    if explicit in ("gemini", "packy"):
        return "gemini"
    if explicit in ("micu", "micuapi"):
        return "micu"
    try:
        from scripts.battle_report.micu_vision import micu_vision_available

        if micu_vision_available():
            return "micu"
    except Exception:
        pass
    return "gemini"


def _vision_gemini_fallback_enabled() -> bool:
    return os.environ.get("HD_VISION_GEMINI_FALLBACK", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_openai_vision_base(base_url: str) -> bool:
    return "centos.hk" in base_url or "api.centos.hk" in base_url or "moxin.studio" in base_url


def _openai_vision(image_path: Path, prompt: str, key: str, base: str, timeout: int = 45) -> str | None:
    """OpenAI-compatible /v1/chat/completions Vision (centos.hk)."""
    models_raw = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash,gemini-3-flash-preview")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    with open(image_path, "rb") as f:
        raw = f.read()
    mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    if "packyapi.com" in base:
        headers["User-Agent"] = "Mozilla/5.0"
    api_url = f"{base}/v1/chat/completions"

    for model in models:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
            "max_tokens": 4096,
        }).encode()
        req = urllib.request.Request(api_url, data=body, headers=headers, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return content
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                if e.code in (500, 503) and attempt < 2:
                    time.sleep(4)
                    continue
                break
            except Exception:
                if attempt < 2:
                    time.sleep(2)
    return None


def _openai_vision_multi(image_paths: list[Path], prompt: str, key: str, base: str, timeout: int = 60) -> str | None:
    """OpenAI-compatible /v1/chat/completions multi-image Vision (centos.hk)."""
    models_raw = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash,gemini-3-flash-preview")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    content: list[dict] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        if not p.is_file():
            continue
        with open(p, "rb") as f:
            raw = f.read()
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        b64 = base64.standard_b64encode(raw).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    if len(content) <= 1:
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    if "packyapi.com" in base:
        headers["User-Agent"] = "Mozilla/5.0"
    api_url = f"{base}/v1/chat/completions"

    for model in models:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 4096,
        }).encode()
        req = urllib.request.Request(api_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            content_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content_text:
                return content_text
        except Exception:
            continue
    return None


def _gemini_vision(image_path: Path, prompt: str, *, timeout: int = 45) -> str | None:
    _load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")

    # centos.hk / moxin.studio 使用 OpenAI 兼容 /v1/chat/completions
    if _is_openai_vision_base(base):
        return _openai_vision(image_path, prompt, key, base, timeout)

    api_base = f"{base}/v1beta/models" if base else "https://generativelanguage.googleapis.com/v1beta/models"
    models_raw = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash,gemini-3-flash-preview")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    with open(image_path, "rb") as f:
        raw = f.read()
    mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    b64 = base64.standard_b64encode(raw).decode("ascii")
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
    headers = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        headers["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in base:
        headers["User-Agent"] = "Mozilla/5.0"

    for model in models:
        url = f"{api_base}/{model}:generateContent"
        if not key.startswith("sk-"):
            url = f"{url}?key={key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
                for p in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    if "text" in p:
                        return p["text"]
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                if e.code in (500, 503) and attempt < 2:
                    time.sleep(4)
                    continue
                break
            except Exception:
                if attempt < 2:
                    time.sleep(2)
    return None


def call_hd_vision(image_path: Path, prompt: str, *, timeout: int = 45) -> str | None:
    """单图 Vision，返回模型文本。"""
    if not image_path.is_file():
        return None
    backend = hd_vision_backend()
    if backend == "micu":
        from scripts.battle_report.micu_vision import call_micu_vision_single

        print(f"[hd_vision] MICU Vision: {image_path.name}", flush=True)
        text = call_micu_vision_single(prompt, image_path, timeout=timeout)
        if text:
            return text
        if _vision_gemini_fallback_enabled():
            print("[hd_vision] MICU Vision 不可用，回退 Gemini Vision", flush=True)
        else:
            print("[hd_vision] MICU Vision 不可用（未开启 HD_VISION_GEMINI_FALLBACK）", flush=True)
            return None
    else:
        print(f"[hd_vision] Gemini Vision: {image_path.name}", flush=True)
    return _gemini_vision(image_path, prompt, timeout=timeout)


def _gemini_vision_multi(
    image_paths: list[Path],
    prompt: str,
    *,
    timeout: int = 60,
) -> str | None:
    _load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")

    # centos.hk / moxin.studio 使用 OpenAI 兼容 /v1/chat/completions
    if _is_openai_vision_base(base):
        return _openai_vision_multi(image_paths, prompt, key, base, timeout)

    api_base = f"{base}/v1beta/models" if base else "https://generativelanguage.googleapis.com/v1beta/models"
    models_raw = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash,gemini-3-flash-preview")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]

    parts: list[dict] = [{"text": prompt}]
    for p in image_paths:
        if not p.is_file():
            continue
        with open(p, "rb") as f:
            raw = f.read()
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        b64 = base64.standard_b64encode(raw).decode("ascii")
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    if len(parts) <= 1:
        return None
    body = json.dumps(
        {
            "contents": [{"parts": parts}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        headers["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in base:
        headers["User-Agent"] = "Mozilla/5.0"

    for model in models:
        url = f"{api_base}/{model}:generateContent"
        if not key.startswith("sk-"):
            url = f"{url}?key={key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            for p in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "text" in p:
                    return p["text"]
        except Exception:
            continue
    return None


def call_hd_vision_multi(
    prompt: str,
    image_paths: list[Path],
    *,
    timeout: int = 60,
) -> str | None:
    paths = [p for p in image_paths if p.is_file()]
    if not paths:
        return None
    backend = hd_vision_backend()
    if backend == "micu":
        from scripts.battle_report.micu_vision import call_micu_vision_with_images

        print(f"[hd_vision] MICU Vision ×{len(paths)}", flush=True)
        text = call_micu_vision_with_images(prompt, paths, timeout=timeout)
        if text:
            return text
        if _vision_gemini_fallback_enabled():
            print("[hd_vision] MICU Vision 不可用，回退 Gemini Vision", flush=True)
        else:
            print("[hd_vision] MICU Vision 不可用（未开启 HD_VISION_GEMINI_FALLBACK）", flush=True)
            return None
    else:
        print(f"[hd_vision] Gemini Vision ×{len(paths)}", flush=True)
    return _gemini_vision_multi(paths, prompt, timeout=timeout)
