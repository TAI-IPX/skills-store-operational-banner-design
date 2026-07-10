#!/usr/bin/env python3
"""
Banner 生成主程序：从图片生成带标题的 Banner。
先 prepare_background（主体检测 + 按安全区裁切），再叠渐变与标题。

使用方法：
    python run_banner.py -i <图片路径> -m <主标题> -s <副标题>

示例：
    python run_banner.py -i input/sample.png -m "办公视觉效率" -s "从设计到出图快人一步"
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

# Fix encoding for Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 路径约束验证
from _paths import validate_paths
validate_paths()

from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()

# 从 .env 加载 API 与后端配置（若存在），供子进程与当前进程使用；勿提交 .env
from _env import load_env
_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY",
    "PACKY7S_API_KEY",
    "PACKYGPT_API_KEY",
    "T8STAR_API_KEY",
    "BANNER_IMAGE_BACKEND",
    "T8STAR_IMAGE_MODEL",
    "T8STAR_BASE_URL",
)
load_env(_ENV_KEYS)

COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"
PREPARE_SCRIPT = (
    ROOT
    / ".claude"
    / "skills"
    / "banner-background-from-image"
    / "scripts"
    / "prepare_background.py"
)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="生成 Banner 图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 基本使用
  python run_banner.py -i input/sample.png -m "主标题" -s "副标题"

  # 指定输出路径
  python run_banner.py -i input/sample.png -m "主标题" -s "副标题" -o output/my_banner.png

  # 使用 Packy API
  python run_banner.py -i input/sample.png -m "主标题" -s "副标题" --packy

  # 自定义尺寸
  python run_banner.py -i input/sample.png -m "主标题" -s "副标题" --width 3320 --height 500
        """,
    )

    parser.add_argument(
        "-i",
        "--image",
        required=True,
        help="输入图片路径（必需）",
    )
    parser.add_argument(
        "-m",
        "--main-title",
        default="办公视觉效率",
        help="主标题（默认：办公视觉效率）",
    )
    parser.add_argument(
        "-s",
        "--subtitle",
        default="从设计到出图快人一步",
        help="副标题（默认：从设计到出图快人一步）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "output/banner.png"),
        help="输出路径（默认：output/banner.png）",
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
        "--preset",
        default="default",
        choices=["default", "wide", "strip"],
        help="预设尺寸（默认：default）",
    )
    parser.add_argument(
        "--no-remove-text",
        action="store_true",
        help="不去除图片中的文字",
    )
    parser.add_argument(
        "--no-ai-linebreak",
        action="store_true",
        help="不使用 AI 智能换行",
    )
    parser.add_argument(
        "--packy",
        action="store_true",
        help="使用 Packy API 作为 Gemini 后端",
    )
    parser.add_argument(
        "--packy7s",
        action="store_true",
        help="使用 Packy7s API 作为 Gemini 后端",
    )
    parser.add_argument(
        "--packygpt",
        "-packygpt",
        action="store_true",
        dest="packygpt",
        help="使用 PackyGPT 专用 key 调用 gpt-image-2（需 .env 中 PACKYGPT_API_KEY）",
    )
    parser.add_argument(
        "--micugpt2",
        "-micugpt2",
        action="store_true",
        dest="micugpt2",
        help="使用 MicuAPI 专用 key 调用 gpt-image-2（需 .env 中 MICUAPI_API_KEY）",
    )
    parser.add_argument(
        "--xingchengpt",
        "-xingchengpt",
        action="store_true",
        dest="xingchengpt",
        help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY）",
    )
    parser.add_argument(
        "--xinchengpt",
        "-xinchengpt",
        action="store_true",
        dest="xinchengpt",
        help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY）",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # 处理 Packy API 配置
    from _packy import apply_packy_backend
    apply_packy_backend(args, allow_packy3s=False)

    # 验证输入文件
    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"❌ 错误：未找到图片 {args.image}", file=sys.stderr)
        print(f"\n请确保图片文件存在，或使用示例：", file=sys.stderr)
        print(f"  python run_banner.py -i input/sample.png -m '主标题' -s '副标题'", file=sys.stderr)
        sys.exit(1)

    # 验证脚本文件
    if not (COMPOSER_SCRIPTS / "compose_banner.py").is_file():
        print(f"❌ 错误：未找到 compose_banner.py 于 {COMPOSER_SCRIPTS}", file=sys.stderr)
        sys.exit(1)
    if not PREPARE_SCRIPT.is_file():
        print(f"❌ 错误：未找到 prepare_background.py 于 {PREPARE_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    # 准备输出目录
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    step1_background = output_path.parent / "step1_prepared_background.png"

    print(f"📋 配置信息：")
    print(f"  输入图片：{image_path}")
    print(f"  主标题：{args.main_title}")
    print(f"  副标题：{args.subtitle}")
    print(f"  输出路径：{output_path}")
    print(f"  尺寸：{args.width} × {args.height}")
    print()

    # Step 1: prepare_background
    python_exe = PYTHON_EXE
    scripts_dir = str(PREPARE_SCRIPT.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        python_exe,
        str(PREPARE_SCRIPT),
        str(image_path.resolve()),
        str(step1_background),
        "--preset",
        args.preset,
        "--safe-zone-scale-outpaint",
    ]
    if not args.no_remove_text:
        cmd.append("--remove-text")

    print("🔄 Step 1: prepare_background（主体检测 + 安全区裁切 + 填充）...")
    r = subprocess.run(cmd, cwd=scripts_dir, env=env)
    if r.returncode != 0:
        print("❌ prepare_background 失败", file=sys.stderr)
        print("   提示：需要设置 GEMINI_API_KEY 环境变量", file=sys.stderr)
        sys.exit(r.returncode)

    # Step 2: compose
    sys.path.insert(0, str(COMPOSER_SCRIPTS))
    from compose_banner import compose, _resolve_output_path

    print("🔄 Step 2: compose（渐变蒙层 + 标题）...")
    compose(
        str(step1_background),
        str(output_path),
        args.main_title,
        args.subtitle,
        width=args.width,
        height=args.height,
        use_ai_linebreak=not args.no_ai_linebreak,
    )

    out_path, _ = _resolve_output_path(str(output_path))
    print(f"✅ 完成！输出文件：{out_path}")

    # 列出 output 目录下所有文件，方便在 IDE 文件树未刷新时确认产物
    out_dir = output_path.parent
    files = sorted(out_dir.glob("*")) if out_dir.is_dir() else []
    if files:
        print(f"\n📁 output 目录当前文件（{out_dir}）：")
        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                print(f"  {f.name}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
