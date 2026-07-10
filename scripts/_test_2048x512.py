import sys, os, json, base64
from pathlib import Path
from io import BytesIO
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k.strip()] = v.strip().strip("'\"")

api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
base_url = "https://www.micuapi.ai/v1"

# Read the synthesized composite image
synthesized_path = ROOT / "output" / "synthesized_20260529_100419.png"
im = Image.open(str(synthesized_path)).convert("RGB")
buf = BytesIO()
im.save(buf, format="PNG")
ref_b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

prompt = """You are an expert banner compositing AI. I will give you one reference image containing three game characters composited together. 

Your task:
1. Create a SINGLE cohesive banner image at exactly 2048x512 pixels (4.0:1 aspect ratio). This is an ULTRA-WIDE horizontal banner.
2. Reproduce the three characters from the reference image, keeping their appearance, posture, and positions.
3. The three characters should occupy the middle 1/3 of the frame width, centered.
4. Extend the background naturally on both sides to fill the ultra-wide frame - same scene, same lighting, same quality.
5. The style should be high-quality game splash art / CG illustration.
6. Do not add any text or logo overlay.

Output the final banner image."""

# Approach A: /v1/images/generations (t2i) with size=2048x512
print("=== Approach A: /v1/images/generations, size=2048x512 ===", flush=True)
body_a = json.dumps({
    "model": "gpt-image-2",
    "prompt": prompt,
    "size": "2048x512",
    "quality": "high",
    "n": 1,
}).encode("utf-8")

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

resp_a = requests.post(f"{base_url}/images/generations", data=body_a, headers=headers, timeout=300)
print(f"Status: {resp_a.status_code}", flush=True)
data_a = resp_a.json()
url_a = ""
for item in data_a.get("data", []):
    url_a = item.get("url", "")
    if url_a: break

if url_a:
    import time
    for retry in range(4):
        try:
            _proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} if retry % 2 == 0 else None
            dl = requests.get(url_a, timeout=120, proxies=_proxies)
            dl.raise_for_status()
            out_a = str(ROOT / "output" / "test_gen_2048x512.png")
            open(out_a, "wb").write(dl.content)
            im_a = Image.open(out_a)
            print(f"Approach A result: {im_a.size[0]}x{im_a.size[1]} -> {out_a}", flush=True)
            break
        except Exception as e:
            if retry < 3:
                time.sleep(3)
            else:
                print(f"Download failed: {e}", flush=True)
else:
    print(f"No URL: {json.dumps(data_a, ensure_ascii=False)[:500]}", flush=True)

# Approach B: /v1/chat/completions with reference image + size
print("\n=== Approach B: /v1/chat/completions, reference + size=2048x512 ===", flush=True)
body_b = json.dumps({
    "model": "gpt-image-2",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref_b64}"}},
        ]
    }],
    "size": "2048x512",
}).encode("utf-8")

resp_b = requests.post(f"{base_url}/chat/completions", data=body_b, headers=headers, timeout=300)
print(f"Status: {resp_b.status_code}", flush=True)
data_b = resp_b.json()
url_b = ""
for choice in data_b.get("choices", []):
    ct = choice.get("message", {}).get("content", "")
    import re
    m = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', ct)
    if m:
        url_b = m.group(1)
        break

if url_b:
    for retry in range(4):
        try:
            _proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"} if retry % 2 == 0 else None
            dl = requests.get(url_b, timeout=120, proxies=_proxies)
            dl.raise_for_status()
            out_b = str(ROOT / "output" / "test_chat_2048x512.png")
            open(out_b, "wb").write(dl.content)
            im_b = Image.open(out_b)
            print(f"Approach B result: {im_b.size[0]}x{im_b.size[1]} -> {out_b}", flush=True)
            break
        except Exception as e:
            if retry < 3:
                import time; time.sleep(3)
            else:
                print(f"Download failed: {e}", flush=True)
else:
    print(f"No URL: {json.dumps(data_b, ensure_ascii=False)[:500]}", flush=True)
