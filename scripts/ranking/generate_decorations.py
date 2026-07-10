#!/usr/bin/env python3
"""
生成排行榜装饰素材：奖牌/徽章
基于 sucai/ 参考素材风格反推提示词，调用 xinchengpt API 生成

用法:
  py scripts/ranking/generate_decorations.py              # 生成全部
  py scripts/ranking/generate_decorations.py --style wheat  # 只生成麦穗风
  py scripts/ranking/generate_decorations.py --tier gold    # 只生成金色
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


def _load_config():
    api_key = os.environ.get("XINCHENGPT_API_KEY") or os.environ.get(
        "XINGCHENGGPT_API_KEY") or os.environ.get("API_KEY", "")
    api_base = os.environ.get("XINCHENGPT_BASE_URL") or os.environ.get(
        "XINGCHENGGPT_BASE_URL") or "https://api.centos.hk/v1"
    return {
        "api_key": api_key,
        "api_base": api_base,
        "api_model": "gpt-image-2",
        "size": os.environ.get("XINCHENGPT_SIZE", "auto"),
        "quality": os.environ.get("XINCHENGPT_QUALITY", "auto"),
    }


# ── 风格A：麦穗奖章 ──
PROMPTS_WHEAT = {
    "gold": (
        "A single circular golden medal badge icon, wheat ear wreath framing left and right sides, "
        "shiny metallic gold gradient with bright highlights, dark golden brown ribbon at bottom, "
        "vector illustration style with clean sharp edges, game achievement emblem, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
    "silver": (
        "A single circular silver medal badge icon, wheat ear wreath framing left and right sides, "
        "cool silver-blue metallic gradient #b0b8c8 with bright silver highlights, dark navy ribbon at bottom, "
        "vector illustration style with clean sharp edges, game achievement emblem, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
    "bronze": (
        "A single circular bronze medal badge icon, wheat ear wreath framing left and right sides, "
        "warm bronze copper metallic gradient with orange highlights, dark brown ribbon at bottom, "
        "vector illustration style with clean sharp edges, game achievement emblem, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
}

# ── 风格B：翅膀徽章 ──
PROMPTS_WINGS = {
    "gold": (
        "Hexagon shaped golden achievement badge with angel wings on both sides, "
        "cartoon game style, golden border with small star decorations, "
        "vibrant colorful premium gaming award emblem, "
        "clean center area, transparent background, centered icon, high quality PNG"
    ),
    "silver": (
        "Hexagon shaped silver achievement badge with angel wings on both sides, "
        "cartoon game style, silver metallic border with star decorations, "
        "premium gaming award emblem with cool blue accents, "
        "clean center area, transparent background, centered icon, high quality PNG"
    ),
    "bronze": (
        "Hexagon shaped bronze achievement badge with angel wings on both sides, "
        "cartoon game style, bronze copper border with star decorations, "
        "premium gaming award emblem with warm orange accents, "
        "clean center area, transparent background, centered icon, high quality PNG"
    ),
}

# ── 风格C：等级徽章 ──
PROMPTS_TIER = {
    "gold": (
        "A single shield-shaped golden tier badge, metallic gold gradient body with ornate border, "
        "glossy highlight shine, small star or diamond gem decorations on the frame, "
        "premium game rank insignia style, clean design, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
    "silver": (
        "A single shield-shaped silver tier badge, cool silver-blue metallic gradient #b0b8c8 body with ornate border, "
        "glossy highlight shine, small star or gem decorations on the frame, "
        "premium game rank insignia style, clean design, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
    "bronze": (
        "A single shield-shaped bronze tier badge, warm copper bronze metallic gradient body with ornate border, "
        "glossy highlight shine, small star or gem decorations on the frame, "
        "premium game rank insignia style, clean design, "
        "centered on pure transparent background, game UI element, 1024x1024, high quality"
    ),
}

# ── 风格D：手绘徽章 ──
PROMPTS_DOODLE = {
    "gold": (
        "Hand-drawn sketch style gold medal badge sticker, "
        "rough artistic brush strokes, casual playful doodle aesthetic, "
        "warm golden yellow and brown tones, game achievement emblem, "
        "sketchy outline, transparent background, centered, high quality PNG"
    ),
    "silver": (
        "Hand-drawn sketch style silver medal badge sticker, "
        "rough artistic brush strokes, casual playful doodle aesthetic, "
        "cool silver gray and blue tones, game achievement emblem, "
        "sketchy outline, transparent background, centered, high quality PNG"
    ),
    "bronze": (
        "Hand-drawn sketch style bronze medal badge sticker, "
        "rough artistic brush strokes, casual playful doodle aesthetic, "
        "warm copper orange and brown tones, game achievement emblem, "
        "sketchy outline, transparent background, centered, high quality PNG"
    ),
}

PROMPT_CORNER_BADGE = (
    "Small square decorative badge icon for UI corner ornament, "
    "golden metallic gradient with subtle shine, minimalist geometric shape, "
    "game UI decoration element, clean edges, transparent background, "
    "centered small icon, 256x256, high quality PNG"
)

PROMPT_RANK_BADGE = (
    "Small circular rank number badge icon, golden metallic ring with laurel wreath, "
    "dark center area for number placement, game UI rank indicator, "
    "elegant premium competitive gaming style, transparent background, "
    "centered small icon, 256x256, high quality PNG"
)

ALL_PROMPTS = {
    "wheat": PROMPTS_WHEAT,
    "wings": PROMPTS_WINGS,
    "tier": PROMPTS_TIER,
    "doodle": PROMPTS_DOODLE,
}


def generate_image(config, prompt, output_path: Path):
    body = {
        "model": config["api_model"],
        "prompt": prompt,
        "n": 1,
        "size": config["size"],
        "quality": config["quality"],
    }

    print(f"  Prompt: {prompt[:100]}...")
    resp = requests.post(
        f"{config['api_base']}/images/generations",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=180,
    )

    if resp.status_code != 200:
        print(f"  ERROR HTTP {resp.status_code}: {resp.text[:300]}")
        return False

    item = resp.json()["data"][0]

    if "b64_json" in item:
        img_bytes = base64.b64decode(item["b64_json"])
    elif "url" in item:
        img_bytes = requests.get(item["url"], timeout=60).content
    else:
        print(f"  ERROR: unknown response format, keys={list(item.keys())}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(img_bytes)
    print(f"  OK -> {output_path} ({len(img_bytes) // 1024} KB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate decoration images")
    parser.add_argument("--style", choices=["wheat", "wings", "tier", "doodle"], help="只生成指定风格")
    parser.add_argument("--tier", choices=["gold", "silver", "bronze"], help="只生成指定等级")
    parser.add_argument("--extras", action="store_true", help="也生成角落装饰和排名徽章")
    args = parser.parse_args()

    config = _load_config()
    if not config["api_key"]:
        print("ERROR: XINCHENGPT_API_KEY not set in .env")
        sys.exit(1)

    out_dir = _RANKING_ASSETS / "medals"
    out_dir.mkdir(parents=True, exist_ok=True)

    styles = [args.style] if args.style else list(ALL_PROMPTS.keys())
    tiers = [args.tier] if args.tier else ["gold", "silver", "bronze"]

    print(f"API Base: {config['api_base']}")
    print(f"Model: {config['api_model']}")
    print(f"Output: {out_dir}")
    print(f"Styles: {styles}, Tiers: {tiers}\n")

    for style in styles:
        prompts = ALL_PROMPTS[style]
        for tier in tiers:
            if tier not in prompts:
                continue
            print(f"[{style}/{tier}]")
            filename = f"{style}_{tier}.png"
            if (out_dir / filename).exists():
                print(f"  SKIP  already exists: {out_dir / filename}")
                continue
            generate_image(config, prompts[tier], out_dir / filename)
            print()

    if args.extras:
        extras = [
            ("corner_badge", PROMPT_CORNER_BADGE, "corner_badge.png"),
            ("rank_badge", PROMPT_RANK_BADGE, "rank_badge.png"),
        ]
        for label, prompt, fname in extras:
            print(f"[extras/{label}]")
            target = out_dir / fname
            if target.exists():
                print(f"  SKIP  already exists: {target}")
                continue
            generate_image(config, prompt, target)
            print()

    print("Done.")


if __name__ == "__main__":
    main()
