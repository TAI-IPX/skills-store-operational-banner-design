"""将合成图扩图到目标尺寸，使用 /v1/images/edits（支持 size 参数）"""
import base64, json, os, sys, re
from pathlib import Path
from io import BytesIO
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

env_file = ROOT / ".env"
for line in env_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k] = v.strip().strip("'\"")

API_KEY = os.environ.get("MICUAPI_API_KEY", "").strip()

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("input", help="输入合成图")
parser.add_argument("--width", type=int, default=2048)
parser.add_argument("--height", type=int, default=512)
parser.add_argument("--output", default=None)
args = parser.parse_args()

src = Path(args.input).resolve()
if not src.is_file():
    print(f"Error: 输入不存在: {src}", file=sys.stderr)
    sys.exit(1)

TW, TH = args.width, args.height
out = Path(args.output) if args.output else src.parent / f"{src.stem}_{TW}x{TH}.png"

im = Image.open(str(src)).convert("RGB")
iw, ih = im.size

scale = TH / ih
nw = max(1, int(iw * scale))
im = im.resize((nw, TH), Image.Resampling.LANCZOS)

canvas = Image.new("RGB", (TW, TH), (0, 0, 1))
x_offset = (TW - nw) // 2
canvas.paste(im, (x_offset, 0))

temp = str(ROOT / "output" / "_expand_input.png")
canvas.save(temp, "PNG")

img_bytes = Path(temp).read_bytes()
files = [("image", ("image.png", img_bytes, "image/png"))]

data = {
    "model": "gpt-image-2",
    "prompt": (
        "Extend this image horizontally to fill the entire canvas. "
        "The center area has the main content (characters and scene); "
        "the solid RGB(0,0,1) blue strips on the left and right sides are empty. "
        "Fill both sides by continuing the background naturally outward: "
        "same scene, same lighting, same perspective, same quality. "
        "Do NOT change the center area at all. "
        "Do NOT add new characters, people, or text. "
        "Make the transition from center to sides seamless."
    ),
    "size": f"{TW}x{TH}",
    "n": "1",
    "response_format": "url",
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

url = "https://www.micuapi.ai/v1/images/edits"
print(f"发图到 /v1/images/edits, size={TW}x{TH} ...", flush=True)
resp = requests.post(url, data=data, files=files, headers=headers, timeout=300)
resp.raise_for_status()
result = resp.json()

img_url = ""
for item in result.get("data", []):
    img_url = item.get("url", "")
    if img_url:
        break

if not img_url:
    print(f"No URL: {json.dumps(result, ensure_ascii=False)[:500]}", file=sys.stderr)
    sys.exit(1)

print(f"Downloading: {img_url[:80]}...", flush=True)
_proxies = None
_sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
if not _sys_proxy:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        if winreg.QueryValueEx(key, "ProxyEnable")[0]:
            _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
            if _sys_proxy and not _sys_proxy.startswith("http"):
                _sys_proxy = "http://" + _sys_proxy
        winreg.CloseKey(key)
    except Exception:
        pass
if _sys_proxy:
    _proxies = {"https": _sys_proxy, "http": _sys_proxy}
for dl_retry in range(4):
    try:
        _p = _proxies if dl_retry % 2 == 0 else None
        dl = requests.get(img_url, timeout=120, proxies=_p)
        dl.raise_for_status()
        break
    except Exception as e:
        if dl_retry < 3:
            import time; time.sleep(3)
        else:
            raise
out.write_bytes(dl.content)
im2 = Image.open(str(out))
print(f"DONE: {out} ({im2.size[0]}x{im2.size[1]})", flush=True)
