#!/usr/bin/env python3
"""
Detect main subject vertical position (0-1) via Gemini Vision for banner crop.
Uses GEMINI_API_KEY. Returns None on missing key or API/parse failure (caller falls back to center crop).
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Vision model: image + text in, text out (no IMAGE response). 可被环境变量 GEMINI_VISION_MODEL 覆盖（逗号分隔多模型时按顺序回退）。
# 注：gemini-3.1-flash 在 v1beta 下不可用；可用 gemini-2.5-flash 或 gemini-3.1-pro-preview
VISION_MODEL = "gemini-3.1-pro-preview"
# 回退链：3.1-pro → 3-flash
VISION_MODEL_FALLBACK = ["gemini-3-flash-preview"]
VISION_503_RETRIES = 3
VISION_503_BACKOFF_BASE = 2
_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"


def _get_vision_models() -> list[str]:
    """解析 GEMINI_VISION_MODEL（逗号分隔）或使用默认回退列表。"""
    raw = os.environ.get("GEMINI_VISION_MODEL", "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        if models:
            return models
    return list(VISION_MODEL_FALLBACK)

SUBJECT_PROMPT_Y = """This image will be used as a horizontal banner background. Identify the MAIN subject: the single most prominent character or object — the one that is largest in scale, most in the foreground, and occupies the most space. If there are multiple characters, choose the dominant one (e.g. a large character on the right), not smaller background figures. Ignore the geometric center of the image; focus on visual prominence.

Reply with exactly one number between 0 and 1: the vertical position of that subject's center as a ratio of image height (0 = top edge, 1 = bottom edge). Example: 0.7 means lower third.

Output only that number, no other text or explanation."""

SUBJECT_PROMPT_XY = """This image will be used as a horizontal banner background. Identify the MAIN subject: the single most prominent character or object — the one that is largest in scale, most in the foreground, and occupies the most space. If there are multiple characters, choose the dominant one (e.g. a large character on the right), not smaller background figures. Ignore the geometric center of the image; focus on visual prominence.

Reply with exactly two numbers between 0 and 1, separated by a space or comma. First: horizontal position of that subject's center (0 = left edge, 1 = right edge). Second: vertical position (0 = top, 1 = bottom). Example: 0.75 0.6 means the subject is on the right and slightly below center.

Output only these two numbers, no other text."""

SUBJECT_PROMPT_BBOX = """This image will be used for a banner. Identify the MAIN subject and reply with its bounding box.

DEFINITION OF MAIN SUBJECT:
(1) If the image contains a visible person or character (human, cartoon character, creature with a face, etc.), the main subject MUST be that person or character — the one that is largest and most in the foreground. The bounding box MUST fully enclose the whole figure: head (including hair, hair buns, head accessories), both hands (including fingers and fingertips), and key visual features (e.g. shoulder armor, ribbons, ornaments). Do not cut off the head, fingertips, or prominent accessories; allow a small margin. The box must cover the entire figure (full body or at least head, torso, and main limbs); do NOT return a box that only contains a hand, arm, or face alone.
(2) If there is NO person or character, the main subject is the single most prominent SCENE or OBJECT GROUP — the one that is largest in scale, most in the foreground, and occupies the most space. Examples: a central island with plants and tools, a table with products, a vehicle with its cargo, a building facade, or any cohesive foreground cluster (e.g. tree seedling + soil mound + watering can + shovel + seed bag on one platform). The box must enclose this ENTIRE visual center or foreground group as one unit; do NOT choose only one small object (e.g. a single flower or one tool) when a larger, coherent group is present. Prefer a box that fits the main scene/group tightly with minimal extra background.

Reply with the bounding box as four numbers between 0 and 1, in order: x_min, y_min, x_max, y_max. x_min = left edge, x_max = right edge; y_min = top edge, y_max = bottom edge. Example: 0.2 0.1 0.8 0.9 means the subject spans from 20% to 80% horizontally and 10% to 90% vertically.

