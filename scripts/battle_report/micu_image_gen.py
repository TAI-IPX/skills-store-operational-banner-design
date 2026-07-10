#!/usr/bin/env python3
"""
战报 / HD：MICU OpenAI 兼容文生图与图编。

环境变量：
  MICU_API_KEY   必填
  MICU_API_URL   默认 https://www.micuapi.ai/v1/images/generations
  MICU_MODEL     默认 gpt-image-2
"""
from __future__ import annotations

import base64
import os
import time
from io import BytesIO
from pathlib import Path

import requests

from scripts.battle_report.env_setup import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def micu_available() -> bool:
    load_dotenv()
    return bool(os.environ.get("MICU_API_KEY", "").strip())


def _micu_config() -> tuple[str, str, str]:
    key = os.environ.get("MICU_API_KEY", "").strip()
    url = (
        os.environ.get("MICU_API_URL", "https://www.micuapi.ai/v1/images/generations")
        .strip()
        .strip('"')
    )
    model = os.environ.get("MICU_MODEL", "gpt-image-2").strip()
    return key, url, model


def _image_has_alpha_channel(img) -> bool:
    import numpy as np

    if img.mode not in ("RGBA", "LA"):
        return False
    a = np.array(img.split()[-1])
    if a.size == 0:
        return False
    return float((a < 250).sum()) / float(a.size) >= 0.02


def run_micu_t2i(
    prompt: str,
    output_path: Path,
    *,
    width: int,
    height: int,
    timeout: int = 360,
    background: str | None = None,
    preserve_alpha: bool = False,
) -> Path | None:
    """MICU 文生图 → 指定像素 PNG（cover 到 width×height）。background=transparent 时尝试保留 alpha。"""
    from PIL import Image

    load_dotenv()
    key, url, model = _micu_config()
    if not key:
        print("[战报/MICU] 未配置 MICU_API_KEY", flush=True)
        return None

    out_path = output_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }
    if background:
        payload["background"] = background
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        body = r.json()
    except requests.RequestException as exc:
        detail = ""
        if hasattr(exc, "response") and exc.response is not None:
            try:
                detail = exc.response.text[:500]
            except Exception:
                pass
        print(f"[战报/MICU] 请求失败: {exc} {detail}", flush=True)
        return None
    except ValueError as exc:
        print(f"[战报/MICU] 响应非 JSON: {exc}", flush=True)
        return None

    items = body.get("data") if isinstance(body, dict) else None
    if not items:
        print(f"[战报/MICU] 响应无 data: {str(body)[:300]}", flush=True)
        return None

    item = items[0]
    raw: bytes | None = None
    if isinstance(item, dict):
        b64 = item.get("b64_json")
        if b64:
            raw = base64.b64decode(b64)
        elif item.get("url"):
            try:
                img_r = requests.get(item["url"], timeout=timeout)
                img_r.raise_for_status()
                raw = img_r.content
            except requests.RequestException as exc:
                print(f"[战报/MICU] 下载图片 URL 失败: {exc}", flush=True)
                return None

    if not raw:
        print("[战报/MICU] 响应中无 b64_json 或 url", flush=True)
        return None

    img = Image.open(BytesIO(raw))
    if preserve_alpha and img.mode != "RGBA":
        img = img.convert("RGBA")
    elif not preserve_alpha:
        img = img.convert("RGB")
    elif img.mode != "RGBA":
        img = img.convert("RGBA")

    if img.size != (width, height):
        sw, sh = img.size
        scale = max(width / sw, height / sh)
        nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left, top = (nw - width) // 2, (nh - height) // 2
        img = resized.crop((left, top, left + width, top + height))

    has_alpha = preserve_alpha and _image_has_alpha_channel(img)
    if preserve_alpha and not has_alpha:
        print("[战报/MICU] t2i 未检测到有效 alpha，保存为 RGB", flush=True)
        img = img.convert("RGB")

    img.save(out_path, "PNG")
    mode_note = " RGBA" if img.mode == "RGBA" else ""
    print(
        f"[战报/MICU] t2i {model} → {out_path.name} ({width}×{height}{mode_note})",
        flush=True,
    )
    return out_path


def micu_edits_url() -> str:
    """MICU 图编 endpoint（OpenAI 兼容 /v1/images/edits）。"""
    from scripts.battle_report.micu_vision import micu_api_base

    return f"{micu_api_base()}/images/edits"


