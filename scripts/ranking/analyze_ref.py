#!/usr/bin/env python3
"""
分析参考素材图片  调用 vision API 获取视觉描述
用法: py scripts/ranking/analyze_ref.py <image_path>
"""
import os
import sys
import json
import base64
import requests
from pathlib import Path

API_KEY = os.environ.get("XINCHENGPT_API_KEY") or os.environ.get(
    "XINGCHENGGPT_API_KEY") or os.environ.get("API_KEY", "")
API_BASE = os.environ.get("XINCHENGPT_BASE_URL") or os.environ.get(
    "XINGCHENGGPT_BASE_URL") or "https://api.centos.hk/v1"


def analyze_image(image_path: str, instruction: str = None) -> str:
    img_bytes = Path(image_path).read_bytes()
    suffix = Path(image_path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    mime = mime_map.get(suffix, "image/png")

    b64 = base64.b64encode(img_bytes).decode()
    data_url = f"data:{mime};base64,{b64}"

    if instruction is None:
        instruction = (
            "请详细描述这张图片的视觉特征，用于写 AI 生图 prompt。包括：\n"
            "1. 形状（圆形/六边形/盾形等）\n"
            "2. 颜色和材质（金属感/渐变/扁平矢量等）\n"
            "3. 装饰元素（边框花纹/翅膀/星星/丝带/麦穗等）\n"
            "4. 整体风格（卡通/矢量扁平/3D立体/手绘等）\n"
            "5. 背景情况（透明底/有色底）\n"
            "请用中文回答，简洁准确。"
        )

    body = {
        "model": "gpt-image-2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }
        ],
        "max_tokens": 800,
    }

    resp = requests.post(
        f"{API_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=120,
    )

    if resp.status_code != 200:
        print(f"ERROR HTTP {resp.status_code}: {resp.text[:500]}")
        sys.exit(1)

    content = resp.json()["choices"][0]["message"]["content"]
    return content


def main():
    if len(sys.argv) < 2:
        print("Usage: py scripts/ranking/analyze_ref.py <image_path>")
        sys.exit(1)

    img_path = sys.argv[1]
    print(f"Analyzing: {img_path}\n")
    desc = analyze_image(img_path)
    print("=" * 60)
    print(desc)
    print("=" * 60)


if __name__ == "__main__":
    main()