Output only these four numbers separated by spaces or commas, no other text."""

# 3320×500 专题长图：识别应「伸入」顶部条带（y=0-40）的主体部分，一般为画面占比最大物体的顶端或人物的头/手等
PROTRUSION_PROMPT = """This image is a horizontal banner crop (e.g. 3320×500). The top 40 pixels will be a strip where we want to show a part of the main subject "extending" into it (e.g. the top of the subject's head, hands, or the top of the largest object).

Identify the region that should be placed in that top strip: usually the part of the MAIN subject that is nearest to the top of the image — e.g. a person's head (including hair), raised hands, or the top portion of the most prominent object. It should be a single contiguous region that looks natural when shown in a shallow horizontal strip.

Reply with the bounding box of that "protrusion" region as four numbers between 0 and 1, in order: x_min, y_min, x_max, y_max. Prefer a region that is near the top (small y_min) and horizontally centered or aligned with the main subject. Example: 0.3 0.0 0.7 0.15 means the top 15% of the image, horizontally from 30% to 70%.

Output only these four numbers separated by spaces or commas, no other text."""

# 识别画面上是否有「未填充的空白区域」（与画面自带的黑背景等区分）
UNFILLED_BLANKS_PROMPT = """This image is a banner that was composited: a subject was pasted onto a canvas and blank areas were supposed to be filled with extended scene. Some areas may still be UNFILLED (leftover blank canvas: solid black or near-black strips, usually at the left/right/top/bottom edges, with a sharp boundary against the scene). Other dark or black areas may be INTENTIONAL (e.g. black background, night sky, dark clothing, shadow).

Does this image have any regions that look UNFILLED (empty canvas, not part of the scene)? Do NOT count intentional black/dark content as unfilled.

Reply with exactly one word: YES or NO. If YES, the image has unfilled blank areas that should be filled. If NO, all dark areas are part of the scene or the image is fully filled."""

# A4 填充质量：画面是否割裂、延展区是否与中心主体内容一致
FILL_QUALITY_NEED_REFILL_PROMPT = """This image was produced by extending/filling blank areas around a central subject so the whole image is one scene. The center region contains the main subject (e.g. a character, object); the outer areas were generated to extend the background.

Check TWO things:
(1) VISUAL CONTINUITY: Is there a visible seam, cut, or discontinuity (割裂) between the center subject area and the extended outer areas? Do the extended areas look like the same continuous scene (same style, lighting, perspective) or do they look pasted/patched?
(2) CONTENT RELEVANCE: Do the extended (filled) areas show content that naturally continues from the center subject's scene (same room, same environment, same story)? Or do they show unrelated content (e.g. different place, different style, content that has nothing to do with the center subject)?

Reply with exactly one word: YES or NO.
- YES = need to re-fill: either (1) there is visible discontinuity/seam, OR (2) the extended content is unrelated to the center subject.
- NO = OK: the image is coherent, no visible seam, and the extended areas naturally continue the same scene as the center subject."""

# A4 一步检测（做法一）：未填满 + 画面割裂/延展与主体无关，合并为一次 Vision 判断
A4_NEED_REFILL_PROMPT = """This image was produced by pasting a central subject onto a canvas and then FILLING the blank areas (solid black or RGB(0,0,1)) by extending the scene. The center has the main subject; the outer areas were generated to extend the background.

Check BOTH of the following. Reply YES if ANY is true; reply NO only if ALL are false.

(1) UNFILLED: Are there any regions that still look UNFILLED—leftover blank canvas, solid black or near-black strips at the edges or elsewhere, with a sharp boundary against the scene? (Do NOT count intentional dark content like night sky or shadow as unfilled.)

(2) VISUAL QUALITY / SEAMS (割裂): Look carefully for ANY sign that the image was stitched, patched, or extended in a broken way. Reply YES if you see ANY of the following:
- Visible vertical or horizontal SEAMS: sharp lines or boundaries where the scene does not continue smoothly—e.g. a vertical strip where the wall, curtain, or ceiling is clearly cut off, stretched, or misaligned with the adjacent area on either side.
- STRETCHED or REPEATED bands: any vertical or horizontal band that looks like a stretched copy of nearby content, or where texture/pattern does not align across the band edges.
- STITCHING ARTIFACTS: areas that look like two or more pieces pasted together—where perspective, lighting, or scale suddenly changes at a boundary; or where objects (e.g. curtains, papers, furniture) are abruptly cut at a vertical/horizontal line and do not flow naturally into the next region.
- UNRELATED extended content: the extended areas show a different place, style, or scene that does not belong with the center subject.

The whole image must look like ONE continuous, single shot—no visible "patches," no vertical/horizontal strips that break the flow. If any region looks like it was filled or extended in a way that creates a visible cut, tear, or mismatch, reply YES.

Reply with exactly one word: YES or NO.
- YES = need to re-fill: unfilled areas, OR any seam/stretch/stitch artifact, OR unrelated extended content.
- NO = OK: fully filled, and the entire image is one seamless scene with no visible boundaries or patches."""

# A4 分步检测：(1) 仅未填满
A4_NEED_REFILL_UNFILLED_PROMPT = """This image was produced by pasting a central subject onto a canvas and then FILLING the blank areas (solid black or RGB(0,0,1)) by extending the scene.

Check ONLY: UNFILLED — Are there any regions that still look UNFILLED? That is: leftover blank canvas, solid black or near-black strips at the edges or elsewhere, with a sharp boundary against the scene. Do NOT count intentional dark content (e.g. night sky, shadow, dark clothing) as unfilled.

Reply with exactly one word: YES or NO.
- YES = there are unfilled areas (need to re-fill).
- NO = the image is fully filled, no blank or black strips."""

# A4 分步检测：(2) 仅画面质量/接缝
A4_NEED_REFILL_SEAMS_PROMPT = """This image was produced by pasting a central subject onto a canvas and then FILLING the blank areas by extending the scene. The center has the main subject; the outer areas were generated to extend the background.

Check ONLY: VISUAL QUALITY / SEAMS (割裂). Look carefully for ANY sign that the image was stitched, patched, or extended in a broken way. Reply YES if you see ANY of the following:
- Visible vertical or horizontal SEAMS: sharp lines or boundaries where the scene does not continue smoothly—e.g. a vertical strip where the wall, curtain, or ceiling is clearly cut off, stretched, or misaligned with the adjacent area on either side.
- STRETCHED or REPEATED bands: any vertical or horizontal band that looks like a stretched copy of nearby content, or where texture/pattern does not align across the band edges.
- REPEATED or MIRRORED objects: the same distinct object (e.g. same window, same curtain, same can, same furniture) appears more than once or in mirrored form in the image—extended areas must not duplicate or mirror existing elements.
- STITCHING ARTIFACTS: areas that look like two or more pieces pasted together—where perspective, lighting, or scale suddenly changes at a boundary; or where objects (e.g. curtains, papers, furniture) are abruptly cut at a vertical/horizontal line and do not flow naturally into the next region.
- UNRELATED extended content: the extended areas show a different place, style, or scene that does not belong with the center subject.
- OBVIOUS VERTICAL OR HORIZONTAL BAND: a single narrow strip (vertical or horizontal) that looks clearly different from the areas beside it—e.g. one column of only window/bright light/curtain while the rest of the image has more detail and structure; or one overexposed or empty-looking band. If such a 'pasted' strip is visible, reply YES.

The whole image must look like ONE continuous, single shot. If any region looks like it was filled or extended in a way that creates a visible cut, tear, or mismatch, reply YES.

Reply with exactly one word: YES or NO.
- YES = need to re-fill: seam/stretch/stitch artifact or unrelated extended content.
- NO = OK: the entire image is one seamless scene with no visible boundaries or patches."""

# A6b：商店专题头图 1740×220 专属 — 全图画质，仅接缝/割裂/重复拼接（不含「是否黑边未填满」）
A6B_SHOP_HEADER_SEAM_DETECT_PROMPT = """This image is the FINAL shop special-topic header banner (1740×220 style)—a very wide horizontal crop. Examine the ENTIRE image edge to edge.

Reply YES if ANY of the following is clearly visible:
- SEAMS / CUTS / FRAGMENTATION (割裂): vertical or horizontal boundaries where walls, floors, ceilings, windows, furniture, or lighting suddenly misalign, jump, or break continuity—like two different patches joined.
- REPETITIVE SPLICING / TILING (重复拼接): the same architectural block, door group, locker row, window pattern, or furniture layout appears copy-pasted, mirrored, or unnaturally repeated to fill width; or obvious stretched/tiled bands.

Reply NO if the scene reads as one coherent space without such stitching or copy-paste repetition.

Do NOT reply YES only for normal shadows, dark clothing, or mild compression—only for clear seam or repetitive-splice defects.

Reply with exactly one word: YES or NO."""


def _get_api_keys() -> list[str]:
    """返回 [主 key, ALT key] 列表（去重、去空）"""
    keys: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    alt = os.environ.get("GEMINI_API_KEY_ALT", "").strip()
    if alt and alt != primary:
        keys.append(alt)
    return keys


def _get_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


# 使用 Packy 等代理时加上浏览器 UA，避免 Cloudflare 1010 拦截
PACKY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _gemini_headers(key: str) -> dict:
    """Packy 等代理使用 Bearer；直连 Google 使用 query key。"""
    h = {"Content-Type": "application/json"}
    if key and key.strip().startswith("sk-"):
        h["Authorization"] = f"Bearer {key.strip()}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        h["User-Agent"] = PACKY_USER_AGENT
    return h


def _gemini_url(api_base: str, model: str, key: str) -> str:
    """生成 generateContent URL，Packy 用 Bearer 时不再在 URL 带 key。"""
    base_url = f"{api_base}/{model}:generateContent"
    if key and key.strip().startswith("sk-"):
        return base_url
    return f"{base_url}?key={key}"


def _encode_image(image_path: str) -> tuple[str, str]:
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(image_path)
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    mime = "image/png"
    if path.suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    return b64, mime


def _call_micugemini_vision(body: dict) -> str | None:
    import requests as _req, os as _os, json as _json, sys as _s
    key = _os.environ.get("MICUGEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        return None
    parts: list = []
    for c in body.get("contents", []):
        for p in c.get("parts", []):
            if "text" in p:
                parts.append({"type": "text", "text": p["text"]})
            elif "inlineData" in p:
                d = p["inlineData"]
                parts.append({"type": "image_url", "image_url": {"url": "data:" + d["mimeType"] + ";base64," + d["data"]}})
    chat_body = {"model": "gemini-3.1-pro-preview", "messages": [{"role": "user", "content": parts}]}
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    try:
        r = _req.post("https://www.micuapi.ai/v1/chat/completions", json=chat_body, headers=h, timeout=60)
        r.raise_for_status()
        for c in r.json().get("choices", []):
            ct = c.get("message", {}).get("content", "")
            if isinstance(ct, str) and ct.strip():
                return ct.strip()
    except Exception as e:
        print("[micugemini vision] fail: " + str(e)[:100], file=sys.stderr)
    return None


def _call_moxingemini_vision(body: dict) -> str | None:
    import requests as _req, os as _os, json as _json, sys as _s
    key = _os.environ.get("MOXINGEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        return None
    base_url = _os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").rstrip("/")
    parts: list = []
    for c in body.get("contents", []):
        for p in c.get("parts", []):
            if "text" in p:
                parts.append({"type": "text", "text": p["text"]})
            elif "inlineData" in p:
                d = p["inlineData"]
                parts.append({"type": "image_url", "image_url": {"url": "data:" + d["mimeType"] + ";base64," + d["data"]}})
    # Vision 模型优先读专用变量 MOXINGEMINI_VISION_MODEL（token 对图编 [白嫖] 系有权、
    # 对 [特价参考]pro-preview 无权 → 需用可访问模型做 Vision）；回退 MOXINGEMINI_MODEL。
    # 支持逗号分隔多模型按序重试（某模型 403/无文本时换下一个）。
    _raw = (
        _os.environ.get("MOXINGEMINI_VISION_MODEL", "").strip()
        or _os.environ.get("MOXINGEMINI_MODEL", "").strip()
        or "[特价次卡]gemini-3.1-pro-preview-think"
    )
    model_list = [m.strip() for m in _raw.split(",") if m.strip()][:3]
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    for mi, model_name in enumerate(model_list, 1):
        chat_body = {"model": model_name, "messages": [{"role": "user", "content": parts}]}
        try:
            r = _req.post(base_url + "/v1/chat/completions", json=chat_body, headers=h, timeout=60)
            r.raise_for_status()
            for c in r.json().get("choices", []):
                ct = c.get("message", {}).get("content", "")
                if isinstance(ct, str) and ct.strip():
                    return ct.strip()
            print(f"[moxingemini vision] model={model_name} 无文本返回 ({mi}/{len(model_list)})，尝试下一模型...", file=sys.stderr)
        except Exception as e:
            print(f"[moxingemini vision] model={model_name} fail ({mi}/{len(model_list)}): " + str(e)[:90], file=sys.stderr)
    return None


def _post_vision_generate_content(
    body: dict,
    error_prefix: str = "Vision 请求失败",
    *,
    request_timeout: int = 30,
) -> str | None:
    """
    对 Gemini generateContent 发请求；503/500 重试，403/404 换下一模型。
    成功返回第一段 text；失败 stderr 打印并返回 None。
    """
    import sys

    _backend = os.environ.get("BANNER_IMAGE_BACKEND", "") or os.environ.get("BANNER_EDIT_BACKEND", "")
    if _backend.strip().lower() == "micugemini":
        result = _call_micugemini_vision(body)
        if result is not None:
            return result
        print(f"{error_prefix}: micugemini vision failed", file=sys.stderr)
        return None
    if _backend.strip().lower() == "moxingpt" and os.environ.get("MOXINGEMINI_API_KEY", "").startswith("sk-"):
        result = _call_moxingemini_vision(body)
        if result is not None:
            return result
        print(f"{error_prefix}: moxingemini vision failed", file=sys.stderr)
        return None

    api_keys = _get_api_keys()
    if not api_keys:
        print(f"{error_prefix}: 未设置 GEMINI_API_KEY", file=sys.stderr)
        return None

    models = _get_vision_models()
    last_error: str | None = None
    for key in api_keys:
        if not key or not key.strip():
            continue
        try_next_key = False
        for model in models:
            url = _gemini_url(API_BASE, model, key)
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=_gemini_headers(key),
                method="POST",
            )
            for attempt in range(VISION_503_RETRIES):
                try:
                    with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates") or []
                    if not candidates:
                        feedback = data.get("promptFeedback", {})
                        last_error = f"API 未返回 candidates（可能安全拦截）— {feedback}"
                        break
                    resp_parts = candidates[0].get("content", {}).get("parts") or []
                    for part in resp_parts:
                        if "text" in part:
                            return part["text"]
                    last_error = "响应中无 text 字段"
                    break
                except urllib.error.HTTPError as e:
                    err_body = (e.read().decode("utf-8", errors="replace") if e.fp else "")[:500]
                    last_error = f"API HTTP 错误 {e.code} — {err_body}"
                    if e.code == 401:
                        if key != api_keys[-1]:
                            print(f"{error_prefix}: key 鉴权失败，切换到备用 key", file=sys.stderr)
                            try_next_key = True
                            break
                    if e.code in (403, 404):
                        if len(models) > 1:
                            print(f"{error_prefix}: model={model} {e.code}，尝试下一模型", file=sys.stderr)
                        break
                    if e.code in (500, 503) and attempt < VISION_503_RETRIES - 1:
                        wait = VISION_503_BACKOFF_BASE * (2 ** attempt)
                        print(
                            f"{error_prefix}: model={model} HTTP {e.code}，{wait}s 后重试 ({attempt + 1}/{VISION_503_RETRIES})",
                            file=sys.stderr,
                        )
                        time.sleep(wait)
                        continue
                    break
                except (urllib.error.URLError, TimeoutError) as e:
                    last_error = f"网络/超时 — {e}"
                    if attempt < VISION_503_RETRIES - 1:
                        wait = VISION_503_BACKOFF_BASE * (2 ** attempt)
                        print(
                            f"{error_prefix}: model={model} 网络/SSL 错误: {e}，{wait}s 后重试 ({attempt + 1}/{VISION_503_RETRIES})",
                            file=sys.stderr,
                        )
                        time.sleep(wait)
                        continue
                    break
                except json.JSONDecodeError as e:
                    last_error = f"JSON 解析异常 — {e}"
                    break
            if try_next_key:
                break
    if last_error:
        print(f"{error_prefix}: {last_error}", file=sys.stderr)
    return None


def _call_vision_get_text(
    image_path: str,
    prompt: str,
    error_prefix: str = "Vision 请求失败",
) -> str | None:
    """
    使用 Vision 模型列表依次请求；503/500 时重试，403/404 时换下一模型。
    成功时返回响应中的第一段 text，失败时在 stderr 打印并返回 None。
    BANNER_IMAGE_BACKEND=lovart 时改用 Lovart 视觉理解。
    """
    # ── lovart 分支 ───────────────────────────────────────────────────
    import os as _os
    _backend = _os.environ.get("BANNER_EDIT_BACKEND", "") or _os.environ.get("BANNER_IMAGE_BACKEND", "")
    if _backend.strip().lower() == "lovart":
        import sys as _sys
        _scripts = Path(__file__).resolve().parent.parent.parent.parent.parent / "scripts"
        if str(_scripts) not in _sys.path:
            _sys.path.insert(0, str(_scripts))
        from lovart_vision import _call_lovart_vision
        return _call_lovart_vision(image_path, prompt)
    # ── micugpt2 分支 ─────────────────────────────────────────────────
    if _backend == "micugpt2":
        return _call_micugpt2_vision(image_path, prompt)
    # ── 原有 Gemini 逻辑 ──────────────────────────────────────────────
    try:
        b64, mime = _encode_image(image_path)
    except Exception as e:
        import sys

        print(f"{error_prefix}: 读图/编码异常 — {e}", file=sys.stderr)
        return None
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    return _post_vision_generate_content(body, error_prefix, request_timeout=30)


def _call_micugpt2_vision(
    image_path: str,
    prompt: str,
    max_dim: int = 1536,
) -> str | None:
    """通过 micuapi.ai /v1/chat/completions + gpt-image-2 Vision 理解单张图片。
    成功返回 text 字符串；失败打印错误并返回 None。"""
    import requests as _requests

    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        import sys as _sys
        print("micugpt2 Vision: MICUAPI_API_KEY 未设置或格式不正确", file=_sys.stderr)
        return None

    ref_path = Path(image_path)
    if not ref_path.is_file():
        import sys as _sys
        print(f"micugpt2 Vision: 图片不存在 {image_path}", file=_sys.stderr)
        return None

    from PIL import Image as _PILImage
    from io import BytesIO as _BytesIO

    im = _PILImage.open(ref_path)
    im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
    w, h = im.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
    buf = _BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = json.dumps({
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    }).encode("utf-8")

    try:
        resp = _requests.post(
            "https://www.micuapi.ai/v1/chat/completions",
            data=body,
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        for choice in data.get("choices", []):
            ct = choice.get("message", {}).get("content", "")
            if isinstance(ct, str) and ct.strip():
                return ct.strip()
        import sys as _sys
        print("micugpt2 Vision: 响应中无 text 内容", file=_sys.stderr)
        return None
    except Exception as e:
        import sys as _sys
        print(f"micugpt2 Vision: 请求失败 — {e}", file=_sys.stderr)
        return None


def _call_micugpt2_vision_multi(
    encoded_images: list[tuple[str, str]],
    prompt: str,
) -> str | None:
    """通过 micuapi.ai /v1/chat/completions + gpt-image-2 Vision 理解多张图片。
    encoded_images: [(base64_str, mime_type), ...] 已经缩放编码好的图片列表。
    成功返回 text 字符串；失败打印错误并返回 None。"""
    import requests as _requests

    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        import sys as _sys
        print("micugpt2 Vision (多图): MICUAPI_API_KEY 未设置或格式不正确", file=_sys.stderr)
        return None

    content: list[dict] = [{"type": "text", "text": prompt}]
    for b64, mime in encoded_images:
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = json.dumps({
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    try:
        resp = _requests.post(
            "https://www.micuapi.ai/v1/chat/completions",
            data=body,
            headers=headers,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        for choice in data.get("choices", []):
            ct = choice.get("message", {}).get("content", "")
            if isinstance(ct, str) and ct.strip():
                return ct.strip()
        import sys as _sys
        print("micugpt2 Vision (多图): 响应中无 text 内容", file=_sys.stderr)
        return None
    except Exception as e:
        import sys as _sys
        print(f"micugpt2 Vision (多图): 请求失败 — {e}", file=_sys.stderr)
        return None


def _encode_images_downscaled_for_vision(
    image_paths: list[str],
    max_long_edge: int = 1024,
) -> list[tuple[str, str]]:
    """将多张图缩放后编码为 PNG base64，降低多图 Vision 请求体积。"""
    from io import BytesIO

    from PIL import Image

    out: list[tuple[str, str]] = []
    for p in image_paths:
        path = Path(p)
        if not path.is_file():
            raise FileNotFoundError(p)
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        long_edge = max(w, h)
        if long_edge > max_long_edge:
            scale = max_long_edge / float(long_edge)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = BytesIO()
        im.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        out.append((b64, "image/png"))
    return out


HD_VISION_SORT_IMAGES_PROMPT_TEMPLATE = """These {n} images are uploaded in this order: after this text, image A is input index 0, the next image is index 1, and so on up to index {last_i}.

They will be used as separate character/subject layers for ONE ultra-wide game marketing banner (3840×1200, about 3.2:1). The pipeline places them in a horizontal row: left to right. The middle position (horizontal slot index {mid_slot}) is drawn last and reads as the main hero / focal character in this layout.

Your task (vision only, no file names):
1) Compare image quality: sharpness, detail, compression artifacts, noise.
2) Compare suitability for this banner: full or partial body visible, face/readability, dynamic pose, whether the subject reads well as a hero at larger scale; do NOT penalize portrait-tall images only for aspect ratio if they are strong heroes.
3) Build a left-to-right order: put the BEST hero / focal character at horizontal slot index {mid_slot} (center of the row). Arrange the others on the left and right sides in a sensible way (e.g. supporting characters, balance).

