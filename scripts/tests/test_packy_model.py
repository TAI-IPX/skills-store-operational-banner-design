#!/usr/bin/env python3
"""测试 Packy 上各模型是否可用（Vision text + Image edit）。"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env_file = ROOT / ".env"
env = {}
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip("\"'")

os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
api_key = env.get("PACKY_API_KEY") or env.get("GEMINI_API_KEY", "")
if not api_key:
    print("Error: PACKY_API_KEY / GEMINI_API_KEY not set", file=sys.stderr)
    sys.exit(1)

base_url = "https://www.packyapi.com/v1beta/models"
is_sk = api_key.strip().startswith("sk-")

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
if is_sk:
    HEADERS["Authorization"] = f"Bearer {api_key}"


def make_url(model: str) -> str:
    endpoint = f"{base_url}/{model}:generateContent"
    return endpoint if is_sk else f"{endpoint}?key={api_key}"


def post(url: str, body: dict, timeout: int = 30) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=dict(HEADERS))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")[:400]
        try:
            return e.code, json.loads(body_txt)
        except Exception:
            return e.code, body_txt
    except Exception as e:
        return -1, str(e)


print(f"key: {api_key[:8]}...  sk-mode={is_sk}\n")

# ---- 1. Vision (text) 测试 ----
VISION_MODELS = [
    "gemini-3.1-flash-image-preview",  # 用户新加的
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-2.5-flash",
]
vision_body = {"contents": [{"parts": [{"text": "Reply with the single word: OK"}]}]}

print("=" * 55)
print("1. Vision text 测试（主体 bbox / 检测用）")
print("=" * 55)
for model in VISION_MODELS:
    code, resp = post(make_url(model), vision_body, timeout=20)
    if isinstance(resp, dict):
        txt = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if txt:
            print(f"  [OK] {model}: {txt.strip()[:60]}")
        else:
            err = resp.get("error") or resp
            print(f"  [FAIL {code}] {model}: {str(err)[:120]}")
    else:
        print(f"  [FAIL {code}] {model}: {resp[:120]}")

# ---- 2. Image edit 测试（图编用）----
# 用一张 1x1 白色像素 PNG 做最小测试，不传真图避免耗时
_1x1_png_b64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
)
IMAGE_MODELS = [
    "gemini-3-pro-image-preview",   # 用户看到的图编模型
    "gemini-3.1-flash-image-preview",  # 用户新加的（也支持图编）
]
image_body = {
    "contents": [{"parts": [
        {"text": "Describe this image in one word."},
        {"inlineData": {"mimeType": "image/png", "data": _1x1_png_b64}},
    ]}],
    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
}

print()
print("=" * 55)
print("2. Image edit 测试（outpaint / 图编用）")
print("=" * 55)
for model in IMAGE_MODELS:
    # 方式A：Bearer（sk- 走 Authorization header，不带 ?key=）
    headers_a = dict(HEADERS)
    url_a = f"{base_url}/{model}:generateContent"
    # 方式B：?key= 参数（不带 Authorization header）
    headers_b = {k: v for k, v in HEADERS.items() if k != "Authorization"}
    url_b = f"{base_url}/{model}:generateContent?key={api_key}"

    for label, url, hdrs in [("Bearer", url_a, headers_a), ("?key=", url_b, headers_b)]:
        data = json.dumps(image_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read().decode("utf-8"))
                code = r.status
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="replace")[:300]
            try:
                resp = json.loads(body_txt)
            except Exception:
                resp = body_txt
            code = e.code
        except Exception as ex:
            resp = str(ex)
            code = -1

        if isinstance(resp, dict):
            cands = resp.get("candidates") or []
            if cands:
                parts = cands[0].get("content", {}).get("parts", [])
                has_img = any("inlineData" in p for p in parts)
                has_txt = any("text" in p for p in parts)
                print(f"  [OK] {model} ({label}): candidates={len(cands)}, img={has_img}, txt={has_txt}")
            else:
                err = resp.get("error") or {k: v for k, v in resp.items() if k != "data"}
                print(f"  [FAIL {code}] {model} ({label}): {str(err)[:160]}")
        else:
            print(f"  [FAIL {code}] {model} ({label}): {str(resp)[:160]}")

print()
print("done.")
