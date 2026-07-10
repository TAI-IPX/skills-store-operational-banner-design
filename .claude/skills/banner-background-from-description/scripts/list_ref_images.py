#!/usr/bin/env python3
"""
列出参考图库中的图片，可按标签筛选。用于写 prompt 时快速选图。

用法：
  python list_ref_images.py
  python list_ref_images.py --tags 3D,春日
  python list_ref_images.py --tags 鱼眼 --output path
"""
import argparse
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import ref_image_library as ril


def main() -> None:
    parser = argparse.ArgumentParser(
        description="列出参考图库条目，可选按标签筛选",
    )
    parser.add_argument("--tags", "-t", default="", help="标签筛选，逗号分隔，如 3D,春日")
    parser.add_argument("--output", "-o", default=None, dest="output", help="将匹配的图片路径写入该文件（每行一条绝对路径）")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if tags:
        entries = ril.get_entries_by_tags(tags)
    else:
        entries = ril.load_all_entries()
        entries.sort(key=lambda e: int(e.get("id", "0")) if str(e.get("id", "0")).isdigit() else 0)

    if not entries:
        print("（无匹配条目）" if tags else "（参考图库为空，请先用 upload_ref_image.py 上传）")
        return

    paths_to_output = []
    for e in entries:
        eid = e.get("id", "")
        cap = e.get("caption", "") or "—"
        tags_str = ", ".join(e.get("tags") or []) or "—"
        p = ril.get_image_path(e)
        path_str = str(p) if p else "(文件缺失)"
        if p:
            paths_to_output.append(str(p))
        print(f"  id={eid}  caption=\"{cap}\"  tags=[{tags_str}]")
        print(f"    path: {path_str}")

    if args.output and paths_to_output:
        out_path = Path(args.output).resolve()
        out_path.write_text("\n".join(paths_to_output) + "\n", encoding="utf-8")
        print(f"\n已写入 {len(paths_to_output)} 条路径到: {out_path}")


if __name__ == "__main__":
    main()
