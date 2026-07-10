#!/usr/bin/env python3
"""本地测试：黑边检测 + 边缘去黑（不调用 Gemini）。
对 output/step1_prepared_background.png 做检测与去黑，结果写回同路径并生成 test_edge_removed.png。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
sys.path.insert(0, str(SCRIPTS))

def main():
    img_path = ROOT / "output" / "step1_prepared_background.png"
    if not img_path.is_file():
        print(f"未找到 {img_path}，请先运行 run_banner.py 生成 Step 1 结果。")
        return 1

    from gemini_image_edit import image_has_black_bars
    from prepare_background import _remove_edge_black
    import shutil

    print("1) 黑边检测（敏感参数：margin_ratio=0.02, black_ratio=0.03, threshold=50）")
    has_bars = image_has_black_bars(str(img_path))
    print(f"   image_has_black_bars = {has_bars}")

    print("2) 边缘去黑（edge_width=2, threshold=40）")
    backup = ROOT / "output" / "step1_prepared_background_backup.png"
    shutil.copy2(img_path, backup)
    _remove_edge_black(str(img_path), edge_width=2, threshold=40)
    print(f"   已写回: {img_path}")

    print("3) 再次检测")
    has_bars_after = image_has_black_bars(str(img_path))
    print(f"   image_has_black_bars = {has_bars_after}")

    print("4) 备份保留于:", backup)
    print("完成。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
