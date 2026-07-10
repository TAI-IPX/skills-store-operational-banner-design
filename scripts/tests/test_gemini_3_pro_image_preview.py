#!/usr/bin/env python3
"""仅测试 Packy 上 gemini-3-pro-image-preview（与 gemini_image_edit 请求体一致）。"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemini-3-pro-image-preview"
BASE = "https://www.packyapi.com"

env_file = ROOT / ".env"
env = {}
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip("\"'")

api_key = env.get("PACKY_API_KEY") or env.get("GEMINI_API_KEY", "")
if not api_key:
    print("Error: set PACKY_API_KEY or GEMINI_API_KEY in .env", file=sys.stderr)
    sys.exit(1)

_1x1_png = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
)
body = {
    "contents": [
        {
            "parts": [
                {"text": "Reply with one short word describing this image only."},
                {"inlineData": {"mimeType": "image/png", "data": _1x1_png}},
            ]
        }
    ],
    "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {"imageSize": "2K"},
    },
}

headers = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
if api_key.strip().startswith("sk-"):
    headers["Authorization"] = f"Bearer {api_key}"

url_bearer = f"{BASE}/v1beta/models/{MODEL}:generateContent"
url_query = f"{url_bearer}?key={urllib.parse.quote(api_key, safe='')}"

print(f"Model: {MODEL}")
print(f"Key:   {api_key[:10]}...")
print()


def try_request(name: str, url: str, hdrs: dict) -> dict | None:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [{name}] HTTP {e.code}: {e.read().decode(errors='replace')[:400]}")
        return None
    except Exception as e:
        print(f"  [{name}] error: {e}")
        return None


resp = None
# 1) Bearer（与仓库 gemini_image_edit 一致）
h1 = dict(headers)
resp = try_request("Bearer + generateContent", url_bearer, h1)

# 2) 仅 ?key=（无 Authorization）
if resp is None or (isinstance(resp.get("code"), int) and resp.get("code") != 0):
    h2 = {k: v for k, v in headers.items() if k != "Authorization"}
    r2 = try_request("?key= + generateContent", url_query, h2)
    if r2 is not None:
        resp = r2

# 3) OpenAI 兼容（仅文本探活，不要求出图）
if resp is None or (isinstance(resp.get("code"), int) and resp.get("code") != 0):
    openai_url = f"{BASE}/v1/chat/completions"
    openai_body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 16,
    }
    ho = {
        "Content-Type": "application/json",
        "User-Agent": headers["User-Agent"],
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data_o = json.dumps(openai_body).encode("utf-8")
    req_o = urllib.request.Request(openai_url, data=data_o, method="POST", headers=ho)
    try:
        with urllib.request.urlopen(req_o, timeout=60) as r:
            resp_o = json.loads(r.read().decode("utf-8"))
        ch = (resp_o.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if ch:
            print("[OK] OpenAI /v1/chat/completions (text only):", ch.strip()[:80])
            sys.exit(0)
        print("[FAIL] OpenAI response no content:", str(resp_o)[:500])
    except urllib.error.HTTPError as e:
        print(f"[FAIL] OpenAI HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
    except Exception as e:
        print(f"[FAIL] OpenAI error: {e}")

if resp is None:
    sys.exit(1)

# Packy 包装：顶层 code/msg
if isinstance(resp.get("code"), int) and resp.get("code") != 0:
    print("[FAIL] Packy wrapper:", resp.get("msg") or resp)
    sys.exit(1)

cands = resp.get("candidates") or []
if not cands:
    print("[FAIL] No candidates. Full keys:", list(resp.keys()))
    print(json.dumps(resp, ensure_ascii=False)[:1200])
    sys.exit(1)

parts = cands[0].get("content", {}).get("parts", [])
has_txt = any("text" in p for p in parts)
has_img = any("inlineData" in p for p in parts)
print("[OK] candidates=1")
print(f"     has text: {has_txt}")
print(f"     has image: {has_img}")
for p in parts:
    if "text" in p:
        print(f"     text: {p['text'][:200]}")
    if "inlineData" in p:
        d = p["inlineData"]
        n = len(d.get("data") or "")
        print(f"     image mime={d.get('mimeType')} base64_len={n}")
