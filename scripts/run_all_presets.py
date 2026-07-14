#!/usr/bin/env python3
"""用指定图片跑 prepare_background：仅 default（+ wide、legend_rec_2590 单独）做主体对齐裁切，其余尺寸共用同一张裁切图做 cover 缩放合成，保证同一批次背景为同一张图。"""
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Fix encoding for Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 路径约束验证
from _paths import validate_paths, sanitize_dirname
validate_paths()

from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
COMPOSER_SCRIPTS = ROOT / ".claude" / "skills" / "banner-composer" / "scripts"
PREPARE_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts" / "prepare_background.py"
UPLOAD_PATH_FILE = INPUT_DIR / "upload_path.txt"

# 从 banner-spec 读取规范（PRESETS、规范分组、输出文件名）
_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec
PRESETS = _spec.PRESETS
GENRE_PRESETS = _spec.GENRE_PRESETS
OUTPUT_FILENAME_BY_PRESET = _spec.OUTPUT_FILENAME_BY_PRESET
LAYOUT_BY_CANVAS = _spec.LAYOUT_BY_CANVAS


DEFAULT_INPUT_NAMES = ("uploads/current.png", "source.png", "source.jpg")


def _default_input_image() -> Path | None:
    """未传图片时，优先从 DB 自动提取，再回退到 input/ 下已有图片。"""
    if not INPUT_DIR.is_dir():
        return None
    from _paths import auto_extract_latest
    latest = auto_extract_latest()
    if latest:
        return latest
    for name in DEFAULT_INPUT_NAMES:
        p = INPUT_DIR / name
        if p.is_file():
            return p
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for p in sorted(INPUT_DIR.glob(ext)):
            if p.is_file():
                return p
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="图片 → prepare_background(default + wide 单独) → 同一张图按所有预设 cover 合成")
    parser.add_argument("image", nargs="?", default=None, help="输入图片路径；传 @ 或 upload 则从 input/upload_path.txt 读取（对话框上传后先运行 set_upload_image.py <路径>）；不填则用 input/source.png")
    parser.add_argument("--main-title", "-m", required=True, help="主标题")
    parser.add_argument("--subtitle", "-s", default="", help="副标题")
    parser.add_argument(
        "--genre",
        "-g",
        action="append",
        default=None,
        help="场景分组，可重复传入以合并多组预设，如 -g 商店日常 -g 开放平台；不填则跑全部预设",
    )
    parser.add_argument("--output-dir", default=None, help="指定输出目录（方案 A 调用时传入，与 Step 1 产出的 bg.png 同目录）；不填则自动创建 分组_主标题_时间戳")
    parser.add_argument("--skip-a4-outpaint", action="store_true", help="文生图/有参考图流程时传入，跳过 A4 延展填满；用户直接给图时不传")
    parser.add_argument("--skip-remove-text", action="store_true", dest="skip_remove_text", help="跳过 A1 去干扰（Gemini remove-text），避免比例变形；仅用原图做主体检测与裁切")
    parser.add_argument("--packy", "-packy", action="store_true", dest="packy", help="使用 Packy API 作为 Gemini 后端")
    parser.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s", help="使用 Packy7s 专用 key 作为 Gemini 后端（需 .env 中 PACKY7S_API_KEY）")
    parser.add_argument("--packy3s", "-packy3s", action="store_true", dest="packy3s", help="使用 Packy3s 专用 key 作为 Gemini 后端（需 .env 中 PACKY3S_API_KEY）")
    parser.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt", help="使用 PackyGPT 专用 key 调用 gpt-image-2（需 .env 中 PACKYGPT_API_KEY）")
    parser.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2", help="使用 MicuAPI 专用 key 调用 gpt-image-2（需 .env 中 MICUAPI_API_KEY）")
    parser.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini", help="使用 MicuAPI 专用 key 调用 gemini-3-flash-preview-thinking（需 .env 中 MICUGEMINI_API_KEY）")
    parser.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini", help="使用 XingchenGemini 专用 key 调用 gemini-3.1-flash-image-preview（需 .env 中 XINGCHENGEMINI_API_KEY）")
    parser.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1", help="使用 XingchenGemini 多 Key 轮换 1 号 key（需 .env 中 XINGCHENGEMINI1_API_KEY）")
    parser.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt", help="使用 MoxinGPT 专用 key 调用 gpt-image-2（需 .env 中 MOXINGPT_API_KEY）")
    parser.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini", help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY）")
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt", help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY）")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt", help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY）")
    parser.add_argument("--lovart", "-lovart", action="store_true", dest="lovart", help="使用 Lovart AI 作为图编后端（去文字/扩图/图生图）")
    parser.add_argument("--text-art", default=None, dest="text_art", help="文字艺术字透明 PNG 路径（粘贴到 text_art_rect 区域）")
    parser.add_argument("--text-art-prompt", "-P", default=None, dest="text_art_prompt", help="艺术字文本描述（走生成管线：即梦/Gemini生成->BiRefNet抠图")
    parser.add_argument("--dialog", default=None, dest="dialog", help="对话框透明 PNG 路径（粘贴到 dialog_rect 区域）")
    args = parser.parse_args()

    logo_path = None
    if args.image and args.image.strip() not in ("@", "upload", "对话框上传"):
        image_path = Path(args.image.strip().strip('"\'')).resolve()
    elif args.image and args.image.strip() in ("@", "upload", "对话框上传"):
        from _paths import auto_extract_latest
        auto_extract_latest()
        if not UPLOAD_PATH_FILE.is_file():
            print("Error: 未找到 input/upload_path.txt。请输入任意图片到对话框后重试。", file=sys.stderr)
            sys.exit(1)
        with open(UPLOAD_PATH_FILE, "r", encoding="utf-8") as f:
            lines = [ln.strip().strip('"\'') for ln in f.readlines() if ln.strip()]
        if not lines:
            print("Error: input/upload_path.txt 为空。", file=sys.stderr)
            sys.exit(1)
        image_path = Path(lines[0]).resolve()
        logo_path = Path(lines[1]).resolve() if len(lines) > 1 and lines[1] else None
        if logo_path is not None and not logo_path.is_file():
            logo_path = None
        print(f"使用对话框上传图片: 背景={image_path}", flush=True)
        if logo_path:
            print(f"  logo={logo_path}", flush=True)
    else:
        image_path = _default_input_image()
        if image_path is None:
            print("Error: 未指定图片，input/ 下没有可用图片，且未在对话框中上传。", file=sys.stderr)
            print("请上传图片到对话框后重试，或指定图片路径。", file=sys.stderr)
            print("对话框上传：先运行 python scripts/set_upload_image.py <图片路径>，再运行 run_all_presets.py @ ...", file=sys.stderr)
            sys.exit(1)
        print(f"使用默认输入图片: {image_path}", flush=True)
    if not image_path.is_file():
        print(f"Error: 未找到图片 {image_path}", file=sys.stderr)
        sys.exit(1)

    main_title = args.main_title
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
        # 当所有指定预设的 no_text=True 时，跳过 default（无叠字预设不需要 default 画布）
        _all_no_text = bool(merged)
        for p in merged:
            w, h = PRESETS.get(p, (0, 0))
            layout = LAYOUT_BY_CANVAS.get((w, h), {})
            if not layout.get("no_text", False):
                _all_no_text = False
                break
        if _all_no_text:
            need_default = False
            print(f"所有指定预设均为无文字条幅，跳过 default 预设处理", flush=True)
        else:
            need_default = True
    else:
        presets_to_run = None  # 不填 -g 时跑全部，在 import PRESETS 后设为 list(PRESETS.keys())
        need_default = True

    # 本次运行输出到独立子目录，全部保留；若由方案 A 传入 --output-dir 则直接使用
    if getattr(args, "output_dir", None) and str(args.output_dir).strip():
        run_dir = Path(args.output_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"本次输出目录（已指定）: {run_dir}", flush=True)
    else:
        genre_label = (
            sanitize_dirname("+".join((g or "").strip() for g in args.genre))
            if args.genre
            else "all"
        )
        title_safe = sanitize_dirname(main_title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = OUTPUT_DIR / f"{genre_label}_{title_safe}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"本次输出目录: {run_dir}", flush=True)

    # 加载 .env 中的 API 与后端配置（GEMINI_API_KEY、T8STAR_API_KEY 等）；勿提交 .env
    from _env import load_env
    _env_keys = ("GEMINI_API_KEY", "GEMINI_MODEL", "GOOGLE_GEMINI_BASE_URL", "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKYGPT_API_KEY", "MICUAPI_API_KEY", "MICUGEMINI_API_KEY", "XINGCHENGEMINI_API_KEY", "XINGCHENGEMINI1_API_KEY", "MOXINGPT_API_KEY", "MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL", "XINGCHENGGPT_API_KEY", "XINCHENGPT_API_KEY", "T8STAR_API_KEY", "BANNER_IMAGE_BACKEND", "T8STAR_IMAGE_MODEL", "T8STAR_BASE_URL", "LOVART_ACCESS_KEY", "LOVART_SECRET_KEY", "LOVART_PROJECT_ID", "LOVART_BASE_URL", "LOVART_PREFER_MODELS", "LOVART_UNLIMITED_TIMEOUT", "LOVART_FAST_TIMEOUT", "HF_HUB_OFFLINE")
    load_env(_env_keys)
    from _packy import apply_packy_backend
    apply_packy_backend(args)

    if getattr(args, "lovart", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "nano-banana"
        os.environ["LOVART_USE_FOR_ALL"] = "1"
        print("使用 Lovart AI 作为图编后端", flush=True)
        _lovart_keys = ("LOVART_ACCESS_KEY", "LOVART_SECRET_KEY", "LOVART_PROJECT_ID", "LOVART_BASE_URL")
        load_env(_lovart_keys, override=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scripts_dir = str(PREPARE_SCRIPT.parent)
    env = os.environ.copy()
    # Packy7s 渠道对部分 Vision/图编模型可能不开放。
    # 仅在用户未显式配置时使用安全默认值，已配置则尊重用户选择。
    if getattr(args, "packy7s", False):
        env.setdefault("GEMINI_MODEL", "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview")
        env.setdefault("GEMINI_VISION_MODEL", "gemini-3.1-pro-preview,gemini-3-flash-preview")
        if not getattr(args, "packygpt", False) and not getattr(args, "micugpt2", False) and not getattr(args, "micugemini", False) and not getattr(args, "moxingpt", False) and not getattr(args, "moxingemini", False) and not getattr(args, "xingchengpt", False):
            env["BANNER_IMAGE_BACKEND"] = "gemini"
    if getattr(args, "micugemini", False) and not getattr(args, "packy7s", False):
        env["GOOGLE_GEMINI_BASE_URL"] = "https://www.micuapi.ai"
        env["GEMINI_API_KEY"] = os.environ.get("MICUGEMINI_API_KEY", "")
        env["BANNER_IMAGE_BACKEND"] = "micugemini"
    if getattr(args, "xingchengemini", False) and not getattr(args, "packy7s", False) and not getattr(args, "xingchengpt", False):
        env["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk").strip()
        env["GEMINI_API_KEY"] = os.environ.get("XINGCHENGEMINI_API_KEY", "")
        env.setdefault("GEMINI_MODEL", "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview")
        env.setdefault("GEMINI_VISION_MODEL", "gemini-3.1-flash-image-preview")
        env["BANNER_IMAGE_BACKEND"] = "gemini"
    if getattr(args, "moxingemini", False) and not getattr(args, "packy7s", False) and not getattr(args, "moxingpt", False):
        env["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").strip()
        env["GEMINI_API_KEY"] = os.environ.get("MOXINGEMINI_API_KEY", "")
        env.setdefault("GEMINI_MODEL", env.get("MOXINGEMINI_MODEL", "[特价次卡]gemini-3.1-pro-preview,[次]gemini-3-pro-image"))
        env.setdefault("GEMINI_VISION_MODEL", env.get("MOXINGEMINI_VISION_MODEL", "[特价次卡]gemini-3.1-pro-preview,[特价次卡]gemini-3.1-pro-preview-think,[特价次卡]gemini-2.5-pro"))
        env["BANNER_IMAGE_BACKEND"] = "gemini"
    if getattr(args, "xingchengemini1", False) and not getattr(args, "packy7s", False) and not getattr(args, "xingchengpt", False):
        env["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI1_BASE_URL", os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk")).strip()
        env["GEMINI_API_KEY"] = os.environ.get("XINGCHENGEMINI1_API_KEY", "")
        env.setdefault("GEMINI_MODEL", "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview")
        env.setdefault("GEMINI_VISION_MODEL", "gemini-3.1-flash-image-preview")
        env["BANNER_IMAGE_BACKEND"] = "gemini"
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    # 读取原始生图描述（Step 1 写入的 prompt.txt），传递给 bbox 检测以提升准确度
    _ctx_prompt = None
    _ctx_prompt_file = run_dir / "prompt.txt"
    if _ctx_prompt_file.is_file():
        _ctx_prompt = _ctx_prompt_file.read_text(encoding="utf-8").strip()
        if _ctx_prompt:
            print("  ✅ 已加载生图描述，将传递给 Vision 辅助主体检测", flush=True)

    # 直达画布预设集合（不使用 A4 2048×512，直接 S4→S5→S6）
    DIRECT_TO_CANVAS_PRESETS = {"default"}

    skip_remove = getattr(args, "skip_remove_text", False)
    # wide 默认走 bg-direct（跳过 tianchong/A4）；WIDE_KEEP_TIANCHONG=1 回退旧 tianchong 流程
    _keep_tianchong = os.environ.get("WIDE_KEEP_TIANCHONG", "0").strip().lower() in ("1", "true", "yes", "on")

    # Step 0: 共享 A1 去干扰 + A2 bbox 检测（在 bg.png 上执行一次）
    shared_bbox_path = run_dir / "shared_subject_bbox.txt"
    shared_bbox = None
    cleaned_bg_for_direct: Path = image_path
    if not skip_remove:
        _pb_scripts = str(PREPARE_SCRIPT.parent)
        if _pb_scripts not in sys.path:
            sys.path.insert(0, _pb_scripts)
        from prepare_background import _remove_text_with_gemini
        print("Step 0a / 共享 A1 去干扰...", flush=True)
        _cleaned = _remove_text_with_gemini(str(image_path))
        if _cleaned is not None:
            cleaned_bg_for_direct = _cleaned
    else:
        print("Step 0a / 跳过去干扰（--skip-remove-text）", flush=True)

    try:
        _pb_scripts2 = str(PREPARE_SCRIPT.parent)
        if _pb_scripts2 not in sys.path:
            sys.path.insert(0, _pb_scripts2)
        from gemini_subject_detect import detect_subject_bbox
        print("Step 0b / 共享 A2 bbox 检测（Gemini Vision）...", flush=True)
        _shared_bbox = detect_subject_bbox(str(cleaned_bg_for_direct), context_prompt=_ctx_prompt)
        if _shared_bbox is None:
            raise RuntimeError("共享 bbox 检测失败")
        shared_bbox = _shared_bbox
        shared_bbox_path.write_text(
            f"{shared_bbox[0]},{shared_bbox[1]},{shared_bbox[2]},{shared_bbox[3]}\n",
            encoding="utf-8",
        )
        print(f"  shared_bbox: {shared_bbox}", flush=True)
    except Exception as e:
        print(f"Error: Step 0 共享检测失败: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 1a: prepare_background default → 直达画布路径 S4→S5→S6（同时产出 tianchong.png 供 wide）
    # 当所有指定预设 no_text=True 时跳过（无叠字条幅不需要 default 画布）
    if need_default:
        step1_path = run_dir / f"step1_temp_{uuid.uuid4().hex[:8]}.png"
        step1_path = step1_path.resolve()
        print("Step 1a: prepare_background (default 1976×464, --direct-to-canvas)...", flush=True)
        cmd = [
            PYTHON_EXE, str(PREPARE_SCRIPT), str(cleaned_bg_for_direct), str(step1_path),
            "--preset", "default", "--safe-zone-scale-outpaint",
            "--direct-to-canvas",
            "--bbox", str(shared_bbox[0]), str(shared_bbox[1]), str(shared_bbox[2]), str(shared_bbox[3]),
        ]
        if _ctx_prompt and _ctx_prompt_file.is_file():
            cmd.extend(["--context-prompt", str(_ctx_prompt_file)])
        r = subprocess.run(cmd, cwd=scripts_dir, env=env)
        if r.returncode != 0:
            if step1_path.is_file():
                step1_path.unlink(missing_ok=True)
            print("prepare_background 失败（需要 GEMINI_API_KEY 且网络可用）", file=sys.stderr)
            sys.exit(r.returncode)
        if not step1_path.is_file():
            print(f"Error: Step 1a 产出不存在: {step1_path}", file=sys.stderr)
            sys.exit(1)

        # 备份 default 填充图，保证 tianchong.png 最终为「最终过程稿」（Step 1c 若运行会覆盖，届时恢复）
        tianchong_final_path = run_dir / "tianchong_final.png"
        tianchong_path = run_dir / "tianchong.png"
        if tianchong_path.is_file():
            shutil.copy2(tianchong_path, tianchong_final_path)
            print("已备份 tianchong.png 为最终过程稿（tianchong_final.png）", flush=True)
    else:
        step1_path = None
        tianchong_path = Path("_not_used_")
        tianchong_final_path = Path("_not_used_")

    # Step 1b: 3320×500 专题长图。
    # 默认 bg-direct：直接用去干扰后的 bg + shared_subject_bbox.txt（Step 0b 已在 bg 上检测），
    #   wide_from_fill 内部做 fit-to-safe-zone + 侧翼 Gemini mask 填充 + A5b 抠图。
    # WIDE_KEEP_TIANCHONG=1：回退旧流程（tianchong 源 + tianchong 上独立检测 bbox）。
    need_wide = presets_to_run is None or "wide" in presets_to_run

    if need_wide and _keep_tianchong:
        # ── 旧流程：在填充源图（tianchong/step1）上独立检测 bbox → tianchong_bbox.txt ──
        _bbox_file_early = run_dir / "tianchong_bbox.txt"
        _early_fill = (
            tianchong_path if tianchong_path.is_file()
            else (step1_path if step1_path is not None and step1_path.is_file() else None)
        )
        if _early_fill is not None:
            try:
                _pb_scripts = str(PREPARE_SCRIPT.parent)
                if _pb_scripts not in sys.path:
                    sys.path.insert(0, _pb_scripts)
                from gemini_subject_detect import detect_subject_bbox
                print("Step 1b 前置 bbox 检测（Gemini Vision）...", flush=True)
                _early_bbox = detect_subject_bbox(str(_early_fill), context_prompt=_ctx_prompt)
                if _early_bbox:
                    _bbox_file_early.write_text(
                        f"{_early_bbox[0]},{_early_bbox[1]},{_early_bbox[2]},{_early_bbox[3]}\n",
                        encoding="utf-8",
                    )
                    print(f"  Step 1b 前置 bbox (tianchong): {_early_bbox}", flush=True)
                else:
                    print("  Step 1b 前置 bbox 检测失败，wide 将用居中裁切", flush=True)
            except Exception as _e:
                print(f"  Step 1b 前置 bbox 检测异常（{_e}），wide 将用居中裁切", flush=True)

    step1_wide_path = None
    if need_wide:
        step1_wide_path = run_dir / f"step1_wide_temp_{uuid.uuid4().hex[:8]}.png"
        step1_wide_path = step1_wide_path.resolve()

    _fill_source = None
    bbox_file = None
    if need_wide:
        if _keep_tianchong:
            # 旧流程：优先 tianchong，回退 step1；bbox 优先 tianchong_bbox.txt，回退 shared
            if tianchong_path.is_file():
                _fill_source = tianchong_path
                print("Step 1b: [KEEP_TIANCHONG] 复用 tianchong → 3320×500...", flush=True)
            elif step1_path is not None and step1_path.is_file():
                _fill_source = step1_path
                print("Step 1b: [KEEP_TIANCHONG] (无 tianchong，用 step1 回退) → 3320×500...", flush=True)
            _tc_bbox = run_dir / "tianchong_bbox.txt"
            _shared_bbox = run_dir / "shared_subject_bbox.txt"
            bbox_file = _tc_bbox if _tc_bbox.is_file() else (_shared_bbox if _shared_bbox.is_file() else None)
        else:
            # 默认 bg-direct：源=去干扰后的 bg，bbox=shared_subject_bbox.txt（bg 上检测）
            if Path(str(cleaned_bg_for_direct)).is_file():
                _fill_source = cleaned_bg_for_direct
                print("Step 1b: [bg-direct] 直接用 bg → 3320×500（fit-to-safe-zone + 侧翼填充 + A5b）...", flush=True)
            _shared_bbox = run_dir / "shared_subject_bbox.txt"
            bbox_file = _shared_bbox if _shared_bbox.is_file() else None

    if _fill_source is not None:
        cmd_wide = [
            PYTHON_EXE, str(PREPARE_SCRIPT), "--wide-from-fill", str(_fill_source), str(step1_wide_path),
        ]
        if bbox_file:
            cmd_wide.extend(["--bbox-file", str(bbox_file)])
        r_wide = subprocess.run(cmd_wide, cwd=scripts_dir, env=env)
        if r_wide.returncode != 0 or not step1_wide_path.is_file():
            if step1_wide_path.is_file():
                step1_wide_path.unlink(missing_ok=True)
            print("Step 1b 失败（3320×500 将用 default 图 cover 缩放）", flush=True)
            step1_wide_path = None
        else:
            step1_wide_path = step1_wide_path.resolve()
    elif need_wide:
        print("未找到可用源图，跳过 Step 1b（3320×500 将用 default 图）", flush=True)
        step1_wide_path = None

    # Step 1c: 2590×392（legend_rec_2590）单独 — 仅当该 preset 在列表中时跑
    need_legend_rec_2590 = presets_to_run is None or "legend_rec_2590" in presets_to_run
    step1_legend_rec_2590_path = None
    if need_legend_rec_2590:
        step1_legend_rec_2590_path = run_dir / f"step1_legend_rec_2590_temp_{uuid.uuid4().hex[:8]}.png"
        step1_legend_rec_2590_path = step1_legend_rec_2590_path.resolve()
        print("Step 1c: prepare_background ({}preset=legend_rec_2590) 2590×392...".format("" if skip_remove else "--remove-text "), flush=True)
        cmd_2590 = [
            PYTHON_EXE, str(PREPARE_SCRIPT), str(image_path), str(step1_legend_rec_2590_path),
            "--preset", "legend_rec_2590", "--safe-zone-scale-outpaint",
        ]
        if not skip_remove:
            cmd_2590.append("--remove-text")
        if getattr(args, "skip_a4_outpaint", False):
            cmd_2590.append("--skip-a4-outpaint")
        r_2590 = subprocess.run(cmd_2590, cwd=scripts_dir, env=env)
        if r_2590.returncode != 0 or not step1_legend_rec_2590_path.is_file():
            if step1_legend_rec_2590_path.is_file():
                step1_legend_rec_2590_path.unlink(missing_ok=True)
            print("prepare_background legend_rec_2590 失败（将用 default 图 cover 缩放）", flush=True)
            step1_legend_rec_2590_path = None
        else:
            step1_legend_rec_2590_path = step1_legend_rec_2590_path.resolve()
        # Step 1c 会覆盖 run_dir/tianchong.png，恢复为 default 填充（最终过程稿）
        if step1_legend_rec_2590_path is not None and tianchong_final_path.is_file():
            shutil.copy2(tianchong_final_path, tianchong_path)
            print("已恢复 tianchong.png 为 default 填充（最终过程稿）", flush=True)
    else:
        step1_legend_rec_2590_path = None

    # Step 1d: 3840×1200（legend_home_3840）单独 — 超宽比例（3.2:1），需专用 prepare_background 避免 cover 严重裁切
    need_legend_home_3840 = presets_to_run is None or "legend_home_3840" in presets_to_run
    step1_legend_home_3840_path = None
    if need_legend_home_3840:
        step1_legend_home_3840_path = run_dir / f"step1_legend_home_3840_temp_{uuid.uuid4().hex[:8]}.png"
        step1_legend_home_3840_path = step1_legend_home_3840_path.resolve()
        print("Step 1d: prepare_background ({}preset=legend_home_3840) 3840×1200...".format("" if skip_remove else "--remove-text "), flush=True)
        cmd_home3840 = [
            PYTHON_EXE, str(PREPARE_SCRIPT), str(image_path), str(step1_legend_home_3840_path),
            "--preset", "legend_home_3840", "--safe-zone-scale-outpaint",
        ]
        if not skip_remove:
            cmd_home3840.append("--remove-text")
        if getattr(args, "skip_a4_outpaint", False):
            cmd_home3840.append("--skip-a4-outpaint")
        if _ctx_prompt and _ctx_prompt_file.is_file():
            cmd_home3840.extend(["--context-prompt", str(_ctx_prompt_file)])
        r_home3840 = subprocess.run(cmd_home3840, cwd=scripts_dir, env=env)
        if r_home3840.returncode != 0 or not step1_legend_home_3840_path.is_file():
            if step1_legend_home_3840_path.is_file():
                step1_legend_home_3840_path.unlink(missing_ok=True)
            print("prepare_background legend_home_3840 失败（将用 default 图 cover 缩放）", flush=True)
            step1_legend_home_3840_path = None
        else:
            step1_legend_home_3840_path = step1_legend_home_3840_path.resolve()
        # Step 1d 会覆盖 run_dir/tianchong.png，恢复为 default 填充（最终过程稿）
        if step1_legend_home_3840_path is not None and tianchong_final_path.is_file():
            shutil.copy2(tianchong_final_path, tianchong_path)
            print("已恢复 tianchong.png 为 default 填充（最终过程稿）", flush=True)
    else:
        step1_legend_home_3840_path = None

    # 每个规范尺寸都做「主体 bbox 缩放到安全区 90%% 中心对齐裁切」：已有 default / wide / legend_rec_2590 / legend_home_3840；
    step1_by_preset = {"default": step1_path}
    if step1_wide_path is not None:
        step1_by_preset["wide"] = step1_wide_path
    if step1_legend_rec_2590_path is not None:
        step1_by_preset["legend_rec_2590"] = step1_legend_rec_2590_path
    if step1_legend_home_3840_path is not None:
        step1_by_preset["legend_home_3840"] = step1_legend_home_3840_path
    all_step1_paths = [step1_path, step1_wide_path, step1_legend_rec_2590_path, step1_legend_home_3840_path]
    if presets_to_run is None:
        presets_to_run = list(PRESETS.keys())

    for name in presets_to_run:
        if name not in PRESETS or name in step1_by_preset:
            continue
        w, h = PRESETS[name]
        step1_preset_path = run_dir / f"step1_{name}_{uuid.uuid4().hex[:8]}.png"
        step1_preset_path = step1_preset_path.resolve()

        if name == "strip":
            print(
                f"Step 1 专题头图 strip ({w}×{h}): prepare_background 直达画布路径（绕过 A4 2048×512 → A5 裁切）...",
                flush=True,
            )
            cmd_strip = [
                PYTHON_EXE,
                str(PREPARE_SCRIPT),
                str(image_path),
                str(step1_preset_path),
                "--preset",
                "strip",
                "--safe-zone-scale-outpaint",
            ]
            if not skip_remove:
                cmd_strip.append("--remove-text")
            if _ctx_prompt and _ctx_prompt_file.is_file():
                cmd_strip.extend(["--context-prompt", str(_ctx_prompt_file)])
            r_strip = subprocess.run(cmd_strip, cwd=scripts_dir, env=env)
            if r_strip.returncode == 0 and step1_preset_path.is_file():
                step1_by_preset[name] = step1_preset_path
                all_step1_paths.append(step1_preset_path)
            else:
                if step1_preset_path.is_file():
                    step1_preset_path.unlink(missing_ok=True)
                print("  strip prepare_background 失败，将用 default 图", flush=True)
            continue

        # 生成式UI封面 1536×1024：直达画布 + API 填充，复用 Step 0 的 shared_bbox 和 cleaned_bg
        if name == "shop_mobile_generative_ui_cover_1536" and shared_bbox is not None:
            print(
                f"Step 1 {name} ({w}×{h}): prepare_background --direct-to-canvas（主体直贴 1536×1024 + API 填充）...",
                flush=True,
            )
            cmd_genui = [
                PYTHON_EXE,
                str(PREPARE_SCRIPT),
                str(cleaned_bg_for_direct),
                str(step1_preset_path),
                "--preset",
                name,
                "--safe-zone-scale-outpaint",
                "--direct-to-canvas",
                "--width-fit",
                "--bbox", str(shared_bbox[0]), str(shared_bbox[1]), str(shared_bbox[2]), str(shared_bbox[3]),
            ]
            if _ctx_prompt and _ctx_prompt_file.is_file():
                cmd_genui.extend(["--context-prompt", str(_ctx_prompt_file)])
            r_genui = subprocess.run(cmd_genui, cwd=scripts_dir, env=env)
            if r_genui.returncode == 0 and step1_preset_path.is_file():
                step1_by_preset[name] = step1_preset_path
                all_step1_paths.append(step1_preset_path)
            else:
                if step1_preset_path.is_file():
                    step1_preset_path.unlink(missing_ok=True)
                print(f"  {name} 直达画布失败，将用 default 图", flush=True)
            continue

        # 直达画布预设：S4→S5→S6，复用 Step 0 的 shared_bbox 和 cleaned_bg
        if name in DIRECT_TO_CANVAS_PRESETS and shared_bbox is not None:
            print(
                f"Step 1 {name} ({w}×{h}): prepare_background --direct-to-canvas（绕过 A4 2048×512）...",
                flush=True,
            )
            cmd_direct = [
                PYTHON_EXE,
                str(PREPARE_SCRIPT),
                str(cleaned_bg_for_direct),
                str(step1_preset_path),
                "--preset",
                name,
                "--safe-zone-scale-outpaint",
                "--direct-to-canvas",
                "--bbox", str(shared_bbox[0]), str(shared_bbox[1]), str(shared_bbox[2]), str(shared_bbox[3]),
            ]
            if _ctx_prompt and _ctx_prompt_file.is_file():
                cmd_direct.extend(["--context-prompt", str(_ctx_prompt_file)])
            r_direct = subprocess.run(cmd_direct, cwd=scripts_dir, env=env)
            if r_direct.returncode == 0 and step1_preset_path.is_file():
                step1_by_preset[name] = step1_preset_path
                all_step1_paths.append(step1_preset_path)
            else:
                if step1_preset_path.is_file():
                    step1_preset_path.unlink(missing_ok=True)
                print(f"  {name} 直达画布失败，将用 default 图", flush=True)
            continue

        print(f"Step 1 {name} ({w}×{h}): 直接使用 step1 背景（由 compose cover-scale 填满画布）", flush=True)

    # Step 2 前：为 legend_center_card 合成联合 logo
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

    try:
        sys.path.insert(0, str(COMPOSER_SCRIPTS))
        from compose_banner import compose, _resolve_output_path

        print(f"Step 2: compose 所有规范（主标题: {main_title!r}, 副标题: {subtitle!r}）")
        for name in presets_to_run:
            if name not in PRESETS:
                continue
            w, h = PRESETS[name]
            out_name = OUTPUT_FILENAME_BY_PRESET.get(name) or f"banner_{name}_{w}x{h}.png"
            out_path = run_dir / out_name
            bg_path = image_path if name == "default" else (step1_by_preset.get(name) or image_path or step1_path)
            if bg_path is None or not Path(str(bg_path)).is_file():
                print(f"  {name} ({w}x{h}): 无可用背景图，跳过", flush=True)
                continue
            if step1_by_preset.get(name) is not None:
                print(f"  {name} ({w}x{h}) -> {out_path.name} [背景: 该尺寸主体安全区裁切]")
            else:
                print(f"  {name} ({w}x{h}) -> {out_path.name} [背景: default 裁切]")
            _effective_logo = (
                str(joint_logo_path)
                if name == "legend_center_card" and joint_logo_path is not None
                else (str(logo_path) if logo_path else None)
            )

            # shop_mobile_nav_icon 走专用合成管线（圆形+主体+艺术字），不走标准 compose
            if name == "shop_mobile_nav_icon":
                print(f"  {name} ({w}x{h}) -> {out_path.name} [专用管线: 圆形+主体+艺术字]")
                cmd_nav = [
                    PYTHON_EXE,
                    str(ROOT / "scripts" / "compose_nav_icon.py"),
                    "--subject", str(image_path),
                    "--output", str(out_path.resolve()),
                ]
                if getattr(args, "text_art", None):
                    cmd_nav.extend(["--text-art", str(args.text_art)])
                if getattr(args, "text_art_prompt", None):
                    cmd_nav.extend(["--text-art-prompt", args.text_art_prompt])
                r_nav = subprocess.run(cmd_nav, cwd=scripts_dir, env=env)
                if r_nav.returncode != 0:
                    print(f"    compose_nav_icon 失败: {name}", flush=True)
                resolved, _ = _resolve_output_path(str(out_path))
                print(f"    -> {resolved}")
                continue

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
                text_art_path=getattr(args, "text_art", None),
                dialog_path=getattr(args, "dialog", None),
                subject_bbox=shared_bbox if name == "shop_mobile_generative_ui_cover_1536" else None,
            )
            resolved, _ = _resolve_output_path(str(out_path))
            print(f"    -> {resolved}")
        print("Done.")

        # 列出本次输出目录下所有文件，方便在 IDE 文件树未刷新时确认产物
        files = sorted(run_dir.glob("*")) if run_dir.is_dir() else []
        if files:
            print(f"\n📁 本次输出目录（{run_dir}）：")
            for f in files:
                if f.is_file():
                    size_kb = f.stat().st_size / 1024
                    print(f"  {f.name}  ({size_kb:.1f} KB)")
    finally:
        for p in all_step1_paths:
            if p is not None and getattr(p, "is_file", None) and p.is_file():
                p.unlink(missing_ok=True)
        # 输出目录只保留 tianchong.png（tianchong_final.png 仅流程中用于恢复）
        if tianchong_final_path.is_file():
            tianchong_final_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