def _fit_edit_image_to_input(out_img, w_in: int, h_in: int):
    """将图编结果 cover 裁切/缩放到与输入同尺寸（任意返回尺寸均保留图编内容）。"""
    from PIL import Image

    w_out, h_out = out_img.size
    if (w_out, h_out) == (w_in, h_in):
        return out_img
    scale = max(w_in / w_out, h_in / h_out)
    nw = max(1, int(round(w_out * scale)))
    nh = max(1, int(round(h_out * scale)))
    resized = out_img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - w_in) // 2)
    top = max(0, (nh - h_in) // 2)
    return resized.crop((left, top, left + w_in, top + h_in))


def _save_micu_edit_output(
    raw: bytes,
    input_path: Path,
    output_path: Path,
    *,
    keep_returned_size: bool,
) -> Path:
    from PIL import Image

    out_path = output_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    try:
        inp = Image.open(input_path)
        out_img = Image.open(out_path)
        w_in, h_in = inp.size
        w_out, h_out = out_img.size
        print(f"[战报/MICU] 图编返回: {w_out}×{h_out}, 输入: {w_in}×{h_in}", flush=True)
        if keep_returned_size:
            out_img.save(str(out_path), "PNG")
        elif (w_out, h_out) == (w_in, h_in):
            pass
        else:
            fitted = _fit_edit_image_to_input(out_img, w_in, h_in)
            if (w_out, h_out) != (w_in, h_in):
                print(
                    f"[战报/MICU] 图编尺寸对齐 → {w_in}×{h_in}（cover，保留图编结果）",
                    flush=True,
                )
            fitted.save(str(out_path), "PNG")
    except Exception:
        pass
    return out_path


def run_micu_edit(
    input_path: Path,
    output_path: Path,
    prompt: str,
    *,
    timeout: int = 360,
    keep_returned_size: bool = False,
) -> Path | None:
    """MICU 图编（/v1/images/edits）：参考图 + 指令 → PNG。"""
    load_dotenv()
    key, _, model = _micu_config()
    if not key:
        print("[战报/MICU] 未配置 MICU_API_KEY", flush=True)
        return None

    path = Path(input_path)
    if not path.is_file():
        print(f"[战报/MICU] 图编输入不存在: {path}", flush=True)
        return None

    url = micu_edits_url()
    headers = {"Authorization": f"Bearer {key}"}
    max_retries = int(os.environ.get("HD_MICU_EDIT_RETRIES", "3"))
    retry_wait_base = int(os.environ.get("HD_MICU_EDIT_RETRY_WAIT", "15"))
    for attempt in range(max_retries + 1):
        try:
            with open(path, "rb") as f:
                files = {"image": (path.name, f, "image/png")}
                data = {
                    "model": model,
                    "prompt": prompt,
                    "n": "1",
                    "size": "auto",
                    "response_format": "b64_json",
                }
                r = requests.post(url, data=data, files=files, headers=headers, timeout=timeout)
            r.raise_for_status()
            body = r.json()
        except requests.RequestException as exc:
            detail = ""
            status = None
            if hasattr(exc, "response") and exc.response is not None:
                status = exc.response.status_code
                try:
                    detail = exc.response.text[:500]
                except Exception:
                    pass
            print(f"[战报/MICU] 图编请求失败: {exc} {detail}", flush=True)
            retryable = status in (524, 502, 503, 504, 429) or isinstance(
                exc,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
            if retryable and attempt < max_retries:
                wait = retry_wait_base * (attempt + 1)
                label = status if status else type(exc).__name__
                print(
                    f"[战报/MICU] 图编 {label}，{wait}s 后重试 ({attempt + 1}/{max_retries})...",
                    flush=True,
                )
                time.sleep(wait)
                continue
            return None
        except ValueError as exc:
            print(f"[战报/MICU] 图编响应非 JSON: {exc}", flush=True)
            return None

        items = body.get("data") if isinstance(body, dict) else None
        if not items:
            print(f"[战报/MICU] 图编响应无 data: {str(body)[:300]}", flush=True)
            return None

        item = items[0]
        raw: bytes | None = None
        if isinstance(item, dict):
            b64 = item.get("b64_json")
            if b64:
                raw = base64.b64decode(b64)
            elif item.get("url"):
                try:
                    img_r = requests.get(item["url"], timeout=timeout)
                    img_r.raise_for_status()
                    raw = img_r.content
                except requests.RequestException as exc:
                    print(f"[战报/MICU] 图编下载 URL 失败: {exc}", flush=True)
                    return None
        if not raw:
            print("[战报/MICU] 图编响应中无 b64_json 或 url", flush=True)
            return None

        out = _save_micu_edit_output(
            raw, path, output_path, keep_returned_size=keep_returned_size
        )
        print(f"[战报/MICU] edit {model} → {out.name}", flush=True)
        return out
    return None
