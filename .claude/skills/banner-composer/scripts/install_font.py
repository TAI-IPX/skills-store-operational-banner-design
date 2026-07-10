#!/usr/bin/env python3
"""
检测本机是否已安装微软雅黑（msyh.ttf / msyhbd.ttf）。
若未安装，输出 Windows / macOS 的安装指引。不下载或分发字体文件。
"""

import os
import sys
from pathlib import Path


def _find_font_in_dir(dir_path: Path, base: str) -> Path | None:
    """Find first existing file: base.ttf, base.ttc, or BASE.TTC (same logic as compose_banner.py)."""
    names = [f"{base}.ttf", f"{base}.ttc", f"{base.upper()}.ttc", f"{base.upper()}.TTC"]
    for name in names:
        p = dir_path / name
        if p.is_file():
            return p
    return None


def _font_paths() -> tuple[str | None, str | None]:
    """Return (path_to_regular, path_to_bold); supports .ttf and .ttc (e.g. MSYH.TTC, MSYHBD.TTC)."""
    if sys.platform == "win32":
        windir = os.environ.get("SystemRoot", "C:\\Windows")
        fonts_dir = Path(windir) / "Fonts"
        r = _find_font_in_dir(fonts_dir, "msyh")
        b = _find_font_in_dir(fonts_dir, "msyhbd")
        return (str(r) if r else None, str(b) if b else None)
    dirs = [Path.home() / "Library" / "Fonts", Path("/Library/Fonts")]
    r = b = None
    for d in dirs:
        if not d.is_dir():
            continue
        if r is None:
            r = _find_font_in_dir(d, "msyh")
        if b is None:
            b = _find_font_in_dir(d, "msyhbd")
        if r and b:
            break
    return (str(r) if r else None, str(b) if b else None)


def main() -> None:
    regular, bold = _font_paths()
    if regular and bold:
        print("微软雅黑已就绪。")
        print(f"  Regular: {regular}")
        print(f"  Bold:    {bold}")
        return

    print("未检测到微软雅黑，无法使用 banner-composer。", file=sys.stderr)
    if not regular:
        print("  缺少: msyh.ttf (Regular)", file=sys.stderr)
    if not bold:
        print("  缺少: msyhbd.ttf (Bold)", file=sys.stderr)
    print(file=sys.stderr)
    if sys.platform == "win32":
        print("Windows 安装指引:", file=sys.stderr)
        print("  1. 从已安装微软雅黑的电脑复制 C:\\Windows\\Fonts\\msyh.ttf 与 msyhbd.ttf，或从合规渠道获取。", file=sys.stderr)
        print("  2. 双击 .ttf 文件，在打开窗口中点击「安装」。", file=sys.stderr)
    else:
        print("macOS 安装指引:", file=sys.stderr)
        print("  1. 从 Windows 电脑或合规渠道获取 msyh.ttf 与 msyhbd.ttf。", file=sys.stderr)
        print("  2. 复制到 ~/Library/Fonts/（仅当前用户）或 /Library/Fonts/（本机所有用户）。", file=sys.stderr)
    print("  详细说明见本 Skill 的 references/install_font.md。", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