Reply with ONLY one JSON object, no markdown. Use exactly these keys:
{{"layout_order":[...],"reason":"one short sentence in Chinese"}}

"layout_order" must be a permutation of the integers [0,1,...,{last_i}] — each input index appears exactly once. The array order is LEFT to RIGHT on the banner: first element = leftmost slot, last element = rightmost slot. The element at array index {mid_slot} (0-based) must be the input index of the image you choose as the main hero.

Example for n=3: mid slot is 1, so layout_order has length 3 and layout_order[1] is the hero's input index."""


def _parse_hd_vision_layout_order(text: str, n: int) -> list[int] | None:
    raw = _extract_json_object((text or "").strip())
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    lo = obj.get("layout_order")
    if not isinstance(lo, list) or len(lo) != n:
        return None
    try:
        indices = [int(x) for x in lo]
    except (TypeError, ValueError):
        return None
    if sorted(indices) != list(range(n)):
        return None
    return indices


def vision_sort_hd_image_layout_order(image_paths: list[str]) -> list[str] | None:
    """
    多图单次 Vision：按画质与横幅群像适合度排序，返回与 image_paths 同长度的重排路径列表
    （左→右对应 Banner；中间位为主视觉）。仅支持 3～5 张；失败返回 None。
    """
    n = len(image_paths)
    if not 3 <= n <= 5:
        return None
    last_i = n - 1
    mid_slot = n // 2
    prompt = HD_VISION_SORT_IMAGES_PROMPT_TEMPLATE.format(
        n=n, last_i=last_i, mid_slot=mid_slot
    )
    try:
        encoded = _encode_images_downscaled_for_vision(list(image_paths))
    except Exception as e:
        import sys

        print(f"[HD 素材排序 Vision]: 读图/缩放异常 — {e}", file=sys.stderr)
        return None
    parts: list[dict] = [{"text": prompt}]
    for b64, mime in encoded:
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }
    text = _post_vision_generate_content(
        body, "[HD 素材排序 Vision]", request_timeout=120
    )
    if not text:
        return None
    order = _parse_hd_vision_layout_order(text, n)
    if order is None:
        import sys

        print(
            "[HD 素材排序 Vision]: 无法解析 layout_order JSON — "
            + repr(text[:500]),
            file=sys.stderr,
        )
        return None
    reason = ""
    try:
        blob = json.loads(_extract_json_object(text.strip()) or "{}")
        if isinstance(blob, dict) and isinstance(blob.get("reason"), str):
            reason = blob["reason"].strip()
    except json.JSONDecodeError:
        pass
    if reason:
        print(f"[HD 素材排序 Vision]: {reason}", flush=True)
    return [image_paths[i] for i in order]


