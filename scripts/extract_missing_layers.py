#!/usr/bin/env python3
"""补提 PSD 缺失图层"""
import sys, os, json, re, base64, time
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_env; load_env()

from PIL import Image
import requests

API_URL = "https://www.micuapi.ai/v1/chat/completions"
KEY = os.environ.get("MICUAPI_API_KEY", "").strip()
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/json",
}
INPUT_PATH = Path(__file__).resolve().parent.parent / "input" / "uploads" / "current.png"
OUT_DIR = sorted((Path(__file__).resolve().parent.parent / "output").glob("psd_layers_*"),
                 key=lambda x: x.stat().st_mtime, reverse=True)[0]

INPUT_SIZE = Image.open(INPUT_PATH).size

MISSING = [
    (4, "巨型发光字母A整"),
    (7, "中景人物角色"),
    (8, "悬浮全息UI卡片"),
    (9, "前景科技小模型"),
    (10, "雾效和氛围光"),
]

im = Image.open(INPUT_PATH).convert("RGBA")
w, h = im.size
MAX_D = 768
if max(w, h) > MAX_D:
    s = MAX_D / max(w, h)
    im = im.resize((max(1, int(w*s)), max(1, int(h*s))), Image.Resampling.LANCZOS)
buf = BytesIO()
im.save(buf, format="PNG")
b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

for idx, name in MISSING:
    print(f"[{idx}] Extracting: {name}...", flush=True)
    prompt = (
        f"Edit this image: Keep ONLY the '{name}' visible. "
        f"Remove everything else, make its area fully transparent. "
        f"Output PNG with transparent background showing only '{name}'. "
        f"Do not add, modify, or move the element."
    )
    body = json.dumps({"model": "gpt-image-2", "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}]}).encode("utf-8")

    dl_content = None
    for attempt in range(4):
        try:
            resp = requests.post(API_URL, data=body, headers=HEADERS, timeout=600, proxies=None)
            resp.raise_for_status()
            data = resp.json()
            img_url = ""
            for c in data.get("choices", []):
                ct = c.get("message", {}).get("content", "")
                if isinstance(ct, str):
                    m = re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", ct)
                    if m:
                        img_url = m.group(1)
                        break
            if not img_url:
                raise Exception(f"No URL in response: {json.dumps(data, ensure_ascii=False)[:200]}")

            for da in range(3):
                try:
                    dl = requests.get(img_url, timeout=300, stream=False)
                    dl.raise_for_status()
                    dl_content = dl.content
                    break
                except Exception as de:
                    if da < 2:
                        time.sleep(10)
                    else:
                        raise de
            break
        except Exception as e:
            wait = (attempt + 1) * 12
            emsg = str(e)[:100]
            print(f"  retry {attempt+1}/4: {emsg}, wait {wait}s", flush=True)
            if attempt < 3:
                time.sleep(wait)
            else:
                print(f"  FAILED after all retries", flush=True)

    if dl_content:
        safe_name = re.sub(r"[^\w]", "_", name)[:16]
        out_path = OUT_DIR / f"layer_{idx:02d}_{safe_name}.png"
        out_path.write_bytes(dl_content)
        im2 = Image.open(out_path).convert("RGBA")
        if im2.size != INPUT_SIZE:
            im2 = im2.resize(INPUT_SIZE, Image.Resampling.LANCZOS)
        im2.save(out_path, "PNG")
        print(f"  saved: {out_path.name} ({im2.size[0]}x{im2.size[1]})", flush=True)

    time.sleep(6)

print("\nAll missing layers done", flush=True)
