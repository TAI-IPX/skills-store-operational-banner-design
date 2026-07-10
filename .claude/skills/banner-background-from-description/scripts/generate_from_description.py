#!/usr/bin/env python3
"""
Generate a banner background from a short description (text-to-image), then crop to target W×H.
默认使用 nano-banana-2（BANNER_IMAGE_BACKEND=nano-banana）；可选 BANNER_IMAGE_BACKEND=gemini 走 Gemini API；可选 BANNER_IMAGE_BACKEND=t8star 走 OpenAI 兼容文生图（需 T8STAR_API_KEY，见 https://gpt-best.apifox.cn/api-341817446）。
Reuses banner-background-from-image's crop_to_target. Requires GEMINI_API_KEY（nano-banana 从 ~/.nano-banana/.env 读取）；t8star 需 T8STAR_API_KEY。
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# 若项目根存在 .env，加载 T8STAR_* / GEMINI_* / BANNER_IMAGE_BACKEND（仅当未设置时），便于即梦等 t8star 模型接入
_script_dir = Path(__file__).resolve().parent
_root = _script_dir.parent.parent.parent.parent  # scripts -> skill -> skills -> .claude -> 项目根
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))
# 确保可以导入 xingchengpt_images_api
_scripts_dir = _root / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
_env_file = _root / ".env"
if _env_file.is_file():
    _env_keys = (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_PROMPT_OPTIMIZER_MODEL",
        "GOOGLE_GEMINI_BASE_URL",
        "PACKY_API_KEY",
        "PACKY7S_API_KEY",
        "PACKYGPT_API_KEY",
        "PACKY_GEMINI_IMAGE_MODELS",
        "ANTHROPIC_API_KEY",
        "CLAUDE_PROMPT_OPTIMIZER_MODEL",
        "ANTHROPIC_API_BASE_URL",
        "T8STAR_API_KEY",
        "BANNER_IMAGE_BACKEND",
        "T8STAR_IMAGE_MODEL",
        "T8STAR_BASE_URL",
        "T8STAR_SIMPLE_T2I",
        "T8STAR_SIMPLE_T2I_SIZE",
        "VOLC_ACCESS_KEY_ID",
        "VOLC_SECRET_ACCESS_KEY",
        "LOVART_ACCESS_KEY",
        "LOVART_SECRET_KEY",
        "LOVART_PROJECT_ID",
        "LOVART_PREFER_MODELS",
        "LOVART_UNLIMITED_TIMEOUT",
        "LOVART_FAST_TIMEOUT",
        "LOVART_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    )
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                if _k in _env_keys and _v.strip().strip('"\'') and _k not in os.environ:
                    os.environ[_k] = _v.strip().strip('"\'')

# 默认生图后端：nano-banana / gemini / t8star（OpenAI 兼容 /v1/images/generations）
BANNER_IMAGE_BACKEND = os.environ.get("BANNER_IMAGE_BACKEND", "nano-banana").strip().lower()

# t8star / OpenAI 兼容文生图（与接口文档 https://gpt-best.apifox.cn/api-341817446 一致）
T8STAR_BASE_URL = os.environ.get("T8STAR_BASE_URL", "https://ai.t8star.cn").rstrip("/")
_t8_models_raw = os.environ.get("T8STAR_IMAGE_MODEL", "nano-banana")
T8STAR_IMAGE_MODELS = [m.strip() for m in _t8_models_raw.split(",") if m.strip()]
if not T8STAR_IMAGE_MODELS:
    T8STAR_IMAGE_MODELS = ["nano-banana"]
T8STAR_MAX_RETRIES = int(os.environ.get("T8STAR_MAX_RETRIES", "3"))
T8STAR_RETRY_DELAY = float(os.environ.get("T8STAR_RETRY_DELAY", "10"))
# 简易文生图：与 https://gpt-best.apifox.cn/api-229045941 一致，仅 prompt/n/size，返回 data[].url
T8STAR_SIMPLE_T2I = os.environ.get("T8STAR_SIMPLE_T2I", "").strip().lower() in ("1", "true", "yes")
T8STAR_SIMPLE_T2I_SIZE = os.environ.get("T8STAR_SIMPLE_T2I_SIZE", "1024x1024").strip()  # 256x256 | 512x512 | 1024x1024

DEFAULT_PROMPT_OPTIMIZER_MODEL = "gemini-3-flash-preview"
PROMPT_PREFIX = ""
PROMPT_SUFFIX = ""
_GEMINI_503_RETRIES = 3
_GEMINI_503_BACKOFF_BASE = 10
DEFAULT_CLAUDE_PROMPT_OPTIMIZER_MODEL = "claude-3-5-sonnet-20241022"

sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "scripts"))
from scripts.ensure_python import get_python_exe
PYTHON_EXE = get_python_exe()

def _nano_banana_exe() -> tuple[Optional[Path], list[str]]:
    """Resolve nano-banana: (exe_path, prefix_args).
    Prefer in-repo .claude/skills/nano-banana-2-skill-check (bun run src/cli.ts), then NANO_BANANA_EXE, else ~/.bun/bin/nano-banana.
    """
    script_dir = Path(__file__).resolve().parent
    exe = os.environ.get("NANO_BANANA_EXE")
    if exe and Path(exe).is_file():
        return (Path(exe), [])
    home = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "")))
    for p in (home / ".bun" / "bin" / "nano-banana.exe", home / ".bun" / "bin" / "nano-banana"):
        if p.is_file():
            return (p, [])
    return (None, [])


def _generate_image_nano_banana(prompt: str, output_path: str) -> Optional[Path]:
    """Use nano-banana CLI for text-to-image. 固定使用 gemini-3.1-flash-image-preview. Returns output path on success, None on failure."""
    exe, prefix_args = _nano_banana_exe()
    if not exe:
        return None
    out_path = Path(output_path)
    out_dir = out_path.parent
    out_stem = out_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        [str(exe)]
        + prefix_args
        + [
            prompt,
            "-o", out_stem,
            "-d", str(out_dir.resolve()),
            "-s", "2K",
            "-a", "16:9",
            "-m", "gemini-3.1-flash-image-preview",
        ]
    )
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[nano-banana] 执行失败: {r.stderr or r.stdout}", file=sys.stderr)
            return None
        # 输出为 out_dir/out_stem.png
        result = out_dir / f"{out_stem}.png"
        if result.is_file():
            if result.resolve() != Path(output_path).resolve():
                shutil.copy2(result, output_path)
            return Path(output_path)
        return None
    except Exception as e:
        print(f"[nano-banana] 调用异常: {e}", file=sys.stderr)
        return None


def _generate_image_nano_banana_i2i(
    prompt: str, reference_image_path: str, output_path: str
) -> Optional[Path]:
    """nano-banana 图生图：使用 CLI -r/--ref 传入参考图。"""
    exe, prefix_args = _nano_banana_exe()
    if not exe:
        return None
    ref_path = Path(reference_image_path).resolve()
    if not ref_path.is_file():
        print(f"[nano-banana i2i] 参考图不存在: {ref_path}", file=sys.stderr)
        return None
    out_path = Path(output_path)
    out_dir = out_path.parent
    out_stem = out_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        [str(exe)]
        + prefix_args
        + [
            prompt,
            "-r", str(ref_path),
            "-o", out_stem,
            "-d", str(out_dir.resolve()),
            "-s", "2K",
            "-a", "16:9",
            "-m", "gemini-3.1-flash-image-preview",
        ]
    )
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[nano-banana i2i] 执行失败: {r.stderr or r.stdout}", file=sys.stderr)
            return None
        result = out_dir / f"{out_stem}.png"
        if result.is_file():
            if result.resolve() != Path(output_path).resolve():
                shutil.copy2(result, output_path)
            return Path(output_path)
        return None
    except Exception as e:
        print(f"[nano-banana i2i] 调用异常: {e}", file=sys.stderr)
        return None


def _decode_b64_to_image(b64_s: str) -> bytes | None:
    """
    将 t8star/即梦 返回的 b64_json 解码为图片字节。
    部分接口返回长度 4k+1 等非法 base64，尝试多种修正策略（去首尾字符、补 padding）后解码，
    仅当解码结果带 PNG/JPEG 魔数时才返回。
    """
    raw = b64_s.replace("\n", "").replace("\r", "").replace(" ", "").strip()
    if not raw:
        return None

    def try_decode(s: str) -> bytes | None:
        if len(s) % 4:
            s = s + ("=" * (4 - len(s) % 4))
        try:
            out = base64.b64decode(s, validate=False)
        except Exception:
            return None
        if len(out) < 100:
            return None
        if out[:4] == b"\x89PNG" or out[:2] == b"\xff\xd8":
            return out
        return None

    out = try_decode(raw)
    if out:
        return out
    # 长度 4k+1 时常见为多一个尾字符或首字符异常
    if len(raw) % 4 == 1:
        out = try_decode(raw[:-1])
        if out:
            return out
        out = try_decode(raw[1:])
        if out:
            return out
    return None


def _generate_image_t8star_simple(prompt: str, output_path: str) -> Optional[Path]:
    """
    简易文生图，与 https://gpt-best.apifox.cn/api-229045941 一致：
    请求体仅 prompt、n、size；响应 data[].url。无 model 参数，适合部分网关/代理。
    """
    url = f"{T8STAR_BASE_URL}/v1/images/generations"
    size = T8STAR_SIMPLE_T2I_SIZE
    if size not in ("256x256", "512x512", "1024x1024"):
        size = "1024x1024"
    body = {"prompt": prompt, "n": 1, "size": size}
    body_bytes = json.dumps(body).encode("utf-8")
    for attempt in range(1, T8STAR_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + _get_t8star_key(),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            if attempt < T8STAR_MAX_RETRIES and e.code in (429, 502, 503):
                time.sleep(T8STAR_RETRY_DELAY)
                continue
            print(f"[t8star simple] API {e.code}: {err_body[:300]}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            if attempt < T8STAR_MAX_RETRIES:
                time.sleep(T8STAR_RETRY_DELAY)
                continue
            print(f"[t8star simple] Request error: {e.reason}", file=sys.stderr)
            return None
        items = data.get("data") or []
        if not items or not items[0].get("url"):
            print("[t8star simple] 响应无 data[].url", file=sys.stderr)
            return None
        img_url = items[0]["url"]
        for with_auth in (True, False):
            try:
                headers = {"Authorization": "Bearer " + _get_t8star_key()} if with_auth else {}
                img_req = urllib.request.Request(img_url, headers=headers)
                with urllib.request.urlopen(img_req, timeout=60) as r:
                    out_bytes = r.read()
                if out_bytes and (out_bytes[:4] == b"\x89PNG" or out_bytes[:2] == b"\xff\xd8"):
                    out_path = Path(output_path)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(out_bytes)
                    return out_path
            except Exception as e:
                if not with_auth:
                    print(f"[t8star simple] 拉取 url 失败: {e}", file=sys.stderr)
        return None
    return None


def _get_t8star_key() -> str:
    key = os.environ.get("T8STAR_API_KEY")
    if not key or not key.strip():
        print(
            "Error: T8STAR_API_KEY not set. Set it: export T8STAR_API_KEY='your-token' (e.g. https://ai.t8star.cn or gpt-best)",
            file=sys.stderr,
        )
        sys.exit(1)
    return key.strip()


def _generate_image_t8star(prompt: str, output_path: str, models: list[str] | None = None) -> Optional[Path]:
    """
    OpenAI 兼容文生图：POST /v1/images/generations。
    按接口文档使用 response_format=b64_json（避免 URL 403）、aspect_ratio=16:9（横图 banner）。
    models: 可选，未传则用全局 T8STAR_IMAGE_MODELS。
    """
    model_list = models if models is not None else T8STAR_IMAGE_MODELS
    url = f"{T8STAR_BASE_URL}/v1/images/generations"
    last_err: str | None = None
    # 即梦等部分模型返回的 b64_json 可能无法正确解码，优先请求 url（文档支持 url 或 b64_json）
    use_url_format = any(
        "jimeng" in m.lower() or "seedream" in m.lower() for m in model_list
    )
    for model in model_list:
        body = {
            "model": model,
            "prompt": prompt,
            "response_format": "url" if use_url_format else "b64_json",
            "aspect_ratio": "16:9",
        }
        body_bytes = json.dumps(body).encode("utf-8")
        data = None
        for attempt in range(1, T8STAR_MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + _get_t8star_key(),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                last_err = None
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                # 模型不可用/未配置价格等时尝试下一模型
                if e.code in (400, 401, 403, 500) and len(model_list) > 1:
                    last_err = f"{e.code}: {err_body[:200]}"
                    break
                if e.code in (429, 502, 503) and attempt < T8STAR_MAX_RETRIES:
                    print(
                        f"[t8star] API {e.code} (model={model}, attempt {attempt}/{T8STAR_MAX_RETRIES}), retry in {T8STAR_RETRY_DELAY}s...",
                        file=sys.stderr,
                    )
                    time.sleep(T8STAR_RETRY_DELAY)
                    continue
                print(f"[t8star] API error {e.code}: {err_body[:500]}", file=sys.stderr)
                return None
            except urllib.error.URLError as e:
                if attempt < T8STAR_MAX_RETRIES:
                    print(
                        f"[t8star] Request error: {e.reason} (model={model}), retry in {T8STAR_RETRY_DELAY}s...",
                        file=sys.stderr,
                    )
                    time.sleep(T8STAR_RETRY_DELAY)
                    continue
                print(f"[t8star] Request error: {e.reason}", file=sys.stderr)
                return None
        if data is None:
            continue
        items = data.get("data") or []
        if not items:
            if data.get("error"):
                last_err = str(data.get("error", ""))[:200]
            continue
        first = items[0]
        out_bytes = None
        if first.get("b64_json"):
            out_bytes = _decode_b64_to_image(first["b64_json"])
        if out_bytes is None and first.get("url"):
            img_url = first["url"]
            for with_auth in (True, False):
                try:
                    headers = {"Authorization": "Bearer " + _get_t8star_key()} if with_auth else {}
                    img_req = urllib.request.Request(img_url, headers=headers)
                    with urllib.request.urlopen(img_req, timeout=60) as r:
                        out_bytes = r.read()
                    if out_bytes and (out_bytes[:4] == b"\x89PNG" or out_bytes[:2] == b"\xff\xd8"):
                        break
                    out_bytes = None
                except Exception as e:
                    if not with_auth:
                        print(f"[t8star] Failed to fetch image URL: {e}", file=sys.stderr)
                    out_bytes = None
        if out_bytes:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(out_bytes)
            return out_path
        if len(model_list) > 1:
            print(f"[t8star] model={model} 返回无法解码或无 url，尝试下一模型...", file=sys.stderr)
    if last_err:
        print(f"[t8star] All candidate models failed. Last error: {last_err}", file=sys.stderr)
    else:
        print("[t8star] b64_json 解码失败且无可用 url，请检查接口返回或联系贞贞的AI工坊。", file=sys.stderr)
    return None


def _generate_image_t8star_i2i(
    prompt: str,
    reference_image_path: str,
    output_path: str,
    models: list[str] | None = None,
) -> Optional[Path]:
    """
    t8star 图生图：尝试 OpenAI 兼容的 /v1/images/edits（image + prompt → 新图）。
    若贞贞未开放该接口则返回 None，调用方将提示用户改用 jimeng/gemini/nano-banana。
    """
    ref_path = Path(reference_image_path).resolve()
    if not ref_path.is_file():
        print(f"[t8star i2i] 参考图不存在: {ref_path}", file=sys.stderr)
        return None
    url = f"{T8STAR_BASE_URL}/v1/images/edits"
    boundary = "----BannerFormBoundary" + str(time.time()).replace(".", "")
    body_bytes = (
        b"--" + boundary.encode() + b"\r\n"
        b'Content-Disposition: form-data; name="image"; filename="ref.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
    )
    try:
        body_bytes += ref_path.read_bytes()
    except Exception as e:
        print(f"[t8star i2i] 读取参考图失败: {e}", file=sys.stderr)
        return None
    body_bytes += (
        b"\r\n--" + boundary.encode() + b"\r\n"
        b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        + prompt.encode("utf-8") + b"\r\n"
        b"--" + boundary.encode() + b"--\r\n"
    )
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={
            "Authorization": "Bearer " + _get_t8star_key(),
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 501):
            print("[t8star i2i] 接口 /v1/images/edits 未开放，请使用 -M jimeng / -M gemini 或 nano-banana。", file=sys.stderr)
        else:
            err_body = e.read().decode("utf-8") if e.fp else ""
            print(f"[t8star i2i] API {e.code}: {err_body[:200]}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"[t8star i2i] 请求错误: {e.reason}", file=sys.stderr)
        return None
    items = data.get("data") or []
    if not items:
        return None
    first = items[0]
    out_bytes = None
    if first.get("b64_json"):
        out_bytes = _decode_b64_to_image(first["b64_json"])
    if out_bytes is None and first.get("url"):
        img_url = first["url"]
        try:
            with urllib.request.urlopen(
                urllib.request.Request(img_url, headers={"Authorization": "Bearer " + _get_t8star_key()}),
                timeout=60,
            ) as r:
                out_bytes = r.read()
        except Exception:
            out_bytes = None
    if out_bytes:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(out_bytes)
        return out_path.resolve()
    return None


def _generate_image_jimeng(
    prompt: str, output_path: str, width: int = 1024, height: int = 1024
) -> Optional[Path]:
    """
    火山引擎即梦 4.0 文生图：调用项目 scripts/jimeng_volc_api.py。
    需在 .env 或环境变量中配置 VOLC_ACCESS_KEY_ID、VOLC_SECRET_ACCESS_KEY。
    width/height：即梦输出尺寸，无图流程建议 4096×1024（4:1，与 A4 画布一致）；即梦文档单边 1024～4096 时常可直接宽高取满。
    """
    jimeng_script = _root / "scripts" / "jimeng_volc_api.py"
    if not jimeng_script.is_file():
        print(
            f"[jimeng] 未找到脚本 {jimeng_script}，请确认项目根目录下存在 scripts/jimeng_volc_api.py",
            file=sys.stderr,
        )
        return None
    if not os.environ.get("VOLC_ACCESS_KEY_ID") or not os.environ.get("VOLC_SECRET_ACCESS_KEY"):
        print(
            "[jimeng] 请设置 VOLC_ACCESS_KEY_ID 和 VOLC_SECRET_ACCESS_KEY（.env 或环境变量）",
            file=sys.stderr,
        )
        return None
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYTHON_EXE, str(jimeng_script), "--t2i", "-p", prompt, "-o", output_path,
        "--width", str(width), "--height", str(height),
    ]
    result = subprocess.run(cmd, cwd=str(_root))
    if result.returncode != 0:
        return None
    return out_path.resolve() if out_path.is_file() else None


def _generate_image_jimeng_i2i(
    prompt: str,
    reference_image_path: str,
    output_path: str,
    width: int = 1024,
    height: int = 1024,
    *,
    use_smart_ref: bool = False,
) -> Optional[Path]:
    """
    火山引擎即梦图生图：以参考图 + 提示词生成图，调用 scripts/jimeng_volc_api.py --i2i。
    use_smart_ref=True 时使用即梦 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致。
    """
    jimeng_script = _root / "scripts" / "jimeng_volc_api.py"
    if not jimeng_script.is_file():
        print(
            f"[jimeng i2i] 未找到脚本 {jimeng_script}",
            file=sys.stderr,
        )
        return None
    if not os.environ.get("VOLC_ACCESS_KEY_ID") or not os.environ.get("VOLC_SECRET_ACCESS_KEY"):
        print("[jimeng i2i] 请设置 VOLC_ACCESS_KEY_ID 和 VOLC_SECRET_ACCESS_KEY", file=sys.stderr)
        return None
    ref_path = Path(reference_image_path).resolve()
    if not ref_path.is_file():
        print(f"[jimeng i2i] 参考图不存在: {ref_path}", file=sys.stderr)
        return None
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYTHON_EXE, str(jimeng_script), "--i2i", "-p", prompt, "-i", str(ref_path),
        "-o", output_path, "--width", str(width), "--height", str(height),
    ]
    if use_smart_ref:
        cmd.append("--smart-ref")
    result = subprocess.run(cmd, cwd=str(_root))
    if result.returncode != 0:
        return None
    return out_path.resolve() if out_path.is_file() else None


def _generate_image_xingchengpt(
    prompt: str,
    output_path: str,
    reference_image: str | None = None,
) -> Optional[Path]:
    """
    XingchenGPT 文生图/图生图：通过 xingchengpt_images_api 调用 gpt-image-2。
    需在 .env 或环境变量中配置 XINGCHENGGPT_API_KEY、XINGCHENGGPT_BASE_URL。
    - 文生图 (t2i)：POST /v1/images/generations
    - 图生图 (i2i)：POST /v1/chat/completions（多模态）
    """
    try:
        from xingchengpt_images_api import generate_image, chat_completions_image
    except ImportError:
        print("[xingchengpt] 无法导入 xingchengpt_images_api", file=sys.stderr)
        return None

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if reference_image:
        ref_path = Path(reference_image)
        if not ref_path.is_file():
            print(f"[xingchengpt i2i] 参考图不存在: {ref_path}", file=sys.stderr)
            return None
        ref_bytes = ref_path.read_bytes()
        try:
            from PIL import Image as _PILImage
            from io import BytesIO as _BytesIO
            im = _PILImage.open(_BytesIO(ref_bytes))
            w, h = im.size
            max_d = 2048
            if max(w, h) > max_d:
                scale = max_d / float(max(w, h))
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
                buf = _BytesIO()
                im.save(buf, format="PNG")
                ref_bytes = buf.getvalue()
                print(f"[xingchengpt i2i] 参考图已缩放至 {nw}x{nh} (原 {w}x{h})", flush=True)
            else:
                print(f"[xingchengpt i2i] 参考图 {w}x{h}，无需缩放", flush=True)
        except Exception:
            print("[xingchengpt i2i] PIL 不可用，直接编码原始图", flush=True)

        import tempfile as _tempfile
        fd, tmp_ref = _tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            Path(tmp_ref).write_bytes(ref_bytes)
            result = chat_completions_image([tmp_ref], prompt, str(out_path))
        finally:
            try:
                os.unlink(tmp_ref)
            except OSError:
                pass
        return result
    else:
        return generate_image(prompt, str(out_path))


def _generate_image_moxingpt(
    prompt: str,
    output_path: str,
    reference_image: str | None = None,
) -> Optional[Path]:
    """
    MoxinGPT 文生图/图生图：通过 moxin.studio 调用 gpt-image-2。
    需在 .env 或环境变量中配置 MOXINGPT_API_KEY、MOXINGPT_BASE_URL。
    - 文生图 (t2i)：POST /v1/chat/completions (OpenAI 兼容)
    """
    try:
        from moxingpt_images_api import generate_image, chat_completions_image
    except ImportError:
        print("[moxingpt] 无法导入 moxingpt_images_api", file=sys.stderr)
        return None

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if reference_image:
        ref_path = Path(reference_image)
        if not ref_path.is_file():
            print(f"[moxingpt i2i] 参考图不存在: {ref_path}", file=sys.stderr)
            return None
        import tempfile as _tempfile
        fd, tmp_ref = _tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            Path(tmp_ref).write_bytes(ref_path.read_bytes())
            result = chat_completions_image([tmp_ref], prompt, str(out_path))
        finally:
            try:
                os.unlink(tmp_ref)
            except OSError:
                pass
        return result
    else:
        return generate_image(prompt, str(out_path))


def _generate_image_packygpt(
    prompt: str,
    output_path: str,
    reference_image: str | None = None,
) -> Optional[Path]:
    """
    PackyGPT 文生图/图生图：通过 packyapi.com 调用 gpt-image-2。
    需在 .env 或环境变量中配置 PACKYGPT_API_KEY。
    - 文生图 (t2i)：POST /v1/images/generations (OpenAI 标准)
    - 图生图 (i2i)：POST /v1/images/edits (multipart/form-data 文件上传)
    文档：https://docs.packyapi.com/docs/paint/GPTImage.html
    """
    api_key = (
        os.environ.get("PACKYGPT_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not api_key or not api_key.startswith("sk-"):
        print("[packygpt] 请设置 PACKYGPT_API_KEY（.env 或环境变量）", file=sys.stderr)
        return None

    base_url = os.environ.get("OPENAI_BASE_URL", "https://www.packyapi.com").rstrip("/")
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }

    # 代理检测（根据文档建议直连 packyapi.com，代理可能断开长连接）
    import requests as _requests
    _proxies = None
    _no_proxy = os.environ.get("PACKYGPT_NO_PROXY", "").strip()
    if _no_proxy.lower() in ("1", "true", "yes"):
        print("[packygpt] PACKYGPT_NO_PROXY=1，跳过代理直连", flush=True)
    else:
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
            print("[packygpt] 检测到系统代理，如请求超时请设 PACKYGPT_NO_PROXY=1 跳过代理", flush=True)

    if reference_image:
        # ── i2i：POST /v1/images/edits (multipart/form-data) ──
        ref_path = Path(reference_image)
        if not ref_path.is_file():
            print(f"[packygpt i2i] 参考图不存在: {ref_path}", file=sys.stderr)
            return None

        url = f"{base_url}/v1/images/edits"
        print(f"[packygpt i2i] 上传参考图 {ref_path.name} ({ref_path.stat().st_size/1024:.0f} KB)...", flush=True)

        # 可选：降低上传图片大小以加速
        try:
            from io import BytesIO as _BytesIO
            from PIL import Image as _PILImage
            ref_bytes = ref_path.read_bytes()
            im = _PILImage.open(_BytesIO(ref_bytes))
            w, h = im.size
            max_d = 2048
            if max(w, h) > max_d:
                scale = max_d / float(max(w, h))
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
                buf = _BytesIO()
                fmt = "PNG" if ref_path.suffix.lower() == ".png" else "JPEG"
                im.save(buf, format=fmt)
                ref_bytes = buf.getvalue()
                print(f"[packygpt i2i] 参考图已缩放至 {nw}x{nh} (原 {w}x{h})", flush=True)
        except Exception:
            ref_bytes = ref_path.read_bytes()

        mime_type = "image/png" if ref_path.suffix.lower() == ".png" else "image/jpeg"
        files = {"image": (ref_path.name, ref_bytes, mime_type)}
        data = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": "1536x1024",
            "quality": "high",
            "output_format": "png",
            "response_format": "url",
            "input_fidelity": "high",
        }
        try:
            resp = _requests.post(url, data=data, files=files, headers=headers, timeout=600, proxies=_proxies)
            resp.raise_for_status()
            result_data = resp.json()
        except Exception as e:
            print(f"[packygpt i2i] 请求失败: {e}", file=sys.stderr)
            return None
    else:
        # ── t2i：POST /v1/images/generations ──
        url = f"{base_url}/v1/images/generations"
        body = json.dumps({
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": "1024x640",
            "quality": "high",
            "n": 1,
        }).encode("utf-8")
        print(f"[packygpt] 生成 1024x640 图片...", flush=True)
        try:
            resp = _requests.post(url, data=body, headers={**headers, "Content-Type": "application/json"}, timeout=300, proxies=_proxies)
            resp.raise_for_status()
            result_data = resp.json()
        except Exception as e:
            print(f"[packygpt] 请求失败: {e}", file=sys.stderr)
            return None

    img_url = result_data.get("data", [{}])[0].get("url", "")
    b64 = result_data.get("data", [{}])[0].get("b64_json", "")

    if not img_url and not b64:
        print(f"[packygpt] 未获取到图片数据。响应: {json.dumps(result_data, ensure_ascii=False)[:300]}", file=sys.stderr)
        return None

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if img_url:
            resp = _requests.get(img_url, timeout=300, proxies=_proxies)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)
        elif b64:
            import base64 as _b64
            with open(tmp_path, "wb") as f:
                f.write(_b64.b64decode(b64))

        try:
            from PIL import Image as _Image
            img = _Image.open(tmp_path)
            gen_w, gen_h = img.size
            img.save(str(out_path))
            print(f"[packygpt] 已保存: {out_path} ({gen_w}x{gen_h})", flush=True)
        except ImportError:
            import shutil
            shutil.copy2(tmp_path, str(out_path))
            print(f"[packygpt] 已保存（PIL 不可用）: {out_path}", flush=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return out_path.resolve() if out_path.is_file() else None


def _generate_image_micugpt2(
    prompt: str,
    output_path: str,
    reference_image: str | None = None,
) -> Optional[Path]:
    """
    MicuGPT2 文生图/图生图：通过 micuapi.ai 调用 gpt-image-2。
    需在 .env 或环境变量中配置 MICUAPI_API_KEY。
    - 文生图 (t2i)：POST /v1/images/generations (OpenAI DALL-E 标准)
    - 图生图 (i2i)：POST /v1/chat/completions (多模态 messages)
    """
    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key or not api_key.startswith("sk-"):
        print("[micugpt2] 请设置 MICUAPI_API_KEY（.env 或环境变量）", file=sys.stderr)
        return None

    base_url = "https://www.micuapi.ai/v1"
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    # 自动检测系统代理
    import requests as _requests
    _proxies = None
    _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not _sys_proxy:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                if _sys_proxy:
                    if not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                    print(f"[micugpt2] 检测到系统代理: {_sys_proxy}", flush=True)
            winreg.CloseKey(key)
        except Exception:
            pass
    if _sys_proxy:
        _proxies = {"https": _sys_proxy, "http": _sys_proxy}

    # 加载参考图（i2i 多模态输入）
    ref_b64 = None
    ref_mime = "image/png"
    if reference_image:
        ref_path = Path(reference_image)
        if not ref_path.is_file():
            print(f"[micugpt2] 参考图不存在: {ref_path}", file=sys.stderr)
            return None
        try:
            from io import BytesIO as _BytesIO
            from PIL import Image as _PILImage
            ref_bytes = ref_path.read_bytes()
            im = _PILImage.open(_BytesIO(ref_bytes))
            im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
            w, h = im.size
            max_d = 1536
            if max(w, h) > max_d:
                scale = max_d / float(max(w, h))
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
                buf = _BytesIO()
                im.save(buf, format="PNG")
                ref_bytes = buf.getvalue()
                print(f"[micugpt2 i2i] 参考图已缩放至 {nw}x{nh} (原 {w}x{h})", flush=True)
            else:
                print(f"[micugpt2 i2i] 参考图 {w}x{h}，无需缩放", flush=True)
            ref_b64 = base64.standard_b64encode(ref_bytes).decode("ascii")
        except ImportError:
            ref_bytes = ref_path.read_bytes()
            ref_b64 = base64.standard_b64encode(ref_bytes).decode("ascii")
            print("[micugpt2 i2i] PIL 不可用，直接编码原始图", flush=True)

    # 构造请求：t2i 走 /v1/images/generations，i2i 走 /v1/chat/completions
    if ref_b64:
        # i2i: /v1/chat/completions 多模态
        url = f"{base_url}/chat/completions"
        body = json.dumps({
            "model": "gpt-image-2",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{ref_mime};base64,{ref_b64}"}},
                ]
            }],
        }).encode("utf-8")
    else:
        # t2i: /v1/images/generations (OpenAI DALL-E 标准)
        url = f"{base_url}/images/generations"
        body = json.dumps({
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": "1024x640",
            "quality": "high",
            "n": 1,
        }).encode("utf-8")

    print(f"[micugpt2] 生成图片...", flush=True)
    try:
        resp = _requests.post(url, data=body, headers=headers, timeout=180, proxies=_proxies)
        data = resp.json()
    except Exception as e:
        print(f"[micugpt2] 请求失败: {e}", file=sys.stderr)
        return None

    # 解析图片 URL
    img_url = ""
    b64_out = ""

    # 格式1: DALL-E 标准 data[0].url / b64_json
    dall_e_data = data.get("data", [{}])
    if dall_e_data:
        img_url = dall_e_data[0].get("url", "")
        b64_out = dall_e_data[0].get("b64_json", "")

    # 格式2: Chat Completions 多模态 content（i2i 回包）
    if not img_url and not b64_out:
        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        img_url = part.get("image_url", {}).get("url", "")
                        if img_url:
                            break
            elif isinstance(content, str):
                md_match = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', content)
                if md_match:
                    img_url = md_match.group(1)
                elif content.startswith("data:image"):
                    b64_out = content.split(",")[-1] if "," in content else content
                elif content.strip().startswith(("https://", "http://")):
                    img_url = content.strip().split()[0]

    if not img_url and not b64_out:
        print(f"[micugpt2] 未获取到图片数据。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    # 下载并保存
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if img_url:
            resp = _requests.get(img_url, timeout=300, proxies=_proxies)
            resp.raise_for_status()
            with open(tmp_path, "wb") as f:
                f.write(resp.content)
        elif b64_out:
            import base64 as _b64
            with open(tmp_path, "wb") as f:
                f.write(_b64.b64decode(b64_out))

        try:
            from PIL import Image as _Image
            img = _Image.open(tmp_path)
            gen_w, gen_h = img.size
            img.save(str(out_path))
            print(f"[micugpt2] 已保存: {out_path} ({gen_w}x{gen_h})", flush=True)
        except ImportError:
            import shutil
            shutil.copy2(tmp_path, str(out_path))
            print(f"[micugpt2] 已保存（PIL 不可用）: {out_path}", flush=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return out_path.resolve() if out_path.is_file() else None


def _vision_micugpt2(
    image_path: str,
    question: str,
) -> Optional[str]:
    """
    MicuGPT2 图像识别（Vision）：向 micuapi.ai 发送图片 + 问题，返回文字描述。
    endpoint: /v1/chat/completions，model: gpt-image-2（多模态输入，文字输出）。
    """
    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key or not api_key.startswith("sk-"):
        print("[micugpt2 vision] 请设置 MICUAPI_API_KEY", file=sys.stderr)
        return None

    ref_path = Path(image_path)
    if not ref_path.is_file():
        print(f"[micugpt2 vision] 图片不存在: {ref_path}", file=sys.stderr)
        return None

    # 加载并编码图片
    try:
        from io import BytesIO as _BytesIO
        from PIL import Image as _PILImage
        ref_bytes = ref_path.read_bytes()
        im = _PILImage.open(_BytesIO(ref_bytes))
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
        w, h = im.size
        max_d = 1024  # Vision 不需要太高分辨率
        if max(w, h) > max_d:
            scale = max_d / float(max(w, h))
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        else:
            nw, nh = w, h
        buf = _BytesIO()
        im.save(buf, format="PNG")
        ref_bytes = buf.getvalue()
        ref_b64 = base64.standard_b64encode(ref_bytes).decode("ascii")
        print(f"[micugpt2 vision] 图片 {w}x{h} -> {nw}x{nh}", flush=True)
    except ImportError:
        ref_bytes = ref_path.read_bytes()
        ref_b64 = base64.standard_b64encode(ref_bytes).decode("ascii")
        print("[micugpt2 vision] PIL 不可用，直接编码", flush=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    body = json.dumps({
        "model": "gpt-image-2",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref_b64}"}},
            ]
        }],
    }).encode("utf-8")

    # 代理检测
    import requests as _requests
    _proxies = None
    _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not _sys_proxy:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                if _sys_proxy and not _sys_proxy.startswith("http"):
                    _sys_proxy = "http://" + _sys_proxy
            winreg.CloseKey(key)
        except Exception:
            pass
    if _sys_proxy:
        _proxies = {"https": _sys_proxy, "http": _sys_proxy}

    url = "https://www.micuapi.ai/v1/chat/completions"
    print(f"[micugpt2 vision] 识别中...", flush=True)
    try:
        resp = _requests.post(url, data=body, headers=headers, timeout=300, proxies=_proxies)
        data = resp.json()
    except Exception as e:
        print(f"[micugpt2 vision] 请求失败: {e}", file=sys.stderr)
        return None

    for choice in data.get("choices", []):
        msg = choice.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            print(f"[micugpt2 vision] 识别结果: {content[:120]}...", flush=True)
            return content
        elif isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            result = "".join(text_parts).strip()
            if result:
                print(f"[micugpt2 vision] 识别结果: {result[:120]}...", flush=True)
                return result

    print(f"[micugpt2 vision] 未获取到文字响应。{json.dumps(data, ensure_ascii=False)[:300]}", file=sys.stderr)
    return None


def _i2i_layout_lock_lead(
    canvas_w: int,
    canvas_h: int,
    safe_zone: tuple[int, int, int, int] | None,
) -> str:
    """
    图生图「布局锁定」引导语：约束人物水平位置、疏密、叠压与可选像素安全区，
    减轻模型把三人摊满全宽、迁出规范区等问题。
    """
    core = (
        f"参考图为 {canvas_w}×{canvas_h} 像素的横版游戏/应用商店 Banner 拼版示意图。"
        "请在保持与参考图几乎一致的人物构图骨架的前提下重绘：可大幅优化背景、氛围、光效与材质，"
        "但【布局锁定】必须满足：（1）从左到右的人物个数与顺序不变；"
        "（2）各人物在画面中的大致水平位置与参考图一致，禁止改成三人均匀铺满整幅宽度、各占左/中/右三分的松散分栏；"
        "（3）人物之间的横向疏密、前后叠压（谁遮住谁）须与参考图一致，可适当加强纵深与轻微重叠，"
        "不要拉远成互不接触的三张贴纸；（4）输出图像尺寸与画幅比例须与参考图一致。"
    )
    if safe_zone is not None:
        sx0, sx1, sy0, sy1 = safe_zone
        core += (
            f"（5）规范安全区：主要人物头身与显著肢体轮廓应落在横向约 x={sx0}～{sx1}、"
            f"纵向约 y={sy0}～{sy1} 像素内（画布原点左上）；"
            "画幅左右两侧条带仅作远景或装饰背景，不要把人物整体挪到极左或极右贴边区。"
        )
    return core


def _generate_image_gemini_i2i(
    prompt: str,
    reference_image_path: str,
    output_path: str,
    *,
    preserve_reference_layout: bool = False,
    canvas_w: int | None = None,
    canvas_h: int | None = None,
    layout_safe_zone: tuple[int, int, int, int] | None = None,
) -> Optional[Path]:
    """
    Gemini 图生图：参考图 + 提示词 → generateContent（多模态输入，IMAGE 输出）。
    需 GEMINI_API_KEY。
    preserve_reference_layout：使用「布局锁定」引导，强调站位、疏密与安全区。
    """
    ref_path = Path(reference_image_path).resolve()
    if not ref_path.is_file():
        print(f"[gemini i2i] 参考图不存在: {ref_path}", file=sys.stderr)
        return None
    try:
        ref_bytes = ref_path.read_bytes()
    except Exception as e:
        print(f"[gemini i2i] 读取参考图失败: {e}", file=sys.stderr)
        return None
    # Packy/代理对大体积 base64 易超时或拒收；长边压到 GEMINI_I2I_REF_MAX（默认 1536）再请求
    try:
        from io import BytesIO

        from PIL import Image

        max_d = int(os.environ.get("GEMINI_I2I_REF_MAX", "1536"))
        if max_d >= 256:
            im = Image.open(BytesIO(ref_bytes))
            im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
            w, h = im.size
            if max(w, h) > max_d:
                scale = max_d / float(max(w, h))
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                im = im.resize((nw, nh), Image.Resampling.LANCZOS)
                buf = BytesIO()
                im.save(buf, format="PNG")
                ref_bytes = buf.getvalue()
                print(
                    f"[gemini i2i] 参考图已缩放至 {nw}x{nh} 以适配接口（原 {w}x{h}）",
                    flush=True,
                )
    except Exception:
        pass
    ref_b64 = base64.standard_b64encode(ref_bytes).decode("ascii")
    mime = "image/png" if ref_path.suffix.lower() == ".png" else "image/jpeg"
    key = get_api_key()
    if (
        preserve_reference_layout
        and canvas_w is not None
        and canvas_h is not None
        and canvas_w > 0
        and canvas_h > 0
    ):
        lead = _i2i_layout_lock_lead(canvas_w, canvas_h, layout_safe_zone)
    else:
        lead = "根据这张参考图的风格与内容，生成一张新的横版 banner 背景图。"
    user_text = f"{lead} 具体画面要求如下：{prompt}\n\n只输出一张图，不要文字说明。"
    # 多模态输入：先图后文，请求根据参考图与提示生成新图
    body = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime, "data": ref_b64}},
                {"text": user_text},
            ]
        }],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    is_packy = "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or "")
    timeout_sec = 300 if is_packy else 120
    headers_base = {"Content-Type": "application/json"}
    if key.strip().startswith("sk-"):
        headers_base["Authorization"] = f"Bearer {key}"
    if is_packy:
        headers_base["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    data = None
    for model in _get_gemini_image_models():
        api_base = _gemini_models_base()
        _base_url = f"{api_base}/{model}:generateContent"
        url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=dict(headers_base),
            method="POST",
        )
        for attempt in range(_GEMINI_503_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                if e.code in (500, 503) and attempt < _GEMINI_503_RETRIES - 1:
                    wait_sec = _GEMINI_503_BACKOFF_BASE * (3 ** attempt)
                    print(f"[gemini i2i] model={model} HTTP {e.code}，{wait_sec}s 后重试 ({attempt+1}/{_GEMINI_503_RETRIES})...", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                if e.code in (500, 503):
                    print(f"[gemini i2i] model={model} 持续 {e.code}，尝试下一模型...", file=sys.stderr)
                    data = None
                    break
                if e.code in (401, 403, 404):
                    print(f"[gemini i2i] model={model} 无权限/不存在（HTTP {e.code}），尝试下一模型...", file=sys.stderr)
                    if err_body.strip():
                        print(f"[gemini i2i] 响应片段: {err_body[:400]}", file=sys.stderr)
                    data = None
                    break
                print(f"[gemini i2i] API {e.code}: {err_body[:500]}", file=sys.stderr)
                return None
            except urllib.error.URLError as e:
                print(f"[gemini i2i] 网络错误: {e.reason}", file=sys.stderr)
                return None
        if data is not None:
            break
    if data is None:
        print("[gemini i2i] 所有模型均失败。", file=sys.stderr)
        return None
    candidates = data.get("candidates") or []
    if not candidates:
        if "promptFeedback" in data:
            print(f"[gemini i2i] {data['promptFeedback']}", file=sys.stderr)
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    for part in parts:
        if "inlineData" in part:
            b64_out = part["inlineData"].get("data")
            if b64_out:
                out_bytes = base64.standard_b64decode(b64_out)
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(out_bytes)
                return out_path.resolve()
    print("[gemini i2i] 响应中无图片。", file=sys.stderr)
    try:
        dbg = json.dumps(data, ensure_ascii=False)[:900]
        print(f"[gemini i2i] 响应摘要: {dbg}", file=sys.stderr)
    except Exception:
        pass
    return None


def _gemini_models_base() -> str:
    base = (os.environ.get("GOOGLE_GEMINI_BASE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/v1beta/models"
    return "https://generativelanguage.googleapis.com/v1beta/models"


def _get_gemini_image_models() -> list[str]:
    raw = os.environ.get("GEMINI_MODEL", "gemini-3-pro-image-preview,gemini-2.5-flash-image")
    return [m.strip() for m in raw.split(",") if m.strip()]


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Error: GEMINI_API_KEY not set.", file=sys.stderr)
        print(
            "Set it: export GEMINI_API_KEY='your-key'  (see banner-background-from-image/references/gemini_edit.md)",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


PROMPT_OPTIMIZER_INSTRUCTION = """你是一个 banner 背景图的提示词撰写助手。根据用户给出的主标题和副标题，写一段用于文生图（即梦/Gemini 等）的图片描述。

