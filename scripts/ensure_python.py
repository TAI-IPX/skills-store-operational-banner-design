#!/usr/bin/env python3
"""
自动检测可用的 Python 解释器。
优先级：当前 Python > 虚拟环境 > 系统 Python
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_python_exe() -> str:
    """
    返回可用的 Python 解释器路径。

    优先级：
    1. 当前运行的 Python（sys.executable），但跳过 WindowsApps 存根
    2. 虚拟环境中的 Python（venv/bin/python 或 venv/Scripts/python.exe）
    3. 系统 PATH 中的 python3 / py / python

    Returns:
        str: Python 解释器的完整路径

    Raises:
        RuntimeError: 如果未找到可用的 Python 解释器
    """
    # 1. 当前 Python（最优先），排除 WindowsApps 存根
    if sys.executable and Path(sys.executable).is_file():
        if "WindowsApps" not in sys.executable:
            try:
                result = subprocess.run(
                    [sys.executable, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return sys.executable
            except Exception:
                pass

    # 2. 虚拟环境
    project_root = Path(__file__).resolve().parent.parent
    venv_paths = [
        project_root / "venv" / "bin" / "python",
        project_root / "venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
        project_root / ".venv" / "Scripts" / "python.exe",
    ]
    for venv_python in venv_paths:
        if venv_python.is_file():
            try:
                # 验证 Python 可执行
                result = subprocess.run(
                    [str(venv_python), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return str(venv_python.resolve())
            except (OSError, subprocess.TimeoutExpired):
                continue

    # 3. 系统 Python（py 优先于 python，避免 WindowsApps 存根）
    for cmd in ["python3", "py", "python"]:
        python_path = shutil.which(cmd)
        if python_path:
            try:
                # 验证 Python 版本
                result = subprocess.run(
                    [python_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return python_path
            except (OSError, subprocess.TimeoutExpired):
                continue

    # 未找到可用的 Python
    raise RuntimeError(
        "未找到可用的 Python 解释器。\n"
        "请确保：\n"
        "  1. Python 3.8+ 已安装并在 PATH 中，或\n"
        "  2. 已创建虚拟环境：python -m venv venv\n"
        "\n"
        "安装 Python：https://www.python.org/downloads/"
    )


def check_python_version(min_version=(3, 8)) -> bool:
    """
    检查 Python 版本是否满足最低要求。

    Args:
        min_version: 最低版本要求，默认 (3, 8)

    Returns:
        bool: 版本是否满足要求
    """
    return sys.version_info >= min_version


if __name__ == "__main__":
    # 测试脚本
    try:
        python_exe = get_python_exe()
        print(f"✅ 找到 Python: {python_exe}")

        # 检查版本
        result = subprocess.run(
            [python_exe, "--version"],
            capture_output=True,
            text=True,
        )
        print(f"   版本: {result.stdout.strip()}")

        # 检查最低版本要求
        if check_python_version():
            print("✅ Python 版本满足要求（3.8+）")
        else:
            print(f"⚠️  Python 版本过低，当前: {sys.version_info.major}.{sys.version_info.minor}")
            print("   建议升级到 Python 3.8 或更高版本")

    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)
