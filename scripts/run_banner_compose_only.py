#!/usr/bin/env python3
"""
仅叠渐变与标题（不跑 prepare_background），用于快速测试已准备好的背景图。

使用方法：
    python run_banner_compose_only.py -i <背景图路径> -m <主标题> -s <副标题>

示例：
    python run_banner_compose_only.py -i output/step1_prepared_background.png -m "主标题" -s "副标题"
"""
import argparse
import sys
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 路径约束验证
from _paths import validate_paths
validate_paths()

COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="仅合成 Banner（不处理背景）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 使用已准备好的背景图
  python run_banner_compose_only.py -i output/step1_prepared_background.png -m "主标题" -s "副标题"

  # 指定输出路径
  python run_banner_compose_only.py -i background.png -m "主标题" -s "副标题" -o output/my_banner.png

  # 自定义尺寸
  python run_banner_compose_only.py -i background.png -m "主标题" -s "副标题" --width 3320 --height 500
        """,
    )

    parser.add_argument(
        "-i",
        "--image",
        required=True,
        help="输入背景图路径（必需）",
    )
    parser.add_argument(
        "-m",
        "--main-title",
        default="开学高能量时刻",
        help="主标题（默认：开学高能量时刻）",
    )
    parser.add_argument(
        "-s",
        "--subtitle",
        default="活力开学季 美味充能时",
        help="副标题（默认：活力开学季 美味充能时）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "output/banner_default_1976x464.png"),
        help="输出路径（默认：output/banner_default_1976x464.png）",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1976,
        help="Banner 宽度（默认：1976）",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=464,
        help="Banner 高度（默认：464）",
    )
    parser.add_argument(
        "--no-ai-linebreak",
        action="store_true",
        help="不使用 AI 智能换行",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # 验证输入文件
    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"❌ 错误：未找到图片 {args.image}", file=sys.stderr)
        print(f"\n请确保图片文件存在，或使用示例：", file=sys.stderr)
        print(
            f"  python run_banner_compose_only.py -i output/step1_prepared_background.png -m '主标题' -s '副标题'",
            file=sys.stderr,
        )
        sys.exit(1)

    # 验证脚本文件
    if not (COMPOSER_SCRIPTS / "compose_banner.py").is_file():
        print(f"❌ 错误：未找到 compose_banner.py 于 {COMPOSER_SCRIPTS}", file=sys.stderr)
        sys.exit(1)

    # 准备输出目录
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"📋 配置信息：")
    print(f"  输入图片：{image_path}")
    print(f"  主标题：{args.main_title}")
    print(f"  副标题：{args.subtitle}")
    print(f"  输出路径：{output_path}")
    print(f"  尺寸：{args.width} × {args.height}")
    print()

    # 合成 Banner
    sys.path.insert(0, str(COMPOSER_SCRIPTS))
    from compose_banner import compose, _resolve_output_path

    print("🔄 Compose: 渐变蒙层 + 主标题 + 副标题...")
    compose(
        str(image_path.resolve()),
        str(output_path),
        args.main_title,
        args.subtitle,
        width=args.width,
        height=args.height,
        use_ai_linebreak=not args.no_ai_linebreak,
    )

    out_path, _ = _resolve_output_path(str(output_path))
    print(f"✅ 完成！输出文件：{out_path}")


if __name__ == "__main__":
    main()