HD_VISION_PLAN_BANNER_PROMPT_TEMPLATE = """These {n} images are uploaded in this order: after this text, input index 0 is first, then 1, … up to index {last_i}.

They will be separate character layers for ONE ultra-wide game marketing banner **{canvas_w}×{canvas_h} pixels**.

**Mandatory content rectangle (all characters' silhouettes must fit inside; side margins outside are for empty/branding space):**
- x: from pixel {safe_x_min} to {safe_x_max} (inclusive pixel columns as used in design specs)
- y: from pixel {safe_y_min} to {safe_y_max}
- Inner width ≈ {safe_w}px, inner height ≈ {safe_h}px

The pipeline places them in a **horizontal row inside that rectangle**, left to right. Horizontal slot index {mid_slot} (0-based) is drawn **last** and reads as the **main hero** in front of neighbors.

Your tasks (vision only):
1) Compare sharpness, artifacts, and suitability for a wide banner (pose, readability, hero presence).
2) Choose **layout_order**: a permutation of [0,1,…,{last_i}] = **left → right** slot order. The input index at array position **{mid_slot}** must be your chosen main hero.
3) Suggest **numeric layout** for a **tight group** with visible overlap/occlusion (store-style key art), not a loose gap row:
   - **overlap_ratio** 0.12–0.32 (fraction of mean layer width overlapped between neighbors; higher = tighter group)
   - **fill_height_ratio** 0.78–0.93 (unified subject height vs inner rectangle height)
   - **max_width_ratio** 0.88–0.99 (max total row span vs inner width)
   - **y_stagger_ratio** 0.02–0.06 (vertical stagger vs inner height; use with stagger_mode)
   - **ground_y_ratio** 0.82–0.91 (foot baseline vs inner height, from top)
   - **stagger_mode**: prefer **"center_pyramid"** for hero-in-front reads (middle higher on canvas); **"sides_up"** only if side characters should read taller.

Reply with **ONLY one JSON object**, no markdown, keys exactly:
{{"layout_order":[...],"overlap_ratio":0.0,"fill_height_ratio":0.0,"max_width_ratio":0.0,"y_stagger_ratio":0.0,"ground_y_ratio":0.0,"stagger_mode":"center_pyramid","reason":"one short sentence in Chinese"}}

"layout_order" must be a permutation of 0..{last_i}."""


