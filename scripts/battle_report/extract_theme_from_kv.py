#!/usr/bin/env python3
"""
从战报 hero_kv 提取 theme Token，写入 scripts/assets/battle-report/themes/{theme_id}.json。

用法:
  python scripts/battle_report/extract_theme_from_kv.py path/to/hero_kv.png
  python scripts/battle_report/extract_theme_from_kv.py kv.png --theme-id nte_lenovo --write
  python scripts/battle_report/extract_theme_from_kv.py kv.png --preview output/battle-report/palette.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.battle_report.color_extract import (  # noqa: E402
    build_theme_json,
    write_palette_preview,
    save_theme,
)

DEFAULT_THEMES_DIR = _PROJECT_ROOT / "scripts" / "assets" / "battle-report" / "themes"


def main() -> int:
    parser = argparse.ArgumentParser(description="从 KV 提取战报 theme 色板")
    parser.add_argument("kv", type=Path, help="hero_kv 图片路径")
    parser.add_argument(
        "--theme-id",
        default=None,
        help="主题 ID（默认：kv 文件名去掉扩展名）",
    )
    parser.add_argument(
        "--style-id",
        default=None,
        help="关联 style_profile ID（默认同 theme-id）",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help=f"输出 JSON（默认：{DEFAULT_THEMES_DIR}/<theme_id>.json）",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="写入 JSON 文件（未指定时仅打印到 stdout）",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="输出色板预览 PNG",
    )
    parser.add_argument(
        "--sample-max-side",
        type=int,
        default=480,
        help="取样时缩略图最长边（默认 480）",
    )
    parser.add_argument(
        "--hero-top-ratio",
        type=float,
        default=0.55,
        help="强调色仅从头图顶部该区域取样（默认 0.55）",
    )
    args = parser.parse_args()

    kv_path = args.kv.expanduser().resolve()
    if not kv_path.is_file():
        print(f"Error: KV 不存在: {kv_path}", file=sys.stderr)
        return 1

    theme_id = args.theme_id or kv_path.stem
    from scripts.battle_report.color_extract import ExtractConfig  # noqa: E402

    cfg = ExtractConfig(
        sample_max_side=args.sample_max_side,
        hero_top_ratio=args.hero_top_ratio,
    )
    theme = build_theme_json(kv_path, theme_id, args.style_id, cfg)

    out_path = args.output or (DEFAULT_THEMES_DIR / f"{theme_id}.json")
    preview_path = args.preview or (
        _PROJECT_ROOT / "output" / "battle-report" / f"palette_{theme_id}.png"
    )

    text = json.dumps(
        {k: v for k, v in theme.items() if k != "extract_meta"},
        ensure_ascii=False,
        indent=2,
    )
    print(text)
    if theme.get("extract_meta"):
        print("\n# accent_candidates / dark_candidates（调试用）:", file=sys.stderr)
        print(json.dumps(theme["extract_meta"], ensure_ascii=False, indent=2), file=sys.stderr)

    if args.write or args.output:
        save_theme(theme, out_path)
        print(f"\nWrote theme: {out_path}", file=sys.stderr)

    if args.preview or args.write:
        write_palette_preview(theme, preview_path)
        print(f"Wrote preview: {preview_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
