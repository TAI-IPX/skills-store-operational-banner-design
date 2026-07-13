#!/usr/bin/env python3
"""
Image edit (outpaint / inpaint). 默认使用 Gemini 3 Pro Image API（BANNER_IMAGE_BACKEND=gemini），模型 gemini-3-pro-image-preview，请求 2K 输出。
可通过 BANNER_IMAGE_BACKEND=nano-banana 改用 nano-banana CLI；BANNER_IMAGE_BACKEND=t8star 改用贞贞的AI工坊（OpenAI 兼容，https://ai.t8star.cn/api-set）。GEMINI_MODEL 可覆盖模型。See references/gemini_edit.md.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None

# 默认图编后端：gemini（Gemini 3.1 API）；nano-banana（nano-banana CLI）；t8star（贞贞的AI工坊 OpenAI 兼容）
_raw_edit = os.environ.get("BANNER_IMAGE_BACKEND", "gemini") or os.environ.get("BANNER_EDIT_BACKEND", "")
BANNER_IMAGE_BACKEND = _raw_edit.strip().lower()

# t8star（贞贞的AI工坊）配置：T8STAR_API_KEY 必填；T8STAR_BASE_URL 默认 https://ai.t8star.cn；T8STAR_IMAGE_MODEL 逗号分隔候选，默认 Gemini 3.1 系列
T8STAR_BASE_URL = os.environ.get("T8STAR_BASE_URL", "https://ai.t8star.cn").rstrip("/")
# 支持逗号分隔的候选模型列表：按序尝试，第一个成功则使用。
_t8_models_raw = os.environ.get(
    "T8STAR_IMAGE_MODEL",
    "gemini-3.1-flash-image-preview,gemini-3.1-flash-image-preview-2k,gemini-3.1-flash-image-preview-4k,gemini-3.1-flash-image-preview-512px",
)
T8STAR_IMAGE_MODELS = [m.strip() for m in _t8_models_raw.split(",") if m.strip()]
if not T8STAR_IMAGE_MODELS:
    T8STAR_IMAGE_MODELS = ["gemini-3.1-flash-image-preview"]
# 502/503 重试：服务端临时不可用时自动重试
T8STAR_MAX_RETRIES = int(os.environ.get("T8STAR_MAX_RETRIES", "3"))
T8STAR_RETRY_DELAY = float(os.environ.get("T8STAR_RETRY_DELAY", "10"))

# Model and endpoint (Gemini 3 Pro Image 支持 2K/4K 输出；默认 2K 降耗)
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
# 图编模型默认回退链（GEMINI_MODEL 未含这些时自动追加；与渠道令牌「仅允许部分模型」兼容）
# 例：One API 等将令牌限制为 gemini-3.1-flash-image-preview 时，Pro 403 后可自动切到该模型。
_GEMINI_MODEL_FALLBACK_CHAIN: tuple[str, ...] = (
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
)
# 503/500 时对同一模型的重试次数与退避基数（秒）：第 n 次等待 base * 3^n，Packy 普通渠道过载时多试几次
_GEMINI_503_RETRIES = 3
_GEMINI_503_BACKOFF_BASE = 6
_gemini_base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
API_BASE = f"{_gemini_base}/v1beta/models" if _gemini_base else "https://generativelanguage.googleapis.com/v1beta/models"


def _get_gemini_model_list() -> list[str]:
    """从 GEMINI_MODEL 读取模型列表（支持逗号分隔），合并默认回退链。
    首模型保持 GEMINI_MODEL 第一个（便于优先试 Pro）；其余候选按 _GEMINI_MODEL_FALLBACK_CHAIN
    的相对顺序排序，避免 .env 里误写 gemini-3-pro-image-preview 时排在 gemini-3.1-flash-image-preview 之前。"""
    raw = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        models = [DEFAULT_MODEL]
    primary = models[0]
    rest: list[str] = []
    seen: set[str] = {primary}
    for m in models[1:]:
        if m not in seen:
            rest.append(m)
            seen.add(m)
    for fb in _GEMINI_MODEL_FALLBACK_CHAIN:
        if fb not in seen:
            rest.append(fb)
            seen.add(fb)
    chain_pos = {name: i for i, name in enumerate(_GEMINI_MODEL_FALLBACK_CHAIN)}

    def _tail_sort_key(item: str) -> tuple[int, int]:
        # 在回退链中的模型优先按链顺序；不在链里的保持 rest 原相对顺序
        pos = chain_pos.get(item)
        if pos is not None:
            return (0, pos)
        return (1, rest.index(item))

    rest_sorted = sorted(rest, key=_tail_sort_key)
    return [primary] + rest_sorted


def _nano_banana_exe() -> tuple[Optional[Path], list[str]]:
    """
    Resolve nano-banana: (exe_path, prefix_args).
    Prefer NANO_BANANA_EXE, then ~/.bun/bin/nano-banana.
    """
    exe = os.environ.get("NANO_BANANA_EXE")
    if exe and Path(exe).is_file():
        return (Path(exe), [])
    # 3) 全局安装的 nano-banana
    home = Path(os.environ.get("USERPROFILE", os.environ.get("HOME", "")))
    for p in (home / ".bun" / "bin" / "nano-banana.exe", home / ".bun" / "bin" / "nano-banana"):
        if p.is_file():
            return (p, [])
    return (None, [])


def _edit_image_nano_banana(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    keep_returned_size: bool = False,
) -> Optional[Path]:
    """Use nano-banana CLI for image edit (ref + instruction). Returns output Path on success. 固定使用 gemini-3.1-flash-image-preview."""
    exe, prefix_args = _nano_banana_exe()
    if not exe:
        return None
    path = Path(input_path)
    if not path.is_file():
        return None
    out_path = Path(output_path)
    out_dir = out_path.parent
    out_stem = out_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = (
        [str(exe)]
        + prefix_args
        + [
            instruction,
            "-r", str(path.resolve()),
            "-o", out_stem,
            "-d", str(out_dir.resolve()),
            "-s", "2K",
            "-m", "gemini-3.1-flash-image-preview",
        ]
    )
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"[nano-banana] edit 失败: {r.stderr or r.stdout}", file=sys.stderr)
            return None
        result = out_dir / f"{out_stem}.png"
        if not result.is_file():
            return None
        if result.resolve() != out_path.resolve():
            shutil.copy2(result, output_path)
        # 可选：与 API 行为一致，按 keep_returned_size 决定是否缩放到输入尺寸
        if Image is not None and not keep_returned_size and path != out_path:
            try:
                inp = Image.open(path).convert("RGB")
                out_img = Image.open(out_path).convert("RGB")
                w_in, h_in = inp.size
                w_out, h_out = out_img.size
                if (w_out, h_out) != (w_in, h_in) and w_out >= w_in and h_out >= h_in:
                    out_img = out_img.resize((w_in, h_in), Image.Resampling.LANCZOS)
                    out_img.save(str(out_path), "PNG")
            except Exception:
                pass
        return Path(output_path)
    except Exception as e:
        print(f"[nano-banana] 调用异常: {e}", file=sys.stderr)
        return None


def _get_t8star_key() -> str:
    key = os.environ.get("T8STAR_API_KEY")
    if not key or not key.strip():
        print("Error: T8STAR_API_KEY not set. Set it: export T8STAR_API_KEY='your-token' (get token at https://ai.t8star.cn/api-set)", file=sys.stderr)
        sys.exit(1)
    return key.strip()


def _edit_image_t8star(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    keep_returned_size: bool = False,
) -> Path:
    """
    使用贞贞的AI工坊（t8star）OpenAI 兼容图编接口：POST /v1/images/edits，multipart 上传 image + prompt。
    与 Gemini 同级，失败不回退。环境变量：T8STAR_API_KEY（必填）、T8STAR_BASE_URL、T8STAR_IMAGE_MODEL。
    """
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "rb") as f:
        raw = f.read()
    # 构建 multipart/form-data
    boundary = b"----FormBoundary" + os.urandom(12).hex().encode()
    crlf = b"\r\n"
    body = b""
    body += b"--" + boundary + crlf
    body += b'Content-Disposition: form-data; name="image"; filename="image.png"' + crlf
    body += b"Content-Type: image/png" + crlf + crlf
    body += raw + crlf
    body += b"--" + boundary + crlf
    body += b'Content-Disposition: form-data; name="prompt"' + crlf + crlf
    body += instruction.encode("utf-8") + crlf
    body += b"--" + boundary + crlf
    body += b'Content-Disposition: form-data; name="model"' + crlf + crlf
    # model value filled per-attempt (placeholder)
    _model_placeholder = b"__MODEL__"
    body += _model_placeholder + crlf
    body += b"--" + boundary + crlf
    body += b'Content-Disposition: form-data; name="size"' + crlf + crlf
    body += b"auto" + crlf
    body += b"--" + boundary + crlf
    body += b'Content-Disposition: form-data; name="response_format"' + crlf + crlf
    body += b"b64_json" + crlf
    body += b"--" + boundary + b"--" + crlf

    url = f"{T8STAR_BASE_URL}/v1/images/edits"
    data = None
    last_err: str | None = None
    used_model: str | None = None
    for model in T8STAR_IMAGE_MODELS:
        used_model = model
        body_for_model = body.replace(_model_placeholder, model.encode("utf-8"), 1)
        data = None
        for attempt in range(1, T8STAR_MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=body_for_model,
                headers={
                    "Content-Type": "multipart/form-data; boundary=" + boundary.decode("ascii"),
                    "Authorization": "Bearer " + _get_t8star_key(),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                last_err = None
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                # 模型不支持/未授权时，直接切换下一个模型尝试
                if e.code in (400, 401, 403) and len(T8STAR_IMAGE_MODELS) > 1:
                    last_err = f"{e.code}: {err_body[:200]}"
                    break
                if e.code in (429, 502, 503) and attempt < T8STAR_MAX_RETRIES:
                    print(
                        f"[t8star] API {e.code} (model={model}, attempt {attempt}/{T8STAR_MAX_RETRIES}), retry in {T8STAR_RETRY_DELAY}s...",
                        file=sys.stderr,
                    )
                    time.sleep(T8STAR_RETRY_DELAY)
                    continue
                # 重试用尽后若有其他候选模型，尝试下一个
                if e.code in (429, 502, 503) and len(T8STAR_IMAGE_MODELS) > 1:
                    print(
                        f"[t8star] API {e.code} (model={model}) after retries, try next candidate.",
                        file=sys.stderr,
                    )
                    last_err = f"{e.code}: {err_body[:200]}"
                    break
                print(f"[t8star] API error {e.code}: {err_body[:500]}", file=sys.stderr)
                sys.exit(1)
            except urllib.error.URLError as e:
                if attempt < T8STAR_MAX_RETRIES:
                    print(
                        f"[t8star] Request error: {e.reason} (model={model}), retry in {T8STAR_RETRY_DELAY}s...",
                        file=sys.stderr,
                    )
                    time.sleep(T8STAR_RETRY_DELAY)
                    continue
                print(f"[t8star] Request error: {e.reason}", file=sys.stderr)
                sys.exit(1)
        if data is not None:
            break

    if data is None:
        if last_err:
            print(f"[t8star] All candidate models failed. Last error: {last_err}", file=sys.stderr)
        else:
            print("[t8star] No response after retries.", file=sys.stderr)
        sys.exit(1)

    items = (data.get("data") or [])
    if not items:
        print("Error: [t8star] No image in response.", file=sys.stderr)
        if data.get("error"):
            print(data["error"], file=sys.stderr)
        sys.exit(1)
    first = items[0]
    out_bytes = None
    if first.get("b64_json"):
        out_bytes = base64.standard_b64decode(first["b64_json"])
    elif first.get("url"):
        img_url = first["url"]
        out_bytes = None
        for with_auth in (True, False):
            try:
                if with_auth:
                    img_req = urllib.request.Request(
                        img_url,
                        headers={"Authorization": "Bearer " + _get_t8star_key()},
                    )
                    with urllib.request.urlopen(img_req, timeout=60) as r:
                        out_bytes = r.read()
                else:
                    with urllib.request.urlopen(img_url, timeout=60) as r:
                        out_bytes = r.read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 403 and with_auth:
                    try:
                        host = urlparse(img_url).netloc
                        print(f"[t8star] 403 when fetching image URL (host={host}); retry without auth.", file=sys.stderr)
                    except Exception:
                        pass
                    continue
                print(f"[t8star] Failed to fetch image URL: {e}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"[t8star] Failed to fetch image URL: {e}", file=sys.stderr)
                sys.exit(1)
        if not out_bytes:
            print("[t8star] Failed to fetch image URL (403 with and without auth).", file=sys.stderr)
            sys.exit(1)
    if not out_bytes:
        print("Error: [t8star] response has no b64_json or url.", file=sys.stderr)
        sys.exit(1)

    out_path.write_bytes(out_bytes)
    if Image is not None and not keep_returned_size and path.resolve() != out_path.resolve():
        try:
            inp = Image.open(path).convert("RGB")
            out_img = Image.open(out_path).convert("RGB")
            w_in, h_in = inp.size
            w_out, h_out = out_img.size
            if (w_out, h_out) != (w_in, h_in) and w_out >= w_in and h_out >= h_in:
                out_img = out_img.resize((w_in, h_in), Image.Resampling.LANCZOS)
                out_img.save(str(out_path), "PNG")
        except Exception:
            pass
    return out_path


def _parse_chat_model_list(env_var: str, default: str, max_models: int = 3) -> list[str]:
    """解析 chat/completions 类图编后端的模型列表（逗号分隔，最多取前 max_models 个）。

    用于 moxingemini/xingchengemini/micugemini 等走 /v1/chat/completions 的编辑函数：
    某模型失败（HTTP 错误或返回内容不含图片）时按顺序换下一个模型重试。
    """
    raw = os.environ.get(env_var, "").strip() or default
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        models = [default]
    return models[:max_models]


def _chat_completions_edit_image(
    *,
    backend_label: str,
    base_url: str,
    api_key: str,
    model_list: list[str],
    input_path: str,
    output_path: str,
    instruction: str,
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> Path:
    """chat/completions 图编通用实现：多模型按序重试（同一 Key 内换模型，不跨 Key）。

    每个模型单次 POST；失败原因（HTTP 错误 / 响应不含图片数据）打印后换下一模型；
    全部模型失败才抛出最后一次异常。
    mask: RGBA PNG（transparent=可编辑，opaque=保留），跟随 sct 标记发送。
    """
    import json as _json, re as _re, requests as _req, base64 as _b64
    from pathlib import Path as _P

    in_path = _P(input_path)
    img_b64 = _b64.standard_b64encode(in_path.read_bytes()).decode("ascii")
    parts: list = [
        {"type": "text", "text": instruction},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
    ]
    if mask_path:
        mp = _P(mask_path)
        if mp.is_file():
            mb64 = _b64.standard_b64encode(mp.read_bytes()).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + mb64}})
            parts.append({"type": "text", "text": "sct=ZolZrUT0e1IDTQOj"})
    h = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}

    last_err: Exception | None = None
    img_url, b64_out = "", ""
    for mi, model_name in enumerate(model_list, 1):
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": parts}],
            "modalities": ["TEXT", "IMAGE"],
        }
        try:
            r = _req.post(base_url + "/v1/chat/completions", json=body, headers=h, timeout=600)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            last_err = e
            print(f"[{backend_label} edit] model={model_name} 请求失败 ({mi}/{len(model_list)}): {e}", file=sys.stderr)
            continue
        img_url, b64_out = "", ""
        for c in data.get("choices", []):
            ct = c.get("message", {}).get("content", "")
            if isinstance(ct, list):
                for p in ct:
                    if isinstance(p, dict) and p.get("type") in ("image_url", "image"):
                        img_url = p.get("image_url", {}).get("url", "") or p.get("image", {}).get("data", "") or p.get("data", "")
                        if img_url and not img_url.startswith("data:"):
                            break
                        elif img_url:
                            b64_out = img_url.split(",", 1)[-1] if "," in img_url else img_url
                            img_url = ""
                            break
            elif isinstance(ct, str):
                m = _re.search(r"!\[.*?\]\((data:image/\w+;base64,[^\s)]+)\)", ct)
                if m:
                    b64_out = m.group(1).split(",", 1)[-1]
                else:
                    m = _re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", ct)
                    if m:
                        img_url = m.group(1)
        if img_url or b64_out:
            break
        # 响应 200 但不含图片（如 think 模型返回文本 JSON）：换下一模型
        last_err = RuntimeError(
            f"{backend_label} edit no image (model={model_name}). resp: "
            + _json.dumps(data, ensure_ascii=False)[:500]
        )
        print(
            f"[{backend_label} edit] model={model_name} 未返回图片 ({mi}/{len(model_list)})，换下一模型...",
            file=sys.stderr,
        )

    if not img_url and not b64_out:
        raise last_err if last_err is not None else RuntimeError(f"{backend_label} edit failed: no image")

    out = _P(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if img_url:
        dl = _req.get(img_url, timeout=300, proxies=None)
        dl.raise_for_status()
        out.write_bytes(dl.content)
    else:
        out.write_bytes(_b64.b64decode(b64_out))
    if not keep_returned_size:
        from PIL import Image as _Img
        orig = _Img.open(in_path)
        ow, oh = orig.size
        ed = _Img.open(out)
        ew, eh = ed.size
        if (ew, eh) != (ow, oh):
            s = max(ow / ew, oh / eh)
            nw, nh = max(ow, int(ew * s)), max(oh, int(eh * s))
            ed = ed.resize((nw, nh), _Img.Resampling.LANCZOS)
            ed = ed.crop(((nw - ow) // 2, (nh - oh) // 2, (nw + ow) // 2, (nh + oh) // 2))
            ed.save(out, "PNG")
        orig.close()
        ed.close()
    return out.resolve()


def _edit_image_micugemini(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> Path:
    """MicuGemini 图编：micuapi.ai /v1/chat/completions，多模型按序重试（MICUGEMINI_MODEL 逗号分隔，最多3个）。
    支持 mask (RGBA PNG：transparent=可编辑，opaque=保留)。"""
    key = os.environ.get("MICUGEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        raise RuntimeError("MICUGEMINI_API_KEY 未设置")
    model_list = _parse_chat_model_list("MICUGEMINI_MODEL", "gemini-3-pro-image-preview")
    return _chat_completions_edit_image(
        backend_label="micugemini",
        base_url="https://www.micuapi.ai",
        api_key=key,
        model_list=model_list,
        input_path=input_path,
        output_path=output_path,
        instruction=instruction,
        keep_returned_size=keep_returned_size,
        mask_path=mask_path,
    )


def _edit_image_xingchengemini(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> Path:
    """XingchenGemini 图编：api.centos.hk /v1/chat/completions，多模型按序重试（XINGCHENGEMINI_MODEL 逗号分隔，最多3个）。
    支持 mask (RGBA PNG：transparent=可编辑，opaque=保留)。"""
    key = os.environ.get("XINGCHENGEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        raise RuntimeError("XINGCHENGEMINI_API_KEY 未设置")
    base_url = os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk").rstrip("/")
    model_list = _parse_chat_model_list("XINGCHENGEMINI_MODEL", "gemini-3.1-flash-image-preview")
    return _chat_completions_edit_image(
        backend_label="xingchengemini",
        base_url=base_url,
        api_key=key,
        model_list=model_list,
        input_path=input_path,
        output_path=output_path,
        instruction=instruction,
        keep_returned_size=keep_returned_size,
        mask_path=mask_path,
    )


def _edit_image_moxingemini(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> Path:
    """MoxinGemini 图编：moxin.studio /v1/chat/completions，多模型按序重试（MOXINGEMINI_MODEL 逗号分隔，最多3个）。
    支持 mask (RGBA PNG：transparent=可编辑，opaque=保留)。

    模型列表优先用非 think 模型避免返回文本而非图片：
    MOXINGEMINI_MODEL=[特价次卡]gemini-3.1-pro-preview,[次]gemini-3-pro-image
    """
    key = os.environ.get("MOXINGEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        raise RuntimeError("MOXINGEMINI_API_KEY 未设置")
    base_url = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").rstrip("/")
    model_list = _parse_chat_model_list(
        "MOXINGEMINI_MODEL",
        "[特价次卡]gemini-3.1-pro-preview,[次]gemini-3-pro-image",
    )
    return _chat_completions_edit_image(
        backend_label="moxingemini",
        base_url=base_url,
        api_key=key,
        model_list=model_list,
        input_path=input_path,
        output_path=output_path,
        instruction=instruction,
        keep_returned_size=keep_returned_size,
        mask_path=mask_path,
    )


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


def get_api_key() -> str:
    keys = _get_api_keys()
    if not keys:
        print("Error: GEMINI_API_KEY not set.", file=sys.stderr)
        print("Set it: export GEMINI_API_KEY='your-key'  (or see references/gemini_edit.md)", file=sys.stderr)
        sys.exit(1)
    return keys[0]


def edit_image(
    input_path: str,
    output_path: str,
    instruction: str,
    *,
    mime_type: str = "image/png",
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> Path:
    """
    Image edit: 默认使用 Gemini 3 Pro Image API（gemini-3-pro-image-preview，2K 输出）。BANNER_IMAGE_BACKEND=nano-banana 时改用 nano-banana CLI。
    Used for outpaint (extend) or inpaint (e.g. remove text). Returns output_path.
    When keep_returned_size=True, do not resize to input size—keep returned dimensions.
    mask_path: optional RGBA mask for micugemini edit (transparent=editable, opaque=preserved).
    """
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)
    if BANNER_IMAGE_BACKEND == "micugemini":
        return _edit_image_micugemini(input_path, output_path, instruction, keep_returned_size=keep_returned_size, mask_path=mask_path)
    if BANNER_IMAGE_BACKEND in ("xingchengpt", "xinchengpt") and os.environ.get("XINGCHENGEMINI_API_KEY", "").startswith("sk-"):
        return _edit_image_xingchengemini(input_path, output_path, instruction, keep_returned_size=keep_returned_size, mask_path=mask_path)
    if BANNER_IMAGE_BACKEND == "moxingpt" and os.environ.get("MOXINGEMINI_API_KEY", "").startswith("sk-"):
        return _edit_image_moxingemini(input_path, output_path, instruction, keep_returned_size=keep_returned_size, mask_path=mask_path)
    if BANNER_IMAGE_BACKEND == "lovart":
        import sys as _sys
        _scripts_dir = Path(__file__).resolve().parent.parent.parent.parent.parent / "scripts"
        if str(_scripts_dir) not in _sys.path:
            _sys.path.insert(0, str(_scripts_dir))
        import lovart_helper as lovart
        _instr_lower = (instruction or "").lower()
        if "remove" in _instr_lower and "text" in _instr_lower:
            result = lovart.edit_inpaint(input_path, output_path, prompt=instruction or lovart.INPAINT_REMOVE_TEXT_PROMPT)
        elif "upscale" in _instr_lower:
            result = lovart.edit_upscale(input_path, output_path)
        else:
            result = lovart.edit_outpaint(input_path, output_path, prompt=instruction or lovart.OUTPAINT_PROMPT)
        if result is None:
            raise RuntimeError("Lovart image edit failed")
        return result
    if BANNER_IMAGE_BACKEND == "t8star":
        return _edit_image_t8star(
            input_path, output_path, instruction, keep_returned_size=keep_returned_size
        )
    if BANNER_IMAGE_BACKEND == "nano-banana":
        result = _edit_image_nano_banana(
            input_path, output_path, instruction, keep_returned_size=keep_returned_size
        )
        if result is not None:
            return result
        print("[banner] nano-banana 不可用或失败，回退到 Gemini API", file=sys.stderr)
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    if mime_type is None:
        mime_type = "image/png"
    if path.suffix.lower() in (".jpg", ".jpeg"):
        mime_type = "image/jpeg"

    body = {
        "contents": [
            {
                "parts": [
                    {"text": instruction},
                    {"inlineData": {"mimeType": mime_type, "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    key = get_api_key()
    api_keys = _get_api_keys()  # [primary, alt]
    key_idx = 0
    _base_for_timeout = os.environ.get("GOOGLE_GEMINI_BASE_URL") or ""
    is_packy = "packyapi.com" in _base_for_timeout or "centos.hk" in _base_for_timeout
    timeout_sec = 300 if is_packy else 120
    headers_base = {"Content-Type": "application/json"}
    if is_packy:
        headers_base["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    model_list = _get_gemini_model_list()
    data = None
    last_503_err = None
    for model in model_list:
        _base_url = f"{API_BASE}/{model}:generateContent"
        url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
        headers = dict(headers_base)
        if key.strip().startswith("sk-"):
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        for attempt in range(_GEMINI_503_RETRIES):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                # Packy 有时会返回 200 但内容是 code/msg 失败（无 candidates）。
                # 这类情况应当继续尝试下一个模型，而不是直接 sys.exit。
                candidates = data.get("candidates") or []
                if candidates:
                    break
                # candidates 为空：若明确是 apikey error/鉴权失败，继续换模型
                msg = (data.get("msg") or data.get("message") or "").lower()
                code = data.get("code")
                if code == -1 and ("apikey" in msg or "key" in msg):
                    print(f"[gemini edit] model={model} returns code=-1 {data.get('msg')}，切换下一模型...", file=sys.stderr)
                    data = None
                    break
                # 其它情况下保留 data，让下面候选检查给出更清晰报错
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8") if e.fp else ""
                last_503_err = (e.code, err_body[:300])
                # 401 / apikey 错误：尝试切换到 ALT key
                if e.code in (401, 403) and (e.code == 401 or ("apikey" in err_body.lower() or "key" in err_body.lower())):
                    key_idx += 1
                    if key_idx < len(api_keys):
                        key = api_keys[key_idx]
                        print(f"[gemini edit] key 鉴权失败，切换到备用 key 重试...", file=sys.stderr)
                        _base_url = f"{API_BASE}/{model}:generateContent"
                        url = _base_url if key.strip().startswith("sk-") else f"{_base_url}?key={key}"
                        headers = dict(headers_base)
                        if key.strip().startswith("sk-"):
                            headers["Authorization"] = f"Bearer {key}"
                        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                        continue
                if e.code in (500, 503):
                    if attempt < _GEMINI_503_RETRIES - 1:
                        wait_sec = _GEMINI_503_BACKOFF_BASE * (3 ** attempt)
                        print(f"[gemini edit] model={model} HTTP {e.code}（服务过载/无渠道），{wait_sec}s 后重试 ({attempt + 1}/{_GEMINI_503_RETRIES})...", file=sys.stderr)
                        time.sleep(wait_sec)
                        continue
                    # 当前模型重试用尽，换下一模型
                    if model != model_list[-1]:
                        print(f"[gemini edit] model={model} 重试后仍 {e.code}，切换下一模型...", file=sys.stderr)
                        break
                    # 已是最后一个模型
                    print(f"Error: API {e.code}", file=sys.stderr)
                    if err_body:
                        print(err_body[:500], file=sys.stderr)
                    raise RuntimeError(f"Gemini image edit failed: HTTP {e.code} (all retries exhausted)")
                # 403：常见于渠道「无权访问该模型」，换下一候选（如 3-pro → 2.5-flash-image）
                if e.code == 403 and model != model_list[-1]:
                    print(
                        f"[gemini edit] model={model} HTTP 403（可能无权使用该模型），切换下一模型...",
                        file=sys.stderr,
                    )
                    data = None
                    break
                print(f"Error: API {e.code}", file=sys.stderr)
                if err_body:
                    print(err_body[:500], file=sys.stderr)
                raise RuntimeError(f"Gemini image edit failed: HTTP {e.code} for model {model}")
            except urllib.error.URLError as e:
                last_503_err = (0, str(e.reason)[:300])
                if attempt < _GEMINI_503_RETRIES - 1:
                    wait_sec = _GEMINI_503_BACKOFF_BASE * (3 ** attempt)
                    print(f"[gemini edit] model={model} 网络/SSL 错误: {e.reason}，{wait_sec}s 后重试 ({attempt + 1}/{_GEMINI_503_RETRIES})...", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                if model != model_list[-1]:
                    print(f"[gemini edit] model={model} 网络错误重试用尽，切换下一模型...", file=sys.stderr)
                    data = None
                    break
                print(f"Error: {e.reason}", file=sys.stderr)
                raise RuntimeError(f"Gemini image edit failed: network error {e.reason}")
        else:
            # 当前模型重试全部失败，继续下一模型
            continue
        if data is not None:
            break
    if data is None:
        print("Error: Gemini image edit 所有模型均失败。", file=sys.stderr)
        if last_503_err:
            print(f"最后错误: HTTP {last_503_err[0]} {last_503_err[1][:200]}", file=sys.stderr)
        raise RuntimeError("Gemini image edit failed: all candidate models returned no data")

    # Extract image from first candidate
    candidates = data.get("candidates") or []
    if not candidates:
        print("Error: No candidates in response.", file=sys.stderr)
        if "promptFeedback" in data:
            print("promptFeedback:", data["promptFeedback"], file=sys.stderr)
        # Debug: print partial response to understand why candidates missing.
        try:
            s = json.dumps(data, ensure_ascii=False)
        except Exception:
            s = str(data)
        print("response_snippet:", s[:2000], file=sys.stderr)
        raise RuntimeError("Gemini image edit failed: no image candidates in response")
    parts = candidates[0].get("content", {}).get("parts") or []
    for part in parts:
        if "inlineData" in part:
            b64_out = part["inlineData"].get("data")
            if b64_out:
                out_bytes = base64.standard_b64decode(b64_out)
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(out_bytes)
                # 若 API 返回尺寸与输入不一致：仅当返回图更大时缩小到输入尺寸；若返回图更小则不放大（保留原图，避免糊）
                if Image is not None:
                    try:
                        inp = Image.open(path).convert("RGB")
                        out_img = Image.open(out_path).convert("RGB")
                        w_in, h_in = inp.size
                        w_out, h_out = out_img.size
                        print(f"Gemini 返回图: {w_out}×{h_out}, 输入: {w_in}×{h_in}", file=sys.stderr)
                        if keep_returned_size:
                            # 保留 API 返回尺寸，不缩放（供调用方做裁切等）
                            out_img.save(str(out_path), "PNG")
                        elif (w_out, h_out) == (w_in, h_in):
                            pass
                        elif w_out >= w_in and h_out >= h_in:
                            out_img = out_img.resize((w_in, h_in), Image.Resampling.LANCZOS)
                            out_img.save(str(out_path), "PNG")
                        else:
                            # 返回图比输入小：不放大，保留原图（填充任务应对空白区域填满并同尺寸输出）
                            shutil.copy2(path, out_path)
                    except Exception:
                        pass
                return out_path
    print("Error: No image in response.", file=sys.stderr)
    if "promptFeedback" in data:
        print("promptFeedback:", data["promptFeedback"], file=sys.stderr)
    if candidates:
        parts = candidates[0].get("content", {}).get("parts") or []
        for i, p in enumerate(parts):
            if "text" in p:
                print(f"  part[{i}] text: {p['text'][:200]}...", file=sys.stderr)
    raise RuntimeError("Gemini image edit failed: response contains no inline image data")


OUTPAINT_PROMPT = (
    "Extend this image to fill a wide banner. "
    "Add content on the sides or top/bottom as needed so the result can be cropped to a wide rectangle. "
    "Keep the same style, lighting, and scene; seamlessly blend new areas with the original."
)

INPAINT_REMOVE_TEXT_PROMPT = (
    "This image will be used as a banner background. The image owner wants to add their own title and subtitle, so overlaid text and UI elements must be removed and the area filled with the underlying scene. "
    "Remove only: overlaid promotional text, date text, logos, solid color blocks or panels, blur overlays, buttons, UI controls, badges, and other on-screen overlays. "
    "Do not alter, redraw, or change any part of the image that is not covered by overlays. Preserve the original artwork, characters, colors, and composition everywhere else; only remove the overlaid elements and inpaint the removed regions to match the immediate surrounding area. "
    "Also remove any shadows, halos, or dark smudges left by the removed text or overlays; the filled area must match the surrounding background with no residual shadows or discoloration. "
    "Also fix any unnatural dark patches or heavy shadows on the character's body (e.g. waist, hip, torso)—blend them into the surrounding skin or fabric lighting so the character looks evenly lit, without dark bands or smudges. "
    "Fill the removed areas naturally: where overlays covered the background (sky, buildings, etc.), extend the surrounding background; "
    "where overlays covered a character (clothing, skin, hair), restore the underlying character appearance seamlessly—match the existing fabric, skin tone, and lighting. "
    "Do not leave dark patches, black lines, or visible seams. The result must look like the original scene with overlays removed—no black marks, no dark bands. "
    "Do not add any new text or graphics. "
    "Do not add, draw, or generate any person, character, human figure, or face in the inpainted areas; only remove overlays and extend or blend the existing background. "
    "Output must have exactly the same dimensions as the input. Return the edited image."
)

# 去除画面中的人物，用背景自然填充（与 remove-text 类似，但目标是人物区域）
INPAINT_REMOVE_PEOPLE_PROMPT = (
    "This image is a horizontal banner with a blue gradient tech-style background. "
    "Remove ALL human figures (people, characters) from the image. There are two women in business attire in the center-left area—remove them completely. "
    "Fill the area where they were with the same blue gradient, abstract light lines, soft glow, and tech atmosphere as the rest of the background. "
    "The filled region must seamlessly match the surrounding background: same lighting, same gradient direction, same style. No visible seam, no dark patches, no leftover body parts or shadows. "
    "Do not alter the existing text, titles, subtitle, or the '了解详情' button—keep all text and UI exactly as they are. "
    "Do not add any new people, characters, or text. Output must have exactly the same dimensions as the input. Return the edited image."
)

# 步骤 5：整张画面空白区域必须填满。须用「延展」方式扩展背景，禁止重复/平铺主体或画面。
OUTPAINT_FILL_BLANK_PROMPT = (
    "This image is a horizontal banner. The middle/center has the real scene (e.g. a character, subject); the LEFT, RIGHT, TOP and BOTTOM have UNFILLED areas in solid RGB(0,0,1). Your task is to FILL those blank areas by EXTENDING the scene—not by repeating or duplicating the existing content. "
    "CRITICAL: (1) EXTEND only: continue the background (sky, clouds, water, light, atmosphere, environment) naturally from the edges of the existing scene into the blank regions. The result must look like one single, continuous wide image. "
    "(2) Do NOT repeat, duplicate, or tile the subject/character or the main foreground. Do NOT copy the character or central figure to the left/right/top/bottom. Blank areas must be filled with natural continuation of the background only (e.g. more sky, more clouds, more water, more ambient light)—never with a second copy of the character or scene. "
    "(3) Treat all solid RGB(0,0,1) or near-black regions as blank. Replace them with seamlessly extended background (same style, lighting, colors). Do not add new characters or text. "
    "(4) Output MUST have exactly the same pixel dimensions as the input. No black bars on any edge. One seamless image, no visible seams or tiling."
)

# 步骤 7 二次填充：未填充区域只做「延展」背景，禁止重复/平铺主体；延展区与现有画面强关联。
OUTPAINT_FILL_REMAINING_BLACK_PROMPT = (
    "This banner still has UNFILLED areas (solid RGB(1,0,254) or near-black) on the left, right, top and/or bottom. Fill them by EXTENDING the background only—do NOT repeat or duplicate the subject/character or main scene. "
    "EXTEND: continue the adjacent background (sky, clouds, water, atmosphere, lighting) naturally into the blank regions so the image looks like one continuous scene. "
    "The filled areas MUST keep the SAME art style, lighting, and perspective as the existing scene—one coherent image with no visible seam. "
    "Do NOT copy, tile, or repeat the character or central figure in the blank areas. Only the environment/background should extend; no second instance of the subject. "
    "Output MUST have exactly the same dimensions as the input. No black bars on any edge. No new characters or text."
)

# A6b 商店专题头图 1740×220：Object/Environment Editing — 向未填充/接缝区域延展环境，融补割裂；不新增人物与文字
A6B_SHOP_HEADER_EXTEND_PROMPT = (
    "This wide shop header banner (same pixel size as input) needs Object/Environment editing. "
    "Treat visible seam lines, fragmented patches, unfilled near-black strips, or obvious copy-pasted/repeated background chunks as areas to FIX by EXTENDING the existing environment only—"
    "continue the same room, lighting, materials, and perspective from adjacent pixels so the whole image becomes one continuous scene. "
    "Blend seams; do not leave vertical or horizontal 'pasted' bands. Do NOT duplicate the main character or add a second subject. "
    "Do NOT add any people, faces, characters, or readable text. "
    "Output MUST be exactly the same width and height as the input—no crop, no letterboxing."
)

# Strip（1740×220）直达画布填充：跳过 2048×512 中间画布，直接在目标尺寸上一次性延展，消除 A4→A5 三段拼接问题
STRIP_DIRECT_FILL_PROMPT = (
    "This wide shop header banner (same pixel size as input) needs Object/Environment editing. "
    "The image has a subject in the center and UNFILLED areas (solid RGB(1,0,254) or near-black) on the left, right, top, and bottom. "
    "Your task: FILL the entire canvas by EXTENDING the scene from the subject outward based on existing content—keep the subject area UNCHANGED; only fill the blank regions. "
    "EXTEND the environment naturally so the result is one seamless image. "
    "CRITICAL—STRONG VISUAL CONTINUITY, NO SEAM: The extended areas MUST look like the SAME single photograph or render—same camera viewpoint, same perspective, same depth of field and scale. "
    "This is a very wide (aspect ~8:1) horizontal banner strip; the filled regions must read as more of the same scene panned naturally left and right, not as separate pasted patches. "
    "(1) Use the EXACT same art style: same rendering (3D vs realistic), same level of detail, same textures and materials. "
    "(2) Use the SAME lighting: same light direction, same color temperature, same shadow softness. "
    "(3) Preserve the SAME perspective and scale: extend the same room/space at the SAME apparent distance and scale; do not zoom out or change viewpoint. "
    "(4) No visible seam: the result must look like one single, coherent image captured or rendered as a whole. "
    "(5) Extended regions must have similar CONTENT DENSITY and type as the center: if the scene is an office with desks, extend with more of the same room—desks, walls, floor, ceiling, lighting fixtures; do NOT fill large areas with only a window, sky, or empty flat color. "
    "(6) Do NOT create an obvious vertical BAND: no single narrow strip that looks clearly different in content or brightness from the areas beside it—the result must be one continuous scene with no 'pasted' column. Light must transition naturally across the image. "
    "(7) Do NOT mirror, tile, or repeat existing background elements (e.g. windows, curtains, furniture). Each extended region must show UNIQUE, naturally continued space. "
    "Do NOT add new people, faces, characters, or readable text. Do NOT repeat or duplicate the subject. "
    "Output MUST be exactly the same width and height as the input—no crop, no letterboxing, no black bars on any edge."
)

# A6b 兜底修复（仅当直达画布填充产出仍有瑕疵时触发一次修复）
# A6B_SHOP_HEADER_EXTEND_PROMPT 保持原定义不变，位于上方 L612

# A4 填充画面：以 bbox 区域为中心、根据画面已有内容向四周延展填充，保持 bbox 内区域不变；不新增人物或文字；生成 2048×512；检查未填充完整则重新填充。输出：output/tianchong.png
OUTPAINT_FILL_TO_3840x1080_PROMPT = (
    "Output must be exactly 2048×512 pixels. "
    "This image has a subject in the center and UNFILLED areas (solid RGB(1,0,254) or near-black) around it. "
    "Your task: FILL the entire image by EXTENDING the scene from the center subject outward based on existing content—keep the subject (bbox) area UNCHANGED; only fill the blank regions. "
    "EXTEND the background (sky, clouds, water, atmosphere, lighting) naturally so the result is one seamless 2048×512 image. "
    "CRITICAL—STRONG VISUAL CONTINUITY, NO SEAM: The extended areas MUST look like the SAME single photograph or render—same camera viewpoint, same perspective, same depth of field and scale. "
    "Do NOT draw a different angle or a 'wider empty corridor' view; the filled regions must feel like more of the same frame (as if the camera panned slightly), not a different shot. There must be NO visible cut or seam between the original content and the extended regions. "
    "(1) Use the EXACT same art style: same rendering (e.g. 3D cartoon vs realistic), same level of detail, same textures and materials. "
    "(2) Use the SAME lighting: same light direction, same color temperature, same shadow softness—the extended areas must feel like one continuous space. "
    "(3) Preserve the SAME perspective and scale: if the existing scene is a room with desks, extend the same room at the SAME apparent distance and scale (same size desks, same floor tiles); do not introduce a different viewpoint or a zoomed-out 'empty hall' view. "
    "(4) There must be NO visible seam or style break between the original and the extended regions—the result must look like one single, coherent image that was captured or rendered as a whole. "
    "Do NOT add new characters or text. Do NOT repeat or duplicate the subject. "
    "Do NOT mirror, tile, or repeat existing background elements (e.g. windows, curtains, furniture, cans, papers). Each extended region must show UNIQUE, naturally continued space—no duplicated or mirrored patches from the same image; the extension should feel like one continuous room or scene, not the same strip copied to the sides. "
    "(5) Extended regions must have similar CONTENT DENSITY and type as the center: if the scene is a room with desks and walls, extend with more of the same (desks, walls, floor, furniture)—do NOT fill a large left or right area with only a window, sky, or flat light; both sides should feel like the same room. "
    "(6) Do NOT create an obvious vertical or horizontal BAND: no single narrow strip (e.g. one vertical column) that looks clearly different in content or brightness from the areas beside it—the result must be one continuous scene with no 'pasted' strip. If there is window or sunlight, the light must transition naturally across the image; avoid one overexposed or empty-looking vertical band. "
    "Output image MUST be exactly 2048 pixels wide and 512 pixels tall. No black bars or unfilled edges."
)

# A4 填充画面 (packygpt 2880×960)：packygpt gpt-image-2 原生 3:1 比例，无需缩-放，直接目标尺寸延展填充
OUTPAINT_FILL_TO_2880x960_PROMPT = (
    "Output must be exactly 2880×960 pixels. "
    "This image has a subject in the center and UNFILLED areas (solid RGB(1,0,254) or near-black) around it. "
    "Your task: FILL the entire image by EXTENDING the scene from the center subject outward based on existing content—keep the subject (bbox) area UNCHANGED; only fill the blank regions. "
    "EXTEND the background (sky, clouds, water, atmosphere, lighting) naturally so the result is one seamless 2880×960 image. "
    "CRITICAL—STRONG VISUAL CONTINUITY, NO SEAM: The extended areas MUST look like the SAME single photograph or render—same camera viewpoint, same perspective, same depth of field and scale. "
    "Do NOT draw a different angle or a 'wider empty corridor' view; the filled regions must feel like more of the same frame (as if the camera panned slightly), not a different shot. There must be NO visible cut or seam between the original content and the extended regions. "
    "(1) Use the EXACT same art style: same rendering (e.g. 3D cartoon vs realistic), same level of detail, same textures and materials. "
    "(2) Use the SAME lighting: same light direction, same color temperature, same shadow softness—the extended areas must feel like one continuous space. "
    "(3) Preserve the SAME perspective and scale: if the existing scene is a room with desks, extend the same room at the SAME apparent distance and scale (same size desks, same floor tiles); do not introduce a different viewpoint or a zoomed-out 'empty hall' view. "
    "(4) There must be NO visible seam or style break between the original and the extended regions—the result must look like one single, coherent image that was captured or rendered as a whole. "
    "Do NOT add new characters or text. Do NOT repeat or duplicate the subject. "
    "Do NOT mirror, tile, or repeat existing background elements (e.g. windows, curtains, furniture, cans, papers). Each extended region must show UNIQUE, naturally continued space—no duplicated or mirrored patches from the same image; the extension should feel like one continuous room or scene, not the same strip copied to the sides. "
    "(5) Extended regions must have similar CONTENT DENSITY and type as the center: if the scene is a room with desks and walls, extend with more of the same (desks, walls, floor, furniture)—do NOT fill a large left or right area with only a window, sky, or flat light; both sides should feel like the same room. "
    "(6) Do NOT create an obvious vertical or horizontal BAND: no single narrow strip (e.g. one vertical column) that looks clearly different in content or brightness from the areas beside it—the result must be one continuous scene with no 'pasted' strip. If there is window or sunlight, the light must transition naturally across the image; avoid one overexposed or empty-looking vertical band. "
    "Output image MUST be exactly 2880 pixels wide and 960 pixels tall. No black bars or unfilled edges."
)


def image_has_black_bars(
    image_path: str,
    margin_ratio: float = 0.02,
    black_ratio: float = 0.03,
    threshold: int = 50,
) -> bool:
    """检测图像上下左右四边是否仍有黑色区域（含极细黑边）。任一边黑像素占比达标即返回 True。"""
    if Image is None:
        return False
    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        n_w = int(w * margin_ratio)
        n_h = int(h * margin_ratio)
        if n_w < 1 and n_h < 1:
            return False
        n_w = max(1, n_w)
        n_h = max(1, n_h)
        left_region = img.crop((0, 0, n_w, h))
        right_region = img.crop((w - n_w, 0, w, h))
        top_region = img.crop((0, 0, w, n_h))
        bottom_region = img.crop((0, h - n_h, w, h))

        def edge_black_ratio(region: Image.Image) -> float:
            pixels = list(region.getdata())
            if not pixels:
                return 0.0
            black = sum(1 for p in pixels if max(p) < threshold)
            return black / len(pixels)

        # 任一边黑占比 >= black_ratio 即触发二次填充
        for region in (left_region, right_region, top_region, bottom_region):
            if edge_black_ratio(region) >= black_ratio:
                return True
        return False
    except Exception:
        return False


def image_has_black_bars_full_image(
    image_path: str,
    threshold: int = 50,
    black_ratio: float = 0.005,
) -> bool:
    """检测整张画面黑像素占比。若整图黑像素占比 >= black_ratio 则返回 True，用于 Step 7 整图范围检测。"""
    if Image is None:
        return False
    try:
        img = Image.open(image_path).convert("RGB")
        pixels = list(img.getdata())
        if not pixels:
            return False
        black = sum(1 for p in pixels if max(p) < threshold)
        return (black / len(pixels)) >= black_ratio
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Edit image with Gemini (outpaint or remove text). Requires GEMINI_API_KEY."
    )
    parser.add_argument("input", help="Input image path")
    parser.add_argument("output", help="Output image path")
    parser.add_argument(
        "--mode",
        choices=["outpaint", "remove-text", "remove-people"],
        default="outpaint",
        help="outpaint: extend image; remove-text: remove text/watermarks and fill; remove-people: remove human figures and fill with background",
    )
    parser.add_argument("--instruction", "-i", default="", help="Custom instruction (overrides --mode default)")
    args = parser.parse_args()

    if args.instruction:
        instruction = args.instruction
    elif args.mode == "outpaint":
        instruction = OUTPAINT_PROMPT
    elif args.mode == "remove-people":
        instruction = INPAINT_REMOVE_PEOPLE_PROMPT
    else:
        instruction = INPAINT_REMOVE_TEXT_PROMPT

    out = edit_image(args.input, args.output, instruction)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
