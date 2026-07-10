#!/usr/bin/env python3
"""
Lovart 图像编辑独立 CLI：outpaint / remove-text / upscale / i2i。
用法：
  python scripts/lovart_edit.py outpaint input.png output.png [--prompt "..."]
  python scripts/lovart_edit.py remove-text input.png output.png
  python scripts/lovart_edit.py upscale input.png output.png
  python scripts/lovart_edit.py i2i input.png output.png --prompt "..."
"""
import argparse
import sys
from pathlib import Path

# 确保 scripts/ 在 sys.path
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import lovart_helper as lovart


def main():
    parser = argparse.ArgumentParser(description="Lovart 图像编辑 CLI")
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("outpaint", help="向外延展填充图片")
    p.add_argument("input", help="输入图片路径")
    p.add_argument("output", help="输出图片路径")
    p.add_argument("--prompt", "-p", default="", help="自定义 outpaint 提示词")

    p = sub.add_parser("remove-text", help="去除图片中的文字/水印")
    p.add_argument("input", help="输入图片路径")
    p.add_argument("output", help="输出图片路径")
    p.add_argument("--prompt", "-p", default="", help="自定义 inpaint 提示词")

    p = sub.add_parser("upscale", help="超分放大图片")
    p.add_argument("input", help="输入图片路径")
    p.add_argument("output", help="输出图片路径")

    p = sub.add_parser("i2i", help="图生图")
    p.add_argument("input", help="参考图路径")
    p.add_argument("output", help="输出图片路径")
    p.add_argument("--prompt", "-p", required=True, help="图生图提示词")

    args = parser.parse_args()

    if args.mode == "outpaint":
        prompt = args.prompt or lovart.OUTPAINT_PROMPT
        result = lovart.edit_outpaint(args.input, args.output, prompt=prompt)
    elif args.mode == "remove-text":
        prompt = args.prompt or lovart.INPAINT_REMOVE_TEXT_PROMPT
        result = lovart.edit_inpaint(args.input, args.output, prompt=prompt)
    elif args.mode == "upscale":
        result = lovart.edit_upscale(args.input, args.output)
    elif args.mode == "i2i":
        result = lovart.generate_i2i(args.prompt, args.input, args.output)
    else:
        parser.print_help()
        sys.exit(1)

    if result is None:
        print(f"[lovart_edit] {args.mode} 失败。", file=sys.stderr)
        sys.exit(1)
    print(f"Saved: {result}")
    sys.exit(0)


if __name__ == "__main__":
    main()
