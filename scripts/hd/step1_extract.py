#!/usr/bin/env python3
"""
HD 生产线 Step 1：Gemini bbox 检测 → 裁切 → BiRefNet 抠图
1a. Gemini Vision 识别完整人物 bbox（含头发/头饰/双手/指尖/肩饰/飘带）
1b. bbox 转像素坐标，加 margin 裁切
1c. BiRefNet 对裁切区域抠图，输出 RGBA PNG
"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BIREFNET_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if str(BIREFNET_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(BIREFNET_SCRIPTS))

from _env import load_env
load_env()

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3-pro-preview"]

BBOX_PROMPT = """Detect the COMPLETE bounding box of the main character/person in this image.

RULES:
- Fully enclose: head (ALL hair, accessories, hats), BOTH hands (ALL fingers/fingertips), full body
- Include shoulder decorations, ribbons, capes, wings, any prominent accessories
- Add small margin so nothing is clipped at edges
- If character is cut off at image edge, extend box to that edge

Reply with ONLY four decimal numbers (0.0 to 1.0): x_min y_min x_max y_max
x_min=left edge, y_min=top edge, x_max=right edge, y_max=bottom edge
Example: 0.05 0.02 0.95 0.98
Output ONLY the four numbers, no other text."""


def _get_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def _headers(key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if key.startswith("sk-"):
        h["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        h["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    return h


def _url(model: str, key: str) -> str:
    u = f"{API_BASE}/{model}:generateContent"
    return u if key.startswith("sk-") else f"{u}?key={key}"


def _encode(path: Path) -> tuple[str, str]:
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return b64, mime


def _call_vision(image_path: Path, prompt: str) -> str | None:
    key = _get_key()
    if not key:
        return None
    b64, mime = _encode(image_path)
    body = json.dumps({
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    for model in VISION_MODELS:
        req = urllib.request.Request(_url(model, key), data=body, headers=_headers(key), method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts:
                    if "text" in p:
                        return p["text"]
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break
                if e.code in (500, 503) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            except Exception:
                if attempt < 2:
                    time.sleep(3)
    return None


def _parse_bbox(text: str) -> tuple[float, float, float, float] | None:
    import re
    if not text:
        return None
    nums = re.findall(r"(?<!\d)(?:0?\.\d+|1\.0*|[01])(?!\d)", text.strip())
    floats = []
    for n in nums:
        try:
            v = float(n)
            if 0.0 <= v <= 1.0:
                floats.append(v)
        except Exception:
            pass
    # 取最后4个（thinking模型把答案放末尾）
    candidates = floats[-4:] if len(floats) >= 4 else floats[:4]
    if len(candidates) == 4:
        x_min, y_min, x_max, y_max = candidates
        if x_min < x_max and y_min < y_max:
            return (x_min, y_min, x_max, y_max)
    return None


def detect_character_bbox(image_path: Path) -> tuple[float, float, float, float]:
    """Gemini Vision 检测人物完整 bbox，失败时返回全图。"""
    print(f"[step1] Gemini bbox 检测: {image_path.name} ...", flush=True)
    text = _call_vision(image_path, BBOX_PROMPT)
    bbox = _parse_bbox(text) if text else None
    if bbox:
        print(f"[step1] bbox: {bbox}", flush=True)
        return bbox
    print(f"[step1] bbox 检测失败，使用全图", flush=True)
    return (0.0, 0.0, 1.0, 1.0)


def crop_with_margin(image_path: Path, bbox: tuple[float, float, float, float],
                     margin: float = 0.05):
    """按 bbox 加 margin 裁切，返回 (cropped_img, pixel_rect)。"""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    x_min, y_min, x_max, y_max = bbox
    mx = (x_max - x_min) * margin
    my = (y_max - y_min) * margin
    x1 = max(0, int((x_min - mx) * w))
    y1 = max(0, int((y_min - my) * h))
    x2 = min(w, int((x_max + mx) * w))
    y2 = min(h, int((y_max + my) * h))
    cropped = img.crop((x1, y1, x2, y2))
    print(f"[step1] 裁切: ({x1},{y1})-({x2},{y2}) → {cropped.size}", flush=True)
    return cropped, (x1, y1, x2, y2)


def birefnet_extract(cropped_img, out_path: Path, alpha_threshold: float = 0.45) -> Path:
    """BiRefNet 抠图，输出 RGBA PNG。"""
    from birefnet_matting import load_birefnet_matting, extract_alpha_pil
    from PIL import Image
    import numpy as np

    print(f"[step1] BiRefNet 推理 {cropped_img.size} ...", flush=True)
    model = load_birefnet_matting()
    alpha = extract_alpha_pil(cropped_img, model=model)
    a_arr = (np.array(alpha, dtype=np.float32) / 255.0 >= alpha_threshold).astype(np.uint8) * 255
    alpha_bin = Image.fromarray(a_arr, mode="L")
    result = cropped_img.convert("RGBA")
    result.putalpha(alpha_bin)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(out_path))
    print(f"[step1] 抠图完成: {out_path.name} {result.size}", flush=True)
    return out_path


def run_step1(image_paths: list[Path], out_dir: Path) -> list[Path]:
    """对每张人物图执行 bbox→裁切→BiRefNet，返回抠图路径列表。"""
    results = []
    for i, img_path in enumerate(image_paths):
        print(f"\n[step1] === 图片 {i}: {img_path.name} ===", flush=True)
        bbox = detect_character_bbox(img_path)
        cropped, _ = crop_with_margin(img_path, bbox, margin=0.05)
        out = out_dir / f"hd_cutout_{i:02d}.png"
        birefnet_extract(cropped, out)
        results.append(out)
    return results


def remove_white_bg(image_path: Path, out_path: Path, threshold: int = 240) -> Path:
    """
    将白底/近白底图片转为透明背景 RGBA PNG。
    threshold: RGB 三通道均 >= threshold 的像素视为白底，设为透明。
    """
    from PIL import Image
    import numpy as np

    img = Image.open(image_path).convert("RGBA")
    arr = np.array(img)
    r, g, b, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
    # 白底像素：RGB 均 >= threshold
    white_mask = (r >= threshold) & (g >= threshold) & (b >= threshold)
    arr[white_mask, 3] = 0  # 设为透明
    result = Image.fromarray(arr, "RGBA")

    # 裁切掉四周透明区域（tight crop）
    bbox = result.getbbox()
    if bbox:
        result = result.crop(bbox)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(out_path))
    print(f"[step1] 去白底完成: {image_path.name} → {out_path.name} {result.size}", flush=True)
    return out_path
