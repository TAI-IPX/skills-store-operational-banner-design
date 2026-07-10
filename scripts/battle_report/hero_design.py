#!/usr/bin/env python3
"""战报头图数据区：可选 MICU / Gemini Vision 读 KV+theme 给出排版参数。"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_HERO_DESIGN: dict[str, Any] = {
    "layout": "plain",
    "panel_title": "",
    "panel_width": 1000,
    "panel_height": 320,
    "value_font_size": 96,
    "label_font_size": 30,
    "ornament": "low",
    "glow": False,
    "source": "default",
}


def _load_dotenv() -> None:
    from scripts.battle_report.env_setup import setup_battle_report_env

    setup_battle_report_env()


def _vision_models() -> list[str]:
    raw = os.environ.get("GEMINI_VISION_MODEL", "").strip()
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return ["gemini-3-flash-preview", "gemini-2.5-flash"]


def _api_base() -> str:
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
    return f"{base}/v1beta/models" if base else "https://generativelanguage.googleapis.com/v1beta/models"


def _image_part(path: Path, *, max_side: int = 0) -> dict[str, str] | None:
    """inline_data part；max_side>0 时先缩小再编码（多图排序用）。"""
    try:
        from PIL import Image
        import io

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
            raw = buf.getvalue()
            mime = "image/jpeg"
    except OSError:
        return None
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return {"inline_data": {"mime_type": mime, "data": b64}}


_last_vision_source: str = "gemini"


def last_vision_source() -> str:
    return _last_vision_source


def _gemini_vision_with_images(
    prompt: str, image_paths: list[Path], *, thumb_max: int = 0
) -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    parts: list[dict] = [{"text": prompt}]
    for p in image_paths:
        block = _image_part(p, max_side=thumb_max)
        if block:
            parts.append(block)
    if len(parts) <= 1:
        return None
    return _post_vision_parts(parts, timeout=120)


def call_vision_with_images(prompt: str, image_paths: list[Path], *, thumb_max: int = 0) -> str | None:
    """Vision 多图：默认 MICU（MICU_API_KEY），失败时回退 Gemini。"""
    global _last_vision_source
    from scripts.battle_report.micu_vision import call_micu_vision_with_images, vision_backend

    if vision_backend() == "micu":
        text = call_micu_vision_with_images(prompt, image_paths, thumb_max=thumb_max)
        if text is not None:
            _last_vision_source = "micu"
            return text
        if os.environ.get("GEMINI_API_KEY", "").strip():
            print("[战报] MICU Vision 不可用，回退 Packy/Gemini Vision", flush=True)
            _last_vision_source = "gemini"
            return _gemini_vision_with_images(prompt, image_paths, thumb_max=thumb_max)
        return None
    _last_vision_source = "gemini"
    return _gemini_vision_with_images(prompt, image_paths, thumb_max=thumb_max)


def _call_vision(kv_path: Path, prompt: str) -> str | None:
    from scripts.battle_report.micu_vision import call_micu_vision_single, vision_backend

    if vision_backend() == "micu":
        text = call_micu_vision_single(prompt, kv_path)
        if text is not None:
            return text
        if os.environ.get("GEMINI_API_KEY", "").strip():
            print("[战报] MICU Vision 不可用，回退 Packy/Gemini Vision", flush=True)
            return _gemini_vision_with_images(prompt, [kv_path])
        return None
    block = _image_part(kv_path)
    if not block:
        return None
    return _post_vision_parts([{"text": prompt}, block])


def _get_api_keys() -> list[str]:
    """返回 [主 key, ALT key] 列表（去重、去空）"""
    keys: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    alt = os.environ.get("GEMINI_API_KEY_ALT", "").strip()
    if alt and alt != primary:
        keys.append(alt)
    return keys


def _is_openai_vision_base() -> bool:
    """Check if GOOGLE_GEMINI_BASE_URL requires OpenAI-compatible /v1/chat/completions format."""
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""
    return "centos.hk" in base or "api.centos.hk" in base or "moxin.studio" in base


def _openai_chat_vision(parts: list[dict], *, timeout: int = 45) -> str | None:
    """OpenAI-compatible /v1/chat/completions Vision for centos.hk / moxin.studio."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").rstrip("/")
    if not base:
        return None

    content: list[dict] = []
    for p in parts:
        if "text" in p:
            content.append({"type": "text", "text": p["text"]})
        elif "inline_data" in p:
            d = p["inline_data"]
            content.append({"type": "image_url", "image_url": {"url": f"data:{d['mime_type']};base64,{d['data']}"}})

    models = _vision_models()
    for model in models:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    f"{base}/v1/chat/completions", data=body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
                for c in data.get("choices", []):
                    ct = c.get("message", {}).get("content", "")
                    if isinstance(ct, str) and ct.strip():
                        return ct.strip()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                if attempt == 0:
                    time.sleep(2)
            except Exception:
                if attempt == 0:
                    time.sleep(2)
    return None


