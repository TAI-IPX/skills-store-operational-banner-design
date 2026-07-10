#!/usr/bin/env python3
"""
邮件长图入口脚本：从 KV 图合成 1920px 竖版邮件长图（自动取色 + Vision 风格分析 + API 装饰背景 + 四区排版）。

用法：
  py scripts/run_email_poster.py --kv input/kv.png --font-title fonts/title.otf \
    -m "主标题" -s "副标题" \
    --event-date "2026/7/6-2026/10/10" \
    --prize-dir "input/prizes" --prize-order "礼盒2|礼盒1|礼盒4|礼盒3|联动活动火热开启|核心资源矩阵" \
    --method-dir "input/screenshots" \
    --method-desc "在联想应用商店，登录并下载...|在LegionZone，登录并下载..." \
    --history-dir "input/history" --history-order "礼品1|礼品4|礼品3|礼品2" \
    --intro-text "《王者荣耀世界》是由腾讯天美工作室研发的..."

也可通过 run_full_with_custom_prompt.py -g 邮件长图 触发：
  py scripts/run_full_with_custom_prompt.py -g 邮件长图 -m "主标题" -s "副标题" \
    --xingchengpt --kv input/kv.png --font-title fonts/title.otf \
    --event-date "2026/7/6-2026/10/10" --prize-dir input/prizes \
    --method-dir input/screenshots --method-desc "文字一|文字二" \
    --history-dir input/history --intro-text "游戏介绍..."
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from _paths import validate_paths, auto_extract_latest

validate_paths()

from _env import load_env

_ENV_KEYS = (
    "GEMINI_API_KEY", "GEMINI_API_KEY_ALT", "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKYGPT_API_KEY",
    "MICUAPI_API_KEY", "MICU_API_KEY",
    "XINGCHENGGPT_API_KEY", "XINGCHENGGPT_BASE_URL",
    "XINGCHENGEMINI_API_KEY", "XINGCHENGEMINI_BASE_URL",
    "BANNER_IMAGE_BACKEND", "BANNER_EDIT_BACKEND",
    "MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
)
load_env(_ENV_KEYS)

from _packy import apply_packy_backend

INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="邮件长图合成：1920px 竖版，KV + EVENT01~04 四区排版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  py scripts/run_email_poster.py --kv input/kv.png --font-title fonts/title.otf \\
    -m "王者荣耀世界" -s "限时活动" \\
    --event-date "2026/7/6-2026/10/10" \\
    --prize-dir "C:/Users/80507/Desktop/邮件长图/活动时间" \\
    --prize-order "礼盒2|礼盒1|礼盒4|礼盒3|联动活动火热开启|核心资源矩阵" \\
    --method-dir "C:/Users/80507/Desktop/邮件长图/参与方法" \\
    --method-desc "在联想应用商店...|在LegionZone..." \\
    --history-dir "C:/Users/80507/Desktop/邮件长图/往期中奖" \\
    --history-order "礼品1|礼品4|礼品3|礼品2" \\
    --intro-text "《王者荣耀世界》是由腾讯天美工作室研发的..." \\
    --xingchengpt
        """,
    )

    ap.add_argument("--kv", default=None, help="KV 主图路径（不传则从 input/ 自动提取）")
    ap.add_argument("--font-title", required=True, help="标题字体路径（.otf / .ttf）")
    ap.add_argument("--font-yahei", default=None, help="微软雅黑字体路径（默认自动查找）")
    ap.add_argument("-m", "--main-title", default="", dest="main_title", help="主标题")
    ap.add_argument("-s", "--subtitle", default="", dest="subtitle", help="副标题")

    ap.add_argument("--event-date", default="", help="EVENT01 活动时间")
    ap.add_argument("--prize-dir", default="", help="EVENT01 奖品图标目录")
    ap.add_argument("--prize-order", default="", help="EVENT01 奖品排序关键词，| 分隔")

    ap.add_argument("--method-dir", default="", help="EVENT02 参与方法截图目录")
    ap.add_argument("--method-desc", default="", help="EVENT02 参与方法文字，| 分隔多段")

    ap.add_argument("--history-dir", default="", help="EVENT03 往期中奖截图目录")
    ap.add_argument("--history-order", default="", help="EVENT03 往期中奖排序关键词，| 分隔")

    ap.add_argument("--intro-text", default="", help="EVENT04 游戏介绍正文")

    ap.add_argument("-o", "--output", default="output/邮件长图.jpg", help="输出路径")
    ap.add_argument("--output-dir", default=None, help="输出目录（与 --output 二选一）")

    # 后端开关（与 changtu / battle_report 参数一致）
    ap.add_argument("--packy", "-packy", action="store_true", dest="packy")
    ap.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s")
    ap.add_argument("--packy3s", "-packy3s", action="store_true", dest="packy3s")
    ap.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt")
    ap.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2")
    ap.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini")
    ap.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini")
    ap.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1")
    ap.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt")
    ap.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt")
    ap.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini")

    return ap.parse_args()


def _resolve_kv_path(args: argparse.Namespace) -> Path:
    if args.kv:
        p = Path(args.kv).resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"KV 图不存在: {p}")

    latest = auto_extract_latest()
    if latest and latest.is_file():
        print(f"[run_email_poster] 自动提取 KV 图: {latest}", flush=True)
        return latest

    for name in ("current.png", "kv.jpg", "kv.png", "KV.jpg", "KV.png", "主k.png"):
        p = INPUT_DIR / name
        if p.is_file():
            return p
        p2 = INPUT_DIR / "uploads" / name
        if p2.is_file():
            return p2

    raise FileNotFoundError(
        "未提供 --kv 参数且 input/ 目录下未找到图片。"
        "请粘贴 KV 图到对话框，或使用 --kv 指定路径。"
    )


def _resolve_output_path(args: argparse.Namespace) -> Path:
    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / "邮件长图.jpg"
    out = Path(args.output)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def main() -> None:
    args = parse_args()

    apply_packy_backend(args)

    kv_path = _resolve_kv_path(args)
    output_path = _resolve_output_path(args)

    prize_order = ([s.strip() for s in args.prize_order.split("|") if s.strip()]
                   if args.prize_order else None)
    history_order = ([s.strip() for s in args.history_order.split("|") if s.strip()]
                     if args.history_order else None)

    sys.path.insert(0, str(ROOT / "scripts"))
    from email_poster import make_email_poster

    print(f"[run_email_poster] KV: {kv_path}", flush=True)
    print(f"[run_email_poster] 标题: {args.main_title}", flush=True)
    print(f"[run_email_poster] 日期: {args.event_date}", flush=True)
    print(f"[run_email_poster] 输出: {output_path}", flush=True)
    backend = os.environ.get("BANNER_IMAGE_BACKEND", "micugpt2")
    print(f"[run_email_poster] 生图后端: {backend}", flush=True)

    make_email_poster(
        kv=kv_path,
        font_title=args.font_title,
        font_yahei=args.font_yahei,
        main_title=args.main_title,
        sub_title=args.subtitle,
        event_date=args.event_date,
        prize_dir=args.prize_dir,
        prize_order=prize_order,
        method_desc=args.method_desc,
        method_dir=args.method_dir,
        history_dir=args.history_dir,
        history_order=history_order,
        intro_text=args.intro_text,
        output=output_path,
    )


if __name__ == "__main__":
    main()
