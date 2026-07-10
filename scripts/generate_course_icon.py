#!/usr/bin/env python3
"""
生成课程3D图标 - 即梦文生图
"""
import sys
from pathlib import Path

# 项目根目录（scripts/ 的上一级）
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).parent))
from jimeng_volc_api import t2i


def main():
    prompt = """课程3D图标，卡通3D风格，立体，等距视图，轴测图，质感圆润，果冻质感，
一本橙色渐变竖立的的书，上面有一个斜着放了一个青绿色渐变的铅笔，铅笔圆润饱满的，
有个黄色的书签，书脊成透明磨砂质感，封面有一个黄色圆角矩形凸起，用鲜艳的颜色，
带有柔和的渐变和微妙的高光，背景为纯白色，现代且俏皮的设计，没有明显的阴影，
适合应用界面，简约简单，干净简洁，无文字"""

    output_path = str(_SCRIPT_ROOT / "output/course_icon_3d.png")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"正在生成课程3D图标...")
    print(f"Prompt: {prompt}")

    success = t2i(prompt, output_path, width=1024, height=1024)

    if success:
        print(f"✓ 已保存到: {Path(output_path).resolve()}")
    else:
        print("✗ 生成失败")
        sys.exit(1)


if __name__ == "__main__":
    main()