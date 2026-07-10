#!/usr/bin/env python3
"""
活动长图入口脚本：从 KV 图合成 1080px 竖版活动长图（自动取色 + AI 背景 + 三区排版）。

用法：
  py scripts/run_changtu.py --kv input/kv.jpg --font-title fonts/title.otf \\
    -m "主标题" -s "副标题" --event-date "1.1-1.15" \\
    --prize-dir input/prizes --rules "规则一|规则二|规则三"

也可通过 run_full_with_custom_prompt.py -g 活动长图 触发：
  py scripts/run_full_with_custom_prompt.py -g 活动长图 -m "主标题" -s "副标题" \\
    --xingchengpt --event-date "1.1-1.15" --prize-dir input/prizes \\
    --rules "规则一|规则二|规则三" --font-title fonts/title.otf
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from _paths import validate_paths, sanitize_dirname, auto_extract_latest

validate_paths()

from _env import load_env, get_env_key

_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_ALT",
    "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY",
    "PACKY7S_API_KEY",
    "PACKYGPT_API_KEY",
    "MICUAPI_API_KEY",
    "MICU_API_KEY",
    "XINGCHENGGPT_API_KEY",
    "XINGCHENGGPT_BASE_URL",
    "XINGCHENGEMINI_API_KEY",
    "XINGCHENGEMINI_BASE_URL",
    "BANNER_IMAGE_BACKEND",
    "BANNER_EDIT_BACKEND",
    "MOXINGEMINI_API_KEY",
    "MOXINGEMINI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
)
load_env(_ENV_KEYS)

from _packy import apply_packy_backend

from scripts.ensure_python import get_python_exe
PYTHON_EXE = get_python_exe()

OUTPUT_DIR = ROOT / "output"
INPUT_DIR = ROOT / "input"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="活动长图合成：1080px 竖版，KV + 福利区 + 规则区",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 完整流程
  py scripts/run_changtu.py --kv input/kv.jpg --font-title fonts/title.otf \\
    -m "春节狂欢" -s "限定皮肤" --event-date "1.1-1.15" \\
    --prize-dir input/prizes --rules "规则一|规则二|规则三" --xingchengpt

  # 不传 --kv 则自动从 input/ 提取
  py scripts/run_changtu.py --font-title fonts/title.otf -m "标题" --xingchengpt
        """,
    )

    ap.add_argument("--kv", default=None, help="KV 图路径（不传则从 input/ 自动提取）")
    ap.add_argument("--font-title", required=True, help="标题字体路径")
    ap.add_argument("--font-yahei", default=None, help="微软雅黑字体路径（默认自动查找）")
    ap.add_argument("-m", "--main-title", default="", dest="main_title", help="主标题")
    ap.add_argument("-s", "--subtitle", default="", dest="subtitle", help="副标题")
    ap.add_argument("--section1", default="福利活动", help="第一区块标题")
    ap.add_argument("--section2", default="活动规则", help="第二区块标题")
    ap.add_argument("--event-date", default="", help="活动日期")
    ap.add_argument("--event-desc", default="", help="参与方式描述")
    ap.add_argument("--prize-dir", default="", help="奖品图片目录")
    ap.add_argument("--prize-order", default="", help="奖品顺序，用 | 分隔文件名关键词")
    ap.add_argument("--rules", default="", help="规则文案，用 | 分隔多条")
    ap.add_argument("--kv-scene", default="", help="KV画面描述，用于AI生成延续背景")
    ap.add_argument("--game-name", default="活动", help="游戏名称（用于AI prompt）")
    ap.add_argument("--game-style", default="", help="游戏风格描述（用于AI prompt）")
    ap.add_argument("-o", "--output", default="output/活动长图.jpg", help="输出路径")
    ap.add_argument("--output-dir", default=None, help="输出目录（与--output二选一，会自动命名）")

    ap.add_argument("--packy", "-packy", action="store_true", dest="packy",
                    help="使用 Packy API 作为 Gemini 后端")
    ap.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s",
                    help="使用 Packy7s 专用 key 作为 Gemini 后端")
    ap.add_argument("--packy3s", "-packy3s", action="store_true", dest="packy3s",
                    help="使用 Packy3s 专用 key 作为 Gemini 后端")
    ap.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt",
                    help="使用 PackyGPT 专用 key 调用 gpt-image-2")
    ap.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2",
                    help="使用 MicuAPI 专用 key 调用 gpt-image-2")
    ap.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini",
                    help="使用 MicuAPI 专用 key 调用 Gemini")
    ap.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini",
                    help="使用 XingchenGemini 专用 key 调用 Gemini")
    ap.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1",
                    help="使用 XingchenGemini 多 Key 轮换 1 号 key")
    ap.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt",
                    help="使用 XingchenGPT 专用 key 调用 gpt-image-2")
    ap.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt",
                    help="使用 MoxinGPT 专用 key 调用 gpt-image-2")
    ap.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini",
                    help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY，与 --moxingpt 组合时编辑走 chat/completions）")

    return ap.parse_args()


def _resolve_kv_path(args: argparse.Namespace) -> Path:
    if args.kv:
        p = Path(args.kv).resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"KV 图不存在: {p}")

    latest = auto_extract_latest()
    if latest and latest.is_file():
        print(f"[run_changtu] 自动提取 KV 图: {latest}", flush=True)
        return latest

    for name in ("current.png", "source.png", "source.jpg",
                 "kv.jpg", "kv.png", "KV.jpg", "KV.png"):
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
        return out_dir / "活动长图.jpg"
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
    rules = [r.strip() for r in args.rules.split("|") if r.strip()]

    sys.path.insert(0, str(ROOT / "scripts"))
    from changtu.poster import make_poster

    print(f"[run_changtu] KV: {kv_path}", flush=True)
    print(f"[run_changtu] 标题: {args.main_title}", flush=True)
    print(f"[run_changtu] 输出: {output_path}", flush=True)
    backend = os.environ.get("BANNER_IMAGE_BACKEND", "micugpt2")
    print(f"[run_changtu] 生图后端: {backend}", flush=True)

    make_poster(
        kv=kv_path,
        font_title=args.font_title,
        font_yahei=args.font_yahei,
        main_title=args.main_title,
        sub_title=args.subtitle,
        section1=args.section1,
        section2=args.section2,
        event_date=args.event_date,
        event_desc=args.event_desc,
        prize_dir=args.prize_dir,
        prize_order=prize_order,
        rules=rules,
        kv_scene=args.kv_scene,
        game_name=args.game_name,
        game_style=args.game_style,
        output=output_path,
    )


if __name__ == "__main__":
    main()
