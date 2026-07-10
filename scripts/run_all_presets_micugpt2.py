#!/usr/bin/env python3
"""micugpt2 专用：用指定图片跑 prepare_background_micugpt2（A4 走 micugpt2），其余与 run_all_presets.py 完全一致。
仅 default（+ wide、legend_rec_2590 单独）做主体对齐裁切，其余尺寸共用同一张裁切图做 cover 缩放合成。"""
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
PREPARE_SCRIPT = ROOT / "scripts" / "prepare_background_micugpt2.py"
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
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt", help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY）")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt", help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY）")
    parser.add_argument("--lovart", "-lovart", action="store_true", dest="lovart", help="使用 Lovart AI 作为图编后端（去文字/扩图/图生图）")
    parser.add_argument("--text-art", default=None, dest="text_art", help="文字艺术字透明 PNG 路径（粘贴到 text_art_rect 区域）")
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
    _env_keys = ("GEMINI_API_KEY", "GEMINI_MODEL", "GOOGLE_GEMINI_BASE_URL", "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKYGPT_API_KEY", "XINGCHENGGPT_API_KEY", "T8STAR_API_KEY", "BANNER_IMAGE_BACKEND", "T8STAR_IMAGE_MODEL", "T8STAR_BASE_URL", "LOVART_ACCESS_KEY", "LOVART_SECRET_KEY", "LOVART_PROJECT_ID", "LOVART_BASE_URL", "LOVART_PREFER_MODELS", "LOVART_UNLIMITED_TIMEOUT", "LOVART_FAST_TIMEOUT", "HF_HUB_OFFLINE")
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
        if not getattr(args, "packygpt", False) and not getattr(args, "micugpt2", False) and not getattr(args, "xingchengpt", False):
            env["BANNER_IMAGE_BACKEND"] = "gemini"
    env["PYTHONPATH"] = scripts_dir + os.pathsep + env.get("PYTHONPATH", "")

    # 读取原始生图描述（Step 1 写入的 prompt.txt），传递给 bbox 检测以提升准确度
    _ctx_prompt = None
    _ctx_prompt_file = run_dir / "prompt.txt"
    if _ctx_prompt_file.is_file():
        _ctx_prompt = _ctx_prompt_file.read_text(encoding="utf-8").strip()
        if _ctx_prompt:
            print("  ✅ 已加载生图描述，将传递给 Vision 辅助主体检测", flush=True)

    # Step 1a: prepare_background default → 供 default / card-500 / card-304 / strip / 商店移动端 等合成（同一张图）
    # 当所有指定预设 no_text=True 时跳过（无叠字条幅不需要 default 画布）
    skip_remove = getattr(args, "skip_remove_text", False)
    if need_default:
        step1_path = run_dir / f"step1_temp_{uuid.uuid4().hex[:8]}.png"
        step1_path = step1_path.resolve()
        print("Step 1a: prepare_background ({}preset=default)...".format("" if skip_remove else "--remove-text "), flush=True)
        cmd = [
            PYTHON_EXE, str(PREPARE_SCRIPT), str(image_path), str(step1_path),
            "--preset", "default", "--safe-zone-scale-outpaint",
        ]
        if not skip_remove:
            cmd.append("--remove-text")
        if getattr(args, "skip_a4_outpaint", False):
            cmd.append("--skip-a4-outpaint")
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

    # Step 1b: 3320×500 专题长图。默认 bg-direct（源=bg，跳过 tianchong 依赖）；
    # WIDE_KEEP_TIANCHONG=1 回退旧 tianchong 源。注意：legacy 仍产出 tianchong（其它 preset 依赖），仅切 wide 取源。
    need_wide = presets_to_run is None or "wide" in presets_to_run
    _keep_tianchong = os.environ.get("WIDE_KEEP_TIANCHONG", "0").strip().lower() in ("1", "true", "yes", "on")
    step1_wide_path = None
    if need_wide:
        step1_wide_path = run_dir / f"step1_wide_temp_{uuid.uuid4().hex[:8]}.png"
        step1_wide_path = step1_wide_path.resolve()

    _fill_source = None
    if need_wide:
        if _keep_tianchong:
            if tianchong_path.is_file():
                _fill_source = tianchong_path
                print("Step 1b: [KEEP_TIANCHONG] 复用 tianchong → 3320×500...", flush=True)
            elif step1_path is not None and step1_path.is_file():
                _fill_source = step1_path
                print("Step 1b: [KEEP_TIANCHONG] (无 tianchong，用 step1 回退) → 3320×500...", flush=True)
        else:
            if Path(str(image_path)).is_file():
                _fill_source = image_path
                print("Step 1b: [bg-direct] 直接用 bg → 3320×500（fit-to-safe-zone + 侧翼填充 + A5b）...", flush=True)

    if _fill_source is not None:
        bbox_file = run_dir / "shared_subject_bbox.txt"
        cmd_wide = [
            PYTHON_EXE, str(PREPARE_SCRIPT), "--wide-from-fill", str(_fill_source), str(step1_wide_path),
        ]
        if bbox_file.is_file():
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
    # strip（专题头图 1740×220）走完整 prepare_background（含 A6/A6b），不用 --crop-from-image；
    # 其余用 --crop-from-image 从母图裁出；裁切后若检测到黑边则兜底补齐（--outpaint-after-crop）
    crop_source = tianchong_path if tianchong_path.is_file() else step1_path
    if not tianchong_path.is_file():
        print("未找到 tianchong.png，各尺寸从 Step 1a 产出裁切（图生图/跳过 A4 时）", flush=True)
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

    # 共用 bbox：对 crop_source 检测一次，供所有 --crop-from-image 复用，避免每个预设单独调用 Vision
    shared_bbox = None
    needs_crop_from_image = any(
        name in PRESETS and name not in step1_by_preset and name != "strip"
        for name in presets_to_run
    )
    # 商店日常 的 card-500/card-304/push112 均直接复用 default 背景，strip 独立检测 bbox，
    # 无任何 preset 实际消费 shared_subject_bbox.txt，跳过以节省 1 次 Vision 调用
    if needs_crop_from_image and args.genre and any(g.strip() == "商店日常" for g in args.genre):
        needs_crop_from_image = False
    if needs_crop_from_image:
        print("Step 1 共用 bbox 检测（Gemini Vision）...", flush=True)
        _prepare_scripts = str(PREPARE_SCRIPT.parent)
        if _prepare_scripts not in sys.path:
            sys.path.insert(0, _prepare_scripts)
        try:
            from gemini_subject_detect import detect_subject_bbox
            shared_bbox = detect_subject_bbox(str(crop_source), context_prompt=_ctx_prompt)
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
            # 传递原始生图描述，帮助 strip 的 Vision 主体检测更准确
            if _ctx_prompt and _ctx_prompt_file.is_file():
                cmd_strip.extend(["--context-prompt", str(_ctx_prompt_file)])
            # strip 使用直达画布路径，无需 --skip-a4-outpaint
            r_strip = subprocess.run(cmd_strip, cwd=scripts_dir, env=env)
            if r_strip.returncode == 0 and step1_preset_path.is_file():
                step1_by_preset[name] = step1_preset_path
                all_step1_paths.append(step1_preset_path)
            else:
                if step1_preset_path.is_file():
                    step1_preset_path.unlink(missing_ok=True)
                print("  strip prepare_background 失败，将用 default 图", flush=True)
            continue

        print(f"Step 1 {name} ({w}×{h}): 直接使用 step1 背景（由 compose cover-scale 填满画布）", flush=True)
        # 对于非特殊预设，跳过 --crop-from-image，由 compose_banner 的 _paste_background cover-scale 填满画布
        # 原因：Gemini 不可用时 crop-from-image 会将子图贴到黑画布导致大面积黑边

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
            bg_path = step1_by_preset.get(name) or step1_path or image_path
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
