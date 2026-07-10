#!/usr/bin/env python3
"""
仅跑商店专题长图 3320×460：prepare_background preset=wide（含 A5 + A5b BiRefNet 顶部条带）→ compose wide → 输出「专题长图 3320x460.png」。
用法: python run_wide_only.py @ -m "主标题" -s "副标题"
      或 python run_wide_only.py <图片路径> -m "主标题" -s "副标题"
      @ 表示从 input/upload_path.txt 读取图片路径。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 路径约束验证
from _paths import validate_paths
validate_paths()

INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
UPLOAD_PATH_FILE = INPUT_DIR / "upload_path.txt"
PREPARE_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts" / "prepare_background.py"
COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"

_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec
PRESETS = _spec.PRESETS
OUTPUT_FILENAME_BY_PRESET = _spec.OUTPUT_FILENAME_BY_PRESET

from scripts.ensure_python import get_python_exe
PYTHON_EXE = get_python_exe()

WIDE_PRESET = "wide"
OUT_NAME = OUTPUT_FILENAME_BY_PRESET.get(WIDE_PRESET, "专题长图 3320x460.png")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="仅生成商店专题长图 3320×460")
    parser.add_argument("image", nargs="?", default=None, help="输入图片路径；传 @ 则从 input/upload_path.txt 读取")
    parser.add_argument("--main-title", "-m", default=None, help="主标题（或 --main-title-file）")
    parser.add_argument("--main-title-file", default=None, help="主标题文本文件路径")
    parser.add_argument("--subtitle", "-s", default="", help="副标题")
    parser.add_argument("--subtitle-file", default=None, help="副标题文本文件路径")
    parser.add_argument("--output-dir", "-o", default=None, help="输出目录，不填则 output/专题长图_时间戳")
    parser.add_argument("--skip-remove-text", action="store_true", dest="skip_remove_text", help="跳过去干扰")
    parser.add_argument("--skip-a4-outpaint", action="store_true", help="跳过 A4 延展（文生图/直接给图时可用）")
    parser.add_argument("--packy", "-packy", action="store_true", dest="packy", help="使用 Packy API 作为 Gemini 后端")
    parser.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s", help="使用 Packy7s 专用 key 作为 Gemini 后端（需 .env 中 PACKY7S_API_KEY）")
    parser.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt", help="使用 PackyGPT 专用 key 调用 gpt-image-2（需 .env 中 PACKYGPT_API_KEY）")
    parser.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2", help="使用 MicuAPI 专用 key 调用 gpt-image-2（需 .env 中 MICUAPI_API_KEY）")
    parser.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt", help="使用 MoxinGPT 专用 key 调用 gpt-image-2（需 .env 中 MOXINGPT_API_KEY）")
    parser.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini", help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY，与 --moxingpt 组合时编辑走 chat/completions）")
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt", help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY）")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt", help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY）")
    args = parser.parse_args()

    if args.image and args.image.strip() in ("@", "upload"):
        from _paths import auto_extract_latest
        auto_extract_latest()
        if not UPLOAD_PATH_FILE.is_file():
            print("Error: 未找到 input/upload_path.txt", file=sys.stderr)
            sys.exit(1)
        with open(UPLOAD_PATH_FILE, "r", encoding="utf-8") as f:
            lines = [ln.strip().strip('"\'') for ln in f.readlines() if ln.strip()]
        if not lines:
            print("Error: input/upload_path.txt 为空", file=sys.stderr)
            sys.exit(1)
        image_path = Path(lines[0]).resolve()
        logo_path = Path(lines[1]).resolve() if len(lines) > 1 and lines[1] else None
        if logo_path is not None and not logo_path.is_file():
            logo_path = None
    elif args.image and args.image.strip():
        image_path = Path(args.image.strip().strip('"\'')).resolve()
        logo_path = None
    else:
        from _paths import auto_extract_latest
        latest = auto_extract_latest()
        if latest:
            image_path = latest
            logo_path = None
        else:
            for name in ("uploads/current.png", "source.png", "source.jpg", "upload.png"):
                p = INPUT_DIR / name
                if p.is_file():
                    image_path = p.resolve()
                    break
            else:
                for p in sorted(INPUT_DIR.glob("*.png")) + sorted(INPUT_DIR.glob("*.jpg")):
                    if p.is_file():
                        image_path = p.resolve()
                        break
                else:
                    print("Error: 未指定图片且 input/ 下无图。传 @ 或图片路径。", file=sys.stderr)
                    sys.exit(1)
        logo_path = None

    if not image_path.is_file():
        print(f"Error: 未找到图片 {image_path}", file=sys.stderr)
        sys.exit(1)

    if args.main_title_file and Path(args.main_title_file).is_file():
        main_title = Path(args.main_title_file).read_text(encoding="utf-8").strip()
    elif args.main_title:
        main_title = args.main_title
    else:
        print("Error: 请提供 --main-title 或 --main-title-file", file=sys.stderr)
        sys.exit(1)
    if args.subtitle_file and Path(args.subtitle_file).is_file():
        subtitle = Path(args.subtitle_file).read_text(encoding="utf-8").strip()
    else:
        subtitle = args.subtitle or ""

    if args.output_dir and str(args.output_dir).strip():
        run_dir = Path(args.output_dir).resolve()
    else:
        from datetime import datetime
        run_dir = OUTPUT_DIR / f"专题长图_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {run_dir}", flush=True)

    from _env import load_env
    _env_keys = (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GOOGLE_GEMINI_BASE_URL",
        "PACKY_API_KEY",
        "PACKY7S_API_KEY",
        "PACKYGPT_API_KEY",
        "MOXINGEMINI_API_KEY",
        "MOXINGEMINI_BASE_URL",
        "T8STAR_API_KEY",
        "BANNER_IMAGE_BACKEND",
    )
    load_env(_env_keys)
    from _packy import apply_packy_backend
    apply_packy_backend(args)
    if getattr(args, "packy", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
        packy_key = None
        gemini_sk = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "PACKY_API_KEY" and v:
                            packy_key = v
                        if k == "GEMINI_API_KEY" and v and v.startswith("sk-"):
                            gemini_sk = v
        if packy_key:
            os.environ["GEMINI_API_KEY"] = packy_key
        elif gemini_sk:
            os.environ["GEMINI_API_KEY"] = gemini_sk
    # packygpt 分支已由 apply_packy_backend() 统一处理（_packy.py），此处不再重复设置

    if getattr(args, "micugpt2", False):
        micugpt2_key = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "MICUAPI_API_KEY" and v:
                            micugpt2_key = v
        if micugpt2_key and micugpt2_key.strip().startswith("sk-"):
            os.environ["MICUAPI_API_KEY"] = micugpt2_key
            os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
        else:
            print("Error: 使用 -micugpt2 时请在 .env 中设置 MICUAPI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "moxingpt", False):
        moxingpt_key = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "MOXINGPT_API_KEY" and v:
                            moxingpt_key = v
        if moxingpt_key and moxingpt_key.strip().startswith("sk-"):
            os.environ["MOXINGPT_API_KEY"] = moxingpt_key
            os.environ["BANNER_IMAGE_BACKEND"] = "moxingpt"
        else:
            print("Error: 使用 -moxingpt 时请在 .env 中设置 MOXINGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "moxingemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").strip()
        moxingemini_key = os.environ.get("MOXINGEMINI_API_KEY")
        if not moxingemini_key and env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "MOXINGEMINI_API_KEY" and v:
                            moxingemini_key = v
                            break
        if moxingemini_key and moxingemini_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = moxingemini_key
            if not os.environ.get("GEMINI_MODEL"):
                os.environ["GEMINI_MODEL"] = os.environ.get("MOXINGEMINI_MODEL", "[次]gemini-3.1-flash-image-preview,[次]gemini-3-pro-image-preview")
        else:
            print("Error: 使用 -moxingemini 时请在 .env 中设置 MOXINGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xingchengpt", False):
        xingchengpt_key = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "XINGCHENGGPT_API_KEY" and v:
                            xingchengpt_key = v
        if xingchengpt_key and xingchengpt_key.strip().startswith("sk-"):
            os.environ["XINGCHENGGPT_API_KEY"] = xingchengpt_key
            os.environ["BANNER_IMAGE_BACKEND"] = "xingchengpt"
        else:
            print("Error: 使用 -xingchengpt 时请在 .env 中设置 XINGCHENGGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xinchengpt", False):
        xinchengpt_key = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "XINCHENGPT_API_KEY" and v:
                            xinchengpt_key = v
        if xinchengpt_key and xinchengpt_key.strip().startswith("sk-"):
            os.environ["XINCHENGPT_API_KEY"] = xinchengpt_key
            os.environ["BANNER_IMAGE_BACKEND"] = "xinchengpt"
        else:
            print("Error: 使用 -xinchengpt 时请在 .env 中设置 XINCHENGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    scripts_dir = str(PREPARE_SCRIPT.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    step1_wide = run_dir / "step1_wide.png"
    skip_remove = getattr(args, "skip_remove_text", False)
    print("Step 1: prepare_background preset=wide 3320×500（含 BiRefNet 顶部条带）...", flush=True)
    cmd = [
        PYTHON_EXE, str(PREPARE_SCRIPT), str(image_path), str(step1_wide),
        "--preset", WIDE_PRESET, "--safe-zone-scale-outpaint",
    ]
    if not skip_remove:
        cmd.append("--remove-text")
    if getattr(args, "skip_a4_outpaint", False):
        cmd.append("--skip-a4-outpaint")
    r = subprocess.run(cmd, cwd=scripts_dir, env=env)
    if r.returncode != 0 or not step1_wide.is_file():
        print("prepare_background wide 失败", file=sys.stderr)
        sys.exit(1)

    w, h = PRESETS[WIDE_PRESET]
    out_path = run_dir / OUT_NAME
    print(f"Step 2: compose wide -> {out_path.name} ...", flush=True)
    sys.path.insert(0, str(COMPOSER_SCRIPTS))
    from compose_banner import compose
    compose(str(step1_wide), str(out_path.resolve()), main_title, subtitle, width=w, height=h, use_ai_linebreak=True, logo_path=str(logo_path) if logo_path else None)
    print(f"已生成: {out_path}", flush=True)
    step1_wide.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
