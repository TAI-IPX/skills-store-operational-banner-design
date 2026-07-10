#!/usr/bin/env python3
"""一键流程：
  Step 1 - 写入上传图路径（背景图 + 可选 logo）
  Step 2 - 用描述生成艺术字透明 PNG（--title-art-desc），或直接使用已有透明图（--title-art）
  Step 3 - 生成 LZ 顶部 banner 底图（run_all_presets -g LZ顶部banner）
  Step 4 - 叠加艺术字到底图输出预览

用法举例（直接用已有艺术字）：
  python scripts/run_lz_top_banner_with_title_art.py \\
    -i "roco.png" \\
    -t "title_art.png" \\
    -m "前程似锦" \\
    --output-dir output/lz_top_run1

用法举例（自动生成艺术字）：
  python scripts/run_lz_top_banner_with_title_art.py \\
    -i "roco.png" \\
    --title-art-desc "前程似锦书法毛笔艺术字，白底黑字，水墨墨迹..." \\
    -m "前程似锦" \\
    --output-dir output/lz_top_run1

仅背景生成（跳过文生图、不合成预览）：
  python scripts/run_lz_top_banner_with_title_art.py \\
    -i "roco.png" -m "前程似锦" --output-dir output/lz_bg_only --background-only
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 路径约束验证
from _paths import validate_paths
validate_paths()

_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if str(_SPEC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec_banner

_TOP_BANNER_FILENAME = _spec_banner.OUTPUT_FILENAME_BY_PRESET["legend_top_banner_3840"]
SET_UPLOAD_SCRIPT = ROOT / "scripts" / "set_upload_image.py"
RUN_PRESETS_SCRIPT = ROOT / "scripts" / "run_all_presets.py"
COMPOSE_TITLE_ART_SCRIPT = ROOT / "scripts" / "compose_title_art_preview.py"
GENERATE_SCRIPT = (
    ROOT
    / ".claude"
    / "skills"
    / "banner-background-from-description"
    / "scripts"
    / "generate_from_description.py"
)
FALLBACK_TITLE_ART_SCRIPT = ROOT / "scripts" / "fallback_title_art_pil.py"

ENV_FILE = ROOT / ".env"


def _load_env() -> dict:
    """从 .env 读取 key/value，返回 dict；不覆盖已有环境变量。"""
    result = {}
    if not ENV_FILE.is_file():
        return result
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and v:
                    result[k] = v
    return result


def _make_env(use_packy7s: bool) -> dict:
    """构建注入了 packy7s key 的子进程环境。"""
    env = os.environ.copy()
    loaded = _load_env()
    # 先写入所有 .env 键（不覆盖已有）
    for k, v in loaded.items():
        if k not in env:
            env[k] = v
    if use_packy7s:
        env["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
        key = loaded.get("PACKY7S_API_KEY") or env.get("PACKY7S_API_KEY", "")
        if key.startswith("sk-"):
            env["GEMINI_API_KEY"] = key
        else:
            print(
                "Error: 使用 packy7s 需在 .env 中设置 PACKY7S_API_KEY（以 sk- 开头）",
                file=sys.stderr,
            )
            sys.exit(1)
    return env


def _run(cmd: list[str], env: dict | None = None) -> None:
    display = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    print(f"> {display}", flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if r.returncode != 0:
        sys.exit(r.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="一条命令跑完：LZ顶部banner 底图 + 艺术字预览。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--image", "-i", required=True, help="背景图路径")
    parser.add_argument(
        "--title-art",
        "-t",
        default=None,
        help="已有艺术字透明 PNG 路径（与 --title-art-desc 二选一）",
    )
    parser.add_argument(
        "--title-art-desc",
        default=None,
        dest="title_art_desc",
        help="艺术字生图描述（自动生成，与 --title-art 二选一）",
    )
    parser.add_argument("--main-title", "-m", default="前程似锦", help="主标题（目录命名用）")
    parser.add_argument("--subtitle", "-s", default="", help="副标题（默认空）")
    parser.add_argument("--logo", default=None, help="可选 logo 透明 PNG 路径")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="输出目录（必须指定，用于定位底图与预览）",
    )
    parser.add_argument(
        "--no-packy7s",
        action="store_true",
        help="关闭 packy7s（默认开启）",
    )
    parser.add_argument(
        "--remove-text",
        action="store_true",
        help="开启去字（默认跳过，适合已经干净的素材）",
    )
    parser.add_argument(
        "--title-art-model",
        default="gemini",
        help="艺术字生图模型，默认 gemini；可选 jimeng / t8-jimeng 等",
    )
    parser.add_argument(
        "--no-title-fallback",
        action="store_true",
        help="文生图失败时不使用 PIL 简易字层回退（默认会回退以保证能出预览）",
    )
    parser.add_argument(
        "--background-only",
        action="store_true",
        help="仅生成 LZ 顶部 banner 底图：跳过文生图与艺术字合成预览（需 -i 与 --output-dir）",
    )
    parser.add_argument(
        "--skip-a4-outpaint",
        action="store_true",
        dest="skip_a4_outpaint",
        help="传给 run_all_presets：跳过 A4 延展填满（底图更贴近上传图；与旧版 -hd 语义相同）",
    )
    args = parser.parse_args()

    if args.background_only:
        if args.title_art or args.title_art_desc:
            parser.error("--background-only 时不要传 --title-art / --title-art-desc")
    elif not args.title_art and not args.title_art_desc:
        parser.error("必须指定 --title-art、--title-art-desc，或使用 --background-only")

    use_packy7s = not args.no_packy7s
    env = _make_env(use_packy7s)

    image_path = Path(args.image).resolve()
    run_dir = Path(args.output_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    logo_path = Path(args.logo).resolve() if args.logo else None

    if not image_path.is_file():
        print(f"Error: 未找到背景图 {image_path}", file=sys.stderr)
        sys.exit(1)
    if logo_path and not logo_path.is_file():
        print(f"Error: 未找到 logo {logo_path}", file=sys.stderr)
        sys.exit(1)

    total_steps = 2 if args.background_only else 4

    # ----- Step 1: 写入 upload_path.txt -----
    print(f"\n[1/{total_steps}] 写入输入图片路径...", flush=True)
    cmd_set = [sys.executable, str(SET_UPLOAD_SCRIPT), str(image_path)]
    if logo_path:
        cmd_set.append(str(logo_path))
    _run(cmd_set, env=env)

    if args.background_only:
        print(f"\n[2/{total_steps}] 生成 LZ 顶部 banner 底图（跳过文生图与预览合成）...", flush=True)
        cmd_run = [
            sys.executable,
            str(RUN_PRESETS_SCRIPT),
            "@",
            "-g", "LZ顶部banner",
            "-m", args.main_title,
            "-s", args.subtitle,
            "--output-dir", str(run_dir),
        ]
        if not args.remove_text:
            cmd_run.append("--skip-remove-text")
        if use_packy7s:
            cmd_run.append("-packy7s")
        if args.skip_a4_outpaint:
            cmd_run.append("--skip-a4-outpaint")
        _run(cmd_run, env=env)
        bg_path = run_dir / _TOP_BANNER_FILENAME
        if not bg_path.is_file():
            print(f"Error: 底图未产出 {bg_path}", file=sys.stderr)
            sys.exit(1)
        print("\nDone.", flush=True)
        print(f"  底图: {bg_path}", flush=True)
        return

    # ----- Step 2: 生成艺术字（如果传了 --title-art-desc）-----
    if args.title_art_desc:
        title_art_path = run_dir / f"{Path(_TOP_BANNER_FILENAME).stem}_title_art.png"
        print("\n[2/4] 生成艺术字透明 PNG（文生图）...", flush=True)
        cmd_art = [
            sys.executable,
            str(GENERATE_SCRIPT),
            args.title_art_desc,
            str(title_art_path),
            "--width", "3840",
            "--height", "1200",
            "--model", args.title_art_model,
        ]
        if use_packy7s:
            cmd_art.append("-packy7s")
        display = " ".join(f'"{c}"' if " " in c else c for c in cmd_art)
        print(f"> {display}", flush=True)
        r_art = subprocess.run(cmd_art, cwd=str(ROOT), env=env)
        if r_art.returncode != 0 or not title_art_path.is_file():
            if args.no_title_fallback:
                print(
                    "Error: 艺术字文生图失败且已禁用回退（--no-title-fallback）。",
                    file=sys.stderr,
                )
                sys.exit(r_art.returncode or 1)
            print(
                "\n[2/4] 文生图不可用（常见：Packy7s 未开放图模 403），改用 PIL 简易透明字层（非书法效果，仅用于合成预览）...",
                flush=True,
            )
            fb_cmd = [
                sys.executable,
                str(FALLBACK_TITLE_ART_SCRIPT),
                "--main",
                args.main_title,
                "--footer",
                "Sunrise Ai",
                "-o",
                str(title_art_path),
                "-p",
                "legend_top_banner_3840",
            ]
            _run(fb_cmd, env=env)
    else:
        title_art_path = Path(args.title_art).resolve()
        if not title_art_path.is_file():
            print(f"Error: 未找到艺术字图 {title_art_path}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[2/4] 使用已有艺术字: {title_art_path}", flush=True)

    # ----- Step 3: 生成底图 -----
    print("\n[3/4] 生成 LZ 顶部 banner 底图...", flush=True)
    cmd_run = [
        sys.executable,
        str(RUN_PRESETS_SCRIPT),
        "@",
        "-g", "LZ顶部banner",
        "-m", args.main_title,
        "-s", args.subtitle,
        "--output-dir", str(run_dir),
    ]
    if not args.remove_text:
        cmd_run.append("--skip-remove-text")
    if use_packy7s:
        cmd_run.append("-packy7s")
    if args.skip_a4_outpaint:
        cmd_run.append("--skip-a4-outpaint")
    _run(cmd_run, env=env)

    # ----- Step 4: 合成艺术字预览 -----
    bg_path = run_dir / _TOP_BANNER_FILENAME
    preview_path = run_dir / f"{Path(_TOP_BANNER_FILENAME).stem}_preview.png"
    if not bg_path.is_file():
        print(f"Error: 底图未产出 {bg_path}", file=sys.stderr)
        sys.exit(1)

    print("\n[4/4] 合成艺术字预览图...", flush=True)
    cmd_compose = [
        sys.executable,
        str(COMPOSE_TITLE_ART_SCRIPT),
        str(bg_path),
        str(title_art_path),
        str(preview_path),
        "-p", "legend_top_banner_3840",
    ]
    _run(cmd_compose, env=env)

    print("\nDone.", flush=True)
    print(f"  底图:   {bg_path}")
    print(f"  艺术字: {title_art_path}")
    print(f"  预览:   {preview_path}")


if __name__ == "__main__":
    main()
