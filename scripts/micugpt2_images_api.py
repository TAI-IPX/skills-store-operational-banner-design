"""
micugpt2_images_api.py — 标准 OpenAI Images API 封装（micuapi.ai）

    三个端点：
  1. generate_image     → POST /v1/images/generations   (JSON body, 单图文生图)
  2. edit_image         → POST /v1/images/edits          (multipart form-data, 支持 mask)
  3. create_variation   → POST /v1/images/variations     (multipart form-data)
  4. chat_completions_image → POST /v1/chat/completions  (JSON body, 多模态多图)

用法：
  from micugpt2_images_api import generate_image, edit_image, create_variation, chat_completions_image

  # 文生图
  generate_image("A cat on the moon", "output/cat.png")

  # 图编（标准 multipart，支持 mask）
  edit_image("input/photo.png", "Remove the background", "output/edited.png")

  # 变体
  create_variation("input/photo.png", "output/variation.png")

  # 多模态多图合成（适用于多角色+参考图的复杂合成场景）
  png_bytes = chat_completions_image(
      ["char1.png", "char2.png", "layout.png"],
      "请按 layout.png 的空间布局将 char1+char2 合成到一张图...",
  )

CLI:
  py scripts/micugpt2_images_api.py generate "A cat" -o output/cat.png
  py scripts/micugpt2_images_api.py edit input/photo.png "Remove bg" -o output/edited.png
  py scripts/micugpt2_images_api.py variation input/photo.png -o output/var.png
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

BASE_URL = "https://www.micuapi.ai/v1"
DEFAULT_MODEL = "gpt-image-2"


def _get_api_key() -> str:
    key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not key or not key.startswith("sk-"):
        raise RuntimeError(
            "MICUAPI_API_KEY 未设置或格式错误（需 sk- 开头）。"
            "请在 .env 或环境变量中配置。"
        )
    return key


def _get_proxies() -> dict | None:
    no_proxy = os.environ.get("MICUGPT2_NO_PROXY", "").strip()
    if no_proxy.lower() in ("1", "true", "yes"):
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

    if sys_proxy:
        return {"https": sys_proxy, "http": sys_proxy}
    return None


def _download_and_save(url_or_b64: str, output_path: Path, proxies: dict | None, *, is_b64: bool = False) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if is_b64:
        raw = base64.b64decode(url_or_b64)
        output_path.write_bytes(raw)
    else:
        import requests
        resp = requests.get(url_or_b64, timeout=300, proxies=proxies)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    return output_path


def _parse_response(data: dict) -> tuple[str, str]:
    """解析响应，返回 (url, b64_json)，至少一个非空。"""
    items = data.get("data", [])
    if not items:
        return "", ""
    item = items[0]
    return item.get("url", ""), item.get("b64_json", "")


# ─────────────────────────────────────────────
# 1. Generate an Image
# POST /v1/images/generations
# ─────────────────────────────────────────────

def generate_image(
    prompt: str,
    output_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    size: str = "1024x1024",
    quality: str = "high",
    n: int = 1,
    response_format: str = "url",
    background: str | None = None,
    output_format: str | None = None,
    output_compression: int | None = None,
    moderation: str | None = None,
) -> Optional[Path]:
    """
    标准 OpenAI Images Generate API。

    POST /v1/images/generations
    Content-Type: application/json
    """
    import requests

    api_key = _get_api_key()
    proxies = _get_proxies()
    out_path = Path(output_path)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    body: dict = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "size": size,
        "quality": quality,
        "response_format": response_format,
    }
    if background is not None:
        body["background"] = background
    if output_format is not None:
        body["output_format"] = output_format
    if output_compression is not None:
        body["output_compression"] = output_compression
    if moderation is not None:
        body["moderation"] = moderation

    url = f"{BASE_URL}/images/generations"
    print(f"[micugpt2 generate] {size} quality={quality} ...", flush=True)

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=180, proxies=None)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[micugpt2 generate] 请求失败: {e}", file=sys.stderr)
        return None

    img_url, b64_json = _parse_response(data)
    if not img_url and not b64_json:
        print(f"[micugpt2 generate] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    try:
        if b64_json:
            _download_and_save(b64_json, out_path, proxies, is_b64=True)
        else:
            _download_and_save(img_url, out_path, proxies)
        print(f"[micugpt2 generate] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    except Exception as e:
        print(f"[micugpt2 generate] 下载/保存失败: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────
# 2. Edit an Image
# POST /v1/images/edits
# ─────────────────────────────────────────────

def edit_image(
    image_path: str | Path,
    prompt: str,
    output_path: str | Path,
    *,
    mask_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    size: str | None = None,
    quality: str = "high",
    n: int = 1,
    response_format: str = "url",
) -> Optional[Path]:
    """
    标准 OpenAI Images Edit API。

    POST /v1/images/edits
    Content-Type: multipart/form-data

    支持 mask（透明区域指示编辑区域）。
    """
    import requests

    api_key = _get_api_key()
    proxies = _get_proxies()
    out_path = Path(output_path)
    img_path = Path(image_path)

    if not img_path.is_file():
        print(f"[micugpt2 edit] 图片不存在: {img_path}", file=sys.stderr)
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    img_bytes = img_path.read_bytes()
    files: list[tuple] = [
        ("image", (img_path.name, img_bytes, "image/png")),
    ]

    if mask_path:
        mask_p = Path(mask_path)
        if mask_p.is_file():
            files.append(("mask", (mask_p.name, mask_p.read_bytes(), "image/png")))

    form_data: dict = {
        "model": model,
        "prompt": prompt,
        "n": str(n),
        "quality": quality,
        "response_format": response_format,
    }
    if size is not None:
        form_data["size"] = size

    url = f"{BASE_URL}/images/edits"
    print(f"[micugpt2 edit] 编辑中...", flush=True)

    try:
        resp = requests.post(url, data=form_data, files=files, headers=headers, timeout=600, proxies=None)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[micugpt2 edit] 请求失败: {e}", file=sys.stderr)
        return None

    img_url, b64_json = _parse_response(data)
    if not img_url and not b64_json:
        print(f"[micugpt2 edit] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    try:
        if b64_json:
            _download_and_save(b64_json, out_path, proxies, is_b64=True)
        else:
            _download_and_save(img_url, out_path, proxies)
        print(f"[micugpt2 edit] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    except Exception as e:
        print(f"[micugpt2 edit] 下载/保存失败: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────
# 3. Create Image Variation
# POST /v1/images/variations
# ─────────────────────────────────────────────

def create_variation(
    image_path: str | Path,
    output_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    size: str | None = None,
    n: int = 1,
    response_format: str = "url",
) -> Optional[Path]:
    """
    标准 OpenAI Images Variations API。

    POST /v1/images/variations
    Content-Type: multipart/form-data
    """
    import requests

    api_key = _get_api_key()
    proxies = _get_proxies()
    out_path = Path(output_path)
    img_path = Path(image_path)

    if not img_path.is_file():
        print(f"[micugpt2 variation] 图片不存在: {img_path}", file=sys.stderr)
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    img_bytes = img_path.read_bytes()
    files = [
        ("image", (img_path.name, img_bytes, "image/png")),
    ]

    form_data: dict = {
        "model": model,
        "n": str(n),
        "response_format": response_format,
    }
    if size is not None:
        form_data["size"] = size

    url = f"{BASE_URL}/images/variations"
    print(f"[micugpt2 variation] 生成变体...", flush=True)

    try:
        resp = requests.post(url, data=form_data, files=files, headers=headers, timeout=300, proxies=None)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[micugpt2 variation] 请求失败: {e}", file=sys.stderr)
        return None

    img_url, b64_json = _parse_response(data)
    if not img_url and not b64_json:
        print(f"[micugpt2 variation] 未获取到图片。响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
        return None

    try:
        if b64_json:
            _download_and_save(b64_json, out_path, proxies, is_b64=True)
        else:
            _download_and_save(img_url, out_path, proxies)
        print(f"[micugpt2 variation] 已保存: {out_path}", flush=True)
        return out_path.resolve()
    except Exception as e:
        print(f"[micugpt2 variation] 下载/保存失败: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────
# 4. Multi-modal Chat Completion（多图合成 / 视觉理解）
# POST /v1/chat/completions
# ─────────────────────────────────────────────

_MD_IMG_PATTERN = re.compile(r'!\[.*?\]\((https?://[^\s)]+)\)')


def chat_completions_image(
    image_paths: list[str | Path],
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = 300,
    max_retries: int = 3,
    max_dim: int = 1536,
    proxy_override: dict | None | str = "auto",
) -> bytes | None:
    """
    micuapi.ai /v1/chat/completions 多模态调用（图生图/视觉理解）。

    把多张本地图片 + 文本 prompt 发给 gpt-image-2 多模态模型，
    从响应中提取 Markdown 图片语法 ![](url) 并下载图片 bytes 返回。

    POST /v1/chat/completions
    Content-Type: application/json

    与 edit_image 的区别：
      - edit_image 用 multipart /v1/images/edits（OpenAI Images Edit 标准接口，支持 mask）
      - chat_completions_image 用 JSON /v1/chat/completions（多模态对话接口，不支持 mask）
      - 前者适合"基于单图精确编辑（可用 mask 保护主体）"；后者适合"多图参考 + 自由合成"。

    参数：
      image_paths: 输入图片路径列表（PNG/JPG），最多 4 张
      prompt: 文本指令
      model: 默认 gpt-image-2
      timeout: 单次请求超时（秒）
      max_retries: 失败重试次数（默认 3）
      max_dim: 上传前最大边（>max_dim 会被缩放，默认 1536）
      proxy_override: 代理覆盖：
        - "auto"（默认）：自动检测（系统代理→MICUGPT2_NO_PROXY）
        - None：强制直连
        - dict：自定义 proxies

    返回：图片 PNG bytes；失败返回 None。
    """
    import requests

    api_key = _get_api_key()
    if proxy_override == "auto":
        proxies = _get_proxies()
    elif proxy_override is None:
        proxies = None
    else:
        proxies = proxy_override

    if not image_paths:
        print("[micugpt2 chat] image_paths 为空", file=sys.stderr)
        return None

    content_blocks: list[dict] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        img_p = Path(p)
        if not img_p.is_file():
            print(f"[micugpt2 chat] 图片不存在: {img_p}", file=sys.stderr)
            return None
        im = _PILImage.open(img_p)
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
        w, h = im.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        buf = BytesIO()
        im.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content_blocks}],
    }

    url = f"{BASE_URL}/chat/completions"
    last_err: str = ""
    for attempt in range(1, max_retries + 1):
        try:
            print(
                f"[micugpt2 chat] 尝试 {attempt}/{max_retries}（{len(image_paths)} 图, timeout={timeout}s）",
                flush=True,
            )
            resp = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=timeout,
                proxies=None,
            )
            resp.raise_for_status()
            data = resp.json()
            for choice in data.get("choices", []):
                ct = choice.get("message", {}).get("content", "")
                if not isinstance(ct, str):
                    continue
                m = _MD_IMG_PATTERN.search(ct)
                if m:
                    img_url = m.group(1)
                    print(f"[micugpt2 chat] 提取到图片URL: {img_url[:80]}...", flush=True)
                    img_resp = requests.get(img_url, timeout=300, proxies=proxies)
                    img_resp.raise_for_status()
                    return img_resp.content
            last_err = "响应中无图片（Markdown语法）"
            print(f"  {last_err}", file=sys.stderr)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  chat 尝试 {attempt}/{max_retries} 失败: {last_err}", file=sys.stderr)
        if attempt < max_retries:
            time.sleep(3)
    print(f"[micugpt2 chat] 全部 {max_retries} 次失败: {last_err}", file=sys.stderr)
    return None


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(
        description="micugpt2 标准 OpenAI Images API (generate / edit / variation)"
    )
    sub = parser.add_subparsers(dest="command")

    # generate
    p_gen = sub.add_parser("generate", help="文生图 /v1/images/generations")
    p_gen.add_argument("prompt", help="生图描述")
    p_gen.add_argument("-o", "--output", default="output/micugpt2_generate.png")
    p_gen.add_argument("--size", default="1024x1024")
    p_gen.add_argument("--quality", default="high", choices=["auto", "high", "medium", "low"])
    p_gen.add_argument("--model", default=DEFAULT_MODEL)
    p_gen.add_argument("--background", choices=["auto", "transparent", "opaque"])
    p_gen.add_argument("--output-format", choices=["png", "jpeg", "webp"])
    p_gen.add_argument("--b64", action="store_true", help="使用 b64_json 响应格式")

    # edit
    p_edit = sub.add_parser("edit", help="图编 /v1/images/edits")
    p_edit.add_argument("image", help="输入图片路径")
    p_edit.add_argument("prompt", help="编辑指令")
    p_edit.add_argument("-o", "--output", default="output/micugpt2_edit.png")
    p_edit.add_argument("--mask", help="蒙版图片路径（透明区域为编辑区）")
    p_edit.add_argument("--size")
    p_edit.add_argument("--quality", default="high", choices=["auto", "high", "medium", "low"])
    p_edit.add_argument("--model", default=DEFAULT_MODEL)
    p_edit.add_argument("--b64", action="store_true")

    # variation
    p_var = sub.add_parser("variation", help="图片变体 /v1/images/variations")
    p_var.add_argument("image", help="输入图片路径")
    p_var.add_argument("-o", "--output", default="output/micugpt2_variation.png")
    p_var.add_argument("--size")
    p_var.add_argument("--model", default=DEFAULT_MODEL)
    p_var.add_argument("--b64", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 加载 .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and v and k not in os.environ:
                    os.environ[k] = v

    if args.command == "generate":
        fmt = "b64_json" if args.b64 else "url"
        result = generate_image(
            args.prompt,
            args.output,
            model=args.model,
            size=args.size,
            quality=args.quality,
            response_format=fmt,
            background=args.background,
            output_format=getattr(args, "output_format", None),
        )
        if result:
            print(f"✅ {result}")
        else:
            sys.exit(1)

    elif args.command == "edit":
        fmt = "b64_json" if args.b64 else "url"
        result = edit_image(
            args.image,
            args.prompt,
            args.output,
            mask_path=args.mask,
            model=args.model,
            size=args.size,
            quality=args.quality,
            response_format=fmt,
        )
        if result:
            print(f"✅ {result}")
        else:
            sys.exit(1)

    elif args.command == "variation":
        fmt = "b64_json" if args.b64 else "url"
        result = create_variation(
            args.image,
            args.output,
            model=args.model,
            size=args.size,
            response_format=fmt,
        )
        if result:
            print(f"✅ {result}")
        else:
            sys.exit(1)


if __name__ == "__main__":
    _cli()
