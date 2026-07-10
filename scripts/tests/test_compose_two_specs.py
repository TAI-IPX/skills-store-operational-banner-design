#!/usr/bin/env python3
"""测试两套规范：生成一张测试背景，分别用 preset default(1976×464) 和 wide(3320×500) 合成并输出。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 生成测试用背景图（1976×464 渐变，compose 会按 cover 缩放到各尺寸）
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow: pip install Pillow", file=sys.stderr)
        sys.exit(1)
    w, h = 1976, 464
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            # 简单渐变便于区分
            r = int(80 + 60 * x / w)
            g = int(100 + 40 * y / h)
            b = 140
            px[x, y] = (r, g, b)
    bg_path = OUTPUT_DIR / "test_background_1976x464.png"
    img.save(str(bg_path))
    print(f"已生成测试背景: {bg_path}")

    sys.path.insert(0, str(COMPOSER_SCRIPTS))
    from compose_banner import compose, _resolve_output_path

    main_title = "办公视觉效率"
    subtitle = "从设计到出图快人一步"

    sizes = [
        ("default", "banner_default_1976x464.png", 1976, 464),
        ("wide", "banner_wide_3320x500.png", 3320, 500),
    ]
    for preset_name, out_name, width, height in sizes:
        out_path = OUTPUT_DIR / out_name
        print(f"合成 preset={preset_name} ({width}×{height}) -> {out_path}")
        compose(str(bg_path), str(out_path), main_title, subtitle, width=width, height=height, use_ai_linebreak=False)
        resolved, _ = _resolve_output_path(str(out_path))
        print(f"  -> {resolved}")

if __name__ == "__main__":
    main()
