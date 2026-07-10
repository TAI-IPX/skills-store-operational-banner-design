#!/usr/bin/env python3
"""
战报长图合成入口（由 run_full_with_custom_prompt.py -g 战报 路由调用）

用法:
    py scripts/run_battle_report.py ~/Desktop/战报 -m "主标题" -s "副标题"
    py scripts/run_battle_report.py ./_report_materials -m "标题" --kv input/uploads/current.png
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.battle_report.compose_battle_report import compose_from_desktop_folder
from scripts.battle_report.fonts import ensure_fonts_ready, log_font_configuration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="战报长图合成：1080px 竖版，KV + 内容区块"
    )
    parser.add_argument("assets_dir", type=Path, help="素材目录（含 KV.jpg 及分区子文件夹）")
    parser.add_argument("-m", "--main-title", required=True, help="主标题")
    parser.add_argument("-s", "--tagline", default="", help="副标题")
    parser.add_argument("--bar-text", default="首发启幕 联动数据重磅揭晓", help="首发条文案")
    parser.add_argument("--stat-exposure", default="", help="曝光数据文字（如 2亿+）")
    parser.add_argument("--stat-download", default="", help="下载数据文字（如 100万+）")
    parser.add_argument("--stat-group", action="append", default=None, dest="stat_groups",
                        help="多组数据模块，格式 '标题|标签1|值1|标签2|值2'，可重复指定（如 --stat-group \"首日|曝光|2亿+|下载|8888w+\"）")
    parser.add_argument("--no-stats", action="store_true", help="完全隐藏数据指标")
    parser.add_argument("--font-family", default=None, dest="font_family",
                        help="指定字体名称，扫描系统字体目录匹配（如 '造字工房启黑体'）")
    parser.add_argument("--theme-id", default="desktop_zhanbao", help="主题 JSON 名称")
    parser.add_argument("--output-dir", type=Path, default=None, help="输出目录")
    parser.add_argument("--kv", type=Path, default=None,
                        help="KV 图路径；不填则从 assets_dir 下自动查找 KV.jpg/KV.png")
    # 以下参数仅占位（环境变量已在父进程中设置），实际逻辑依赖 os.environ
    parser.add_argument("--xingchengpt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--xinchengpt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--xingchengemini", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--xingchengemini1", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--packygpt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--micugpt2", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--micugemini", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--moxingpt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--moxingemini", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--packy7s", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--packy", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # 字体检测（自动扫描，失败报错）
    if args.font_family:
        from scripts.battle_report.fonts import set_font_family
        set_font_family(args.font_family)
    try:
        log_font_configuration()
    except FileNotFoundError as exc:
        print(f"[战报] 字体错误: {exc}", flush=True)
        print("[战报] 请将 4 种字体文件放入 scripts/assets/battle-report/fonts/:", flush=True)
        print("  display-bold.otf  — 主标题/栏目标题", flush=True)
        print("  display-medium.otf — 副标题/强调", flush=True)
        print("  body-regular.otf  — 正文/评论", flush=True)
        print("  data-bold.otf     — 数据数字", flush=True)
        print("  或查看 docs/战报规范.md §4 字体配置", flush=True)
        return 1

    # KV 图：优先 --kv 参数，否则从 assets_dir 下自动查找
    if args.kv and args.kv.is_file():
        kv_dest = args.assets_dir / "KV.jpg"
        if args.kv.suffix.lower() == ".png":
            kv_dest = args.assets_dir / "KV.png"
        if not kv_dest.exists() or args.kv.resolve() != kv_dest.resolve():
            shutil.copy2(args.kv, kv_dest)
    else:
        for name in ("KV.jpg", "KV.png", "kv.jpg", "kv.png"):
            p = args.assets_dir / name
            if p.is_file():
                break
        else:
            print("[战报] 警告: assets_dir 下未找到 KV.jpg / KV.png，合成可能缺少头图背景",
                  flush=True)

    stats = None
    if not args.no_stats:
        stats_list = []
        if args.stat_exposure.strip():
            stats_list.append(("曝光：", args.stat_exposure.strip()))
        if args.stat_download.strip():
            stats_list.append(("下载：", args.stat_download.strip()))
        if stats_list:
            stats = stats_list

    stat_groups = None
    if args.stat_groups:
        stat_groups = []
        for sg in args.stat_groups:
            parts = [p.strip() for p in sg.split("|")]
            if len(parts) >= 5 and (len(parts) - 1) % 2 == 0:
                title = parts[0]
                pairs = [(parts[i], parts[i+1]) for i in range(1, len(parts), 2)]
                stat_groups.append({"title": title, "stats": pairs})

    out = compose_from_desktop_folder(
        args.assets_dir,
        main_title=args.main_title,
        tagline=args.tagline,
        bar_text=args.bar_text,
        stats=stats,
        stat_groups=stat_groups,
        theme_id=args.theme_id,
        out_dir=args.output_dir,
    )
    print(f"[战报] 已输出: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
