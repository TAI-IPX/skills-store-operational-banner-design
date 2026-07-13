#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从已有背景图（bg.png）或全新生图直接生成所有预设 banner。

跳过 A1（去干扰）、A2（主体检测）、A3（主体对齐裁切）、A4（延展填充）四步，
直接从背景图开始做各尺寸裁切（A5）+ 补填（A6）+ Step 2 叠字合成。
节省 50-70% 时间。

用法：
    # 完整新流程：prompt 推导 → 生图 → 合成
    python scripts/run_from_a4.py -g 商店日常 -m "游戏名" -s "副标题" --prompt-engine -micugpt2 -micugemini
    python scripts/run_from_a4.py -g 商店日常 -m "游戏名" -s "副标题" --description "温暖办公场景..." -micugpt2

    # 复用已有图（传路径或自动找最新 bg.png）
    python scripts/run_from_a4.py output/xxx/bg.png --main-title "游戏名" --subtitle "副标题"
    python scripts/run_from_a4.py -m "游戏名" -s "副标题" -g 商店日常  # 自动找最新 bg.png
    python scripts/run_from_a4.py @  # 从 input/upload_path.txt 读取路径
"""
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 路径约束验证
from _paths import validate_paths, sanitize_dirname
validate_paths()

from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"
PREPARE_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts" / "prepare_background.py"
STEP1_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts" / "generate_from_description.py"
PROMPT_ENGINE_SCRIPTS = ROOT / ".claude" / "skills" / "prompt-engine" / "scripts"

_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec
PRESETS = _spec.PRESETS
GENRE_PRESETS = _spec.GENRE_PRESETS
OUTPUT_FILENAME_BY_PRESET = _spec.OUTPUT_FILENAME_BY_PRESET

UPLOAD_PATH_FILE = INPUT_DIR / "upload_path.txt"


def _find_latest_bg() -> Path | None:
    """在 output/ 下递归查找最新的 bg.png，fallback 到 tianchong.png。"""
    if not OUTPUT_DIR.is_dir():
        return None
    for name in ("bg.png", "tianchong.png"):
        candidates = sorted(OUTPUT_DIR.rglob(name), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="从背景图（bg.png）直接生成所有预设 banner，跳过 A1-A4 步骤；或先生图再合成"
    )
    parser.add_argument(
        "image", nargs="?", default=None,
        help="背景图路径（bg.png）；传 @ 或 upload 则从 input/upload_path.txt 读取；不填则自动查找 output/ 下最新的 bg.png"
    )
    parser.add_argument("--main-title", "-m", default="", help="主标题（可选，不填则不叠字）")
    parser.add_argument("--subtitle", "-s", default="", help="副标题")
    parser.add_argument(
        "--genre", "-g", action="append", default=None,
        help="场景分组，可重复传入，如 -g 商店日常 -g LZ全部；不填则跑全部预设"
    )
    parser.add_argument("--output-dir", default=None, help="指定输出目录；不填则自动创建 分组_主标题_时间戳")
    parser.add_argument("--logo", default=None, help="logo 图片路径（可选）")
    # 生图相关参数
    parser.add_argument("--description", "-d", default="", help="文生图描述文本（提供后自动生图）")
    parser.add_argument("--description-file", default=None, help="从文件读取文生图描述")
    parser.add_argument("--prompt-engine", action="store_true", help="用 AI（prompt-engine）推导描述，需要 -m 主标题")
    # 后端参数
    parser.add_argument("--packy", action="store_true", help="使用 Packy API 作为 Gemini 后端")
    parser.add_argument("--packy7s", action="store_true", help="使用 Packy7s 专用 key（需 .env 中 PACKY7S_API_KEY）")
    parser.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt", help="使用 PackyGPT 专用 key 调用 gpt-image-2（需 .env 中 PACKYGPT_API_KEY）")
    parser.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2", help="使用 MicuAPI 专用 key 调用 gpt-image-2（需 .env 中 MICUAPI_API_KEY）")
    parser.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini", help="使用 MicuAPI 专用 key 调用 gemini Vision（需 .env 中 MICUGEMINI_API_KEY）")
    parser.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini", help="使用 XingchenGemini 专用 key 调用 gemini-3.1-flash-image-preview（需 .env 中 XINGCHENGEMINI_API_KEY）")
    parser.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1", help="使用 XingchenGemini 多 Key 轮换 1 号 key（需 .env 中 XINGCHENGEMINI1_API_KEY）")
    parser.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt", help="使用 MoxinGPT 专用 key 调用 gpt-image-2（需 .env 中 MOXINGPT_API_KEY）")
    parser.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini", help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY，与 --moxingpt 组合时编辑走 chat/completions）")
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt", help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY）")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt", help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY）")
    parser.add_argument("--lovart", action="store_true", help="使用 Lovart 作为图编后端（BANNER_IMAGE_BACKEND=lovart）")
    parser.add_argument("--gemini", action="store_true", help="使用 Gemini 作为图编后端（默认）")
    parser.add_argument("--t8star", action="store_true", help="使用 t8star 作为图编后端")
    args = parser.parse_args()

    # --- 解析分组 ---
    main_title = args.main_title or ""
    subtitle = args.subtitle or ""

    if args.genre:
        merged: list[str] = []
        seen: set[str] = set()
        for raw in args.genre:
            genre = (raw or "").strip()
            if not genre:
                continue
            if genre not in GENRE_PRESETS:
                print(f"Error: 未知分组 {genre!r}。当前支持: {', '.join(GENRE_PRESETS)}", file=sys.stderr)
                sys.exit(1)
            for p in GENRE_PRESETS[genre]:
                if p not in seen:
                    seen.add(p)
                    merged.append(p)
        presets_to_run = merged
    else:
        presets_to_run = None  # 跑全部

    # --- 加载 .env + 设置后端环境变量 ---
    from _env import load_env
    _env_keys = (
        "GEMINI_API_KEY", "GEMINI_MODEL", "GOOGLE_GEMINI_BASE_URL",
        "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKYGPT_API_KEY", "MICUAPI_API_KEY", "MICUGEMINI_API_KEY", "XINGCHENGEMINI_API_KEY", "XINGCHENGEMINI1_API_KEY", "MOXINGPT_API_KEY", "MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL", "XINGCHENGGPT_API_KEY", "T8STAR_API_KEY",
        "BANNER_IMAGE_BACKEND", "T8STAR_IMAGE_MODEL", "T8STAR_BASE_URL",
        "LOVART_ACCESS_KEY", "LOVART_SECRET_KEY", "LOVART_PROJECT_ID",
        "LOVART_BASE_URL", "LOVART_PREFER_MODELS", "LOVART_INSECURE_SSL",
        "BANNER_BG_SIZE",
    )
    load_env(_env_keys)
    env_file = ROOT / ".env"
    from _packy import apply_packy_backend
    apply_packy_backend(args)
    if args.packy:
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "PACKY_API_KEY" and v:
                            os.environ["GEMINI_API_KEY"] = v
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

    if getattr(args, "micugemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.micuapi.ai"
        micugemini_key = os.environ.get("MICUGEMINI_API_KEY")
        if not micugemini_key and env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "MICUGEMINI_API_KEY" and v:
                            micugemini_key = v
                            break
        if micugemini_key and micugemini_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = micugemini_key
        else:
            print("Error: 使用 -micugemini 时请在 .env 中设置 MICUGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xingchengemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://api.centos.hk"
        xingchengemini_key = os.environ.get("XINGCHENGEMINI_API_KEY")
        if not xingchengemini_key and env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "XINGCHENGEMINI_API_KEY" and v:
                            xingchengemini_key = v
                            break
        if xingchengemini_key and xingchengemini_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = xingchengemini_key
        else:
            print("Error: 使用 -xingchengemini 时请在 .env 中设置 XINGCHENGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xingchengemini1", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk").strip()
        xingchengemini1_key = os.environ.get("XINGCHENGEMINI1_API_KEY")
        if not xingchengemini1_key and env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "XINGCHENGEMINI1_API_KEY" and v:
                            xingchengemini1_key = v
                            break
        if xingchengemini1_key and xingchengemini1_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = xingchengemini1_key
        else:
            print("Error: 使用 -xingchengemini1 时请在 .env 中设置 XINGCHENGEMINI1_API_KEY（且以 sk- 开头）", file=sys.stderr)
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
                os.environ["GEMINI_MODEL"] = os.environ.get("MOXINGEMINI_MODEL", "[特价次卡]gemini-3.1-pro-preview,[次]gemini-3-pro-image")
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

    if args.packy7s:
        packy7s_key = None
        if env_file.is_file():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"").strip()
                        if k == "PACKY7S_API_KEY" and v:
                            packy7s_key = v
                            break
        if packy7s_key:
            os.environ["GEMINI_API_KEY"] = packy7s_key
            os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"

    # --- 图编后端切换（lovart / gemini / t8star）---
    if args.lovart:
        os.environ["BANNER_IMAGE_BACKEND"] = "lovart"
        print("图编后端: Lovart", flush=True)
    elif args.t8star:
        os.environ["BANNER_IMAGE_BACKEND"] = "t8star"
        print("图编后端: t8star", flush=True)
    elif args.gemini:
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"
        print("图编后端: Gemini", flush=True)
    elif args.packy7s:
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"
        print("图编后端: Gemini (Packy7s)", flush=True)
    else:
        backend = os.environ.get("BANNER_IMAGE_BACKEND", "gemini")
        print(f"图编后端: {backend}", flush=True)

    # --- 确定描述来源（生图模式 vs 复用图模式）---
    description = ""
    _generate_mode = False

    if args.prompt_engine:
        if not main_title:
            print("Error: --prompt-engine 需要 -m 主标题", file=sys.stderr)
            sys.exit(1)
        print("Step 0: prompt-engine 推导描述...", flush=True)
        if str(PROMPT_ENGINE_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(PROMPT_ENGINE_SCRIPTS))
        from prompt_engine_optimizer import prompt_engine_optimize
        # backend 由当前环境 GEMINI_API_KEY / ANTHROPIC_API_KEY 决定，优先 Gemini
        pe_backend = "claude" if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("GEMINI_API_KEY") else "gemini"
        description, _trace = prompt_engine_optimize(
            main_title=main_title,
            subtitle=subtitle,
            backend=pe_backend,
            save_trace=True,
        )
        print(f"[prompt-engine] 描述已推导（{len(description)} 字）", flush=True)
        _generate_mode = True
    elif getattr(args, "description_file", None) and str(args.description_file).strip():
        desc_file = Path(args.description_file.strip())
        if not desc_file.is_file():
            print(f"Error: 描述文件不存在: {desc_file}", file=sys.stderr)
            sys.exit(1)
        description = desc_file.read_text(encoding="utf-8").strip()
        print(f"描述来自文件: {desc_file}（{len(description)} 字）", flush=True)
        _generate_mode = True
    elif getattr(args, "description", None) and str(args.description).strip():
        description = args.description.strip()
        print(f"描述来自参数（{len(description)} 字）", flush=True)
        _generate_mode = True

    # --- 输出目录 ---
    logo_path = None
    if getattr(args, "output_dir", None) and str(args.output_dir).strip():
        run_dir = Path(args.output_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"输出目录（已指定）: {run_dir}", flush=True)
    else:
        genre_label = (
            sanitize_dirname("+".join((g or "").strip() for g in args.genre))
            if args.genre else "all"
        )
        title_safe = sanitize_dirname(main_title) if main_title else "notitle"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if _generate_mode:
            # 生图模式：目录命名与 run_full 一致，无 a4_ 前缀
            run_dir = OUTPUT_DIR / f"{genre_label}_{title_safe}_{timestamp}"
        else:
            # 复用图模式：保留 a4_ 前缀便于区分
            run_dir = OUTPUT_DIR / f"a4_{genre_label}_{title_safe}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"输出目录: {run_dir}", flush=True)

    # --- Step 0: 生图（有描述时）---
    if _generate_mode:
        if not STEP1_SCRIPT.is_file():
            print(f"Error: 生图脚本不存在: {STEP1_SCRIPT}", file=sys.stderr)
            sys.exit(1)
        bg_out = run_dir / "bg.png"
        # 确定生图尺寸：micugpt2 直出宽图；其余读 BANNER_BG_SIZE 或默认 1920×1080
        _backend_now = os.environ.get("BANNER_IMAGE_BACKEND", "gemini").lower()
        if _backend_now == "micugpt2":
            _w, _h = 4096, 1024
        else:
            _bg_size = os.environ.get("BANNER_BG_SIZE", "").strip()
            if _bg_size and "x" in _bg_size.lower():
                try:
                    _parts = _bg_size.lower().split("x")
                    _w, _h = int(_parts[0]), int(_parts[1])
                except ValueError:
                    _w, _h = 1920, 1080
            else:
                _w, _h = 1920, 1080

        print(f"Step 0: 生图 {_w}×{_h}（backend={_backend_now}）...", flush=True)
        # 保存描述到 prompt.txt
        (run_dir / "prompt.txt").write_text(description, encoding="utf-8")

        step0_env = os.environ.copy()
        cmd_step0 = [
            PYTHON_EXE, str(STEP1_SCRIPT),
            description, str(bg_out),
            "--width", str(_w), "--height", str(_h),
        ]
        r_step0 = subprocess.run(cmd_step0, env=step0_env)
        if r_step0.returncode != 0 or not bg_out.is_file():
            print("Error: Step 0 生图失败。", file=sys.stderr)
            sys.exit(1)
        print(f"Step 0 完成: {bg_out}", flush=True)
        tianchong_path_input = bg_out
    else:
        # --- 复用已有图：解析图片路径 ---
        if args.image and args.image.strip() in ("@", "upload", "对话框上传"):
            from _paths import auto_extract_latest
            auto_extract_latest()
            if not UPLOAD_PATH_FILE.is_file():
                print("Error: 未找到 input/upload_path.txt。请先运行：", file=sys.stderr)
                print("  python scripts/set_upload_image.py <图片路径>", file=sys.stderr)
                sys.exit(1)
            with open(UPLOAD_PATH_FILE, "r", encoding="utf-8") as f:
                lines = [ln.strip().strip('"\'') for ln in f.readlines() if ln.strip()]
            if not lines:
                print("Error: input/upload_path.txt 为空。", file=sys.stderr)
                sys.exit(1)
            tianchong_path_input = Path(lines[0]).resolve()
            logo_path = Path(lines[1]).resolve() if len(lines) > 1 and lines[1] else None
            if logo_path is not None and not logo_path.is_file():
                logo_path = None
            print(f"使用 upload_path.txt: {tianchong_path_input}", flush=True)
        elif args.image:
            tianchong_path_input = Path(args.image.strip().strip('"\'')).resolve()
        else:
            tianchong_path_input = _find_latest_bg()
            if tianchong_path_input is None:
                print("Error: 未指定图片，且 output/ 下未找到 bg.png 或 tianchong.png。", file=sys.stderr)
                print("请传入路径：python scripts/run_from_a4.py output/xxx/bg.png", file=sys.stderr)
                sys.exit(1)
            print(f"自动找到最新图片: {tianchong_path_input}", flush=True)

        if not tianchong_path_input.is_file():
            print(f"Error: 未找到背景图 {tianchong_path_input}", file=sys.stderr)
            sys.exit(1)

    if args.logo:
        logo_path = Path(args.logo.strip().strip('"\'')).resolve()
        if not logo_path.is_file():
            print(f"Warning: logo 文件不存在，忽略: {logo_path}", flush=True)
            logo_path = None

    scripts_dir = str(PREPARE_SCRIPT.parent)
    env = os.environ.copy()
    # 确保 Lovart 相关环境变量传递给 subprocess
    for k in ["LOVART_PREFER_MODELS", "LOVART_BASE_URL", "LOVART_INSECURE_SSL"]:
        if k in os.environ:
            env[k] = os.environ[k]
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 复制 tianchong.png 到输出目录 ---
    tianchong_path = run_dir / "tianchong.png"
    if tianchong_path_input.resolve() != tianchong_path.resolve():
        shutil.copy2(tianchong_path_input, tianchong_path)
        print(f"已复制填充图到输出目录: {tianchong_path}", flush=True)
    else:
        print(f"填充图已在输出目录，跳过复制: {tianchong_path}", flush=True)

    if presets_to_run is None:
        presets_to_run = list(PRESETS.keys())

    step1_by_preset: dict[str, Path] = {}
    all_step1_paths: list[Path] = []

    # --- Step 1b: wide（3320×500）从填充图裁切 ---
    need_wide = "wide" in presets_to_run
    step1_wide_path = None
    if need_wide:
        step1_wide_path = run_dir / f"step1_wide_temp_{uuid.uuid4().hex[:8]}.png"
        step1_wide_path = step1_wide_path.resolve()
        print("Step 1b: 填充图 → 3320×500（wide，cover + 顶部条带）...", flush=True)
        bbox_file = run_dir / "shared_subject_bbox.txt"
        cmd_wide = [
            PYTHON_EXE, str(PREPARE_SCRIPT), "--wide-from-fill",
            str(tianchong_path), str(step1_wide_path),
        ]
        if bbox_file.is_file():
            cmd_wide.extend(["--bbox-file", str(bbox_file)])
        r_wide = subprocess.run(cmd_wide, cwd=scripts_dir, env=env)
        if r_wide.returncode != 0 or not step1_wide_path.is_file():
            if step1_wide_path.is_file():
                step1_wide_path.unlink(missing_ok=True)
            print("Step 1b 失败，wide 将用填充图 cover 缩放", flush=True)
            step1_wide_path = None
        else:
            step1_wide_path = step1_wide_path.resolve()
            step1_by_preset["wide"] = step1_wide_path
            all_step1_paths.append(step1_wide_path)

    # --- Step 1c: legend_rec_2590（2590×392）单独裁切 ---
    need_legend_rec_2590 = "legend_rec_2590" in presets_to_run
    step1_legend_rec_2590_path = None
    if need_legend_rec_2590:
        step1_legend_rec_2590_path = run_dir / f"step1_legend_rec_2590_temp_{uuid.uuid4().hex[:8]}.png"
        step1_legend_rec_2590_path = step1_legend_rec_2590_path.resolve()
        print("Step 1c: 填充图 → 2590×392（legend_rec_2590）...", flush=True)
        cmd_2590 = [
            PYTHON_EXE, str(PREPARE_SCRIPT), "--crop-from-image",
            str(tianchong_path), str(step1_legend_rec_2590_path),
            "--preset", "legend_rec_2590", "--outpaint-after-crop",
        ]
        r_2590 = subprocess.run(cmd_2590, cwd=scripts_dir, env=env)
        if r_2590.returncode != 0 or not step1_legend_rec_2590_path.is_file():
            if step1_legend_rec_2590_path.is_file():
                step1_legend_rec_2590_path.unlink(missing_ok=True)
            print("Step 1c 失败，legend_rec_2590 将用填充图 cover 缩放", flush=True)
            step1_legend_rec_2590_path = None
        else:
            step1_legend_rec_2590_path = step1_legend_rec_2590_path.resolve()
            step1_by_preset["legend_rec_2590"] = step1_legend_rec_2590_path
            all_step1_paths.append(step1_legend_rec_2590_path)

    # --- 共用 bbox 检测（供其余尺寸 crop-from-image 复用）---
    crop_source = tianchong_path
    shared_bbox = None
    needs_crop_from_image = any(
        name in PRESETS and name not in step1_by_preset and name != "strip"
        for name in presets_to_run
    )
    if needs_crop_from_image:
        print("共用 bbox 检测（Gemini Vision）...", flush=True)
        _prepare_scripts = str(PREPARE_SCRIPT.parent)
        if _prepare_scripts not in sys.path:
            sys.path.insert(0, _prepare_scripts)
        try:
            from gemini_subject_detect import detect_subject_bbox
            shared_bbox = detect_subject_bbox(str(crop_source))
            if shared_bbox is None:
                print("  共用 bbox 检测失败，各尺寸将单独检测", flush=True)
            else:
                print(f"  共用 bbox: {shared_bbox}", flush=True)
                bbox_file = run_dir / "shared_subject_bbox.txt"
                bbox_file.write_text(
                    f"{shared_bbox[0]},{shared_bbox[1]},{shared_bbox[2]},{shared_bbox[3]}\n",
                    encoding="utf-8",
                )
        except Exception as e:
            print(f"  共用 bbox 检测异常（{e}），各尺寸将单独检测", flush=True)

    # --- 其余预设：从填充图裁切 ---
    for name in presets_to_run:
        if name not in PRESETS or name in step1_by_preset:
            continue
        w, h = PRESETS[name]
        step1_preset_path = run_dir / f"step1_{name}_{uuid.uuid4().hex[:8]}.png"
        step1_preset_path = step1_preset_path.resolve()

        if name == "strip":
            print(f"Step 1 strip ({w}×{h}): prepare_background 完整流程（含 A6/A6b）...", flush=True)
            cmd_strip = [
                PYTHON_EXE, str(PREPARE_SCRIPT), str(crop_source), str(step1_preset_path),
                "--preset", "strip", "--safe-zone-scale-outpaint", "--skip-a4-outpaint",
            ]
            r_strip = subprocess.run(cmd_strip, cwd=scripts_dir, env=env)
            if r_strip.returncode == 0 and step1_preset_path.is_file():
                step1_by_preset[name] = step1_preset_path
                all_step1_paths.append(step1_preset_path)
            else:
                if step1_preset_path.is_file():
                    step1_preset_path.unlink(missing_ok=True)
                print("  strip 失败，将用填充图", flush=True)
            continue

        print(f"Step 1 裁切 {name} ({w}×{h})...", flush=True)
        cmd_crop = [
            PYTHON_EXE, str(PREPARE_SCRIPT), "--crop-from-image",
            str(crop_source), str(step1_preset_path),
            "--preset", name, "--outpaint-after-crop",
        ]
        if shared_bbox is not None:
            cmd_crop += [
                "--subject-bbox-norm",
                str(shared_bbox[0]), str(shared_bbox[1]),
                str(shared_bbox[2]), str(shared_bbox[3]),
            ]
        r_crop = subprocess.run(cmd_crop, cwd=scripts_dir, env=env)
        if r_crop.returncode == 0 and step1_preset_path.is_file():
            step1_by_preset[name] = step1_preset_path
            all_step1_paths.append(step1_preset_path)
        else:
            if step1_preset_path.is_file():
                step1_preset_path.unlink(missing_ok=True)
            print(f"  {name} 裁切失败，将用填充图 cover 缩放", flush=True)

    # --- Step 2 前：合成联合 logo ---
    _LOGO2_PATH = ROOT / "scripts" / "assets" / "logo2.png"
    joint_logo_path = None
    if logo_path is not None and logo_path.is_file() and _LOGO2_PATH.is_file():
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from combine_joint_logo import combine_joint_logo
            _joint_out = run_dir / "joint_logo.png"
            combine_joint_logo(logo_path, _LOGO2_PATH, _joint_out)
            if _joint_out.is_file():
                joint_logo_path = _joint_out
                print(f"联合 logo 已合成: {joint_logo_path}", flush=True)
        except Exception as e:
            print(f"联合 logo 合成失败（跳过）: {e}", flush=True)

    # --- Step 2: 叠字合成 ---
    try:
        sys.path.insert(0, str(COMPOSER_SCRIPTS))
        from compose_banner import compose, _resolve_output_path

        print(f"\nStep 2: 叠字合成（主标题: {main_title!r}, 副标题: {subtitle!r}）", flush=True)
        for name in presets_to_run:
            if name not in PRESETS:
                continue
            w, h = PRESETS[name]
            out_name = OUTPUT_FILENAME_BY_PRESET.get(name) or f"banner_{name}_{w}x{h}.png"
            out_path = run_dir / out_name
            bg_path = step1_by_preset.get(name) or tianchong_path
            src_label = "裁切图" if name in step1_by_preset else "填充图 cover 缩放"
            print(f"  {name} ({w}x{h}) -> {out_path.name} [{src_label}]")
            _effective_logo = (
                str(joint_logo_path)
                if name == "legend_center_card" and joint_logo_path is not None
                else (str(logo_path) if logo_path else None)
            )
            compose(
                str(bg_path),
                str(out_path.resolve()),
                main_title,
                subtitle,
                width=w,
                height=h,
                use_ai_linebreak=True,
                logo_path=_effective_logo,
                preset=name,
            )
            resolved, _ = _resolve_output_path(str(out_path))
            print(f"    -> {resolved}")
        print("\nDone.", flush=True)
    finally:
        for p in all_step1_paths:
            if p is not None and p.is_file():
                p.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
