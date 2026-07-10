#!/usr/bin/env python3
"""
生成日历UI图标 - 即梦文生图
"""
import sys
from pathlib import Path

# 项目根目录（scripts/ 的上一级）
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).parent))
from jimeng_volc_api import t2i


def main():
    prompt = """UI图标，采用卡通3D风格，从斜45度视角俯视，日历图标，绿色外框，中间白色且带勾号，
使用鲜艳的颜色，带有柔和的渐变和微妙的高光，背景为纯白色，现代且俏皮的设计，
适合应用界面，简约简单，干净简洁，无文字，3D立体感，圆润饱满"""

    output_path = str(_SCRIPT_ROOT / "output/calendar_icon_3d.png")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"正在生成日历UI图标...")
    success = t2i(prompt, output_path, width=1024, height=1024)

    if success:
        print(f"✓ 已保存到: {Path(output_path).resolve()}")
    else:
        print("✗ 生成失败")
        sys.exit(1)


if __name__ == "__main__":
    main()