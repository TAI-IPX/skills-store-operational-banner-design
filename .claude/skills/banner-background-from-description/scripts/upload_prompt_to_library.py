#!/usr/bin/env python3
"""
单独上传 prompt 到 prompt_library，供模型（Gemini/Qwen）学习、优化产出提示词。
仅通过本脚本写入库；generate_from_description 主副标题生成描述时不再自动写入。

用法：
  python upload_prompt_to_library.py --prompt "你的文生图描述..."
  python upload_prompt_to_library.py --prompt-file input/my_prompt.txt
  python upload_prompt_to_library.py --prompt-file input/my_prompt.txt --main-title "主标题" --subtitle "副标题" --tags "科技,横版"
"""
import argparse
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import prompt_library as pl


def main() -> None:
    parser = argparse.ArgumentParser(
        description="单独上传一条 prompt 到 prompt_library，供模型学习使用",
    )
    parser.add_argument("--prompt", "-p", default=None, help="文生图描述（与 --prompt-file 二选一）")
    parser.add_argument("--prompt-file", dest="prompt_file", default=None, help="从 UTF-8 文件读取描述")
    parser.add_argument("--main-title", "-m", default="", help="主标题（可选）")
    parser.add_argument("--subtitle", "-s", default="", help="副标题（可选）")
    parser.add_argument("--tags", "-t", default="", help="标签，逗号分隔")
    parser.add_argument("--source", default="用户上传", help="来源，默认 用户上传")
    args = parser.parse_args()

    if args.prompt_file:
        path = Path(args.prompt_file).resolve()
        if not path.is_file():
            print(f"Error: 文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
        prompt = path.read_text(encoding="utf-8").strip()
    elif args.prompt is not None:
        prompt = args.prompt.strip()
    else:
        print("Error: 请提供 --prompt 或 --prompt-file", file=sys.stderr)
        sys.exit(1)

    if not prompt:
        print("Error: 描述不能为空", file=sys.stderr)
        sys.exit(1)

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    eid = pl.add_entry(
        prompt=prompt,
        source=args.source,
        main_title=args.main_title,
        subtitle=args.subtitle,
        tags=tags,
        notes="",
    )
    print(f"已上传到 prompt_library: {eid}.json")
    idx = pl.write_index_md()
    print(f"索引已更新: {idx}")


if __name__ == "__main__":
    main()