要求：
1. 只输出一段可直接用于文生图的描述文字，不要解释、不要加引号或标题。
2. 根据主副标题的语义提炼主题、氛围和可视觉化的元素（场景、物体、光线、色调等）。
3. 描述应为横版 banner 背景服务：无人物特写、适合后续叠主副标题。
4. 文字约束——画面中不出现作为标题/标语/活动名的大字（后期会压字），但物体自带的细节文字（如票面信息、书本内页、包装标签、门牌号等）可以出现，不必禁止。描述结尾注明「画面无标题文字」而非笼统的「无文字」。
5. 运营插画类（活动/运营主副标题）：描述须按「运营插画风格→语义重点→风格（3D/色彩）→主体与构图→整体观感」的结构写；禁止字面化（如「充能/电量」不画电池、电量条、充电图标），用氛围与元素表达语义。
6. 使用中文，风格可写「非写实/梦幻/清新」等，结尾可带「色调：xxx，横版，高清」。
7. 长度适中，约 80～150 字（运营插画可略长以覆盖五段结构）。
8. 严格参考下方示例与 user_preferences 中的「运营插画描述结构」：用词、标点与信息密度尽量与示例一致，以产出同样高质量的 prompt。"""


def _load_user_preferences() -> str:
    """从 prompt_library/user_preferences.md 读取用户习惯与偏好；不存在或空则返回空串。"""
    prefs_path = _script_dir.parent / "prompt_library" / "user_preferences.md"
    if not prefs_path.is_file():
        return ""
    try:
        text = prefs_path.read_text(encoding="utf-8").strip()
        if not text:
            return ""
        return text
    except Exception:
        return ""


def _build_prompt_optimizer_instruction() -> str:
    """在默认规范后追加用户偏好（若存在）。"""
    instruction = PROMPT_OPTIMIZER_INSTRUCTION
    prefs = _load_user_preferences()
    if prefs:
        instruction = instruction + "\n\n用户习惯与偏好（请尽量遵循）：\n" + prefs
    return instruction


def _load_prompt_library_examples(n: int = 3) -> str:
    """从 prompt_library 取 n 条示例，格式化为 few-shot 文本；失败或空则返回空串。"""
    try:
        import prompt_library as _pl
        entries = _pl.get_examples(n=n)
        return _pl.format_examples_for_prompt_optimizer(entries)
    except Exception:
        return ""


def _prompt_optimizer_request(key: str, model: str, body: dict) -> dict:
    """单次 prompt-optimizer 请求；成功返回 data，HTTPError 抛出供上层处理。"""
    _base_url = f"{_gemini_models_base()}/{model}:generateContent"
    url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
    headers = {"Content-Type": "application/json"}
    if key.strip().startswith("sk-"):
        headers["Authorization"] = f"Bearer {key}"
    if "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""):
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def prompt_optimizer(main_title: str, subtitle: str) -> str:
    """
    用 Gemini 根据主标题、副标题生成文生图用的描述（prompt-optimizer）。
    需 GEMINI_API_KEY。按 GEMINI_PROMPT_OPTIMIZER_MODEL、GEMINI_MODEL、默认文本模型依次尝试；
    对 500 重试最多 2 次，403/无权限则换下一模型。返回可直接作为 description 的文本。
    """
    key = get_api_key()
    models = []
    for m in (
        os.environ.get("GEMINI_PROMPT_OPTIMIZER_MODEL"),
        os.environ.get("GEMINI_MODEL"),
        DEFAULT_PROMPT_OPTIMIZER_MODEL,
    ):
        if m and m.strip() and m not in models:
            models.append(m.strip())
    if not models:
        models = [DEFAULT_PROMPT_OPTIMIZER_MODEL]

    examples_text = _load_prompt_library_examples(5)
    user_text = f"主标题：{main_title.strip()}\n副标题：{subtitle.strip()}\n\n请根据以上主副标题写出文生图描述。"
    if examples_text:
        user_text = examples_text + "\n---\n本次任务：\n" + user_text
    instruction = _build_prompt_optimizer_instruction()
    body = {
        "contents": [{"parts": [{"text": instruction + "\n\n" + user_text}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512},
    }

    last_err = None
    for model in models:
        for attempt in range(3):
            try:
                data = _prompt_optimizer_request(key, model, body)
                candidates = data.get("candidates") or []
                if not candidates:
                    last_err = RuntimeError("prompt-optimizer: Gemini 未返回内容")
                    continue
                parts = candidates[0].get("content", {}).get("parts") or []
                if not parts or "text" not in parts[0]:
                    last_err = RuntimeError("prompt-optimizer: 无法解析返回文本")
                    continue
                text = parts[0]["text"].strip()
                if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                    text = text[1:-1].strip()
                return text
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                print(f"[prompt-optimizer] model={model} API {e.code}: {err_body[:200]}", file=sys.stderr)
                last_err = e
                if e.code == 500 and attempt < 2:
                    time.sleep(5)
                    continue
                if e.code in (401, 403, 404):
                    break
                if attempt >= 2:
                    break
            except urllib.error.URLError as e:
                print(f"[prompt-optimizer] model={model} 网络错误: {e.reason}", file=sys.stderr)
                last_err = e
                break

    raise RuntimeError(
        "prompt-optimizer 所有模型均失败。请在 .env 中设置 GEMINI_PROMPT_OPTIMIZER_MODEL 为当前 Packy 分组支持的模型名（如 gemini-2.0-flash），或使用 --description-file 传入描述跳过优化。"
    ) from last_err


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not key.strip():
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        print("Set it in project root .env: ANTHROPIC_API_KEY=sk-ant-api03-...", file=sys.stderr)
        sys.exit(1)
    return key.strip()


def _anthropic_api_base() -> str:
    raw = os.environ.get("ANTHROPIC_API_BASE_URL", "").strip().rstrip("/")
    return raw if raw else "https://api.anthropic.com"


def _anthropic_messages_request(api_key: str, body: dict) -> dict:
    url = f"{_anthropic_api_base()}{ANTHROPIC_MESSAGES_PATH}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def prompt_optimizer_claude(main_title: str, subtitle: str) -> str:
    """
    用 Anthropic Claude 根据主标题、副标题生成文生图描述（prompt-optimizer）。
    需 ANTHROPIC_API_KEY；模型名由 CLAUDE_PROMPT_OPTIMIZER_MODEL 指定，缺省为 claude-3-5-sonnet-20241022。
    可选 ANTHROPIC_API_BASE_URL 指向兼容代理（须实现 /v1/messages）。
    """
    api_key = get_anthropic_api_key()
    model = (
        os.environ.get("CLAUDE_PROMPT_OPTIMIZER_MODEL", "").strip()
        or DEFAULT_CLAUDE_PROMPT_OPTIMIZER_MODEL
    )

    examples_text = _load_prompt_library_examples(5)
    user_text = f"主标题：{main_title.strip()}\n副标题：{subtitle.strip()}\n\n请根据以上主副标题写出文生图描述。"
    if examples_text:
        user_text = examples_text + "\n---\n本次任务：\n" + user_text
    instruction = _build_prompt_optimizer_instruction()

    body = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0.7,
        "system": instruction,
        "messages": [{"role": "user", "content": user_text}],
    }

    last_err = None
    for attempt in range(3):
        try:
            data = _anthropic_messages_request(api_key, body)
            blocks = data.get("content") or []
            text = None
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    text = b["text"].strip()
                    break
            if not text:
                last_err = RuntimeError("prompt-optimizer (Claude): 无法解析返回文本")
                continue
            if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                text = text[1:-1].strip()
            return text
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            print(f"[prompt-optimizer claude] API {e.code}: {err_body[:400]}", file=sys.stderr)
            last_err = e
            if e.code in (429, 529) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code in (401, 403):
                break
        except urllib.error.URLError as e:
            print(f"[prompt-optimizer claude] 网络错误: {e.reason}", file=sys.stderr)
            last_err = e
            break

    raise RuntimeError(
        "prompt-optimizer (Claude) 失败。请检查 ANTHROPIC_API_KEY、CLAUDE_PROMPT_OPTIMIZER_MODEL，"
        "或使用 --description-file 传入描述跳过优化。"
    ) from last_err


OLLAMA_PROMPT_OPTIMIZER_URL = os.environ.get("OLLAMA_PROMPT_OPTIMIZER_URL", "http://localhost:11434/api/chat").strip()
OLLAMA_PROMPT_OPTIMIZER_MODEL = os.environ.get("OLLAMA_PROMPT_OPTIMIZER_MODEL", "qwen3:8b").strip()


def prompt_optimizer_local(main_title: str, subtitle: str) -> str:
    """
    用本地 Ollama（如 qwen3）根据主标题、副标题生成文生图描述。
    会从 prompt_library 取若干条作为 few-shot。需本机已启动 Ollama 且已拉取对应模型。
    返回一段可直接作为 description 传入 description_to_prompt 的文本。
    """
    examples_text = _load_prompt_library_examples(5)
    user_content = f"主标题：{main_title.strip()}\n副标题：{subtitle.strip()}\n\n请根据以上主副标题写出文生图描述（只输出一段描述，不要解释、不要加引号）。"
    if examples_text:
        user_content = examples_text + "\n---\n本次任务：\n" + user_content
    instruction = _build_prompt_optimizer_instruction()
    body = {
        "model": OLLAMA_PROMPT_OPTIMIZER_MODEL,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
    }
    req = urllib.request.Request(
        OLLAMA_PROMPT_OPTIMIZER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        print(f"[prompt-optimizer local] Ollama HTTP 错误 {e.code}: {err_body[:300]}", file=sys.stderr)
        raise RuntimeError("prompt-optimizer 本地调用失败") from e
    except urllib.error.URLError as e:
        print(f"[prompt-optimizer local] 无法连接 Ollama（{OLLAMA_PROMPT_OPTIMIZER_URL}）: {e.reason}", file=sys.stderr)
        raise RuntimeError("prompt-optimizer 本地调用失败") from e
    msg = data.get("message")
    if not msg or "content" not in msg:
        raise RuntimeError("prompt-optimizer 本地: Ollama 未返回有效 content")
    text = msg["content"].strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    return text


def prompt_optimizer_template(main_title: str, subtitle: str, mode: str = "auto", subject_override: str = "", prompt_format: str = "compact") -> str:
    """
    用确定性模板引擎根据主标题、副标题生成文生图描述。

    语义理解由调用方（Claude）完成，通过 subject_override 传入场景描述。
    未传 subject_override 时，compact 格式会提示用户补充；full 格式走模板推导。

    参数：
      main_title: 主标题
      subtitle: 副标题
      mode: 场景模式 "auto"|"product"|"campaign"|"collection"
      subject_override: 场景视觉描述（由 Claude 语义理解后生成，传入此处）
      prompt_format: "compact"（~300字自然语言）或 "full"（~2400字约束式）

    返回可直接作为 description 传入 description_to_prompt 的文本。
    """
    _prompt_engine_dir = _script_dir.parent.parent / "prompt-engine" / "scripts"
    if str(_prompt_engine_dir) not in sys.path:
        sys.path.insert(0, str(_prompt_engine_dir))
    import template_prompt_builder as _tpb

    # 自动检测模式
    if mode == "auto":
        mode = _tpb._detect_mode(main_title, subtitle, "")

    return _tpb.prompt_optimizer_template(
        main_title=main_title,
        subtitle=subtitle,
        category="",
        style_idx=0,
        row_idx=0,
        icon_url="",
        mode=mode,
        subject_override=subject_override,
        prompt_format=prompt_format,
        aspect_ratio="16:9",
    )


def prompt_optimizer_engine(
    main_title: str,
    subtitle: str,
    backend: str = "gemini",
    save_trace: bool = False,
    trace_dir: str | None = None,
) -> tuple[str, str]:
    """
    用 prompt-engine (PROMPT_SYSTEM .md) 根据主副标题执行完整 6 步管道推导，
    返回 (精简中文描述, 完整推导文本)。

    backend: "gemini" / "claude"
    save_trace: 是否保存完整推导过程到 trace_dir/prompt_engine_trace.md
    """
    _prompt_engine_dir = _script_dir.parent.parent / "prompt-engine" / "scripts"
    if str(_prompt_engine_dir) not in sys.path:
        sys.path.insert(0, str(_prompt_engine_dir))
    import prompt_engine_optimizer as _peo

    examples_text = _load_prompt_library_examples(3)
    description, full_trace = _peo.prompt_engine_optimize(
        main_title=main_title,
        subtitle=subtitle,
        backend=backend,
        examples_text=examples_text,
        save_trace=save_trace,
        trace_dir=trace_dir,
    )
    return description, full_trace


def description_to_prompt(description: str) -> str:
    """Turn user description into image generation prompt (see prompt_guidelines.md)."""
    return PROMPT_PREFIX + description.strip() + PROMPT_SUFFIX


def generate_image(
    prompt: str,
    output_path: str,
    backend: str | None = None,
    t8star_models: list[str] | None = None,
    width: int | None = None,
    height: int | None = None,
    reference_image: str | None = None,
) -> Path:
    """
    Text-to-image: nano-banana（默认）/ gemini / t8star / jimeng / packygpt。
    backend: 未传则用环境变量 BANNER_IMAGE_BACKEND。t8star_models: 仅 t8star 时有效。
    width/height: 仅 jimeng 时有效，即梦输出尺寸；未传则 1024×1024。
    reference_image: 参考图路径，图生图时传入（仅 packygpt 支持）。
    """
    be = (backend or os.environ.get("BANNER_IMAGE_BACKEND", "nano-banana")).strip().lower()
    if be == "lovart":
        import lovart_helper as lovart
        result = lovart.generate_t2i(prompt, output_path, prefer_models=t8star_models)
        if result is not None:
            return result
        print("[banner] Lovart 文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "jimeng":
        w = width if width is not None else 1024
        h = height if height is not None else 1024
        result = _generate_image_jimeng(prompt, output_path, width=w, height=h)
        if result is not None:
            return result
        print("[banner] 即梦（火山）文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "packygpt":
        result = _generate_image_packygpt(prompt, output_path, reference_image=reference_image)
        if result is not None:
            return result
        print("[banner] PackyGPT 文生图/图生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "micugpt2":
        result = _generate_image_micugpt2(prompt, output_path, reference_image=reference_image)
        if result is not None:
            return result
        print("[banner] MicuGPT2 文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "xingchengpt":
        result = _generate_image_xingchengpt(prompt, output_path, reference_image=reference_image)
        if result is not None:
            return result
        print("[banner] XingchenGPT 文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "moxingpt":
        result = _generate_image_moxingpt(prompt, output_path, reference_image=reference_image)
        if result is not None:
            return result
        print("[banner] MoxinGPT 文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "t8star":
        # 简易文生图（gpt-best 文档 api-229045941：仅 prompt/n/size，返回 url）优先
        if T8STAR_SIMPLE_T2I:
            result = _generate_image_t8star_simple(prompt, output_path)
            if result is not None:
                return result
        result = _generate_image_t8star(prompt, output_path, models=t8star_models)
        if result is not None:
            return result
        print("[banner] t8star 文生图失败。", file=sys.stderr)
        sys.exit(1)
    if be == "nano-banana":
        result = _generate_image_nano_banana(prompt, output_path)
        if result is not None:
            return result
        print("[banner] nano-banana 不可用或失败，回退到 Gemini API", file=sys.stderr)
    key = get_api_key()
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    is_packy = "packyapi.com" in (os.environ.get("GOOGLE_GEMINI_BASE_URL") or "")
    timeout_sec = 300 if is_packy else 120
    headers_base = {"Content-Type": "application/json"}
    if key.strip().startswith("sk-"):
        headers_base["Authorization"] = f"Bearer {key}"
    if is_packy:
        headers_base["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    data = None
    for model in _get_gemini_image_models():
        api_base = _gemini_models_base()
        _base_url = f"{api_base}/{model}:generateContent"
        url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=dict(headers_base),
            method="POST",
        )
        for attempt in range(_GEMINI_503_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                if e.code in (500, 503) and attempt < _GEMINI_503_RETRIES - 1:
                    wait_sec = _GEMINI_503_BACKOFF_BASE * (3 ** attempt)
                    print(f"[gemini t2i] model={model} HTTP {e.code}，{wait_sec}s 后重试 ({attempt+1}/{_GEMINI_503_RETRIES})...", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                if e.code in (500, 503):
                    print(f"[gemini t2i] model={model} 持续 {e.code}，尝试下一模型...", file=sys.stderr)
                    data = None
                    break
                if e.code in (401, 403, 404):
                    print(f"[gemini t2i] model={model} 无权限/不存在（HTTP {e.code}），尝试下一模型...", file=sys.stderr)
                    data = None
                    break
                print(f"Error: API {e.code}", file=sys.stderr)
                if err_body:
                    print(err_body[:500], file=sys.stderr)
                sys.exit(1)
            except urllib.error.URLError as e:
                print(f"Error: {e.reason}", file=sys.stderr)
                sys.exit(1)
        if data is not None:
            break
    if data is None:
        print("Error: 文生图：所有模型均失败。", file=sys.stderr)
        sys.exit(1)

    candidates = data.get("candidates") or []
    if not candidates:
        print("Error: No candidates in response.", file=sys.stderr)
        if "promptFeedback" in data:
            print(data["promptFeedback"], file=sys.stderr)
        sys.exit(1)
    parts = candidates[0].get("content", {}).get("parts") or []
    for part in parts:
        if "inlineData" in part:
            b64_out = part["inlineData"].get("data")
            if b64_out:
                out_bytes = base64.standard_b64decode(b64_out)
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(out_bytes)
                return out_path
    print("Error: No image in response.", file=sys.stderr)
    sys.exit(1)


def crop_to_target_script() -> Path:
    """Path to banner-background-from-image's crop_to_target.py (sibling skill)."""
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent / "banner-background-from-image" / "scripts" / "crop_to_target.py"


