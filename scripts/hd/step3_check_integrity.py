#!/usr/bin/env python3
"""
HD 生产线 Step 3：主体完整性检测 + Gemini inpaint 补齐 + 统一光源色调
3a. Gemini Vision 检测每个主体是否完整（头/手/脸/身体/衣服）
3b. 不完整 → Gemini inpaint 补画缺失部分
3c. 统一 3 个主体的光源方向和色调
"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IMAGE_EDIT_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if str(IMAGE_EDIT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(IMAGE_EDIT_SCRIPTS))

_env_file = ROOT / ".env"
if _env_file.is_file():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                if _k not in os.environ:
                    os.environ[_k] = _v.strip().strip("\"'")

_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"
VISION_MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3-pro-preview"]

INTEGRITY_PROMPT = """Analyze this character cutout image. Check if the following body parts are COMPLETE and VISIBLE:
1. HEAD (including hair, top of head)
2. FACE (eyes, nose, mouth visible)
3. HANDS (both hands, fingers)
4. BODY (torso, clothing)
5. OVERALL completeness

Reply with ONLY a JSON object:
{"head": true/false, "face": true/false, "hands": true/false, "body": true/false, "complete": true/false, "missing": "brief description of what is missing or 'nothing'"}
Output ONLY the JSON, no markdown."""

COMPLETE_INPAINT_PROMPT = """This is a character cutout with transparent background. The character is missing: {missing_parts}.

Please complete the character by naturally extending/drawing the missing parts in the same art style, lighting, and color palette as the existing parts. Keep the transparent background. Do not change any existing parts of the character.

Output the completed character with the same transparent background."""

UNIFY_LIGHT_PROMPT = """This character cutout needs its lighting adjusted to match a scene with light coming from the upper-left direction. Adjust the highlights and shadows subtly to be consistent with upper-left lighting. Keep the art style and colors the same. Keep the transparent background."""


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


def _call_image_edit(image_path: Path, prompt: str, out_path: Path) -> Path | None:
    """调用 Gemini 图编，返回结果路径或 None。"""
    try:
        from gemini_image_edit import edit_image
        result = edit_image(str(image_path), str(out_path), prompt)
        if result and Path(result).is_file():
            return Path(result)
    except Exception as e:
        print(f"[step3] 图编失败: {e}", flush=True)
    return None


def check_integrity(cutout_path: Path) -> dict:
    """检测主体完整性，返回 {head, face, hands, body, complete, missing}。"""
    print(f"[step3] 检测完整性: {cutout_path.name} ...", flush=True)
    text = _call_vision(cutout_path, INTEGRITY_PROMPT)
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
                            print(f"[step3] 完整性: {obj}", flush=True)
                            return obj
                        except Exception:
                            break
    print(f"[step3] 完整性检测失败，假设完整", flush=True)
    return {"head": True, "face": True, "hands": True, "body": True, "complete": True, "missing": "nothing"}


def inpaint_missing(cutout_path: Path, missing_desc: str, out_path: Path) -> Path:
    """用 Gemini inpaint 补齐缺失部分。"""
    print(f"[step3] inpaint 补齐: {missing_desc} ...", flush=True)
    prompt = COMPLETE_INPAINT_PROMPT.format(missing_parts=missing_desc)
    result = _call_image_edit(cutout_path, prompt, out_path)
    if result:
        print(f"[step3] 补齐完成: {out_path.name}", flush=True)
        return result
    print(f"[step3] 补齐失败，保留原图", flush=True)
    import shutil
    shutil.copy2(cutout_path, out_path)
    return out_path


def unify_lighting(cutout_path: Path, out_path: Path) -> Path:
    """统一光源方向（左上光）。"""
    print(f"[step3] 统一光源: {cutout_path.name} ...", flush=True)
    result = _call_image_edit(cutout_path, UNIFY_LIGHT_PROMPT, out_path)
    if result:
        print(f"[step3] 光源统一完成: {out_path.name}", flush=True)
        return result
    print(f"[step3] 光源统一失败，保留原图", flush=True)
    import shutil
    shutil.copy2(cutout_path, out_path)
    return out_path


def run_step3(cutout_paths: list[Path], out_dir: Path) -> list[Path]:
    """
    对每个抠图：检测完整性 → 补齐 → 统一光源。
    返回处理后的路径列表。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, path in enumerate(cutout_paths):
        print(f"\n[step3] === 处理抠图 {i}: {path.name} ===", flush=True)
        current = path

        # 3a: 完整性检测
        integrity = check_integrity(current)

        # 3b: 不完整则补齐
        if not integrity.get("complete", True):
            missing = integrity.get("missing", "unknown parts")
            inpaint_out = out_dir / f"hd_inpaint_{i:02d}.png"
            current = inpaint_missing(current, missing, inpaint_out)

        # 3c: 统一光源
        light_out = out_dir / f"hd_unified_{i:02d}.png"
        current = unify_lighting(current, light_out)

        results.append(current)

    return results
