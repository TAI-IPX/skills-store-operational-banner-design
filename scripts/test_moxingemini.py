#!/usr/bin/env python3
"""Test moxingemini models for text and vision capability."""
import os, sys, json, base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts._env import load_env
load_env(("MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL"))

import requests

key = os.environ.get("MOXINGEMINI_API_KEY", "").strip()
base = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").rstrip("/")
h = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

model_env = os.environ.get("MOXINGEMINI_MODEL", "").strip()
if model_env:
    models = [model_env]
else:
    models = [
        "[特价次卡]gemini-3.1-pro-preview-think",
        "[特价次卡]gemini-3.1-pro-preview",
        "[特价次卡]gemini-2.5-pro",
        "[次]gemini-3.1-flash-image-preview",
        "[次]gemini-3.1-flash-image",
        "[次]gemini-3-pro-image",
        "[次]gemini-3-pro-image-preview",
    ]

# Test 1: text only
print("=== 纯文本测试 ===")
for m in models:
    body = {"model": m, "messages": [{"role": "user", "content": "Reply with: PONG"}]}
    try:
        r = requests.post(base + "/v1/chat/completions", json=body, headers=h, timeout=20)
        d = r.json()
        choices = d.get("choices", [])
        if choices:
            print(f"[TEXT OK] {m}: {choices[0]['message']['content'][:60]}")
        else:
            print(f"[TEXT FAIL] {m}: {json.dumps(d, ensure_ascii=False)[:120]}")
    except Exception as e:
        print(f"[TEXT ERR] {m}: {e}")

# Test 2: vision (small image)
print("\n=== Vision 测试（小图）===")
img_path = ROOT / "output" / "商店日常_暑期摸鱼清单_20260707_162602" / "bg.png"
if img_path.is_file():
    from PIL import Image
    from io import BytesIO
    im = Image.open(img_path).convert("RGB").resize((256, 80))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=70)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    for m in models:
        body = {
            "model": m,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "What is in this image? Reply in 5 words."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
            ]}],
        }
        try:
            r = requests.post(base + "/v1/chat/completions", json=body, headers=h, timeout=30)
            d = r.json()
            choices = d.get("choices", [])
            if choices:
                print(f"[VISION OK] {m}: {choices[0]['message']['content'][:80]}")
            else:
                print(f"[VISION FAIL] {m}: {json.dumps(d, ensure_ascii=False)[:150]}")
        except Exception as e:
            print(f"[VISION ERR] {m}: {e}")
else:
    print(f"测试图不存在: {img_path}")