def _post_vision_parts(parts: list[dict], *, timeout: int = 45) -> str | None:
    # centos.hk / moxin.studio → OpenAI 兼容 /v1/chat/completions
    if _is_openai_vision_base():
        return _openai_chat_vision(parts, timeout=timeout)

    api_keys = _get_api_keys()
    if not api_keys:
        return None
    body = json.dumps(
        {
            "contents": [{"parts": parts}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
    ).encode()
    for key in api_keys:
        if not key or not key.strip():
            continue
        headers = {"Content-Type": "application/json"}
        if key.startswith("sk-"):
            headers["Authorization"] = f"Bearer {key}"
        if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
            headers["User-Agent"] = "Mozilla/5.0"

        try_next_key = False
        for model in _vision_models():
            url = f"{_api_base()}/{model}:generateContent"
            if not key.startswith("sk-"):
                url = f"{url}?key={key}"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        data = json.loads(r.read())
                    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                        if "text" in part:
                            return part["text"]
                except urllib.error.HTTPError as e:
                    if e.code == 401:
                        if key != api_keys[-1]:
                            try_next_key = True
                            break  # break attempt loop
                        break
                    if e.code in (403, 404):
                        break
                except Exception:
                    if attempt == 0:
                        time.sleep(2)
            if try_next_key:
                break
    return None


def _parse_design_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _clamp_design(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_HERO_DESIGN)
    title = raw.get("panel_title") or raw.get("title")
    if isinstance(title, str) and title.strip():
        out["panel_title"] = title.strip()[:12]
    layout = raw.get("layout")
    if layout in ("monument", "classic", "framed", "ai_stage", "plain"):
        out["layout"] = layout
    for key, lo, hi in (
        ("panel_width", 880, 1040),
        ("panel_height", 260, 400),
        ("value_font_size", 72, 128),
        ("label_font_size", 24, 36),
    ):
        v = raw.get(key)
        if isinstance(v, (int, float)):
            out[key] = int(max(lo, min(hi, v)))
    orn = raw.get("ornament")
    if orn in ("low", "medium", "high"):
        out["ornament"] = orn
    if "glow" in raw:
        out["glow"] = bool(raw["glow"])
    from scripts.battle_report.micu_vision import vision_backend

    out["source"] = "micu" if vision_backend() == "micu" else "gemini"
    return out


def resolve_hero_design(kv_path: Path, theme: dict[str, Any]) -> dict[str, Any]:
    """
    默认用大面板版式；设 BATTLE_REPORT_AI_DESIGN=1 且配置 MICU_API_KEY（或 GEMINI）时，
    由 Vision 结合 KV 与 theme Token 微调标题/字号/装饰强度。
    """
    _load_dotenv()
    flag = os.environ.get("BATTLE_REPORT_AI_DESIGN", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return dict(DEFAULT_HERO_DESIGN)

    prompt = f"""你是游戏战报头图的数据区排版顾问。参考「巨幕数据海报」：超大白色数字 + 暗场底光，根据附图 KV 与 theme 只输出一个 JSON（不要 markdown）。

theme:
- accent_primary: {theme.get("accent_primary")}
- accent_secondary: {theme.get("accent_secondary")}
- bg_page: {theme.get("bg_page")}

要求：
1. layout 固定为 monument（巨幕数字舞台，非小卡片排版）。
2. 数据区是全页视觉核心：panel_height 260–320，value_font_size 96–120，label_font_size 26–34。
3. ornament 建议 low（少角标，让数字说话）；glow: true。
4. panel_title 可省略或 0 字，monument 模式不显示小标题条。

JSON 字段（全部必填）:
layout, panel_title, panel_width, panel_height, value_font_size, label_font_size, ornament, glow
"""
    text = _call_vision(kv_path, prompt)
    parsed = _parse_design_json(text or "")
    if parsed:
        design = _clamp_design(parsed)
        print(
            f"[战报] AI 数据区设计: title={design['panel_title']} "
            f"h={design['panel_height']} value={design['value_font_size']}px ({design['source']})",
            flush=True,
        )
        return design
    print("[战报] AI 数据区设计未返回，使用默认大面板参数", flush=True)
    return dict(DEFAULT_HERO_DESIGN)
