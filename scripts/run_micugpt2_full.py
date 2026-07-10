#!/usr/bin/env python3
"""
micugpt2 专用全流程入口。
替代 run_full_with_custom_prompt.py，硬编码 micugpt2 后端。所有操作走 micugpt2。

用法：
  py scripts/run_micugpt2_full.py -g 商店日常 -m "主标题" -s "副标题" --skip-remove-text -i input/xxx.png
  py scripts/run_micugpt2_full.py -g 商店日常 -m "主标题" --description "背景描述..."
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from _paths import validate_paths, sanitize_dirname
validate_paths()

_ENV_FILE = ROOT / ".env"
_ENV_KEYS = (
    "MICUAPI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_PROMPT_OPTIMIZER_MODEL",
    "ANTHROPIC_API_BASE_URL",
    "BANNER_IMAGE_BACKEND",
)
if _ENV_FILE.is_file():
    with open(_ENV_FILE, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if "=" in _line and not _line.startswith("#"):
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                _v = _v.strip().strip("'\"").strip()
                if _k in _ENV_KEYS and _v:
                    if _k not in os.environ:
                        os.environ[_k] = _v

sys.path.insert(0, str(ROOT))
from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()
OUTPUT_DIR = ROOT / "output"

STEP1_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts" / "generate_from_description.py"
STEP2_PRESETS_SCRIPT = ROOT / "scripts" / "run_all_presets_micugpt2.py"
MOBILE_SCRIPT = ROOT / "scripts" / "run_mobile_presets.py"

OPEN_PLATFORM_DEFAULT_REF = ROOT / "input" / "open_platform_style_ref.png"

_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec


def main() -> None:
    parser = argparse.ArgumentParser(
        description="micugpt2 专用全流程入口 — Step 1 生图 + Step 2 背景处理 + 叠字",
    )
    parser.add_argument("--description", default=None, help="整段生图描述（与 --description-file 二选一）")
    parser.add_argument("--description-file", dest="description_file", default=None, help="从 UTF-8 文件读取生图描述")
    parser.add_argument("--main-title", "-m", default=None, dest="main_title", help="主标题")
    parser.add_argument("--main-title-file", dest="main_title_file", default=None, help="从 UTF-8 文件读取主标题")
    parser.add_argument("--subtitle", "-s", default="", dest="subtitle", help="副标题")
    parser.add_argument("--subtitle-file", dest="subtitle_file", default=None, help="从 UTF-8 文件读取副标题")
    parser.add_argument("--ref", "-i", dest="ref", default=None, help="可选：Step 1 参考图路径（i2i）")
    parser.add_argument("--group", "-g", dest="genre_groups", action="append", default=None, help="场景分组，可重复传入")
    parser.add_argument("--group-file", dest="group_file", default=None, help="从 UTF-8 文件读取分组名")
    parser.add_argument("--prompt-engine", action="store_true", dest="prompt_engine", help="用 prompt-engine 调用 Gemini 生成描述")
    parser.add_argument("--prompt-engine-claude", action="store_true", dest="prompt_engine_claude", help="用 prompt-engine 调用 Claude 生成描述")
    parser.add_argument("--prompt-optimizer-template", action="store_true", dest="prompt_optimizer_template", help="用确定性模板引擎生成描述")
    parser.add_argument("--mode", default="auto", choices=("auto", "product", "campaign", "collection"), dest="mode")
    parser.add_argument("--subject", default="", dest="subject")
    parser.add_argument("--prompt-format", default="compact", choices=("compact", "full"), dest="prompt_format")
    parser.add_argument("--text-art", default=None, dest="text_art", metavar="DESC", help="文字艺术字描述")
    parser.add_argument("--dialog", default=None, dest="dialog", metavar="DESC", help="对话框描述")
    parser.add_argument("--skip-remove-text", action="store_true", dest="skip_remove_text", help="跳过 A1 去干扰")
    parser.add_argument("--width", "-W", type=int, default=None, help="生图宽度")
    parser.add_argument("--height", "-H", type=int, default=None, help="生图高度")
    args = parser.parse_args()

    # ════════════════════════════════════════════════════════════════════════
    # Step 0: 强制设置 micugpt2 后端
    # ════════════════════════════════════════════════════════════════════════
    micugpt2_key = os.environ.get("MICUAPI_API_KEY")
    if not micugpt2_key and _ENV_FILE.is_file():
        with open(_ENV_FILE, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if "=" in _line and not _line.startswith("#"):
                    _k, _, _v = _line.partition("=")
                    _k, _v = _k.strip(), _v.strip().strip("'\"").strip()
                    if _k == "MICUAPI_API_KEY" and _v:
                        micugpt2_key = _v
                        break
    if not micugpt2_key or not micugpt2_key.strip().startswith("sk-"):
        print("Error: 请在 .env 中设置 MICUAPI_API_KEY（以 sk- 开头）", file=sys.stderr)
        sys.exit(1)
    os.environ["MICUAPI_API_KEY"] = micugpt2_key
    os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"

    # ════════════════════════════════════════════════════════════════════════
    # Step 0b: 解析参数
    # ════════════════════════════════════════════════════════════════════════
    if args.main_title_file:
        pt = Path(args.main_title_file).resolve()
        if not pt.is_file():
            print(f"Error: 主标题文件不存在: {pt}", file=sys.stderr)
            sys.exit(1)
        main_title = pt.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    elif args.main_title:
        main_title = args.main_title
    else:
        print("Error: 请提供 --main-title 或 --main-title-file。", file=sys.stderr)
        sys.exit(1)

    if args.subtitle_file:
        ps = Path(args.subtitle_file).resolve()
        if ps.is_file():
            subtitle = ps.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        else:
            subtitle = args.subtitle or ""
    else:
        subtitle = args.subtitle or ""

    groups: list[str] = []
    if getattr(args, "genre_groups", None):
        for _g in args.genre_groups:
            _g = (_g or "").strip()
            if _g:
                groups.append(_g)
    if args.group_file:
        pg = Path(args.group_file).resolve()
        if pg.is_file():
            for line in pg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    groups.append(line)

    # 验证分组名
    for _gn in groups:
        if _gn not in _spec.GENRE_PRESETS:
            print(f"Error: 未知分组 {_gn!r}。当前支持: {', '.join(_spec.GENRE_PRESETS)}", file=sys.stderr)
            sys.exit(1)

    # ════════════════════════════════════════════════════════════════════════
    # 参考图解析（提前，供描述块判断是否需要生图）
    # ════════════════════════════════════════════════════════════════════════
    ref_to_use = Path(args.ref).resolve() if args.ref else None
    _open_ref = ref_to_use is None and OPEN_PLATFORM_DEFAULT_REF.is_file() and any(
        (x or "").strip() == "开放平台" for x in groups
    )
    if _open_ref:
        ref_to_use = OPEN_PLATFORM_DEFAULT_REF.resolve()
        print(f"[micugpt2] 使用开放平台默认参考图: {ref_to_use}", flush=True)
    if ref_to_use is not None and not ref_to_use.is_file():
        print(f"Error: 参考图不存在: {ref_to_use}", file=sys.stderr)
        sys.exit(1)

    # ════════════════════════════════════════════════════════════════════════
    # 描述解析
    # ════════════════════════════════════════════════════════════════════════
    _engine_trace = None
    _skip_step1 = False
    if args.description_file:
        path = Path(args.description_file).resolve()
        if not path.is_file():
            print(f"Error: 描述文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
        description = path.read_text(encoding="utf-8").strip()
    elif args.description:
        description = args.description
    elif (
        getattr(args, "prompt_optimizer_template", False)
        or getattr(args, "prompt_engine", False)
        or getattr(args, "prompt_engine_claude", False)
    ):
        opt_count = sum([
            getattr(args, "prompt_optimizer_template", False),
            getattr(args, "prompt_engine", False),
            getattr(args, "prompt_engine_claude", False),
        ])
        if opt_count > 1:
            print("Error: --prompt-optimizer-template / --prompt-engine / --prompt-engine-claude 请三选一。", file=sys.stderr)
            sys.exit(1)
        use_engine = getattr(args, "prompt_engine", False)
        use_engine_claude = getattr(args, "prompt_engine_claude", False)
        label = "Anthropic Claude" if use_engine_claude else "Gemini"
        mode_label = "prompt-engine 完整管线" if (use_engine or use_engine_claude) else "prompt-optimizer-template"
        print(f"[micugpt2] 未提供描述，根据主副标题用 {label} {mode_label} 生成文生图描述...", flush=True)
        sys.path.insert(0, str(STEP1_SCRIPT.parent))
        import generate_from_description as _gfd
        try:
            if use_engine or use_engine_claude:
                backend = "claude" if use_engine_claude else "gemini"
                description, full_trace = _gfd.prompt_optimizer_engine(
                    main_title, subtitle or "", backend=backend, save_trace=False,
                )
                _engine_trace = full_trace
            else:
                description = _gfd.prompt_optimizer_template(
                    main_title, subtitle or "",
                    mode=getattr(args, "mode", "auto"),
                    subject_override=getattr(args, "subject", ""),
                    prompt_format=getattr(args, "prompt_format", "compact"),
                )
        except RuntimeError as e:
            print(f"Error: {mode_label} 失败: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"[micugpt2] {mode_label} 生成描述: {description[:80]}...", flush=True)
        if use_engine or use_engine_claude:
            print(f"[micugpt2] prompt-engine 完整推导: {len(_engine_trace)} 字符", flush=True)
    else:
        # 无描述时：有参考图 → 跳过生图，直接用图
        if ref_to_use is not None:
            description = ""
            _skip_step1 = True
            print("[micugpt2] 已提供参考图且无描述，跳过生图，直接处理图片。", flush=True)
        else:
            print(
                "Error: 未提供描述。请使用 --description / --description-file / --prompt-engine / --prompt-engine-claude / --prompt-optimizer-template。",
                file=sys.stderr,
            )
            sys.exit(1)

    if not STEP1_SCRIPT.is_file():
        print(f"Error: Step 1 脚本不存在: {STEP1_SCRIPT}", file=sys.stderr)
        sys.exit(1)
    if not STEP2_PRESETS_SCRIPT.is_file():
        print(f"Error: Step 2 脚本不存在: {STEP2_PRESETS_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    # ════════════════════════════════════════════════════════════════════════
    # 创建 run_dir
    # ════════════════════════════════════════════════════════════════════════
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    genre_label = sanitize_dirname("+".join(groups)) if groups else "all"
    title_safe = sanitize_dirname(main_title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{genre_label}_{title_safe}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    step1_bg_path = run_dir / "bg.png"

    # 按分组追加风格描述（仅当有描述且非跳过生图时追加）
    _style_seen: set[str] = set()
    _gsp = getattr(_spec, "GENRE_STYLE_PROMPT", {})
    for _gn in groups:
        _frag = _gsp.get(_gn or "", "")
        if _frag and _frag not in _style_seen:
            _style_seen.add(_frag)
            if not _skip_step1:
                description = description.rstrip() + _frag
                print(f"[micugpt2] 已追加分组 {_gn!r} 的风格描述到 Step 1 prompt", flush=True)

    # 参考图已在前面解析，此处无需重复

    if not _skip_step1:
        (run_dir / "prompt.txt").write_text(description, encoding="utf-8")
    if _engine_trace is not None:
        (run_dir / "prompt_engine_trace.md").write_text(_engine_trace, encoding="utf-8")
        print(f"[micugpt2] prompt-engine 完整推导已保存到 {run_dir / 'prompt_engine_trace.md'}", flush=True)

    env = os.environ.copy()

    # ════════════════════════════════════════════════════════════════════════
    # Step 1: 生图（有描述时 subprocess；无描述且有图时直接复制）
    # ════════════════════════════════════════════════════════════════════════
    if _skip_step1:
        import shutil as _shutil
        _shutil.copy2(str(ref_to_use), str(step1_bg_path))
        print(f"[micugpt2] Step 1 跳过生图，直接使用图片: {step1_bg_path}", flush=True)
    else:
        cmd1 = [
            PYTHON_EXE,
            str(STEP1_SCRIPT),
            description,
            str(step1_bg_path),
        ]
        if ref_to_use:
            cmd1.extend(["--reference-image", str(ref_to_use)])
        if args.width is not None and args.height is not None:
            cmd1.extend(["--width", str(args.width), "--height", str(args.height)])
        elif groups:
            _all_presets_in_groups: list[str] = []
            for _gn in groups:
                _all_presets_in_groups.extend(_spec.GENRE_PRESETS.get(_gn, []))
            _is_ultrawide_only = bool(_all_presets_in_groups) and all(
                _spec.PRESETS.get(p, (0, 0))[0] / max(_spec.PRESETS.get(p, (1, 1))[1], 1) > 3.0
                for p in _all_presets_in_groups if p in _spec.PRESETS
            )
            if _is_ultrawide_only:
                _gw, _gh = 1920, 600
            else:
                _gw, _gh = 1024, 640
            cmd1.extend(["--width", str(_gw), "--height", str(_gh)])

        print("[micugpt2] Step 1: 根据描述生成背景...", flush=True)
        r1 = subprocess.run(cmd1, cwd=str(ROOT), env=env)
        if r1.returncode != 0:
            print("Step 1 失败，已终止。", file=sys.stderr)
            sys.exit(r1.returncode)

    if not step1_bg_path.is_file():
        print(f"Error: Step 1 未产出文件: {step1_bg_path}", file=sys.stderr)
        sys.exit(1)
    print(f"[micugpt2] Step 1 完成: {step1_bg_path}", flush=True)

    # ════════════════════════════════════════════════════════════════════════
    # Step 1b: 文字艺术字
    # ════════════════════════════════════════════════════════════════════════
    text_art_rgba_path = None
    if getattr(args, "text_art", None):
        _first_group = groups[0] if groups else None
        _first_preset = _spec.GENRE_PRESETS.get(_first_group, [None])[0] if _first_group else None
        if _first_preset and _first_preset in _spec.PRESETS:
            _cw, _ch = _spec.PRESETS[_first_preset]
            _ta_zone = _spec.TEXT_ART_ZONE_BY_CANVAS.get((_cw, _ch))
        else:
            _ta_zone = None
        if _ta_zone:
            _ta_w = _ta_zone[1] - _ta_zone[0]
            _ta_h = _ta_zone[3] - _ta_zone[2]
            print(f"[micugpt2] Step 1b: 生成文字艺术字 ({_ta_w}×{_ta_h})...", flush=True)
            text_art_bg_path = run_dir / "text_art_raw.png"
            cmd_ta = [
                PYTHON_EXE, str(STEP1_SCRIPT), args.text_art, str(text_art_bg_path),
                "--width", "1024", "--height", "640",
            ]
            r_ta = subprocess.run(cmd_ta, cwd=str(ROOT), env=env)
            if r_ta.returncode != 0 or not text_art_bg_path.is_file():
                print("Warning: 文字艺术字生图失败，跳过。", file=sys.stderr)
            else:
                text_art_rgba_path = run_dir / "text_art_rgba.png"
                try:
                    from PIL import Image as _PILImage
                    import numpy as _np
                    ta_img = _PILImage.open(text_art_bg_path).convert("RGBA")
                    gray = ta_img.convert("L")
                    avg = _np.array(gray).mean()
                    alpha = gray.point(lambda x: 255 - x) if avg > 128 else gray.point(lambda x: x)
                    ta_img.putalpha(alpha)
                    ta_img.save(str(text_art_rgba_path), "PNG")
                    print(f"[micugpt2] Step 1b 完成 (亮度蒙版, avg={avg:.0f}): {text_art_rgba_path}", flush=True)
                except Exception as _e:
                    print(f"Warning: 亮度蒙版处理失败 ({_e})，跳过。", file=sys.stderr)
                    text_art_rgba_path = None
        else:
            print("Warning: 当前分组未配置 TEXT_ART_ZONE，跳过文字艺术字。", file=sys.stderr)

    # ════════════════════════════════════════════════════════════════════════
    # Step 1c: 对话框横幅
    # ════════════════════════════════════════════════════════════════════════
    dialog_rgba_path = None
    _first_group = groups[0] if groups else None
    _first_preset = _spec.GENRE_PRESETS.get(_first_group, [None])[0] if _first_group else None
    if _first_preset and _first_preset in _spec.PRESETS:
        _cw, _ch = _spec.PRESETS[_first_preset]
        _d_zone = _spec.DIALOG_ZONE_BY_CANVAS.get((_cw, _ch))
    else:
        _d_zone = None

    if _d_zone:
        _d_w = _d_zone[1] - _d_zone[0]
        _d_h = _d_zone[3] - _d_zone[2]
        _dialog_banner_script = ROOT / "scripts" / "generate_dialog_banner.py"
        if getattr(args, "dialog", None):
            print(f"[micugpt2] Step 1c: 生成对话框 ({_d_w}×{_d_h})...", flush=True)
            dialog_bg_path = run_dir / "dialog_raw.png"
            cmd_d = [
                PYTHON_EXE, str(STEP1_SCRIPT), args.dialog, str(dialog_bg_path),
                "--width", str(_d_w), "--height", str(_d_h),
            ]
            r_d = subprocess.run(cmd_d, cwd=str(ROOT), env=env)
            if r_d.returncode != 0 or not dialog_bg_path.is_file():
                print("Warning: 对话框生图失败，跳过。", file=sys.stderr)
            else:
                dialog_rgba_path = dialog_bg_path
                print(f"[micugpt2] Step 1c 完成: {dialog_rgba_path}", flush=True)
        elif _dialog_banner_script.is_file() and step1_bg_path.is_file():
            print(f"[micugpt2] Step 1c: 从背景图取色生成六边形横幅 ({_d_w}×{_d_h})...", flush=True)
            dialog_bg_path = run_dir / "dialog_raw.png"
            cmd_d = [
                PYTHON_EXE, str(_dialog_banner_script),
                "--bg", str(step1_bg_path),
                "--region", str(_d_zone[0]), str(_d_zone[2]), str(_d_zone[1]), str(_d_zone[3]),
                "--width", str(_d_w), "--height", str(_d_h),
                "--output", str(dialog_bg_path),
            ]
            r_d = subprocess.run(cmd_d, cwd=str(ROOT), env=env)
            if r_d.returncode != 0 or not dialog_bg_path.is_file():
                print("Warning: 对话框横幅生成失败，跳过。", file=sys.stderr)
            else:
                dialog_rgba_path = dialog_bg_path
                print(f"[micugpt2] Step 1c 完成: {dialog_rgba_path}", flush=True)

    # ════════════════════════════════════════════════════════════════════════
    # Step 2: 背景处理 + 叠字
    # ════════════════════════════════════════════════════════════════════════
    MOBILE_GROUP = "商店移动端日常"
    has_mobile = MOBILE_GROUP in groups
    desktop_groups = [g for g in groups if g != MOBILE_GROUP]

    env2 = env.copy()

    if desktop_groups or not has_mobile:
        cmd2 = [
            PYTHON_EXE, str(STEP2_PRESETS_SCRIPT),
            str(step1_bg_path.resolve()),
            "--main-title", main_title,
            "--subtitle", subtitle,
            "--output-dir", str(run_dir.resolve()),
        ]
        cmd2.append("--skip-a4-outpaint")
        if getattr(args, "skip_remove_text", False):
            cmd2.append("--skip-remove-text")
        for _gn in desktop_groups if has_mobile else groups:
            cmd2.extend(["--genre", _gn])
        # micugpt2：STEP2_PRESETS_SCRIPT 指向 run_all_presets_micugpt2.py，
        # 它内部调用 prepare_background_micugpt2.py，已强制 BANNER_IMAGE_BACKEND=micugpt2
        cmd2.append("-micugpt2")
        if text_art_rgba_path and text_art_rgba_path.is_file():
            cmd2.extend(["--text-art", str(text_art_rgba_path.resolve())])
        if dialog_rgba_path and dialog_rgba_path.is_file():
            cmd2.extend(["--dialog", str(dialog_rgba_path.resolve())])
        print("[micugpt2] Step 2: 多尺寸叠字合成（run_all_presets_micugpt2.py）...", flush=True)
        r2 = subprocess.run(cmd2, cwd=str(ROOT), env=env2)
        if r2.returncode != 0:
            print("Step 2（桌面端）失败。", file=sys.stderr)
            sys.exit(r2.returncode)

    if has_mobile:
        cmd_m = [
            PYTHON_EXE, str(MOBILE_SCRIPT),
            str(step1_bg_path.resolve()),
            "-m", main_title,
            "-s", subtitle,
            "--output-dir", str(run_dir.resolve()),
            "--micugpt2",
        ]
        if text_art_rgba_path and text_art_rgba_path.is_file():
            cmd_m.extend(["--text-art", str(text_art_rgba_path.resolve())])
        if dialog_rgba_path and dialog_rgba_path.is_file():
            cmd_m.extend(["--dialog", str(dialog_rgba_path.resolve())])
        print("[micugpt2] Step 2: 移动端管线（run_mobile_presets.py）...", flush=True)
        r_m = subprocess.run(cmd_m, cwd=str(ROOT), env=env2)
        if r_m.returncode != 0:
            print("Step 2（移动端）失败。", file=sys.stderr)
            sys.exit(r_m.returncode)

    print("[micugpt2] 全部完成。", flush=True)

    files = sorted(run_dir.glob("*")) if run_dir.is_dir() else []
    if files:
        print(f"\n本次输出目录（{run_dir}）：")
        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                print(f"  {f.name}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