def _parse_hd_vision_plan_banner(text: str, n: int) -> dict[str, object] | None:
    raw = _extract_json_object((text or "").strip())
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    lo = obj.get("layout_order")
    if not isinstance(lo, list) or len(lo) != n:
        return None
    try:
        indices = [int(x) for x in lo]
    except (TypeError, ValueError):
        return None
    if sorted(indices) != list(range(n)):
        return None

    def fkey(k: str, lo_: float, hi: float, default: float) -> float:
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return max(lo_, min(hi, float(v)))
        return default

    sm = obj.get("stagger_mode")
    if not isinstance(sm, str):
        sm = "center_pyramid"
    sm = sm.strip().lower()
    if sm not in ("sides_up", "center_pyramid"):
        sm = "center_pyramid"

    reason = ""
    r = obj.get("reason")
    if isinstance(r, str):
        reason = r.strip()

    return {
        "layout_order": indices,
        "overlap_ratio": fkey("overlap_ratio", 0.0, 0.35, 0.22),
        "fill_height_ratio": fkey("fill_height_ratio", 0.35, 0.95, 0.88),
        "max_width_ratio": fkey("max_width_ratio", 0.52, 1.0, 0.94),
        "y_stagger_ratio": fkey("y_stagger_ratio", 0.0, 0.08, 0.04),
        "ground_y_ratio": fkey("ground_y_ratio", 0.55, 0.94, 0.87),
        "stagger_mode": sm,
        "reason": reason,
    }


def vision_plan_hd_banner_layout(
    image_paths: list[str],
    *,
    canvas_w: int,
    canvas_h: int,
    safe_x_min: int,
    safe_y_min: int,
    safe_x_max: int,
    safe_y_max: int,
) -> dict[str, object] | None:
    """
    单次 Vision：左→右排序（中间位主英雄）+ 建议 overlap/fill/stagger 等，供 HD 拼版 clamp 后使用。
    失败返回 None。safe_* 为规范矩形（与 spec 一致），用于提示模型与本地安全区内几何。
    """
    n = len(image_paths)
    if not 3 <= n <= 5:
        return None
    last_i = n - 1
    mid_slot = n // 2
    safe_w = max(1, int(safe_x_max) - int(safe_x_min))
    safe_h = max(1, int(safe_y_max) - int(safe_y_min))
    prompt = HD_VISION_PLAN_BANNER_PROMPT_TEMPLATE.format(
        n=n,
        last_i=last_i,
        mid_slot=mid_slot,
        canvas_w=int(canvas_w),
        canvas_h=int(canvas_h),
        safe_x_min=int(safe_x_min),
        safe_x_max=int(safe_x_max),
        safe_y_min=int(safe_y_min),
        safe_y_max=int(safe_y_max),
        safe_w=safe_w,
        safe_h=safe_h,
    )
    try:
        encoded = _encode_images_downscaled_for_vision(list(image_paths))
    except Exception as e:
        import sys

        print(f"[HD 智能拼版 Vision]: 读图/缩放异常 — {e}", file=sys.stderr)
        return None
    _backend = os.environ.get("BANNER_EDIT_BACKEND", "") or os.environ.get("BANNER_IMAGE_BACKEND", "")
    if _backend.strip().lower() == "micugpt2":
        text = _call_micugpt2_vision_multi(encoded, prompt)
    else:
        parts: list[dict] = [{"text": prompt}]
        for b64, mime in encoded:
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        text = _post_vision_generate_content(
            body, "[HD 智能拼版 Vision]", request_timeout=120
        )
    if not text:
        return None
    parsed = _parse_hd_vision_plan_banner(text, n)
    if parsed is None:
        import sys

        print(
            "[HD 智能拼版 Vision]: 无法解析 JSON — " + repr(text[:500]),
            file=sys.stderr,
        )
        return None
    order = parsed["layout_order"]
    assert isinstance(order, list)
    paths_out = [image_paths[i] for i in order]
    reason = parsed.get("reason", "")
    if isinstance(reason, str) and reason.strip():
        print(f"[HD 智能拼版 Vision]: {reason.strip()}", flush=True)
    return {
        "paths": paths_out,
        "overlap_ratio": parsed["overlap_ratio"],
        "fill_height_ratio": parsed["fill_height_ratio"],
        "max_width_ratio": parsed["max_width_ratio"],
        "y_stagger_ratio": parsed["y_stagger_ratio"],
        "ground_y_ratio": parsed["ground_y_ratio"],
        "stagger_mode": parsed["stagger_mode"],
    }


