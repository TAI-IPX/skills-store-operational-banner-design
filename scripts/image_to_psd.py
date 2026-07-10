#!/usr/bin/env python3
"""
图片转 PSD（多图层拆分）
使用 micugpt2 (gpt-image-2) Vision 识别图中各元素，
逐一提取为透明背景图层，最终组装为 PSD 文件。

用法:
    py scripts/image_to_psd.py [输入图片路径] [-o output/result.psd]
    py scripts/image_to_psd.py  # 默认读取 input/uploads/current.png
"""
import os
import sys
import json
import re
import base64
import time
import argparse
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _env import load_env, ROOT

load_env()

from PIL import Image
import requests


MICUAPI_URL = "https://www.micuapi.ai/v1/chat/completions"


def _get_proxy():
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
        return {"https": _sys_proxy, "http": _sys_proxy}
    return None


def _encode_image(image_path: str, max_dim: int = 1536) -> tuple[str, tuple[int, int]]:
    im = Image.open(image_path)
    im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
    orig_size = im.size
    w, h = im.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return b64, orig_size


def _micugpt2_headers():
    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key or not api_key.startswith("sk-"):
        print("[错误] MICUAPI_API_KEY 未设置或格式不正确", file=sys.stderr)
        sys.exit(1)
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }


def vision_analyze(image_path: str) -> list[str]:
    print("[1/3] 使用 micugpt2 Vision 分析图片中的元素...", flush=True)
    b64, size = _encode_image(image_path, max_dim=1024)
    print(f"  图片尺寸: {size[0]}×{size[1]}", flush=True)

    question = """请分析这张图片，列出8-12个可以作为独立图层分离的主要视觉元素。
要求：
1. 只列出主要的、可明确区分的大元素（不要拆分到像素级细节）
2. 合并相似/相近的小元素为一组（如"所有漂浮图标"、"所有文字"）
3. 每个元素用简短中文描述（不超过15字）
4. 按从底层到顶层的顺序排列（背景在最前）
5. 最多不超过12个，最少不少于5个
6. 只输出编号列表，不要其他解释

格式示例：
1. 整体背景（含远景建筑）
2. 中景平台结构
3. 左侧笔记本电脑
4. 中间人物角色
5. 右侧设备
6. 前景物体
7. 漂浮的图标和卡片
8. UI界面元素
9. 光效和粒子
10. 文字和标题"""

    body = json.dumps({
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    }).encode("utf-8")

    proxies = _get_proxy()
    resp = requests.post(MICUAPI_URL, data=body, headers=_micugpt2_headers(), timeout=300, proxies=proxies)
    resp.raise_for_status()
    data = resp.json()

    content = ""
    for choice in data.get("choices", []):
        msg = choice.get("message", {})
        ct = msg.get("content", "")
        if isinstance(ct, str):
            content = ct
            break
        elif isinstance(ct, list):
            content = "".join(p.get("text", "") for p in ct if p.get("type") == "text")
            break

    if not content:
        print(f"[错误] Vision 无返回: {json.dumps(data, ensure_ascii=False)[:300]}", file=sys.stderr)
        sys.exit(1)

    print(f"  识别结果:\n{content}\n", flush=True)

    layers = []
    for line in content.strip().split("\n"):
        line = line.strip()
        m = re.match(r'^\d+[\.\)、]\s*(.+)$', line)
        if m:
            layers.append(m.group(1).strip())

    if not layers:
        layers = [l.strip() for l in content.strip().split("\n") if l.strip()]

    if len(layers) > 15:
        print(f"  识别了 {len(layers)} 个元素，截取前 15 个主要图层", flush=True)
        layers = layers[:15]

    print(f"  共 {len(layers)} 个图层元素", flush=True)
    return layers


