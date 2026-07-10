#!/usr/bin/env python3
"""用指定图片测试：prepare_background（去字+安全区）→ 同一张中间图合成 default 与 wide 两尺寸。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()

# 默认测试图片：使用 input/source.png，或通过命令行参数指定
DEFAULT_IMAGE = ROOT / "input" / "source.png"
OUTPUT_DIR = ROOT / "output"
COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"
PREPARE_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts" / "prepare_background.py"

STEP1_BG = OUTPUT_DIR / "step1_prepared_background.png"
MAIN_TITLE = "办公视觉效率"
SUBTITLE = "从设计到出图快人一步"


def main():
    image_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE
    image_path = Path(image_path)
    if not image_path.is_file():
        print(f"Error: 未找到图片 {image_path}", file=sys.stderr)
        print("用法: python scripts/test_with_image.py [图片路径]", file=sys.stderr)
        sys.exit(1)

    # 加载 .env 中的 GEMINI_API_KEY
    env_file = ROOT / ".env"
    if env_file.is_file():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY=") and "=" in line:
                    _, _, value = line.partition("=")
                    value = value.strip().strip('"\'')
                    if value:
                        os.environ["GEMINI_API_KEY"] = value
                    break

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scripts_dir = str(PREPARE_SCRIPT.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    # Step 1: prepare_background（去字 + 主体安全区 + 拼画布 + 填空白）
    print("Step 1: prepare_background (--remove-text --safe-zone-scale-outpaint preset=default)...")
    cmd = [
        PYTHON_EXE, str(PREPARE_SCRIPT), str(image_path), str(STEP1_BG),
        "--preset", "default", "--remove-text", "--safe-zone-scale-outpaint",
    ]
    r = subprocess.run(cmd, cwd=scripts_dir, env=env)
    if r.returncode != 0:
        print("prepare_background 失败（需要 GEMINI_API_KEY 且网络可用）", file=sys.stderr)
        sys.exit(r.returncode)

    # Step 2: 用同一张中间图合成两种尺寸
    sys.path.insert(0, str(COMPOSER_SCRIPTS))
    from compose_banner import compose, _resolve_output_path

    step1_abs = STEP1_BG.resolve()
    if not step1_abs.is_file():
        print(f"Error: Step 1 产出不存在: {step1_abs}", file=sys.stderr)
        sys.exit(1)
    for name, out_name, w, h in [
        ("default", "banner_test_default_1976x464.png", 1976, 464),
        ("wide", "banner_test_wide_3320x500.png", 3320, 500),
    ]:
        out_path = OUTPUT_DIR / out_name
        print(f"Step 2: compose preset={name} ({w}x{h}) -> {out_path}")
        compose(str(step1_abs), str(out_path.resolve()), MAIN_TITLE, SUBTITLE, width=w, height=h, use_ai_linebreak=True)
        resolved, _ = _resolve_output_path(str(out_path))
        print(f"  -> {resolved}")
    print("Done.")


if __name__ == "__main__":
    main()
