"""
xinchengpt_images_api.py — 标准 OpenAI Images API 封装（api.centos.hk / XinchenGPT）

     三个端点：
  1. generate_image     → POST /v1/images/generations   (JSON body, 单图文生图)
  2. edit_image         → POST /v1/images/edits          (multipart form-data, 支持 mask)
  3. chat_completions_image → POST /v1/chat/completions  (JSON body, 多模态多图)

 用法：
   from xinchengpt_images_api import generate_image, edit_image, chat_completions_image

   # 文生图
   generate_image("A cat on the moon", "output/cat.png")

   # 图编（标准 multipart，支持 mask）
   edit_image("input/photo.png", "Remove the background", "output/edited.png")

   # 多模态多图合成
   png_bytes = chat_completions_image(
       ["char1.png", "char2.png"],
       "请将两个角色合成到一张图...",
   )

 CLI:
   py scripts/xinchengpt_images_api.py generate "A cat" -o output/cat.png
   py scripts/xinchengpt_images_api.py edit input/photo.png "Remove bg" -o output/edited.png
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image as _PILImage

BASE_URL = os.environ.get("XINCHENGPT_BASE_URL", "https://api.centos.hk").rstrip("/") + "/v1"
DEFAULT_MODEL = "gpt-image-2"


def _get_api_key() -> str:
    key = os.environ.get("XINCHENGPT_API_KEY", "").strip()
    if not key or not key.startswith("sk-"):
        raise RuntimeError(
            "XINCHENGPT_API_KEY 未设置或格式错误（需 sk- 开头）。"
            "请在 .env 或环境变量中配置。"
        )
    return key


def _get_proxies() -> dict | None:
    """默认直连（不读系统代理），避免本机代理软件掐断 gpt-image-2 长连接请求。
    需要走代理时显式设置 XINCHENGPT_USE_PROXY=1 才会探测 HTTPS_PROXY / Windows 注册表代理。
    XINCHENGPT_NO_PROXY=1 仍受支持（向后兼容，效果与不设置任何代理开关一致）。
    """
    no_proxy = os.environ.get("XINCHENGPT_NO_PROXY", "").strip()
    if no_proxy.lower() in ("1", "true", "yes"):
        return None

    use_proxy = os.environ.get("XINCHENGPT_USE_PROXY", "").strip()
    if use_proxy.lower() not in ("1", "true", "yes"):
        return None

    sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not sys_proxy:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                if sys_proxy and not sys_proxy.startswith("http"):
                    sys_proxy = "http://" + sys_proxy
            winreg.CloseKey(key)
        except Exception:
            pass
    if not sys_proxy:
        return None
    return {"https": sys_proxy, "http": sys_proxy}


def _get_headers(content_type: str = "application/json") -> dict:
    api_key = _get_api_key()
    return {
        "Content-Type": content_type,
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }


def _resolve_image_url(data: dict) -> tuple[str, str]:
    """从响应中提取图片 URL 或 base64。返回 (url, b64)。"""
    img_url = ""
    b64_out = ""

    dall_e_data = data.get("data", [{}])
    if dall_e_data:
        img_url = dall_e_data[0].get("url", "")
        b64_out = dall_e_data[0].get("b64_json", "")

    if not img_url and not b64_out:
        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                        img_url = part.get("image_url", {}).get("url", "") or part.get("image", {}).get("data", "") or part.get("data", "")
                        if img_url and not img_url.startswith("data:"):
                            break
                        elif img_url:
                            b64_out = img_url.split(",", 1)[-1] if "," in img_url else img_url
                            img_url = ""
                            break
            elif isinstance(content, str):
                mk = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', content)
                if mk:
                    img_url = mk.group(1)
                elif content.startswith("data:image"):
                    b64_out = content.split(",")[-1] if "," in content else content
                elif content.strip().startswith(("https://", "http://")):
                    img_url = content.strip().split()[0]

    return img_url, b64_out


def _download_image(img_url: str, b64_out: str) -> bytes:
    """下载图片，返回 bytes。"""
    import requests as _requests
    if img_url:
        resp = _requests.get(img_url, timeout=300, proxies=_get_proxies())
        resp.raise_for_status()
        return resp.content
    elif b64_out:
        return base64.b64decode(b64_out)
    raise RuntimeError("无图片数据")


def generate_image(
    prompt: str,
    output_path: str | None = None,
    *,
    model: str | None = None,
    size: str = "auto",
    quality: str = "auto",
    n: int = 1,
    response_format: str = "url",
) -> Path | bytes | None:
    """
    文生图：POST /v1/images/generations
    output_path 为 None 时返回 bytes。
    """
    import requests as _requests
    api_key = _get_api_key()
    model = model or os.environ.get("XINCHENGPT_MODEL", DEFAULT_MODEL).strip()
    _size = size or os.environ.get("XINCHENGPT_SIZE", "auto").strip()
    _quality = quality or os.environ.get("XINCHENGPT_QUALITY", "auto").strip()

    url = f"{BASE_URL}/images/generations"
    body = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": _size,
        "quality": _quality,
        "response_format": response_format,
    }
    print(f"[xinchengpt t2i] 生成图片（{model}，size={_size}，quality={_quality}）...", flush=True)
    resp = _requests.post(url, json=body, headers=_get_headers(), timeout=300, proxies=_get_proxies())
    data = resp.json()

    img_url, b64_out = _resolve_image_url(data)
    if not img_url and not b64_out:
        print(f"[xinchengpt t2i] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    img_bytes = _download_image(img_url, b64_out)
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        print(f"[xinchengpt t2i] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    return img_bytes


def edit_image(
    image_path: str,
    prompt: str,
    output_path: str | None = None,
    *,
    mask_path: str | None = None,
    model: str | None = None,
    size: str = "auto",
    quality: str = "auto",
) -> Path | bytes | None:
    """
    图编：POST /v1/images/edits（multipart form-data）
    output_path 为 None 时返回 bytes。
    """
    import requests as _requests
    model = model or os.environ.get("XINCHENGPT_MODEL", DEFAULT_MODEL).strip()
    _size = size or os.environ.get("XINCHENGPT_SIZE", "auto").strip()
    _quality = quality or os.environ.get("XINCHENGPT_QUALITY", "auto").strip()

    img_path = Path(image_path)
    if not img_path.is_file():
        raise FileNotFoundError(f"图片不存在: {img_path}")

    url = f"{BASE_URL}/images/edits"
    files = []
    files.append(("image", (img_path.name, img_path.open("rb"), "image/png")))
    if mask_path and Path(mask_path).is_file():
        files.append(("mask", (Path(mask_path).name, Path(mask_path).open("rb"), "image/png")))

    data_fields = {
        "prompt": prompt,
        "model": model,
        "size": _size,
        "quality": _quality,
    }
    print(f"[xinchengpt edit] 编辑图片（{model}）...", flush=True)
    resp = _requests.post(
        url,
        files=files,
        data=data_fields,
        headers={"Authorization": f"Bearer {_get_api_key()}"},
        timeout=600,
        proxies=_get_proxies(),
    )
    data = resp.json()

    img_url, b64_out = _resolve_image_url(data)
    if not img_url and not b64_out:
        print(f"[xinchengpt edit] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    img_bytes = _download_image(img_url, b64_out)
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        print(f"[xinchengpt edit] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    return img_bytes


def chat_completions_image(
    image_paths: list[str],
    prompt: str,
    output_path: str | None = None,
    *,
    model: str | None = None,
    size: str = "auto",
    quality: str = "auto",
) -> Path | bytes | None:
    """
    多模态图编/图生图：POST /v1/chat/completions
    output_path 为 None 时返回 bytes。
    """
    import requests as _requests
    model = model or os.environ.get("XINCHENGPT_MODEL", DEFAULT_MODEL).strip()
    _size = size or os.environ.get("XINCHENGPT_SIZE", "auto").strip()
    _quality = quality or os.environ.get("XINCHENGPT_QUALITY", "auto").strip()

    content_parts: list = [{"type": "text", "text": prompt}]
    for ip in image_paths:
        p = Path(ip)
        if not p.is_file():
            print(f"[xinchengpt chat] 图片不存在: {p}", file=sys.stderr)
            continue
        b64 = base64.standard_b64encode(p.read_bytes()).decode("ascii")
        content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

    url = f"{BASE_URL}/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content_parts}],
        "size": _size,
        "quality": _quality,
    }
    print(f"[xinchengpt chat] 生成图片（{model}）...", flush=True)
    resp = _requests.post(url, json=body, headers=_get_headers(), timeout=600, proxies=_get_proxies())
    data = resp.json()

    img_url, b64_out = _resolve_image_url(data)
    if not img_url and not b64_out:
        print(f"[xinchengpt chat] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    img_bytes = _download_image(img_url, b64_out)
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        print(f"[xinchengpt chat] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    return img_bytes


def main():
    parser = argparse.ArgumentParser(description="XinchenGPT Images API CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="文生图")
    p_gen.add_argument("prompt", help="文生图描述")
    p_gen.add_argument("-o", "--output", required=True, help="输出路径")

    p_edit = sub.add_parser("edit", help="图编")
    p_edit.add_argument("image", help="输入图片路径")
    p_edit.add_argument("prompt", help="编辑指令")
    p_edit.add_argument("-o", "--output", required=True, help="输出路径")

    p_chat = sub.add_parser("chat", help="多模态图编")
    p_chat.add_argument("images", nargs="+", help="输入图片路径（可多张）")
    p_chat.add_argument("-p", "--prompt", required=True, help="合成指令")
    p_chat.add_argument("-o", "--output", required=True, help="输出路径")

    args = parser.parse_args()
    if args.command == "generate":
        generate_image(args.prompt, args.output)
    elif args.command == "edit":
        edit_image(args.image, args.prompt, args.output)
    elif args.command == "chat":
        chat_completions_image(args.images, args.prompt, args.output)


if __name__ == "__main__":
    main()