def extract_layer(image_path: str, layer_name: str, layer_idx: int, output_dir: Path, max_retries: int = 3) -> Path | None:
    print(f"  [{layer_idx}] 提取: {layer_name}...", flush=True)
    b64, size = _encode_image(image_path, max_dim=768)

    prompt = (
        f"Edit this image: Keep ONLY the '{layer_name}' element visible. "
        f"Remove everything else and make those areas completely transparent (alpha=0). "
        f"The output must be a PNG with transparent background, showing only the '{layer_name}'. "
        f"Do not add, modify or reposition the element - keep it in its exact original position and appearance."
    )

    body = json.dumps({
        "model": "gpt-image-2",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    }).encode("utf-8")

    proxies = _get_proxy()
    data = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(MICUAPI_URL, data=body, headers=_micugpt2_headers(), timeout=600, proxies=None)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            wait = (attempt + 1) * 15
            print(f"    [重试 {attempt+1}/{max_retries}] {e} — 等待 {wait}s", file=sys.stderr, flush=True)
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                print(f"    [失败] 所有重试均失败", file=sys.stderr)
                return None

    if data is None:
        return None

    img_url = ""
    for choice in data.get("choices", []):
        ct = choice.get("message", {}).get("content", "")
        if isinstance(ct, str):
            m = re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', ct)
            if m:
                img_url = m.group(1)
                break

    if not img_url:
        print(f"    [警告] 无图片URL返回: {json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr)
        return None

    dl_content = None
    for dl_attempt in range(3):
        try:
            dl = requests.get(img_url, timeout=300, proxies=proxies, stream=False)
            dl.raise_for_status()
            dl_content = dl.content
            break
        except Exception as dl_e:
            print(f"    [下载重试 {dl_attempt+1}/3] {dl_e}", file=sys.stderr, flush=True)
            if dl_attempt < 2:
                time.sleep(10)
    if dl_content is None:
        print(f"    [失败] 图片下载失败", file=sys.stderr)
        return None

    out_path = output_dir / f"layer_{layer_idx:02d}_{layer_name[:10].replace(' ', '_')}.png"
    out_path.write_bytes(dl_content)

    im = Image.open(out_path)
    im = im.convert("RGBA")
    im = im.resize(size, Image.Resampling.LANCZOS)
    im.save(out_path, format="PNG")

    print(f"    已保存: {out_path.name} ({im.size[0]}×{im.size[1]})", flush=True)
    return out_path


def build_psd(layer_paths: list[tuple[str, Path]], orig_size: tuple[int, int], output_path: Path):
    print(f"\n[3/3] 组装 PSD 文件 ({orig_size[0]}×{orig_size[1]})...", flush=True)
    from psd_tools import PSDImage

    psd = PSDImage.new("RGBA", orig_size)

    for idx, (name, path) in enumerate(reversed(layer_paths)):
        if path is None or not path.is_file():
            continue
        im = Image.open(path).convert("RGBA")
        if im.size != orig_size:
            im = im.resize(orig_size, Image.Resampling.LANCZOS)
        layer_label = f"Layer{idx+1}" if not name.isascii() else name
        psd.create_pixel_layer(im, name=layer_label)
        print(f"  + 图层: {layer_label} ({name})", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    psd.save(str(output_path))
    print(f"\n✅ PSD 已保存: {output_path}", flush=True)
    print(f"   共 {len([p for _, p in layer_paths if p])} 个图层", flush=True)


def main():
    parser = argparse.ArgumentParser(description="图片转多图层 PSD")
    parser.add_argument("input", nargs="?", default=str(ROOT / "input" / "uploads" / "current.png"))
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"[错误] 输入文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    ts = time.strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "output" / f"psd_layers_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        psd_path = Path(args.output)
    else:
        psd_path = output_dir / "result.psd"

    im = Image.open(input_path)
    orig_size = im.size
    print(f"输入: {input_path} ({orig_size[0]}×{orig_size[1]})\n", flush=True)

    layers = vision_analyze(str(input_path))

    print(f"\n[2/3] 逐一提取 {len(layers)} 个图层...\n", flush=True)
    extracted = []
    for idx, layer_name in enumerate(layers, 1):
        path = extract_layer(str(input_path), layer_name, idx, output_dir)
        extracted.append((layer_name, path))
        if idx < len(layers):
            time.sleep(5)

    successful = [(n, p) for n, p in extracted if p is not None]
    if not successful:
        print("[错误] 所有图层提取失败", file=sys.stderr)
        sys.exit(1)

    build_psd(successful, orig_size, psd_path)
    print(f"\n图层 PNG 文件保存在: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
