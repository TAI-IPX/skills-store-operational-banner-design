#!/usr/bin/env python3
"""
将「对话框上传」的图片路径写入 input/upload_path.txt，之后可直接运行：
  python scripts/run_all_presets.py @ -g "商店日常" -m "主标题" -s "副标题"
顺序约定：第 1 行 = 背景图，第 2 行 = logo 图（可选）。只传一张则只写第 1 行。

用法：
  python scripts/set_upload_image.py <背景图路径>              # 只写路径
  python scripts/set_upload_image.py <背景图路径> --copy      # 复制到 uploads/current.png 再写路径
  python scripts/set_upload_image.py <背景图路径> <logo路径>   # 背景 + logo
"""
import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
UPLOADS_DIR = INPUT_DIR / "uploads"
UPLOAD_PATH_FILE = INPUT_DIR / "upload_path.txt"
CURRENT_IMG = UPLOADS_DIR / "current.png"


def _save_copy(src: Path, dest: Path) -> Path:
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = UPLOADS_DIR / f"{ts}.png"
        shutil.copy2(src, alt)
        shutil.copy2(src, dest)
    else:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="设置当前上传图片：默认只写路径，--copy 则复制到 input/uploads/current.png"
    )
    parser.add_argument("background", help="背景图路径")
    parser.add_argument("logo", nargs="?", default=None, help="logo 图路径（可选）")
    parser.add_argument(
        "--copy", "-c", action="store_true",
        help="将图片复制到 input/uploads/current.png 再写入 upload_path.txt（推荐流程）"
    )
    args = parser.parse_args()

    bg_path = Path(args.background).resolve()
    if not bg_path.is_file():
        print(f"Error: 未找到背景图 {bg_path}", file=__import__('sys').stderr)
        __import__('sys').exit(1)

    paths = [str(bg_path)]
    if args.logo:
        logo_path = Path(args.logo).resolve()
        if not logo_path.is_file():
            print(f"Error: 未找到 logo 图 {logo_path}", file=__import__('sys').stderr)
            __import__('sys').exit(1)
        paths.append(str(logo_path))

    if args.copy:
        new_bg = _save_copy(bg_path, CURRENT_IMG)
        paths[0] = str(new_bg)
        print(f"已复制到: {new_bg}")

    UPLOAD_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_PATH_FILE.write_text("\n".join(paths), encoding="utf-8")
    print(f"已写入: {UPLOAD_PATH_FILE}")
    print(f"第1行(背景): {paths[0]}")
    if len(paths) > 1:
        print(f"第2行(logo): {paths[1]}")
    print("可直接运行: python scripts/run_all_presets.py @ -g \"商店日常\" -m \"主标题\" -s \"副标题\"")


if __name__ == "__main__":
    main()