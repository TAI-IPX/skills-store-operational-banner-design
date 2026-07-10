"""共享路径定义与验证。"""
import re
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"


def auto_extract_latest() -> Path | None:
    """从 OpenCode DB 自动提取最新图片到 input/uploads/current.png。
    返回 current.png 路径，失败返回 None。
    """
    lib_dir = ROOT / "lib"
    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))
    from opencode_image_input import extract_latest

    return extract_latest()


def sanitize_dirname(s: str, max_len: int = 40) -> str:
    """将主标题等转为可作目录名的字符串：去掉非法字符，截断过长。"""
    if not s or not s.strip():
        return "untitled"
    s = s.strip()
    for c in r'\/:*?"<>|':
        s = s.replace(c, "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] if len(s) > max_len else (s or "untitled")


def validate_paths():
    """检查并阻止在项目外创建 input/output 目录。

    强制约束：所有输入输出必须使用项目内的 input/ 和 output/ 目录。
    禁止在项目外创建同名目录。
    """
    parent_input = ROOT.parent / "input"
    parent_output = ROOT.parent / "output"

    issues = []

    if parent_input.exists() and INPUT_DIR.exists() and not parent_input.samefile(INPUT_DIR):
        issues.append(f"输入目录应使用 {INPUT_DIR}，而非 {parent_input}")

    if parent_output.exists() and OUTPUT_DIR.exists() and not parent_output.samefile(OUTPUT_DIR):
        issues.append(f"输出目录应使用 {OUTPUT_DIR}，而非 {parent_output}")

    if issues:
        print("路径错误：")
        for issue in issues:
            print(f"  - {issue}")
        print(f"\n正确的路径：")
        print(f"  input/  应为：{INPUT_DIR}")
        print(f"  output/ 应为：{OUTPUT_DIR}")
        print(f"\n请删除外部目录后重试。")
        sys.exit(1)