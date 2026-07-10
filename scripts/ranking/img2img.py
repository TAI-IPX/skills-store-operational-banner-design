#!/usr/bin/env python3
"""
图生图：将参考素材发给 gpt-image-2，基于参考风格生成新奖牌图
"""
import os
import sys
import json
import base64
import argparse
import requests
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
_RANKING_ASSETS = _SCRIPT_DIR.parent / "assets" / "ranking"

API_KEY = os.environ.get("XINCHENGPT_API_KEY") or os.environ.get(
    "XINGCHENGGPT_API_KEY") or os.environ.get("API_KEY", "")
API_BASE = os.environ.get("XINCHENGPT_BASE_URL") or os.environ.get(
    "XINGCHENGGPT_BASE_URL") or "https://api.centos.hk/v1"


# ── 生图 Prompt ──
PROMPTS = {
    "wheat_gold": (
        "Based on the reference image style, generate a new circular golden medal badge icon "
        "with wheat ear wreath. Keep the same wheat ear pattern and lotus-like top decoration, "
        "but use richer metallic gold gradient with highlight shine. "
        "Centered on pure transparent background, 1024x1024, high quality PNG"
    ),
    "wheat_silver": (
        "Based on the reference image style, generate a circular silver medal badge icon "
        "with wheat ear wreath. Use cool silver-blue metallic gradient instead of gold, "
        "keep the wheat ear wreath motif. Centered on pure transparent background"
    ),
    "wheat_bronze": (
        "Based on the reference image style, generate a circular bronze medal badge icon "
        "with wheat ear wreath. Use warm copper-bronze metallic gradient instead of gold, "
        "keep the wheat ear wreath motif. Centered on pure transparent background"
    ),
}


def generate_i2i(ref_path: str, prompt: str, output_path: Path):
    img_bytes = Path(ref_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()
    suffix = Path(ref_path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    mime = mime_map.get(suffix, "image/png")

    body = {
        "model": "gpt-image-2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                ],
            }
        ],
    }

    resp = requests.post(
        f"{API_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=180,
    )

    if resp.status_code != 200:
        print(f"ERROR HTTP {resp.status_code}: {resp.text[:500]}")
        return False

    content = resp.json()["choices"][0]["message"]["content"]

    if "![" in content and "](" in content:
        import re
        match = re.search(r"!\[.*?\]\((.*?)\)", content)
        if match:
            data_url = match.group(1)
        else:
            print("No image found in response")
            return False
    else:
        data_url = content.strip()

    if data_url.startswith("data:image"):
        _, encoded = data_url.split(",", 1)
        img_data = base64.b64decode(encoded)
    elif data_url.startswith("http"):
        img_data = requests.get(data_url, timeout=60).content
    else:
        print(f"Unknown format: {data_url[:100]}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(img_data)
    print(f"OK -> {output_path} ({len(img_data) // 1024} KB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="图生图生成奖牌")
    parser.add_argument("--ref", required=True, help="参考素材路径")
    parser.add_argument("--style", default="wheat", choices=["wheat"], help="风格")
    parser.add_argument("--tier", default="gold", choices=["gold", "silver", "bronze"], help="等级")
    parser.add_argument("--output", default=None, help="输出路径")
    args = parser.parse_args()

    key = f"{args.style}_{args.tier}"
    if key not in PROMPTS:
        print(f"Unknown prompt key: {key}")
        sys.exit(1)

    out = Path(args.output) if args.output else _RANKING_ASSETS / "medals" / f"{args.style}_{args.tier}.png"
    generate_i2i(args.ref, PROMPTS[key], out)


if __name__ == "__main__":
    main()
