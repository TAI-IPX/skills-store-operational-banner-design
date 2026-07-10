"""测试 A4 替代方案：文生图背景 + Pillow 叠主体"""
import sys, os
from pathlib import Path

# load .env
for line in open(".env", encoding="utf-8").readlines():
    line = line.strip()
    if line.startswith("MICUAPI_API_KEY="):
        os.environ["MICUAPI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

sys.path.insert(0, "scripts")
import base64, json
import requests
from PIL import Image, ImageFilter
import numpy as np

key = os.environ["MICUAPI_API_KEY"]
OUT_DIR = Path("output")

# === Step 1: 文生图纯背景 ===
url = "https://www.micuapi.ai/v1/images/generations"
body = {
    "model": "gpt-image-2",
    "prompt": "Q版3D卡通风格 暖橙蓝渐变抽象背景 柔和几何装饰元素 模糊光斑 无人物 无文字 横版",
    "n": 1, "size": "1024x640", "quality": "high",
    "response_format": "url",
}
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
print("[A4 test] 生成背景...", flush=True)
resp = requests.post(url, json=body, headers=headers, timeout=300)
resp.raise_for_status()
data = resp.json()
img_url = next((item.get("url", "") for item in data.get("data", [])), "")
if not img_url:
    print("FAILED: no url"); sys.exit(1)

# download with retry
for retry in range(4):
    try:
        dl = requests.get(img_url, timeout=120, proxies={"https": "http://127.0.0.1:7890", "http": "http://127.0.0.1:7890"} if retry % 2 == 0 else None)
        dl.raise_for_status(); break
    except Exception as e:
        if retry < 3: import time; time.sleep(2)
        else: raise

bg_raw = OUT_DIR / "_test_a4_bg_raw.png"
bg_raw.write_bytes(dl.content)
bg = Image.open(bg_raw).convert("RGB")
print(f"[A4 test] 背景: {bg.size[0]}x{bg.size[1]}", flush=True)

# === Step 2: resize 背景到 4096x1024 ===
bg = bg.resize((4096, 1024), Image.Resampling.LANCZOS)

# === Step 3: 叠入原图主体 ===
from pathlib import Path
subject = Image.open(Path("input/Clipboard - 2026-06-01 10.00.56.png")).convert("RGB")
sw, sh = subject.size
# 缩放到安全区比例: 主体填入 4096 画布的安全区 x≈1536-3072, y=0-1024
# target_bbox_width = 3072-1536 = 1536, target_bbox_height = 1024
scale = min(1536 / sw, 1024 / sh)
nw, nh = int(sw * scale), int(sh * scale)
subject = subject.resize((nw, nh), Image.Resampling.LANCZOS)
# 居中粘贴
px = (4096 - nw) // 2
py = (1024 - nh) // 2

# 主体区域羽化 mask（接缝柔和）
mask = Image.new("L", (nw, nh), 255)
# 边缘渐变: 外围 30px 从透明渐入
edge = 30
for x in range(nw):
    for y in range(nh):
        dist = min(x, y, nw - 1 - x, nh - 1 - y)
        if dist < edge:
            mask.putpixel((x, y), int(255 * dist / edge))

mask_blur = mask.filter(ImageFilter.GaussianBlur(radius=8))
bg.paste(subject, (px, py), mask_blur)
out = OUT_DIR / "_test_a4_composited.png"
bg.save(out, "PNG")
print(f"[A4 test] 完成: {out} ({bg.size[0]}x{bg.size[1]})", flush=True)