def _parse_ratio(text: str) -> float | None:
    """Extract a single float in [0, 1] from model output."""
    if not text or not text.strip():
        return None
    # Allow number with optional decimals, possibly surrounded by whitespace/markdown
    match = re.search(r"0?\.\d+|1\.0*|0|1\b", text.strip())
    if not match:
        return None
    try:
        v = float(match.group())
        return max(0.0, min(1.0, v))
    except ValueError:
        return None


def _parse_two_ratios(text: str) -> tuple[float | None, float | None]:
    """Extract two floats in [0, 1] from model output. Returns (x_ratio, y_ratio)."""
    if not text or not text.strip():
        return (None, None)
    # Find all numbers in range 0-1 (e.g. 0.7, 0.6, .8, 1.0)
    matches = re.findall(r"0?\.\d+|1\.0*|0|1\b", text.strip())
    if len(matches) < 2:
        return (None, None)
    try:
        x = max(0.0, min(1.0, float(matches[0])))
        y = max(0.0, min(1.0, float(matches[1])))
        return (x, y)
    except ValueError:
        return (None, None)


def _parse_bbox_labeled(text: str) -> tuple[float, float, float, float] | None:
    """
    从带标签的说明里取 x_min/y_min/x_max/y_max（模型常不按顺序输出四个数）。
    例如：y_min at 0.02, y_max at 1.0, x_min at 0.33, x_max at 0.68
    """
    if not text or not text.strip():
        return None
    t = text.replace("\n", " ")

    def grab(pat: str) -> float | None:
        m = re.search(pat, t, re.IGNORECASE)
        if not m:
            return None
        try:
            v = float(m.group(1))
            return max(0.0, min(1.0, v))
        except (ValueError, IndexError):
            return None

    num = r"(0?\.\d+|1\.0*|0|1)"
    x_min = grab(rf"x_min[^\d.]*{num}")
    y_min = grab(rf"y_min[^\d.]*{num}")
    x_max = grab(rf"x_max[^\d.]*{num}")
    y_max = grab(rf"y_max[^\d.]*{num}")
    if x_min is None or y_min is None or x_max is None or y_max is None:
        return None
    if x_min >= x_max or y_min >= y_max:
        return None
    return (x_min, y_min, x_max, y_max)


def _parse_bbox(text: str) -> tuple[float, float, float, float] | None:
    """Extract four floats in [0, 1] as x_min, y_min, x_max, y_max. Returns None if invalid."""
    if not text or not text.strip():
        return None
    s = text.strip()
    # 1) 带标签的叙述（优先，避免按文中出现顺序误取四个数）
    labeled = _parse_bbox_labeled(s)
    if labeled is not None:
        return labeled
    # 2) 方括号内四个数，顺序 x_min y_min x_max y_max
    bracket = re.search(
        r"\[\s*(0?\.\d+|1\.0*|0|1)\s*[,;\s]+\s*(0?\.\d+|1\.0*|0|1)\s*[,;\s]+\s*(0?\.\d+|1\.0*|0|1)\s*[,;\s]+\s*(0?\.\d+|1\.0*|0|1)\s*\]",
        s,
    )
    if bracket:
        try:
            vals = [max(0.0, min(1.0, float(bracket.group(i)))) for i in range(1, 5)]
            x_min, y_min, x_max, y_max = vals
            if x_min < x_max and y_min < y_max:
                return (x_min, y_min, x_max, y_max)
        except (ValueError, TypeError):
            pass
    # 3) 按出现顺序的四个 0–1 数字（兼容科学计数法 1.34e-02、0-1000 刻度 999→0.999；思考模型末尾优先）
    def _normalize_num(s: str) -> float | None:
        try:
            v = float(s)
            if 0.0 <= v <= 1.0:
                return v
            if 1.0 < v <= 1000.0:  # 模型有时用 0-1000 刻度（如 999 表示 0.999）
                return round(v / 1000.0, 5)
        except (ValueError, OverflowError):
            pass
        return None
    all_num_strs = re.findall(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s)
    normalized = [_normalize_num(n) for n in all_num_strs]
    matches = [str(v) for v in normalized if v is not None]
    if len(matches) < 4:
        return None
    def _try_four(vals4: list) -> tuple | None:
        try:
            vals = [max(0.0, min(1.0, float(m))) for m in vals4]
            x_min, y_min, x_max, y_max = vals
            if x_min < x_max and y_min < y_max:
                return (x_min, y_min, x_max, y_max)
        except (ValueError, TypeError):
            pass
        return None
    # 末尾优先（thinking 模型把答案放最后）
    result = _try_four(matches[-4:])
    if result is not None:
        return result
    # 再试开头
    result = _try_four(matches[:4])
    if result is not None:
        return result
    return None


def _parse_yes_no(text: str) -> bool | None:
    """从模型输出中解析 YES/NO。返回 True=yes, False=no, None=无法解析。"""
    if not text or not text.strip():
        return None
    t = text.strip().upper()
    if "YES" in t and "NO" not in t[: t.find("YES")]:
        return True
    if "NO" in t:
        return False
    return None


