#!/usr/bin/env python3
"""
Ask Gemini for natural line-break position for banner main title only (generic rules).
Uses GEMINI_API_KEY (text-only, no image). Returns (main_break, None); subtitle has no line-break rule.
"""

import json
import os
import re
import urllib.error
import urllib.request

# Text-in text-out model
MODEL = "gemini-2.0-flash"
_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"


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


def _get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def _build_prompt(main_title: str) -> str:
    return f"""你是一个中文排版助手。下面是一条 Banner 的主标题，需要给出一个换行位置（最多 2 行，主标题≥10 字时按语义断行，约每行 10 字内）。

**主标题**：{main_title!r}

规则（通用，适用于任意中文标题）：
- **禁止在词语中间断开**：不得拆开多字词，例如「互联网」「独立游戏」「白皮书」「业务」「服务」等必须保持完整。
- **优先在短语边界断行**：在「的」后、或语义短语结束处换行，两行长度尽量均衡。

正确示例：主标题「我们喜爱的独立游戏」→ 在第一行保留 5 字后换行，即第一行「我们喜爱的」，第二行「独立游戏」（回复 5）。
错误示例：不要回复 4（会变成「我们喜爱」+「的独立游戏」，的与独立拆开）；不要回复 6（会变成「我们喜爱的独」+「立游戏」，拆开「独立」）。

只回复一个整数：主标题第一行保留几个字后换行（1 到 主标题长度-1）；若主标题不超过 10 字可回复 0 表示不换行。不要其他文字。"""


def _parse_one_int(text: str) -> int | None:
    """Parse first integer from model output. Returns None on failure."""
    if not text or not text.strip():
        return None
    parts = re.split(r"[\s,]+", text.strip())
    for p in parts:
        if not p:
            continue
        try:
            return int(p)
        except ValueError:
            continue
    return None


def get_line_breaks(main_title: str, subtitle: str = "") -> tuple[int | None, int | None]:
    """
    Call Gemini to get main_break (subtitle has no line-break rule; second value always None).
    Returns (None, None) if key missing, API error, or parse failure.
    """
    api_keys = _get_api_keys()
    if not api_keys or not main_title:
        return (None, None)

    model = os.environ.get("GEMINI_LINEBREAK_MODEL", MODEL)
    prompt_text = _build_prompt(main_title)
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}]
    }

    for key in api_keys:
        if not key or not key.strip():
            continue
        _base_url = f"{API_BASE}/{model}:generateContent"
        url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
        headers = {"Content-Type": "application/json"}
        if key.strip().startswith("sk-"):
            headers["Authorization"] = f"Bearer {key}"
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and key != api_keys[-1]:
                continue  # try next key
            return (None, None)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return (None, None)

        candidates = data.get("candidates") or []
        if not candidates:
            return (None, None)
        parts = candidates[0].get("content", {}).get("parts") or []
        for part in parts:
            if "text" in part:
                raw = _parse_one_int(part["text"])
                main_break = None
                if raw is not None and main_title and 0 <= raw < len(main_title) and raw > 0:
                    main_break = raw
                return (main_break, None)  # subtitle has no break rule
        return (None, None)
    return (None, None)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: gemini_linebreak.py <main_title>", file=sys.stderr)
        sys.exit(1)
    m, _ = get_line_breaks(sys.argv[1])
    if m is None:
        print("No result.", file=sys.stderr)
        sys.exit(1)
    print(f"main_break={m}")
