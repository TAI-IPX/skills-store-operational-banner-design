import sys, os, json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k.strip()] = v.strip().strip("'\"")

api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

# 测试1: /v1/images/generations + size=2048x512 (t2i, 验证模型是否支持 4:1)
print("=== Test1: /v1/images/generations size=2048x512 ===", flush=True)
body1 = json.dumps({
    "model": "gpt-image-2",
    "prompt": "a simple test image, abstract shapes",
    "size": "2048x512",
    "n": 1,
    "response_format": "url",
})
resp1 = requests.post("https://www.micuapi.ai/v1/images/generations", data=body1, headers=headers, timeout=180)
print(f"Status: {resp1.status_code}", flush=True)
text1 = resp1.text[:500]
print(f"Response: {text1}", flush=True)

# 测试2: /v1/chat/completions with size in body (验证 chat 端点是否支持 size)
print("\n=== Test2: /v1/chat/completions with size ===", flush=True)
body2 = json.dumps({
    "model": "gpt-image-2",
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Generate a simple test image at the exact requested size. Do not add text."}]}],
    "size": "2048x512",
})
resp2 = requests.post("https://www.micuapi.ai/v1/chat/completions", data=body2, headers=headers, timeout=180)
print(f"Status: {resp2.status_code}", flush=True)
print(f"Response: {resp2.text[:500]}", flush=True)
