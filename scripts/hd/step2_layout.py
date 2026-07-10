#!/usr/bin/env python3
"""
HD 生产线 Step 2：Gemini 智能排版
Gemini 分析 3 个抠图的清晰度/完整度/视觉重量，决定遮挡关系和位置。
主体高度比例：主角 95%，左配角 90%，右配角 88%（相对画布高度 1200px）
安全区：x=820~2660（legend_top_banner_3840 spec）
"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VISION_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if str(VISION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VISION_SCRIPTS))

from _env import load_env
load_env()

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3-pro-preview"]

CANVAS_W, CANVAS_H = 3840, 1200
# 安全区 x=820~2660（legend_top_banner_3840）
SAFE_X_MIN, SAFE_X_MAX = 820, 2660
# 主体高度比例
HEIGHT_RATIOS = [0.95, 0.90, 0.88]  # 主角/左配角/右配角

RANK_PROMPT = """You are given {n} character cutout images (transparent PNG). Analyze each one and rank them.

Criteria:
1. Visual quality: sharpness, detail level, clean edges
2. Completeness: full body visible (head, hands, feet), no major parts cut off
3. Visual weight: size, presence, how dominant the character looks

Reply with ONLY a JSON array of indices sorted from BEST to WORST.
Example for 3 images: [2, 0, 1] means image_2 is best (main character), image_0 is second, image_1 is third.
Output ONLY the JSON array, nothing else."""

BG_COLOR_PROMPT = """These are character cutouts arranged for a banner. Based on their visual style and the user's creative brief below, suggest a subtle gradient background color.

User brief: \"\"\"{prompt}\"\"\"