def run_crop(generated_path: str, output_path: str, width: int, height: int) -> Path:
    """Run crop_to_target.py on generated image; return path to cropped file."""
    crop_script = crop_to_target_script()
    if not crop_script.is_file():
        print(
            f"Error: crop_to_target.py not found at {crop_script}. Ensure banner-background-from-image skill is present.",
            file=sys.stderr,
        )
        sys.exit(1)
    cmd = [
        PYTHON_EXE,
        str(crop_script),
        generated_path,
        output_path,
        "--width",
        str(width),
        "--height",
        str(height),
        "--align-image-center",  # 文生图无主体检测，画面中心对齐安全区裁切
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)
    # crop_to_target writes to output/ when path has no parent (same as its DEFAULT_OUTPUT_DIR)
    p = Path(output_path)
    if not p.parent or p.parent == Path("."):
        return (Path("output") / p.name).resolve()
    return p.resolve() if not p.is_absolute() else p


def generate_from_description(
    description: str,
    output_path: str,
    width: int,
    height: int,
    backend: str | None = None,
    t8star_models: list[str] | None = None,
    reference_image: str | None = None,
    jimeng_smart_ref: bool = False,
    *,
    preserve_reference_layout: bool = False,
    layout_safe_zone: tuple[int, int, int, int] | None = None,
) -> Path:
    """
    Generate banner background: prompt → 文生图(t2i) 或 图生图(i2i) → crop to W×H.
    reference_image: 传入则走图生图(i2i)。支持 backend: jimeng / gemini / nano-banana；t8star 尝试 /v1/images/edits，未开放则报错提示改用其它模型。
    jimeng_smart_ref: 即梦图生图时使用 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致；可由环境变量 JIMENG_I2I_SMART_REF=1 或 --jimeng-smart-ref 开启。
    preserve_reference_layout / layout_safe_zone: 图生图时追加「布局锁定」约束（与 HD 产线 spec 安全区配合）。
    """
    prompt = description_to_prompt(description)
    lock_extra = ""
    if preserve_reference_layout and width > 0 and height > 0:
        lock_extra = "\n\n" + _i2i_layout_lock_lead(width, height, layout_safe_zone)
    prompt_i2i = prompt + lock_extra
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        temp_path = f.name
    try:
        be = (backend or os.environ.get("BANNER_IMAGE_BACKEND", "nano-banana")).strip().lower()
        if reference_image:
            # 有参考图则走图生图(i2i)；仅 jimeng / gemini / nano-banana 支持，t8star 不支持则报错
            if be == "jimeng":
                result = _generate_image_jimeng_i2i(
                    prompt_i2i,
                    reference_image,
                    temp_path,
                    width=width,
                    height=height,
                    use_smart_ref=jimeng_smart_ref,
                )
                if result is None:
                    print("[banner] 即梦图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "gemini":
                result = _generate_image_gemini_i2i(
                    prompt,
                    reference_image,
                    temp_path,
                    preserve_reference_layout=preserve_reference_layout,
                    canvas_w=width,
                    canvas_h=height,
                    layout_safe_zone=layout_safe_zone,
                )
                if result is None:
                    print("[banner] Gemini 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "nano-banana":
                result = _generate_image_nano_banana_i2i(
                    prompt_i2i, reference_image, temp_path
                )
                if result is None:
                    print("[banner] nano-banana 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "lovart":
                import lovart_helper as lovart
                result = lovart.generate_i2i(prompt_i2i, reference_image, temp_path)
                if result is None:
                    print("[banner] Lovart 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "t8star":
                result = _generate_image_t8star_i2i(
                    prompt_i2i, reference_image, temp_path, models=t8star_models
                )
                if result is None:
                    print(
                        "[banner] t8star 图生图(i2i) 失败或接口未开放。参考图(i2i) 请使用 -M jimeng / -M gemini 或 BANNER_IMAGE_BACKEND=nano-banana。",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            elif be == "packygpt":
                result = _generate_image_packygpt(
                    prompt_i2i, temp_path, reference_image=reference_image
                )
                if result is None:
                    print("[banner] PackyGPT 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "micugpt2":
                result = _generate_image_micugpt2(
                    prompt_i2i, temp_path, reference_image=reference_image
                )
                if result is None:
                    print("[banner] MicuGPT2 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "xingchengpt":
                result = _generate_image_xingchengpt(
                    prompt_i2i, temp_path, reference_image=reference_image
                )
                if result is None:
                    print("[banner] XingchenGPT 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            elif be == "moxingpt":
                result = _generate_image_moxingpt(
                    prompt_i2i, temp_path, reference_image=reference_image
                )
                if result is None:
                    print("[banner] MoxinGPT 图生图(i2i) 失败。", file=sys.stderr)
                    sys.exit(1)
            else:
                print(
                    "Error: 参考图(i2i) 当前仅支持 --model jimeng / gemini / nano-banana / packygpt / micugpt2（t8star 暂不支持）。请使用 -M jimeng、-M gemini、-M packygpt、--micugpt2 或确保 BANNER_IMAGE_BACKEND=nano-banana/packygpt/micugpt2，或移除 -i 后重试。",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            generate_image(
                prompt, temp_path,
                backend=backend, t8star_models=t8star_models,
                width=width, height=height,
            )
        out = run_crop(temp_path, output_path, width, height)
        return out
    finally:
        if os.path.isfile(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def main() -> None:
    global PRESETS, MODEL_ALIASES
    _spec_dir = _script_dir.parent.parent / "banner-spec" / "scripts"
    if str(_spec_dir) not in sys.path:
        sys.path.insert(0, str(_spec_dir))
    try:
        import spec as _spec
        PRESETS = _spec.PRESETS
    except Exception:
        PRESETS = {"default": (1976, 464)}
    MODEL_ALIASES = {
        "gemini": ("gemini", None),
        "jimeng": ("jimeng", None),
        "t8-gemini": ("t8star", ["gemini-3.1-flash-image-preview"]),
        "t8-jimeng": ("t8star", ["jimeng"]),
        "lovart": ("lovart", None),
        "lovart-seedream": ("lovart", ["generate_image_seedream_3_0"]),
        "lovart-seedream45": ("lovart", ["generate_image_seedream_4_5"]),
        "lovart-banana": ("lovart", ["generate_image_nano_banana_pro"]),
        "lovart-midjourney": ("lovart", ["generate_image_midjourney"]),
        "packygpt": ("packygpt", ["gpt-image-2"]),
        "micugpt2": ("micugpt2", ["gpt-image-2"]),
        "xingchengpt": ("xingchengpt", None),
        "nano-banana": ("nano-banana", None),
        "t8star": ("t8star", None),
    }
    parser = argparse.ArgumentParser(
        description="Generate banner background from description or from 主副标题（prompt-optimizer）. Output: output/."
    )
    parser.add_argument(
        "description",
        nargs="?",
        default=None,
        help="Short description or marketing phrase. 与 --main-title/--subtitle 二选一。",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="banner_bg.png",
        help="Output path or filename (default: banner_bg.png in output/)",
    )
    parser.add_argument(
        "--main-title", "-m",
        dest="main_title",
        default=None,
        help="主标题（与 --subtitle 一起使用时由 prompt-optimizer 生成文生图描述）",
    )
    parser.add_argument(
        "--subtitle", "-s",
        dest="subtitle",
        default=None,
        help="副标题（与 --main-title 一起使用时由 prompt-optimizer 生成文生图描述）",
    )
    parser.add_argument(
        "--reference-image", "-i",
        dest="reference_image",
        default=None,
        help="参考图路径；传入则走图生图(i2i)。支持模型: jimeng / gemini / nano-banana / packygpt；t8star 暂不支持",
    )
    parser.add_argument(
        "--preserve-reference-layout",
        action="store_true",
        help="图生图(i2i)时启用「布局锁定」：保持参考图人物顺序、站位、疏密与叠压；可配合 --layout-safe-zone 传入像素安全区",
    )
    parser.add_argument(
        "--layout-safe-zone",
        nargs=4,
        type=int,
        metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"),
        default=None,
        help="与 banner-spec 一致：x_min x_max y_min y_max（像素），须与 --preserve-reference-layout 同用",
    )
    parser.add_argument(
        "--jimeng-smart-ref",
        action="store_true",
        dest="jimeng_smart_ref",
        help="即梦图生图时使用 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致；也可设环境变量 JIMENG_I2I_SMART_REF=1",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS), default="default")
    group.add_argument("--width", "-W", type=int, help="Target width (use with --height)")
    parser.add_argument("--height", "-H", type=int, help="Target height")
    parser.add_argument(
        "--model",
        "-M",
        choices=list(MODEL_ALIASES),
        default=None,
        help="文生图模型: gemini / t8-gemini / t8-jimeng / jimeng 或 即梦（火山即梦4.0直连）/ lovart / lovart-seedream / lovart-seedream45 / lovart-banana / lovart-midjourney. 未指定时用环境变量 BANNER_IMAGE_BACKEND",
    )
    parser.add_argument("--packy", "-packy", action="store_true", dest="packy", help="使用 Packy API 作为 Gemini 后端")
    parser.add_argument(
        "--prompt-optimizer",
        dest="prompt_optimizer",
        choices=("gemini", "local", "claude", "template"),
        default=os.environ.get("BANNER_PROMPT_OPTIMIZER", "gemini").strip().lower() or "gemini",
        help="主副标题→描述: Gemini(gemini) / Anthropic Claude(claude，需 ANTHROPIC_API_KEY) / 本地 Ollama(local) / 确定性模板(template，不调用 LLM). 默认 gemini；可用 BANNER_PROMPT_OPTIMIZER",
    )
    args = parser.parse_args()
    if getattr(args, "packy", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
        pkey = (
            os.environ.get("PACKY_API_KEY", "").strip()
            or os.environ.get("PACKY7S_API_KEY", "").strip()
        )
        if pkey:
            os.environ["GEMINI_API_KEY"] = pkey
    if not getattr(args, "jimeng_smart_ref", False) and os.environ.get("JIMENG_I2I_SMART_REF", "").strip().lower() in ("1", "true", "yes"):
        args.jimeng_smart_ref = True

    # Prompt 来源规则（与 prompt_library / Qwen 的关系）：
    # - 若用户上传了 prompt（提供了 description）：Qwen、prompt_library 不参与，直接将 prompt 传给即梦生图。
    # - 若用户未上传 prompt（仅提供主副标题）：根据主副标题用 Qwen/Gemini + prompt_library 生成 prompt，再传给即梦生图。
    if args.main_title is not None and args.subtitle is not None:
        po = args.prompt_optimizer
        if po == "local":
            label = "本地 Ollama"
        elif po == "claude":
            label = "Anthropic Claude"
        elif po == "template":
            label = "确定性模板引擎（12风格+10构图）"
        else:
            label = "Gemini"
        print(f"[prompt-optimizer] 根据主副标题生成文生图描述（{label}）...", flush=True)
        try:
            if po == "local":
                description = prompt_optimizer_local(args.main_title, args.subtitle)
            elif po == "claude":
                description = prompt_optimizer_claude(args.main_title, args.subtitle)
            elif po == "template":
                description = prompt_optimizer_template(args.main_title, args.subtitle)
            else:
                description = prompt_optimizer(args.main_title, args.subtitle)
        except RuntimeError:
            sys.exit(1)
        print(f"[prompt-optimizer] 生成描述: {description[:80]}...", flush=True)
        # prompt 库改为仅支持用户单独上传，此处不再自动写入
    elif args.description:
        # 用户已上传 prompt，直通即梦，不调用 Qwen、不读取 prompt_library
        description = args.description
    else:
        print("Error: 请提供 description 或同时提供 --main-title 与 --subtitle。", file=sys.stderr)
        sys.exit(1)

    if args.width is not None and args.height is not None:
        width, height = args.width, args.height
    else:
        width, height = PRESETS[args.preset]

    backend, t8star_models = None, None
    if args.model:
        backend, t8star_models = MODEL_ALIASES[args.model]
        # 指定 t8-jimeng 时固定用即梦模型列表，不随 T8STAR_IMAGE_MODEL 覆盖；其他 t8star 时可用环境变量覆盖
        if backend == "t8star" and args.model != "t8-jimeng" and os.environ.get("T8STAR_IMAGE_MODEL"):
            t8star_models = [m.strip() for m in os.environ.get("T8STAR_IMAGE_MODEL", "").split(",") if m.strip()]
    lz = getattr(args, "layout_safe_zone", None)
    layout_sz = tuple(lz) if lz is not None else None
    out = generate_from_description(
        description,
        args.output,
        width,
        height,
        backend=backend,
        t8star_models=t8star_models,
        reference_image=args.reference_image,
        jimeng_smart_ref=getattr(args, "jimeng_smart_ref", False),
        preserve_reference_layout=getattr(args, "preserve_reference_layout", False),
        layout_safe_zone=layout_sz,
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
