#!/usr/bin/env python3
"""
商店移动端田字格 355*350 Banner 生成脚本。

用法示例：
  # 方式1：图片输入 + 渐变色
  python scripts/run_shop_mobile_tianzige.py -i input/game.png -m "王者荣耀" -c 蓝色

  # 方式2：prompt输入（文生图）
  python scripts/run_shop_mobile_tianzige.py -i "游戏角色原神" -m "原神" -c 绿色

参数：
  --input/-i     必填，输入是prompt还是图片路径，自动判断
  --main-title/-m  必填，主标题文字
  --color/-c     必填，渐变方案：蓝色/绿色/黄色/紫色
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 路径约束验证
from _paths import validate_paths, sanitize_dirname
validate_paths()

# 从项目根 .env 加载 API 与后端配置
_ENV_FILE = ROOT / ".env"
_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY",
    "PACKY7S_API_KEY",
    "PACKY3S_API_KEY",
    "PACKYGPT_API_KEY",
    "ANTHROPIC_API_KEY",
    "T8STAR_API_KEY",
    "BANNER_IMAGE_BACKEND",
    "T8STAR_IMAGE_MODEL",
    "T8STAR_BASE_URL",
    "BANNER_IMAGE_BACKEND",
)
if _ENV_FILE.is_file():
    with open(_ENV_FILE, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                _v = _v.strip().strip("'\"").strip()
                if _k in _ENV_KEYS and _v:
                    if _k not in os.environ:
                        os.environ[_k] = _v
sys.path.insert(0, str(ROOT))
from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
UPLOAD_PATH_FILE = INPUT_DIR / "upload_path.txt"

COLOR_TO_VARIANT = {
    "蓝色": 1,
    "绿色": 2,
    "黄色": 3,
    "紫色": 4,
}


def extract_subject(input_path: str) -> str:
    """使用 BiRefNet 抠图，返回透明PNG路径。"""
    extract_script = ROOT / "scripts" / "extract_subject_birefnet.py"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_out:
        tmp_out_path = tmp_out.name

    result = subprocess.run(
        [str(PYTHON_EXE), str(extract_script), input_path, "--output", tmp_out_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: 抠图失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    if not Path(tmp_out_path).exists():
        print(f"Error: 抠图输出文件不存在", file=sys.stderr)
        sys.exit(1)

    return tmp_out_path


def generate_and_extract(prompt: str) -> str:
    """文生图 + 抠图，返回透明PNG路径。"""
    step1_script = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts" / "generate_from_description.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        bg_path = tmpdir_path / "background.png"

        result = subprocess.run(
            [
            str(PYTHON_EXE),
            str(step1_script),
            prompt,
            str(bg_path),
            "--width", "1024",
            "--height", "1024",
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=300,
        )
        if result.returncode != 0:
            print(f"Error: 文生图失败: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        if not bg_path.exists():
            print(f"Error: 文生图输出文件不存在", file=sys.stderr)
            sys.exit(1)

        return extract_subject(str(bg_path))


def main() -> None:
    parser = argparse.ArgumentParser(description="商店移动端田字格 355*350 Banner 生成")
    parser.add_argument("--input", "-i", default=None, help="输入：prompt 字符串、图片路径，或传 @ 从对话框上传提取；不填则自动从对话框提取")
    parser.add_argument("--main-title", "-m", required=True, help="主标题文字")
    parser.add_argument("--color", "-c", required=True, choices=["蓝色", "绿色", "黄色", "紫色"], help="渐变方案")
    args = parser.parse_args()

    main_title = args.main_title.strip()
    color = args.color.strip()

    if args.input and args.input.strip():
        input_val = args.input.strip()
        if input_val in ("@", "upload", "对话框上传"):
            from _paths import auto_extract_latest
            auto_extract_latest()
            if not UPLOAD_PATH_FILE.is_file():
                print("Error: 未找到 input/upload_path.txt。请先上传图片到对话框。", file=sys.stderr)
                sys.exit(1)
            with open(UPLOAD_PATH_FILE, "r", encoding="utf-8") as f:
                lines = [ln.strip().strip('"\'') for ln in f.readlines() if ln.strip()]
            if not lines:
                print("Error: input/upload_path.txt 为空。", file=sys.stderr)
                sys.exit(1)
            input_val = lines[0]
    else:
        from _paths import auto_extract_latest
        print("[自动] 从对话框提取最新图片...", flush=True)
        latest = auto_extract_latest()
        if not latest:
            print("Error: 未指定输入，且无法从对话框提取图片。请传 -i 指定 prompt 或图片路径。", file=sys.stderr)
            sys.exit(1)
        input_val = str(latest)
        print(f"[自动] 提取成功: {latest}", flush=True)

    # Step 1: 判断输入类型
    input_path = Path(input_val)
    if input_path.exists():
        print(f"[Step 1] 检测到图片输入: {input_val}")
        subject_path = extract_subject(input_val)
        print(f"[Step 1] 抠图完成: {subject_path}")
    else:
        print(f"[Step 1] 检测到 prompt 输入: {input_val}")
        subject_path = generate_and_extract(input_val)
        print(f"[Step 1] 文生图+抠图完成: {subject_path}")

    # Step 2: 匹配渐变方案
    variant = COLOR_TO_VARIANT[color]
    print(f"[Step 2] 渐变方案: {color} (variant={variant})")

    # Step 3: 合成
    compose_script = ROOT / ".claude" / "skills" / "banner-composer" / "scripts" / "compose_banner.py"
    output_path = OUTPUT_DIR / "商店移动端田字格355x350.png"

    # 使用固定渐变背景，不需要真实背景图，传入一个存在的占位图
    placeholder_bg = ROOT / "input" / "shop_daily_bg.jpg"
    result = subprocess.run(
        [
            str(PYTHON_EXE),
            str(compose_script),
            str(placeholder_bg),
            str(output_path),
            "--main-title", main_title,
            "--preset", "shop_mobile_tianzige_355",
            "--variant", str(variant),
            "--subject", subject_path,
            "--no-ai-linebreak",
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    # 清理临时文件
    try:
        os.unlink(subject_path)
        print(f"[Step 3] 清理临时文件: {subject_path}")
    except Exception:
        pass

    if result.returncode != 0:
        print(f"Error: 合成失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"完成！输出: {output_path}")


if __name__ == "__main__":
    main()