Reply with ONLY a JSON object:
{{"top_rgb":[R,G,B],"bottom_rgb":[R,G,B]}}
R,G,B are integers 0-255. No markdown, no explanation."""


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


def _call_vision_multi(image_paths: list[Path], prompt: str) -> str | None:
    """多图 Vision 请求。"""
    key = _get_key()
    if not key:
        return None
    parts = [{"text": prompt}]
    for p in image_paths:
        b64, mime = _encode(p)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    for model in VISION_MODELS:
        req = urllib.request.Request(_url(model, key), data=body, headers=_headers(key), method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                parts_resp = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts_resp:
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


def _call_vision_single(image_path: Path, prompt: str) -> str | None:
    return _call_vision_multi([image_path], prompt)


def rank_characters(cutout_paths: list[Path]) -> list[int]:
    """Gemini 分析抠图质量，返回排序后的索引（最佳→最差）。"""
    n = len(cutout_paths)
    print(f"[step2] Gemini 分析 {n} 个抠图质量...", flush=True)
    prompt = RANK_PROMPT.format(n=n)
    text = _call_vision_multi(cutout_paths, prompt)
    if text:
        import re
        m = re.search(r"\[[\d,\s]+\]", text)
        if m:
            try:
                order = json.loads(m.group())
                if len(order) == n and all(isinstance(i, int) and 0 <= i < n for i in order):
                    print(f"[step2] 排序结果: {order}", flush=True)
                    return order
            except Exception:
                pass
    print(f"[step2] 排序失败，使用默认顺序", flush=True)
    return list(range(n))


def suggest_bg_color(cutout_paths: list[Path], user_prompt: str) -> tuple[tuple, tuple]:
    """Gemini 建议渐变底色。"""
    print(f"[step2] Gemini 建议底色...", flush=True)
    prompt = BG_COLOR_PROMPT.format(prompt=user_prompt[:500])
    text = _call_vision_multi(cutout_paths[:1], prompt)
    if text:
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i, c in enumerate(text[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start:i+1])
                            top = tuple(int(x) for x in obj["top_rgb"])
                            bot = tuple(int(x) for x in obj["bottom_rgb"])
                            print(f"[step2] 底色: top={top} bottom={bot}", flush=True)
                            return top, bot
                        except Exception:
                            break
    print(f"[step2] 底色建议失败，使用默认", flush=True)
    return (20, 30, 60), (40, 60, 100)


def _make_gradient_bg(w: int, h: int, top_rgb: tuple, bottom_rgb: tuple):
    from PIL import Image
    import numpy as np
    top = np.array(top_rgb, dtype=np.float32)
    bottom = np.array(bottom_rgb, dtype=np.float32)
    t = np.linspace(0, 1, h).reshape(h, 1, 1)
    gradient = (top * (1 - t) + bottom * t).astype(np.uint8)
    gradient = np.broadcast_to(gradient, (h, w, 3)).copy()
    return Image.fromarray(gradient, "RGB")


def _paste_character(canvas, char_rgba, x_center: int, y_bottom: int, target_h: int):
    from PIL import Image
    cw, ch = char_rgba.size
    scale = target_h / ch
    new_w = max(1, int(round(cw * scale)))
    resized = char_rgba.resize((new_w, target_h), Image.Resampling.LANCZOS)
    x = x_center - new_w // 2
    y = y_bottom - target_h
    src_x = max(0, -x); src_y = max(0, -y)
    dst_x = max(0, x); dst_y = max(0, y)
    src_w = min(new_w - src_x, CANVAS_W - dst_x)
    src_h = min(target_h - src_y, CANVAS_H - dst_y)
    if src_w > 0 and src_h > 0:
        patch = resized.crop((src_x, src_y, src_x + src_w, src_y + src_h))
        canvas.paste(patch, (dst_x, dst_y), patch)


def run_step2(cutout_paths: list[Path], out_dir: Path, user_prompt: str = "") -> tuple[Path, list[dict]]:
    """
    智能排版，生成 layout_ref.png。
    返回 (layout_ref_path, layout_params)
    layout_params: [{"path": Path, "x_center": int, "y_bottom": int, "height": int, "z_order": int}, ...]
    """
    from PIL import Image

    n = len(cutout_paths)
    # Gemini 排序
    order = rank_characters(cutout_paths)
    ranked = [cutout_paths[i] for i in order]

    # 布局参数：主角居中，左配角偏左，右配角偏右
    # 安全区 x=820~2660，中心=1740
    safe_center = (SAFE_X_MIN + SAFE_X_MAX) // 2  # 1740
    positions = [
        {"x_center": safe_center, "y_bottom": CANVAS_H, "height": int(CANVAS_H * HEIGHT_RATIOS[0])},       # 主角
        {"x_center": SAFE_X_MIN + 200, "y_bottom": CANVAS_H - 30, "height": int(CANVAS_H * HEIGHT_RATIOS[1])},  # 左配角
        {"x_center": SAFE_X_MAX - 100, "y_bottom": CANVAS_H - 50, "height": int(CANVAS_H * HEIGHT_RATIOS[2])},  # 右配角
    ]

    layout_params = []
    for i, (path, pos) in enumerate(zip(ranked, positions[:n])):
        layout_params.append({
            "path": path,
            "x_center": pos["x_center"],
            "y_bottom": pos["y_bottom"],
            "height": pos["height"],
            "z_order": i,  # 0=最前（主角），越大越后
        })
        print(f"[step2] 角色{i}: {path.name} x={pos['x_center']} h={pos['height']}", flush=True)

    # 建议底色
    top_rgb, bot_rgb = suggest_bg_color(ranked[:1], user_prompt)
    bg = _make_gradient_bg(CANVAS_W, CANVAS_H, top_rgb, bot_rgb)
    canvas = bg.convert("RGBA")

    # 按 z_order 从大到小绘制（远→近）
    for lp in sorted(layout_params, key=lambda x: x["z_order"], reverse=True):
        if lp["path"].is_file():
            char_img = Image.open(lp["path"]).convert("RGBA")
            _paste_character(canvas, char_img, lp["x_center"], lp["y_bottom"], lp["height"])

    out_dir.mkdir(parents=True, exist_ok=True)
    layout_ref = out_dir / "layout_ref.png"
    canvas.convert("RGB").save(str(layout_ref))
    print(f"[step2] 拼版完成: {layout_ref}", flush=True)
    return layout_ref, layout_params
