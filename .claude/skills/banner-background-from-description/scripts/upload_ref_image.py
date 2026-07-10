#!/usr/bin/env python3
"""
将一张参考图加入参考图库，用于辅助写 prompt。
图片会复制到 ref_image_library/images/，元数据写入 ref_image_library/refs.json。

用法：
  python upload_ref_image.py --image path/to/ref.png --caption "橙蓝渐变 3D 篮球" --tags "3D,运动,鱼眼"
  python upload_ref_image.py --image ref.jpg --caption "春日书店" --tags "春日,3D" --prompt-id 5
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
        description="上传一张参考图到参考图库，辅助写 prompt",
    )
    parser.add_argument("--image", "-i", required=True, help="参考图路径（支持 png/jpg/jpeg/webp）")
    parser.add_argument("--caption", "-c", default="", help="简短说明（可选）")
    parser.add_argument("--tags", "-t", default="", help="标签，逗号分隔，如 3D,春日,中心构图")
    parser.add_argument("--prompt-id", "-p", default="", dest="prompt_id", help="关联的 prompt 库条目 id（可选）")
    args = parser.parse_args()

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        print(f"Error: 图片不存在: {image_path}", file=sys.stderr)
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    try:
        eid = ril.add_entry(
            image_path=image_path,
            caption=args.caption.strip(),
            tags=tags,
            prompt_id=args.prompt_id.strip(),
        )
        idx = ril.write_index_md()
        print(f"已加入参考图库: id={eid}, 索引已更新: {idx}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