def detect_subject_bbox(
    image_path: str,
    *,
    strict: bool = False,
    max_retries: int = 1,
    context_prompt: str | None = None,
) -> tuple[float, float, float, float] | None:
    """
    Call Gemini Vision to get main subject bounding box as (x_min, y_min, x_max, y_max) in ratios [0, 1].
    Returns None on failure when strict=True（无本地/默认框兜底）.
    strict=False 时：API/解析失败则用非黑像素估计框或默认框，保证流程不断。
    503/500 重试，403/404 自动换下一模型。
    max_retries：Vision 无响应或无法解析 bbox 时的整轮重试次数（默认 1；HD 产线可设 3）。
    context_prompt：可选，原始生图描述，帮助 Vision 更准确识别画面预期主体。
    """
    import sys

    def _local_bbox_fallback(img_path: str) -> tuple[float, float, float, float] | None:
        """
        Vision 403/失败时的兜底：
        对图片做降采样后，按非黑像素阈值估计内容 bbox，并映射到 0-1 比例。
        这是为了保证 auto 流程不中断（质量可能不如 Vision，但不直接失败）。
        """
        try:
            from PIL import Image

            img = Image.open(img_path).convert("RGB")
            w, h = img.size
            if w <= 1 or h <= 1:
                return None

            # 降采样加速：保证扫描像素量不会太大
            target_max = 640
            scale = min(1.0, target_max / float(max(w, h)))
            if scale < 1.0:
                nw = max(1, int(round(w * scale)))
                nh = max(1, int(round(h * scale)))
                img = img.resize((nw, nh), Image.Resampling.BILINEAR)
                w_s, h_s = img.size
            else:
                w_s, h_s = w, h

            # 灰度亮度阈值：把深色/接近黑的背景剔除
            gray = img.convert("L")
            threshold = 25  # 经验值：低于该亮度视作背景
            pix = list(gray.getdata())

            xs = []
            ys = []
            for idx, v in enumerate(pix):
                if v >= threshold:
                    x = idx % w_s
                    y = idx // w_s
                    xs.append(x)
                    ys.append(y)

            if not xs or not ys:
                return None

            x_min_s, x_max_s = min(xs), max(xs)
            y_min_s, y_max_s = min(ys), max(ys)

            # 给一点边距，减少 bbox 过紧导致的主体裁切
            margin = 0.05
            x_min = max(0.0, x_min_s / float(w_s) - margin)
            x_max = min(1.0, x_max_s / float(w_s) + margin)
            y_min = max(0.0, y_min_s / float(h_s) - margin)
            y_max = min(1.0, y_max_s / float(h_s) + margin)

            # 保证 bbox 有有效面积
            if x_max - x_min < 0.05 or y_max - y_min < 0.05:
                return (0.15, 0.05, 0.85, 0.9)
            return (x_min, y_min, x_max, y_max)
        except Exception:
            return None

    n_try = max(1, int(max_retries))
    last_text: str | None = None
    for attempt in range(n_try):
        prefix = f"主体 bbox 检测失败 (尝试 {attempt + 1}/{n_try})"
        _vision_prompt = SUBJECT_PROMPT_BBOX
        if context_prompt:
            _vision_prompt = f"Image content hint (expected scene): {context_prompt}\n\n{SUBJECT_PROMPT_BBOX}"
        text = _call_vision_get_text(
            image_path, _vision_prompt, error_prefix=prefix
        )
        last_text = text
        if text is not None:
            bbox = _parse_bbox(text)
            if bbox is not None:
                return bbox
            if attempt < n_try - 1:
                time.sleep(1.5)
                continue
        elif attempt < n_try - 1:
            time.sleep(1.5)
            continue

    if last_text is None:
        if strict:
            print("主体 bbox 检测失败（strict）：Vision 无有效响应。", file=sys.stderr)
            return None
        bbox_local = _local_bbox_fallback(image_path)
        if bbox_local is not None:
            return bbox_local
        return (0.15, 0.05, 0.85, 0.9)

    tail = repr(last_text[-200:]) if len(last_text) > 300 else ""
    print(
        "主体 bbox 检测失败: 无法解析 bbox（需 4 个 0–1 数字 x_min,y_min,x_max,y_max）— 模型返回开头: "
        + repr(last_text[:200])
        + (f"  末尾: {tail}" if tail else ""),
        file=sys.stderr,
    )
    if strict:
        return None
    bbox_local = _local_bbox_fallback(image_path)
    return bbox_local if bbox_local is not None else (0.15, 0.05, 0.85, 0.9)


HD_LAYOUT_BG_PROMPT_TEMPLATE = """This image is a horizontal banner LAYOUT REFERENCE: main subjects are cut out and arranged in a row on a temporary neutral background. This reference will be sent to an image-to-image model.

The user's creative brief (you MUST align mood, palette, and atmosphere with this text):
\"\"\"
{user_prompt}
\"\"\"

Your task:
1) Analyze the subjects' visual content AND the user's brief together.
2) Propose a SUBTLE canvas background (colors only) to sit behind these subjects on this reference — harmonious, low contrast, no busy patterns. No text, no logos, no UI.
3) Prefer a soft vertical gradient from top to bottom; if a flat backdrop fits better, use the same RGB for top and bottom.

Reply with ONLY one JSON object, no markdown fences, no other text. Use exactly these keys:
{{"top_rgb":[R,G,B],"bottom_rgb":[R,G,B],"hint":"one short sentence in Chinese describing ambient light / environment for the final banner generator"}}

R,G,B are integers from 0 to 255."""


def _extract_json_object(text: str) -> str | None:
    if not text or not text.strip():
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_hd_layout_bg_json(text: str) -> dict | None:
    raw = _extract_json_object(text.strip())
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    top = obj.get("top_rgb")
    bottom = obj.get("bottom_rgb")
    hint = obj.get("hint")
    if not isinstance(top, list) or len(top) != 3:
        return None
    if not isinstance(bottom, list) or len(bottom) != 3:
        return None

    def triplet(v: list) -> tuple[int, int, int] | None:
        try:
            r, g, b = (int(v[0]), int(v[1]), int(v[2]))
            if not all(0 <= x <= 255 for x in (r, g, b)):
                return None
            return (r, g, b)
        except (TypeError, ValueError, IndexError):
            return None

    tt = triplet(top)
    bb = triplet(bottom)
    if tt is None or bb is None:
        return None
    hint_s = hint.strip() if isinstance(hint, str) else ""
    return {"top_rgb": tt, "bottom_rgb": bb, "hint": hint_s}


def suggest_hd_layout_background(image_path: str, user_prompt: str) -> dict | None:
    """
    Gemini Vision：根据拼版参考图 + 用户 prompt 建议纵向渐变底色与一句中文环境提示。
    成功返回 {"top_rgb": (r,g,b), "bottom_rgb": (r,g,b), "hint": str}；失败返回 None。
    """
    safe = (user_prompt or "").strip()
    if len(safe) > 4000:
        safe = safe[:4000]
    prompt = HD_LAYOUT_BG_PROMPT_TEMPLATE.format(user_prompt=safe if safe else "(none)")
    text = _call_vision_get_text(
        image_path,
        prompt,
        error_prefix="HD 拼版背景（Gemini）",
    )
    if not text:
        return None
    parsed = _parse_hd_layout_bg_json(text)
    if parsed is None:
        import sys

        print(
            "HD 拼版背景: 无法解析 JSON（期望 top_rgb/bottom_rgb/hint）— 返回片段: "
            + repr(text[:400]),
            file=sys.stderr,
        )
    return parsed


def detect_protrusion_bbox(image_path: str) -> tuple[float, float, float, float] | None:
    """
    识别应伸入顶部条带（y=0-40）的主体部分 bbox，用于 3320×500 专题长图。
    返回 (x_min, y_min, x_max, y_max) 比例 [0,1]，失败返回 None。支持多模型回退。
    """
    text = _call_vision_get_text(image_path, PROTRUSION_PROMPT, error_prefix="伸入区域 bbox 检测")
    if text is None:
        return None
    return _parse_bbox(text)


