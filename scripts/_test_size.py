import sys, os, json, base64

env_file = ".env"
if os.path.isfile(env_file):
    for line in open(env_file, encoding="utf-8").readlines():
        line = line.strip()
        if line.startswith("MICUAPI_API_KEY="):
            os.environ["MICUAPI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

import requests
from PIL import Image

key = os.environ.get("MICUAPI_API_KEY", "").strip()

url = "https://www.micuapi.ai/v1/images/generations"
body = {
    "model": "gpt-image-2",
    "prompt": "Q版3D卡通风格 圆润充气造型 高中生角色跃起握拳冲刺姿态 糖果色系 暖橙背景",
    "n": 1,
    "size": "1920x640",
    "quality": "high",
    "response_format": "b64_json",
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {key}",
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "identity",  # disable chunked encoding
}

print("Requesting (no proxy)...", flush=True)
resp = requests.post(url, json=body, headers=headers, timeout=300, proxies=None, stream=True)
resp.raise_for_status()
raw = resp.content
data = json.loads(raw)

b64 = data.get("data", [{}])[0].get("b64_json", "")
if not b64:
    print(f"FAILED: no b64_json in response: {json.dumps(data, ensure_ascii=False)[:500]}")
    sys.exit(1)

raw_img = base64.b64decode(b64)
with open("output/test_1920x640.png", "wb") as f:
    f.write(raw_img)

img = Image.open("output/test_1920x640.png")
print(f"OK: {img.size[0]}x{img.size[1]} ratio={img.size[0]/img.size[1]:.2f}")
