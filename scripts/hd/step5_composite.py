#!/usr/bin/env python3
"""
HD 生产线 Step 5：最终合成 + 画面割裂检测
5a. 背景 + 3 个主体按 layout_params 合成
5b. Gemini Vision 检查画面是否割裂
5c. 割裂 → 返回 Step 4 重新填充（最多 2 次）
5d. 通过 → 输出 LZ顶部banner 3840x1200.png
"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if str(SPEC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SPEC_SCRIPTS))

from _env import load_env
load_env()

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview"]

CANVAS_W, CANVAS_H = 3840, 1200
FINAL_OUTPUT_NAME = "LZ顶部banner 3840x1200.png"

LOGO_RECT = (40, 318, 345, 192)       # (x, y, w, h)
TITLE_ART_RECT = (40, 385, 318, 510)  # (x, y, w, h)

SEAM_CHECK_PROMPT = """Examine this banner image carefully for visual quality issues.

Reply YES if ANY of the following is visible:
- SEAMS or CUTS: sharp boundaries where the background scene breaks or misaligns
- STITCHING ARTIFACTS: areas that look like two different images pasted together
- CHARACTERS look unnaturally pasted (wrong lighting, wrong scale, floating)
- UNRELATED content: background doesn't match the characters' world/style

Reply NO if the image looks like one coherent, seamless scene with characters naturally placed.

Reply with ONLY one word: YES or NO."""


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


def _check_seams(composite_path: Path) -> bool:
    """检查画面是否有割裂。True=有问题需重做，False=通过。"""
    key = _get_key()
    if not key:
        return False
    b64, mime = _encode(composite_path)
    body = json.dumps({
        "contents": [{"parts": [
            {"text": SEAM_CHECK_PROMPT},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    for model in VISION_MODELS:
        req = urllib.request.Request(_url(model, key), data=body, headers=_headers(key), method="POST")
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for p in parts:
                    if "text" in p:
                        t = p["text"].strip().upper()
                        if "YES" in t:
                            return True
                        if "NO" in t:
                            return False
            except Exception:
                if attempt < 1:
                    time.sleep(3)
    return False


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


def _paste_asset(canvas, asset_path: Path, rect: tuple):
    from PIL import Image
    if not asset_path or not asset_path.is_file():
        return
    asset = Image.open(asset_path).convert("RGBA")
    rx, ry, rw, rh = rect
    aw, ah = asset.size
    scale = min(rw / aw, rh / ah)
    new_w = max(1, int(round(aw * scale)))
    new_h = max(1, int(round(ah * scale)))
    resized = asset.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = rx + (rw - new_w) // 2
    y = ry + (rh - new_h) // 2
    canvas.paste(resized, (x, y), resized)


def composite(bg_path: Path, layout_params: list[dict],
              logo_path: Path | None, title_art_path: Path | None,
              out_path: Path) -> Path:
    """合成一次，输出到 out_path。"""
    from PIL import Image
    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (CANVAS_W, CANVAS_H):
        bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)

    # 按 z_order 从大到小绘制（远→近）
    for lp in sorted(layout_params, key=lambda x: x["z_order"], reverse=True):
        p = lp["path"]
        if p and Path(p).is_file():
            char_img = Image.open(p).convert("RGBA")
            _paste_character(bg, char_img, lp["x_center"], lp["y_bottom"], lp["height"])
            print(f"[step5] 叠加角色 z={lp['z_order']}: x={lp['x_center']} h={lp['height']}", flush=True)

    if logo_path and logo_path.is_file():
        _paste_asset(bg, logo_path, LOGO_RECT)
        print(f"[step5] 叠加 logo", flush=True)

    if title_art_path and title_art_path.is_file():
        _paste_asset(bg, title_art_path, TITLE_ART_RECT)
        print(f"[step5] 叠加 title_art", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(str(out_path))
    return out_path


def run_step5(
    bg_path: Path,
    layout_params: list[dict],
    logo_path: Path | None,
    title_art_path: Path | None,
    out_dir: Path,
    regen_bg_fn=None,
    max_retries: int = 2,
) -> Path:
    """
    合成 + 割裂检测，不合格则调用 regen_bg_fn 重新生成背景后重试。
    regen_bg_fn: callable() -> Path，用于重新生成背景。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    current_bg = bg_path
    out_path = out_dir / "composite_0.png"  # default

    for attempt in range(max_retries + 1):
        out_path = out_dir / f"composite_{attempt}.png"
        print(f"\n[step5] 合成 第 {attempt+1} 次...", flush=True)
        composite(current_bg, layout_params, logo_path, title_art_path, out_path)

        print(f"[step5] 检查画面割裂...", flush=True)
        has_seams = _check_seams(out_path)
        if not has_seams:
            print(f"[step5] 画面检查通过", flush=True)
            break
        else:
            print(f"[step5] 检测到割裂，{'重新生成背景' if regen_bg_fn and attempt < max_retries else '已达最大重试次数，使用当前结果'}", flush=True)
            if regen_bg_fn and attempt < max_retries:
                current_bg = regen_bg_fn()
            else:
                break

    # 输出最终文件
    final = out_dir / FINAL_OUTPUT_NAME
    import shutil
    shutil.copy2(out_path, final)
    print(f"[step5] 最终输出: {final}", flush=True)
    return final