# 专题长图 A5b 语义 keep-mask：列出所有真实前景物体/角色框，排除环境与装饰氛围
FOREGROUND_OBJECTS_PROMPT = """This image is a horizontal strip cropped from the TOP area of a banner. It may contain one or more FOREGROUND objects/characters (e.g. people, characters, products, physical props/items) placed in front of a background.

List the bounding boxes of ALL clear FOREGROUND objects/characters — the real, solid subjects a viewer would treat as the main content.

STRICTLY EXCLUDE (do NOT list):
- Environment/background: sky, walls, floor, ground, ceiling, backdrops, plain color or gradient fills, ambient lighting.
- Decorative / atmosphere elements: floating particles, sparkles, glows, light rays, bokeh, dust, small scattered decorative icons, textures, patterns.

For each kept foreground object, output its bounding box as four numbers between 0 and 1: x_min, y_min, x_max, y_max (relative to THIS image).

Reply ONLY with a JSON array of arrays, e.g.:
[[0.30,0.05,0.55,0.95],[0.60,0.10,0.80,0.90]]
If there are no clear foreground objects, reply with an empty array: []
No other text."""


def _parse_bbox_list(text: str) -> list[tuple[float, float, float, float]]:
    """解析模型返回的「数组的数组」为 bbox 列表；兼容 JSON 与 0-1000 刻度。无有效框返回 []。"""
    if not text or not text.strip():
        return []
    s = text.strip()
    m = re.search(r"\[.*\]", s, re.S)
    raw = m.group(0) if m else s
    boxes: list = []
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, (list, tuple)) and len(item) >= 4:
                boxes.append(item[:4])
    if not boxes:
        for g in re.findall(
            r"\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]", raw
        ):
            boxes.append(g)
    out: list[tuple[float, float, float, float]] = []
    for box in boxes:
        try:
            vals = [float(v) for v in box[:4]]
        except (ValueError, TypeError):
            continue
        if any(v > 1.0 for v in vals):
            vals = [v / 1000.0 for v in vals]
        vals = [max(0.0, min(1.0, v)) for v in vals]
        x0, y0, x1, y1 = vals
        if x1 > x0 and y1 > y0:
            out.append((x0, y0, x1, y1))
    return out


def detect_foreground_objects_bboxes(
    image_path: str,
    context_prompt: str | None = None,
) -> list[tuple[float, float, float, float]] | None:
    """
    专题长图 A5b 用：列出图中所有真实前景物体/角色 bbox（排除环境与装饰氛围）。
    返回归一化框列表（可能为空 []），API/解析失败返回 None（调用方可回退纯 BiRefNet）。
    """
    prompt = FOREGROUND_OBJECTS_PROMPT
    if context_prompt:
        prompt = f"Image content hint: {context_prompt.strip()}\n\n" + prompt
    text = _call_vision_get_text(image_path, prompt, error_prefix="前景物体检测")
    if text is None:
        return None
    return _parse_bbox_list(text)


def image_has_unfilled_blanks(image_path: str) -> bool | None:
    """
    用 Gemini Vision 判断图中是否存在「未填充的空白区域」（如边缘黑条/空白画布），
    而非画面自带的黑/深色背景。失败或无法解析时返回 None（调用方可回退到 image_has_black_bars）。支持多模型回退。
    """
    text = _call_vision_get_text(image_path, UNFILLED_BLANKS_PROMPT, error_prefix="未填充区域检测")
    if text is None:
        return None
    return _parse_yes_no(text)


def image_fill_quality_need_refill(image_path: str) -> bool | None:
    """
    A4 填充质量检查：画面是否割裂、延展区内容是否与中心主体相关。
    Returns True=需要重新填充（有割裂或延展内容与主体无关），False=通过，None=API/解析失败（调用方不强制重填）。支持多模型回退。
    """
    text = _call_vision_get_text(image_path, FILL_QUALITY_NEED_REFILL_PROMPT, error_prefix="A4 填充质量检测")
    if text is None:
        return None
    return _parse_yes_no(text)


def _image_a4_need_refill_with_prompt(image_path: str, prompt: str) -> bool | None:
    """用指定 prompt 调用 Vision，返回 True=需重填, False=通过, None=失败。支持多模型回退。"""
    text = _call_vision_get_text(image_path, prompt, error_prefix="A4 重填检测")
    if text is None:
        return None
    return _parse_yes_no(text)


def image_a4_need_refill_unfilled(image_path: str) -> bool | None:
    """A4 分步检测 (1)：是否还有明显未填满。True=需重填, False=通过, None=失败。"""
    return _image_a4_need_refill_with_prompt(image_path, A4_NEED_REFILL_UNFILLED_PROMPT)


def image_a4_need_refill_seams(image_path: str) -> bool | None:
    """A4 分步检测 (2)：是否有明显接缝/拉伸/拼接/延展与中心无关。True=需重填, False=通过, None=失败。"""
    return _image_a4_need_refill_with_prompt(image_path, A4_NEED_REFILL_SEAMS_PROMPT)


def image_a6b_shop_header_need_repair(image_path: str) -> bool | None:
    """
    A6b（商店专题头图 1740×220）：是否有画面割裂、重复拼接。True=需修复, False=通过, None=Vision 失败。
    """
    text = _call_vision_get_text(
        image_path, A6B_SHOP_HEADER_SEAM_DETECT_PROMPT, error_prefix="A6b 专题头图画质检测"
    )
    if text is None:
        return None
    return _parse_yes_no(text)


def image_a4_need_refill(image_path: str) -> bool | None:
    """
    A4 一步检测（兼容）：先 (1) 未填满 再 (2) 接缝/割裂，任一项为 True 即需重填。
    Returns True=需要重新填充，False=通过，None=API/解析失败（调用方可用本地黑边检测兜底）。
    """
    unfilled = image_a4_need_refill_unfilled(image_path)
    if unfilled:
        return True
    seams = image_a4_need_refill_seams(image_path)
    if seams:
        return True
    if unfilled is False and seams is False:
        return False
    return None


def detect_subject_y_ratio(image_path: str) -> float | None:
    """
    Call Gemini Vision to get main subject vertical center as ratio in [0, 1].
    Returns None if key missing, API error, or unparseable response (caller should use center crop). 支持多模型回退。
    """
    text = _call_vision_get_text(image_path, SUBJECT_PROMPT_Y, error_prefix="主体 y 比例检测")
    if text is None:
        return None
    return _parse_ratio(text)


def detect_subject_xy_ratio(image_path: str) -> tuple[float | None, float | None]:
    """
    Call Gemini Vision to get main subject (x, y) center as ratios in [0, 1].
    Returns (x_ratio, y_ratio); (None, None) on failure. 支持多模型回退。
    """
    text = _call_vision_get_text(image_path, SUBJECT_PROMPT_XY, error_prefix="主体 xy 比例检测")
    if text is None:
        return (None, None)
    return _parse_two_ratios(text)


def main() -> None:
    import sys
    if len(sys.argv) < 2:
        print("Usage: gemini_subject_detect.py <image_path>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]
    ratio = detect_subject_y_ratio(path)
    if ratio is None:
        print("No ratio (missing key, API error, or unparseable).", file=sys.stderr)
        sys.exit(1)
    print(ratio)


if __name__ == "__main__":
    main()
