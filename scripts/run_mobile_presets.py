#!/usr/bin/env python3
"""
商店移动端日常 Banner 独立处理管线。
替代 run_all_presets.py 处理 -g 商店移动端日常，使用移动端定制的 A2→A4→A5→A6→compose 流程。

用法:
    py scripts/run_mobile_presets.py <bg.png路径> \\
      --main-title "标题" --subtitle "副标题" \\
      --output-dir "output/xxx" \\
      [--micugpt2] [--packy7s]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

# 确保项目根在 path，以便导入 _env / _packy
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# prepare_background / gemini_image_edit 所在目录
_PREPARE_DIR = str(ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts")
if _PREPARE_DIR not in sys.path:
    sys.path.insert(0, _PREPARE_DIR)

# spec / compose_banner 所在目录
_SPEC_DIR = str(ROOT / ".claude" / "skills" / "banner-spec" / "scripts")
_COMPOSER_DIR = str(ROOT / ".claude" / "skills" / "banner-composer" / "scripts")
if _SPEC_DIR not in sys.path:
    sys.path.insert(0, _SPEC_DIR)
if _COMPOSER_DIR not in sys.path:
    sys.path.insert(0, _COMPOSER_DIR)

# ── 移动端常量 ──
FILL_CANVAS_W, FILL_CANVAS_H = 2048, 512
MAX_FILL_ROUNDS = 4
SUBJECT_RATIO = 0.85
SAFE_ZONE_SCALE = 0.90

MOBILE_PRESETS = [
    "shop_mobile_banner_984",
    "shop_mobile_card_650",
    "shop_mobile_strip_720",
    "商店移动端noti700x300_art",
    "shop_mobile_nav_icon_96",
]

# 生成式UI封面单独处理（direct-to-canvas，不进 A5 裁切循环）
GENUI_PRESET = "shop_mobile_generative_ui_cover_1536"

PREPARE_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts" / "prepare_background.py"

# A4 扩图 prompt（移动端，不指定具体像素尺寸）
MOBILE_OUTPAINT_FILL_PROMPT = (
    "This image has a subject in the center and UNFILLED areas (solid RGB(0,0,1) or near-black) around it. "
    "Your task: FILL the entire image by EXTENDING the scene from the center subject outward based on existing content—keep the subject area UNCHANGED; only fill the blank regions. "
    "EXTEND the background naturally so the result is one seamless image. "
    "CRITICAL—STRONG VISUAL CONTINUITY, NO SEAM: The extended areas MUST look like the SAME single photograph or render—same camera viewpoint, same perspective, same depth of field and scale. "
    "Do NOT draw a different angle or a 'wider empty corridor' view; the filled regions must feel like more of the same frame, not a different shot. "
    "(1) Use the EXACT same art style: same rendering, same level of detail, same textures and materials. "
    "(2) Use the SAME lighting: same light direction, same color temperature, same shadow softness. "
    "(3) Preserve the SAME perspective and scale. "
    "(4) No visible seam between original content and extended regions. "
    "(5) Extended regions must have similar CONTENT DENSITY as the center. "
    "(6) Do NOT mirror, tile, or repeat existing background elements—each extended region must show UNIQUE, naturally continued space. "
    "(7) Do NOT create an obvious vertical BAND that looks different in content or brightness. "
    "Do NOT add new characters or text. Do NOT repeat or duplicate the subject. "
    "Output must be exactly the same dimensions as the input. No black bars or unfilled edges."
)


def _sanitize_dirname(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in "._-+")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="商店移动端日常 Banner 独立处理管线")
    p.add_argument("bg_path", help="bg.png 路径")
    p.add_argument("--main-title", "-m", required=True, help="主标题")
    p.add_argument("--subtitle", "-s", default="", help="副标题")
    p.add_argument("--output-dir", default=None, help="输出目录（默认自动生成）")
    p.add_argument("--text-art", default=None, help="文字艺术字透明 PNG 路径（可选）")
    p.add_argument("--dialog", default=None, help="对话框透明 PNG 路径（可选）")
    p.add_argument("--packy7s", action="store_true", help="使用 Packy7s（Gemini Vision 编辑）")
    p.add_argument("--micugpt2", action="store_true", help="使用 MicuGPT2（图编补黑边）")
    p.add_argument("--micugemini", action="store_true", help="使用 MicuGemini（gemini-3-flash-preview-thinking 文生图）")
    p.add_argument("--xingchengemini", action="store_true", help="使用 XingchenGemini（gemini-3.1-flash-image-preview 文生图）")
    p.add_argument("--xingchengemini1", action="store_true", help="使用 XingchenGemini 多 Key 轮换 1 号 key（需 .env 中 XINGCHENGEMINI1_API_KEY）")
    p.add_argument("--moxingpt", action="store_true", help="使用 MoxinGPT（gpt-image-2 图编补黑边）")
    p.add_argument("--moxingemini", action="store_true", help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY，与 --moxingpt 组合时编辑走 chat/completions）")
    p.add_argument("--xingchengpt", action="store_true", help="使用 XingchenGPT（gpt-image-2 图编补黑边）")
    p.add_argument("--xinchengpt", action="store_true", help="使用 XinchenGPT（gpt-image-2 图编补黑边）")
    p.add_argument("--packygpt", action="store_true", help="使用 PackyGPT（图编补黑边）")
    return p.parse_args()


def main():
    args = parse_args()

    bg_path = Path(args.bg_path).resolve()
    if not bg_path.is_file():
        print(f"Error: bg.png 不存在: {bg_path}", file=sys.stderr)
        sys.exit(1)

    # ── 加载环境 ──
    from _env import load_env
    _env_keys = (
        "GEMINI_API_KEY", "GEMINI_MODEL", "GOOGLE_GEMINI_BASE_URL",
        "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKYGPT_API_KEY",
        "MICUAPI_API_KEY", "MICUGEMINI_API_KEY", "XINGCHENGEMINI_API_KEY", "XINGCHENGEMINI1_API_KEY", "MOXINGPT_API_KEY", "MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL", "XINGCHENGGPT_API_KEY", "BANNER_IMAGE_BACKEND",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    )
    load_env(_env_keys)

    from _packy import apply_packy_backend
    apply_packy_backend(args)

    # 设置 Gemini Vision 模型（packy7s 用），仅在未配置时设置默认值
    env = os.environ.copy()
    if getattr(args, "packy7s", False):
        env.setdefault("GEMINI_MODEL", "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview")
        env.setdefault("GEMINI_VISION_MODEL", "gemini-3.1-pro-preview,gemini-3-flash-preview")
        if not getattr(args, "packygpt", False) and not getattr(args, "micugpt2", False) and not getattr(args, "micugemini", False) and not getattr(args, "moxingpt", False) and not getattr(args, "moxingemini", False) and not getattr(args, "xingchengpt", False):
            env["BANNER_IMAGE_BACKEND"] = "gemini"

    BANNER_IMAGE_BACKEND = env.get("BANNER_IMAGE_BACKEND", "gemini").strip().lower()
    os.environ["BANNER_IMAGE_BACKEND"] = BANNER_IMAGE_BACKEND

    # ── 输出目录 ──
    main_title = args.main_title
    subtitle = args.subtitle
    if args.output_dir:
        run_dir = Path(args.output_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        title_safe = _sanitize_dirname(main_title)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = ROOT / "output" / f"商店移动端日常_{title_safe}_{ts}"
        run_dir.mkdir(parents=True, exist_ok=True)

    # 复制 bg.png 到输出目录（如果还没在那里）
    bg_in_dir = run_dir / "bg.png"
    if not bg_in_dir.samefile(bg_path) if hasattr(Path, "samefile") else bg_in_dir.resolve() != bg_path.resolve():
        shutil.copy2(bg_path, bg_in_dir)
    bg_path = bg_in_dir

    print(f"=== 商店移动端日常 独立管线 ===", flush=True)
    print(f"bg.png: {bg_path}  ({bg_path.stat().st_size / 1024:.0f} KB)", flush=True)
    print(f"输出目录: {run_dir}", flush=True)

    # ── 导入模块 ──
    from spec import PRESETS, OUTPUT_FILENAME_BY_PRESET
    from gemini_subject_detect import detect_subject_bbox
    from safe_zone_scale_composite import composite_to_canvas_center
    from gemini_image_edit import edit_image

    # ── Step 1 (A2): 主体 bbox 检测 ──
    print("\n[Step 1] A2 — 主体 bbox 检测 (Gemini Vision)...", flush=True)
    _ctx_prompt = None
    _ctx_file = run_dir / "prompt.txt"
    if _ctx_file.is_file():
        _ctx_prompt = _ctx_file.read_text(encoding="utf-8").strip()
        if _ctx_prompt:
            print("  [OK] 已加载生图描述，将传递给 Vision 辅助主体检测", flush=True)

    bbox = detect_subject_bbox(str(bg_path), context_prompt=_ctx_prompt)
    if bbox is None:
        print("Error: 主体 bbox 检测失败", file=sys.stderr)
        sys.exit(1)
    print(f"  bbox: {bbox}", flush=True)

    # ── Step 2 (A4): 扩图填满 (2048×512) ──
    print(f"\n[Step 2] A4 — 扩图填满 {FILL_CANVAS_W}×{FILL_CANVAS_H} (Gemini)...", flush=True)

    fd, temp_canvas = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    tianchong_path = run_dir / "tianchong_mobile.png"

    try:
        composite_to_canvas_center(
            str(bg_path),
            temp_canvas,
            canvas_w=FILL_CANVAS_W,
            canvas_h=FILL_CANVAS_H,
            subject_bbox=bbox,
            subject_ratio=SUBJECT_RATIO,
            center_x_ratio=0.5,
            center_y_ratio=0.5,
        )
        fill_input = temp_canvas
        for r in range(MAX_FILL_ROUNDS):
            print(f"  A4 第 {r + 1}/{MAX_FILL_ROUNDS} 轮...", flush=True)
            try:
                edit_image(
                    fill_input,
                    str(tianchong_path),
                    MOBILE_OUTPAINT_FILL_PROMPT,
                    keep_returned_size=True,
                )
            except Exception as e:
                print(f"  A4 图编失败，改用本地画布继续: {e}", file=sys.stderr)
                try:
                    shutil.copy2(temp_canvas, str(tianchong_path))
                except Exception:
                    pass
                break
            # 检查是否填满：优先像素级黑色占比检测（阈值 3%）
            need_refill = False
            try:
                import numpy as np
                from PIL import Image as _PILCheck
                _chk = _PILCheck.open(str(tianchong_path)).convert("RGB")
                _arr = np.array(_chk)
                _black_mask = (_arr[:, :, 0] < 20) & (_arr[:, :, 1] < 20) & (_arr[:, :, 2] < 20)
                _black_ratio = _black_mask.sum() / _black_mask.size
                if _black_ratio > 0.03:
                    print(f"  A4 检测到黑色像素占比 {_black_ratio:.1%}，需要重新填充", flush=True)
                    need_refill = True
                else:
                    # 黑色占比正常，再检测接缝
                    try:
                        from gemini_subject_detect import image_a4_need_refill_seams
                        seams = image_a4_need_refill_seams(str(tianchong_path))
                        need_refill = bool(seams)
                        if need_refill:
                            print(f"  A4 检测到接缝/割裂，重新填充...", flush=True)
                    except Exception:
                        pass
            except Exception:
                # numpy 不可用时回退原逻辑
                try:
                    from gemini_subject_detect import image_a4_need_refill_unfilled, image_a4_need_refill_seams
                    unfilled = image_a4_need_refill_unfilled(str(tianchong_path))
                    if unfilled is None:
                        from gemini_image_edit import image_has_black_bars, image_has_black_bars_full_image
                        unfilled = (
                            image_has_black_bars_full_image(str(tianchong_path))
                            or image_has_black_bars(str(tianchong_path))
                        )
                    seams = image_a4_need_refill_seams(str(tianchong_path))
                    need_refill = unfilled or (seams if seams is not None else True)
                    if need_refill and r < MAX_FILL_ROUNDS - 1:
                        reasons = []
                        if unfilled:
                            reasons.append("未填满")
                        if seams:
                            reasons.append("接缝/割裂")
                        elif seams is None and not unfilled:
                            reasons.append("接缝/割裂(检测未返回)")
                        print(f"  A4 检测不通过（{' + '.join(reasons)}），重新填充...", flush=True)
                except Exception as e:
                    print(f"  A4 检测异常（{e}），继续", flush=True)
                    need_refill = False

            if not need_refill:
                break
            fill_input = temp_canvas

        print(f"  A4 产出 → {tianchong_path}", flush=True)
        try:
            from PIL import Image as _PILImg
            with _PILImg.open(str(tianchong_path)) as img:
                tw, th = img.size
                print(f"  tianchong_mobile.png 尺寸: {tw}×{th}", flush=True)
        except Exception:
            pass
    finally:
        if os.path.isfile(temp_canvas):
            try:
                os.unlink(temp_canvas)
            except OSError:
                pass

    # ── Step 3: A5 共用 bbox 检测（tianchong_mobile.png 上一次，3 个预设共享） ──
    print(f"\n[Step 3] A5 — 对 tianchong_mobile.png 检测主体 bbox（共用）...", flush=True)
    try:
        from gemini_subject_detect import detect_subject_bbox
        mobile_bbox = detect_subject_bbox(str(tianchong_path), context_prompt=_ctx_prompt)
        if mobile_bbox is None:
            raise RuntimeError("bbox 检测返回 None")
        print(f"  共用 bbox: {mobile_bbox}", flush=True)
    except Exception as e:
        print(f"  共用 bbox 检测失败（{e}），各预设将单独检测", flush=True)
        mobile_bbox = None

    # ── Step 4 (A5/A6): 缩放至画布 + 填满 ──
    print(f"[Step 4] A5/A6 — 缩放至各移动端画布 + 填满...", flush=True)

    from prepare_background import _crop_step5_to_canvas

    step1_paths: dict[str, Path] = {}
    for preset_name in MOBILE_PRESETS:
        w, h = PRESETS[preset_name]
        out_path = run_dir / f"step1_mobile_{preset_name}.png"
        print(f"\n  {preset_name} ({w}×{h})...", flush=True)

        # A5 裁切（传入共用 bbox，免重复检测）
        try:
            _crop_step5_to_canvas(
                str(tianchong_path),
                str(out_path),
                w, h,
                preset=preset_name,
                subject_bbox_norm=mobile_bbox,
            )
        except Exception as e:
            print(f"  A5 裁切失败: {e}", file=sys.stderr)
            continue

        # A6 填满黑边
        try:
            from gemini_subject_detect import image_has_unfilled_blanks
        except ImportError:
            image_has_unfilled_blanks = None

        has_unfilled = False
        # 优先用像素级黑色占比检测（阈值 3%），避免内部大面积黑色区域被边缘检测漏掉
        try:
            import numpy as np
            from PIL import Image as _PILCheck
            _chk = _PILCheck.open(str(out_path)).convert("RGB")
            _arr = np.array(_chk)
            # 近纯黑：RGB 均 < 20
            _black_mask = (_arr[:, :, 0] < 20) & (_arr[:, :, 1] < 20) & (_arr[:, :, 2] < 20)
            _black_ratio = _black_mask.sum() / _black_mask.size
            if _black_ratio > 0.03:
                print(f"    检测到黑色像素占比 {_black_ratio:.1%}，触发 A6 填充", flush=True)
                has_unfilled = True
        except Exception as _e:
            # numpy 检测失败，回退到原有检测逻辑
            if image_has_unfilled_blanks is not None:
                has_unfilled = image_has_unfilled_blanks(str(out_path))
                if has_unfilled is None:
                    try:
                        from gemini_image_edit import image_has_black_bars, image_has_black_bars_full_image
                        has_unfilled = (
                            image_has_black_bars_full_image(str(out_path))
                            or image_has_black_bars(str(out_path))
                        )
                    except ImportError:
                        pass

        if has_unfilled:
            print("    检测到未填充区域，延展补齐...", flush=True)
            try:
                from gemini_image_edit import OUTPAINT_FILL_REMAINING_BLACK_PROMPT
                _original_size = (w, h)
                if BANNER_IMAGE_BACKEND == "packygpt":
                    from prepare_background import _packygpt_edit_image
                    _packygpt_edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "moxingpt":
                    from prepare_background import _moxingpt_edit_image
                    _moxingpt_edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "xingchengpt":
                    from prepare_background import _xingchengpt_edit_image
                    _xingchengpt_edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "xinchengpt":
                    from prepare_background import _xinchengpt_edit_image
                    _xinchengpt_edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "micugpt2":
                    from prepare_background import _micugpt2_edit_image
                    _micugpt2_edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                    )
                    # _micugpt2_edit_image 可能返回不同尺寸，缩回原 canvas
                    from PIL import Image as _PILImg
                    _im = _PILImg.open(str(out_path))
                    if _im.size != _original_size:
                        _im = _im.resize(_original_size, _PILImg.Resampling.LANCZOS)
                        _im.save(str(out_path), "PNG")
                        print(f"    已缩放回 {_original_size[0]}×{_original_size[1]}", flush=True)
                else:
                    edit_image(
                        str(out_path), str(out_path),
                        OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
                        keep_returned_size=True,
                    )
                print(f"    填充完成", flush=True)
            except Exception as e:
                print(f"    A6 填充失败（保留裁切结果）: {e}", file=sys.stderr)
        else:
            print(f"    无未填充区域，跳过填充", flush=True)

        step1_paths[preset_name] = out_path

    # ── Step 4b: 生成式UI封面 1536×1024 — direct-to-canvas + API 填充 ──
    # 复用 tianchong_mobile.png（与其他移动端 preset 同源，保证画面内容一致）
    print(f"\n[Step 4b] {GENUI_PRESET} (1536×1024) — direct-to-canvas + API 填充...", flush=True)
    genui_out_path = run_dir / f"step1_mobile_{GENUI_PRESET}.png"
    genui_w, genui_h = PRESETS[GENUI_PRESET]

    _bbox_for_genui = mobile_bbox  # 使用 tianchong 上检测到的共用 bbox
    if _bbox_for_genui is None:
        print("  [WARN] 共用 bbox 不可用，跳过生成式UI封面", file=sys.stderr)
    else:
        cmd_genui = [
            sys.executable,
            str(PREPARE_SCRIPT),
            str(tianchong_path),
            str(genui_out_path),
            "--preset", GENUI_PRESET,
            "--safe-zone-scale-outpaint",
            "--direct-to-canvas",
            "--width-fit",
            "--bbox",
            str(_bbox_for_genui[0]),
            str(_bbox_for_genui[1]),
            str(_bbox_for_genui[2]),
            str(_bbox_for_genui[3]),
        ]
        if _ctx_prompt and _ctx_file.is_file():
            cmd_genui.extend(["--context-prompt", str(_ctx_file)])
        r_genui = subprocess.run(cmd_genui, cwd=str(ROOT), env=env)
        if r_genui.returncode == 0 and genui_out_path.is_file():
            step1_paths[GENUI_PRESET] = genui_out_path
            print(f"  [OK] {genui_out_path.name}", flush=True)
        else:
            if genui_out_path.is_file():
                genui_out_path.unlink(missing_ok=True)
            print("  [WARN] 生成式UI封面 direct-to-canvas 失败，将跳过该 preset", file=sys.stderr)

    # ── Step 5: 合成文字 ──
    print(f"\n[Step 5] compose — 叠字合成...", flush=True)

    from compose_banner import compose, _resolve_output_path

    for preset_name in MOBILE_PRESETS + [GENUI_PRESET]:
        if preset_name not in step1_paths:
            continue
        w, h = PRESETS[preset_name]
        out_name = OUTPUT_FILENAME_BY_PRESET.get(preset_name) or f"banner_{preset_name}_{w}x{h}.png"
        out_path = str((run_dir / out_name).resolve())
        bg_step1 = str(step1_paths[preset_name].resolve())

        print(f"  {preset_name} ({w}x{h}) → {Path(out_path).name}", flush=True)
        try:
            compose(
                bg_step1,
                out_path,
                main_title,
                subtitle,
                width=w,
                height=h,
                use_ai_linebreak=True,
                preset=preset_name,
                text_art_path=args.text_art,
                dialog_path=args.dialog,
            )
            resolved, _ = _resolve_output_path(out_path)
            print(f"    → {resolved}", flush=True)
        except Exception as e:
            print(f"    compose 失败: {e}", file=sys.stderr)

    # ── 清理 ──
    for p in step1_paths.values():
        if p.is_file():
            p.unlink(missing_ok=True)

    # ── 列出产出 ──
    files = sorted(run_dir.glob("*")) if run_dir.is_dir() else []
    if files:
        print(f"\n本次输出目录（{run_dir}）：")
        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                print(f"  {f.name}  ({size_kb:.1f} KB)")

    print("\n[移动端管线] 全部完成。", flush=True)


if __name__ == "__main__":
    main()
