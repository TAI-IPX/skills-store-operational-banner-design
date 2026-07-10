#!/usr/bin/env python3
"""
LZ顶部banner 3840x1200 一站式流水线。

用法:
  py scripts/run_lz_top_banner_3840.py "角色1.png" "角色2.png" "角色3.png" -HD 活动1
  py scripts/run_lz_top_banner_3840.py "角色1.png" "角色2.png" "角色3.png" -HD 1 \
      --text-art "前程似锦书法毛笔艺术字" --main-title "前程似锦" --logo "logo.png"

流水线:
  S1: 3角色 → micugpt2 i2i → 3:1 合成图
  S2: 合成图 → micugpt2 i2i → 3840×1200 扩图
  S3: --text-art → gpt-image-2 t2i → 亮度蒙版 → 花字透明PNG
  S4: 叠花字 (title_art_rect) + 叠Logo (logo_rect) → 最终输出

依赖:
  - scripts/micugpt2_images_api.py    chat_completions_image / 自动代理
  - .claude/skills/banner-background-from-image/scripts/prepare_background.py  _micugpt2_edit_image
  - .claude/skills/banner-background-from-image/scripts/safe_zone_scale_composite.py  composite_to_canvas_center
  - .claude/skills/banner-background-from-image/scripts/gemini_subject_detect.py  detect_subject_bbox / _call_micugpt2_vision
  - .claude/skills/banner-background-from-description/scripts/generate_from_description.py  _generate_image_micugpt2
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

# 加载 spec.py
_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if str(_SPEC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec

# 加载 micugpt2_images_api.py（统一 chat_completions_image / 代理检测 / 重试）
sys.path.insert(0, str(ROOT / "scripts"))
from micugpt2_images_api import chat_completions_image

# 加载 generate_from_description.py（复用 _generate_image_micugpt2）
_GEN_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts"
if str(_GEN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_GEN_SCRIPTS))

# 加载 banner-background-from-image 基建（bbox检测 / 扩图 / 合成）
_BG_SCRIPTS = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if str(_BG_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BG_SCRIPTS))

TOP_BANNER_PRESET = "legend_top_banner_3840"
TOP_BANNER_W, TOP_BANNER_H = _spec.PRESETS[TOP_BANNER_PRESET]
TOP_BANNER_FILENAME = _spec.OUTPUT_FILENAME_BY_PRESET[TOP_BANNER_PRESET]
LAYOUT = _spec.get_layout(TOP_BANNER_W, TOP_BANNER_H, TOP_BANNER_PRESET)

SAFE_ZONE = (820, 2660, 0, 1200)  # x_min, x_max, y_min, y_max
TITLE_ART_RECT = LAYOUT.get("title_art_rect")  # (1380, 2460, 607, 935)
TITLE_ART_SCALE = float(LAYOUT.get("title_art_fit_scale", 0.95))
LOGO_RECT = LAYOUT.get("logo_rect")  # (1160, 240, 450, 120)
LOGO_SCALE = float(LAYOUT.get("logo_fit_scale", 0.95))

# 安全区中心比例（bbox → canvas 对齐用）
_sx0, _sx1, _sy0, _sy1 = SAFE_ZONE
SAFE_CENTER_X_RATIO = ((_sx0 + _sx1) / 2) / TOP_BANNER_W   # ≈ 0.453
SAFE_CENTER_Y_RATIO = ((_sy0 + _sy1) / 2) / TOP_BANNER_H   # = 0.5

# 扩图填充 Prompt（改编自 STRIP_DIRECT_FILL_PROMPT，适配 3840×1200 赛博朋克场景）
S2_FILL_PROMPT = (
    f"This ultra-wide banner ({TOP_BANNER_W}x{TOP_BANNER_H}) has subjects in the center and "
    "UNFILLED areas (solid RGB(0,0,1) or near-black) on the left and right. "
    "Your task: FILL the entire canvas by EXTENDING the cyberpunk cityscape from the center outward "
    "based on the existing scene content — keep the subject area UNCHANGED; only fill the blank regions. "
    "EXTEND the cityscape, neon lights, skyscrapers, glowing signs, and night sky naturally on both sides "
    "so the result is one seamless ultra-wide cyberpunk banner. "
    "CRITICAL—STRONG VISUAL CONTINUITY, NO SEAM: The extended areas MUST look like the SAME single render — "
    "same camera viewpoint, same perspective, same depth of field and scale. "
    "This is a very wide (aspect ~3.2:1) horizontal banner; the filled regions must read as more of the "
    "same cityscape panned naturally left and right, not as separate pasted patches. "
    "(1) Use the EXACT same art style: same rendering quality, same level of detail, same textures. "
    "(2) Use the SAME lighting: same light direction, same color temperature, same neon glow intensity. "
    "(3) Preserve the SAME perspective and scale: extend the cityscape at the SAME apparent distance. "
    "(4) No visible seam: the result must look like one single, coherent image. "
    "(5) Extended regions must have similar CONTENT DENSITY: continue the city buildings, streets, neon signs, "
    "skyline — do NOT fill large areas with only empty sky or flat dark color. "
    "(6) Do NOT mirror, tile, or repeat existing buildings or signs. Each extended region shows UNIQUE, "
    "naturally continued cityscape. "
    '(7) Light must transition naturally across the image — from center to edges. '
    "Do NOT add new people, characters, or readable text. Do NOT repeat or duplicate the subjects. "
    "Output MUST be exactly the same width and height as the input."
)

# ── 加载 .env ────────────────────────────────────────────────
ENV_FILE = ROOT / ".env"
for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v

API_KEY = os.environ.get("MICUAPI_API_KEY", "").strip()
if not API_KEY.startswith("sk-"):
    print("Error: MICUAPI_API_KEY 未设置或格式不正确", file=sys.stderr)
    sys.exit(1)


# ── Shared helpers ────────────────────────────────────────────

def _brightness_mask_to_rgba(image_bytes):
    """Generate transparent PNG from light-text-on-dark-background."""
    im = Image.open(BytesIO(image_bytes)).convert("L")
    alpha = im.point(lambda x: x)  # white=255→opaque, black=0→transparent
    rgba = Image.new("RGBA", im.size)
    rgba.putalpha(alpha)
    return rgba


def _count_distinct_characters(image_path: str, vision_fn) -> int:
    """调用 Vision 数画面里独立角色数。失败返回 -1（未知）。
    vision_fn: _call_micugpt2_vision(image_path, prompt) -> str | None
    """
    prompt = (
        "Count how many DISTINCT characters/people you see in this banner image. "
        "A 'character' is a complete human or humanoid figure with a visible body "
        "(not a face alone, not a hand, not background figures that are tiny/blurred). "
        "Reply with ONLY one number: 0, 1, 2, or 3. No other text."
    )
    raw = vision_fn(image_path, prompt)
    if not raw:
        return -1
    m = re.search(r'\b([0-3])\b', raw)
    if not m:
        return -1
    return int(m.group(1))


def _validate_text_art_format(image_path: str) -> dict:
    """像素级校验花字生图格式：背景应近黑、字符区应有亮像素。
    返回 dict：bg_mean, bg_dark, fg_ratio, has_text, note
    """
    im = Image.open(image_path).convert("L")
    arr = list(im.getdata())
    n = len(arr)
    if n == 0:
        return {"bg_mean": 0, "bg_dark": False, "fg_ratio": 0, "has_text": False, "note": "empty"}
    mean_val = sum(arr) / n
    bright = sum(1 for v in arr if v >= 200)
    fg_ratio = bright / n
    bg_dark = mean_val <= 30
    has_text = fg_ratio >= 0.05
    if not bg_dark and not has_text:
        note = "both failed: 输出既不是黑底也无亮字"
    elif not bg_dark:
        note = "background too bright（应纯黑但实际偏亮）"
    elif not has_text:
        note = "no text detected（亮像素不足）"
    else:
        note = "OK"
    return {"bg_mean": mean_val, "bg_dark": bg_dark, "fg_ratio": fg_ratio, "has_text": has_text, "note": note}

# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="LZ顶部banner 3840x1200 一站式流水线")
    parser.add_argument("char1", help="角色1（左位）")
    parser.add_argument("char2", help="角色2（中位）")
    parser.add_argument("char3", help="角色3（右位）")
    parser.add_argument("-HD", "--template", dest="template_name", default=None,
                        help="模板名（如 活动1 或 1），读取 scripts/synthesize_templates.json")
    parser.add_argument("--text-art", default=None, dest="text_art_desc",
                        help='花字生图描述，如: 前程似锦毛笔书法')
    parser.add_argument("--main-title", "-m", default="", help="主标题（命名用）")
    parser.add_argument("--logo", default=None, help="Logo 透明PNG路径")
    parser.add_argument("--output-dir", default=None, help="输出目录（默认 auto）")
    args = parser.parse_args()

    # ── 校验输入 ──────────────────────────────────────────────
    char_images = [Path(p).resolve() for p in (args.char1, args.char2, args.char3)]
    for i, p in enumerate(char_images, 1):
        if not p.is_file():
            print(f"Error: 角色图{i} 不存在: {p}", file=sys.stderr)
            sys.exit(1)

    # ── 加载模板 ──────────────────────────────────────────────
    templates_file = ROOT / "scripts" / "synthesize_templates.json"
    templates = json.loads(templates_file.read_text(encoding="utf-8")) if templates_file.is_file() else {}

    raw = args.template_name
    if raw and raw.isdigit():
        raw = f"活动{raw}"
    tpl = templates.get(raw) if raw else None
    if raw and not tpl:
        print(f"Error: 模板不存在: {args.template_name}", file=sys.stderr)
        print(f"可用模板: {', '.join(templates.keys())}", file=sys.stderr)
        sys.exit(1)

    layout_image = Path(tpl["layout"]) if tpl else (ROOT / "input" / "layout_template.png")
    if not Path(layout_image).is_file():
        print(f"Error: 排版参考图不存在: {layout_image}", file=sys.stderr)
        sys.exit(1)

    tpl_label = args.template_name or "default"
    print(f"模板: {tpl_label} | 排版参考: {Path(layout_image).name}", flush=True)

    # ── 输出目录 ──────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{raw}_" if raw else ""
    title = args.main_title or ""
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:30]
    run_dir = Path(args.output_dir).resolve() if args.output_dir else (
        ROOT / "output" / f"{prefix}LZ顶部_{safe_title}_{ts}" if safe_title else ROOT / "output" / f"{prefix}LZ顶部_{ts}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {run_dir}", flush=True)

    total = 4 if args.text_art_desc else 3
    tgt_w = tpl["width"] if tpl else 2172
    tgt_h = tpl["height"] if tpl else 724

    # ═══════════════ S1: 合成 3:1 复合图 ════════════════════
    print(f"\n[1/{total}] 合成3角色到 3:1 复合图...", flush=True)
    SYNTH_PROMPT = f"""You are an expert banner compositing AI. I will give you 4 reference images:

Images 1-3 contain three different game characters.
Image 4 is a PRECISE SPATIAL TEMPLATE — a blurred version of the target composition showing exact character positions, sizes, overlap relationships, and background layout. Use this as a rigid composition guide.

Your task:
1. Create a SINGLE cohesive banner image. The three characters combined should occupy approximately 30% of the frame width, centered in the middle. Leave breathing room on both sides for the background.
2. Place all THREE characters from images 1-3 into the EXACT positions shown in the spatial template (Image 4):
   - Match each character's position, scale, and overlap depth precisely to the template
   - The overlap zones shown in the template are your exact guide for how characters interlock
3. Keep each character's appearance, clothing, pose, and dynamics EXACTLY as they are - do not change them
4. Unify the background with a cohesive cyberpunk city nightscape (neon pink/cyan lights, skyscrapers, glowing signs, night sky) following Image 4's spatial layout
5. Unify the lighting and color palette across all three characters to make them look like they belong in the same scene
6. The style should be high-quality game splash art / CG illustration, consistent dramatic lighting

Output the final banner image. Do not add any text or logo overlay.
Output image MUST be exactly {tgt_w}x{tgt_h} pixels."""

    all_images = char_images + [Path(layout_image)]
    labels = ["角色1(左)", "角色2(中)", "角色3(右)", "排版模板"]
    for i, (p, lb) in enumerate(zip(all_images, labels), 1):
        sz = Image.open(str(p)).size
        print(f"  [{lb}] {p.name} {sz[0]}x{sz[1]}")

    print("  发送合成请求 (micugpt2 chat i2i)...", flush=True)
    s1_content = None
    s1_last_err: str = ""
    for s1_retry in range(3):
        s1_content = chat_completions_image(
            [str(p) for p in all_images],
            SYNTH_PROMPT,
            timeout=300,
            max_retries=1,
        )
        if s1_content is not None:
            break
        s1_last_err = f"尝试 {s1_retry+1}/3 失败"
        print(f"    S1 {s1_last_err}", flush=True)
        if s1_retry < 2:
            time.sleep(5)
    if s1_content is None:
        print(f"Error: S1 合成失败（3次重试均失败，最近错误: {s1_last_err}）", file=sys.stderr)
        sys.exit(1)

    s1_path = run_dir / "s1_synthesized.png"
    s1_path.write_bytes(s1_content)
    s1_img = Image.open(str(s1_path))
    print(f"  S1 完成: {s1_path} ({s1_img.size[0]}x{s1_img.size[1]})", flush=True)

    # S1c: 完整性检查（Vision 数角色数）—— 不阻塞，仅警告
    print("  S1c: micugpt2 Vision 数角色完整性检查...", flush=True)
    os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
    try:
        from gemini_subject_detect import _call_micugpt2_vision as _vision
        n_chars = _count_distinct_characters(str(s1_path), _vision)
        expected = 3
        status = "OK" if n_chars >= expected else "WARN"
        print(f"  S1c 角色数: {n_chars}（期望 {expected}）— {status}", flush=True)
        (run_dir / "s1c_integrity.log").write_text(
            f"expected={expected}\ndetected={n_chars}\nstatus={status}\n",
            encoding="utf-8",
        )
    except Exception as e:
        print(f"  S1c 跳过（Vision 不可用: {e}）", flush=True)

    # ═══════════════ S2: 扩图到 3840×1200 ════════════════════
    print(f"\n[2/{total}] 扩图到 {TOP_BANNER_W}x{TOP_BANNER_H}...", flush=True)

    # S2a: micugpt2 Vision bbox 检测
    print("  S2a: micugpt2 Vision 检测主体 bbox...", flush=True)
    os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
    from gemini_subject_detect import detect_subject_bbox
    bbox = detect_subject_bbox(str(s1_path), max_retries=2)
    if bbox is None:
        print("Warning: bbox 检测失败，使用默认框 (0.1, 0.1, 0.9, 0.9)", file=sys.stderr)
        bbox = (0.1, 0.1, 0.9, 0.9)
    print(f"  bbox: ({bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f})", flush=True)

    # S2b: 主体贴入 3840×1200 安全区（空白填 sentinel 色）
    print("  S2b: 主体贴入画布安全区...", flush=True)
    from safe_zone_scale_composite import composite_to_canvas_center

    s2b_path = run_dir / "s2b_composited.png"
    composite_to_canvas_center(
        str(s1_path), str(s2b_path),
        canvas_w=TOP_BANNER_W, canvas_h=TOP_BANNER_H,
        subject_bbox=bbox,
        subject_ratio=0.80,
        center_x_ratio=SAFE_CENTER_X_RATIO,
        center_y_ratio=SAFE_CENTER_Y_RATIO,
    )
    s2b_img = Image.open(str(s2b_path))
    print(f"  S2b 完成: {s2b_path} ({s2b_img.size[0]}x{s2b_img.size[1]})", flush=True)

    # S2c: micugpt2 i2i 填充空白区（带 mask 保护主体）
    print("  S2c: micugpt2 i2i 填充空白区域（sentinel mask 保护主体）...", flush=True)
    from prepare_background import _micugpt2_edit_image, _generate_sentinel_mask

    s2c_mask_tmp = _generate_sentinel_mask(str(s2b_path))
    print(f"  sentinel mask: {s2c_mask_tmp}", flush=True)

    s2c_path = run_dir / "s2c_filled_temp.png"
    s2c_ok = False
    s2c_last_error = None
    try:
        for s2c_attempt in range(4):
            try:
                os.environ.pop("MICUGPT2_NO_PROXY", None) if s2c_attempt % 2 == 0 else os.environ.__setitem__("MICUGPT2_NO_PROXY", "1")
                _micugpt2_edit_image(
                    str(s2b_path), str(s2c_path), S2_FILL_PROMPT,
                    mask_path=s2c_mask_tmp,
                )
                s2c_ok = True
                break
            except Exception as e:
                s2c_last_error = e
                if s2c_attempt < 3:
                    time.sleep(3)
    finally:
        try:
            os.unlink(s2c_mask_tmp)
        except OSError:
            pass
    if not s2c_ok:
        print(f"Error: S2c 失败: {s2c_last_error}", file=sys.stderr); sys.exit(1)

    s2c_img = Image.open(str(s2c_path))
    if s2c_img.size != (TOP_BANNER_W, TOP_BANNER_H):
        print(f"  S2c 尺寸不符 {s2c_img.size[0]}x{s2c_img.size[1]}，缩放到 {TOP_BANNER_W}x{TOP_BANNER_H}...", flush=True)
        s2c_img = s2c_img.resize((TOP_BANNER_W, TOP_BANNER_H), Image.Resampling.LANCZOS)
        s2c_img.save(str(s2c_path), "PNG")
    print(f"  S2c 完成: {s2c_path} ({s2c_img.size[0]}x{s2c_img.size[1]})", flush=True)

    s2_path = run_dir / "s2_expanded.png"
    shutil.copy2(str(s2c_path), str(s2_path))
    print(f"  S2 完成: {s2_path} ({TOP_BANNER_W}x{TOP_BANNER_H})", flush=True)

    # Vision 风格分析（用于花字色调统一）
    text_art_style_hint = ""
    if args.text_art_desc:
        style_prompt = (
            "Analyze this banner image. Describe the dominant colors, color temperature, "
            "lighting mood, and overall artistic style in 1-2 short sentences (in Chinese). "
            "Focus on visual atmosphere and palette. Reply with only the description."
        )
        os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
        from gemini_subject_detect import _call_micugpt2_vision
        raw_hint = _call_micugpt2_vision(str(s2_path), style_prompt) or ""
        raw_hint = re.sub(r'!\[.*?\]\(https?://[^\s)]+\)', '', raw_hint).strip()
        if raw_hint:
            text_art_style_hint = raw_hint
            print(f"  画面风格分析: {text_art_style_hint}", flush=True)

    # ═══════════════ S3: 生成花字（可选） ═════════════════════
    title_art_rgba_path = None
    if args.text_art_desc:
        print(f"\n[3/{total}] 生成花字...", flush=True)
        print(f"  描述: {args.text_art_desc[:80]}...")

        text_art_prompt = (
            (f"Style reference (match this visual style): {text_art_style_hint}. " if text_art_style_hint else "") +
            f"Create an artistic text design: {args.text_art_desc}. "
            "CRITICAL FORMAT REQUIREMENT (mandatory):\n"
            "(1) Background MUST be a flat, solid PURE BLACK (RGB 0,0,0) — NOT dark gray, NOT gradient, NOT scene background.\n"
            "(2) The text characters MUST be WHITE or near-white (RGB ≥ 230,230,230) — high contrast against the black background.\n"
            "(3) The text must fill ~60-80% of the frame area, centered both horizontally and vertically.\n"
            "(4) No other elements — no borders, no shadows, no textures, no scene — just the stylized text on pure black.\n"
            "(5) The text should be the only bright area; everything else must be solid black.\n"
            "Failure to provide a pure black background will break downstream processing."
        )

        try:
            from generate_from_description import _generate_image_micugpt2
        except ImportError:
            print("Error: 无法导入 generate_from_description 模块", file=sys.stderr)
            sys.exit(1)

        ta_raw_path = run_dir / "s3_text_art_raw.png"
        for ta_retry in range(3):
            result = _generate_image_micugpt2(text_art_prompt, str(ta_raw_path))
            if result and result.is_file():
                break
            if ta_retry < 2:
                time.sleep(3)
        if result and result.is_file():
            print(f"  花字生图完成: {ta_raw_path}", flush=True)

            ta_check = _validate_text_art_format(str(ta_raw_path))
            print(f"  S3 格式检查: 背景均值 {ta_check['bg_mean']:.1f}（≤30?）= {ta_check['bg_dark']} | "
                  f"亮像素占比 {ta_check['fg_ratio']:.1%}（≥5%?）= {ta_check['has_text']}", flush=True)
            if not ta_check["bg_dark"] or not ta_check["has_text"]:
                print(f"  Warning: 花字生图未达预期（{ta_check['note']}），亮度蒙版结果可能异常。", flush=True)

            rgba = _brightness_mask_to_rgba(ta_raw_path.read_bytes())
            title_art_rgba_path = run_dir / "s3_text_art_rgba.png"
            rgba.save(str(title_art_rgba_path), "PNG")
            print(f"  亮度蒙版完成: {title_art_rgba_path}", flush=True)
        else:
            print("Warning: 花字生图失败，跳过。", file=sys.stderr)

    # ═══════════════ S4: 叠花字 + Logo → 最终输出 ═════════════
    step_num = 4 if args.text_art_desc else 3
    print(f"\n[{step_num}/{total}] 合成最终输出...", flush=True)

    final_bg = Image.open(str(s2_path)).convert("RGB")
    final = final_bg.convert("RGBA")

    # 叠花字
    if title_art_rgba_path and title_art_rgba_path.is_file():
        _composite_rect_centered(final, title_art_rgba_path, TITLE_ART_RECT, TITLE_ART_SCALE, "title_art")
    else:
        print("  (跳过花字)", flush=True)

    # 叠 Logo
    if args.logo:
        logo_path = Path(args.logo).resolve()
        if logo_path.is_file() and LOGO_RECT:
            logo_rect_xywh = (LOGO_RECT[0], LOGO_RECT[1], LOGO_RECT[2], LOGO_RECT[3])
            _composite_logo(final, logo_path, logo_rect_xywh, LOGO_SCALE)
        else:
            print(f"  Warning: Logo不存在或无logo_rect: {logo_path}", file=sys.stderr)
    else:
        print("  (跳过 Logo)", flush=True)

    # 输出
    final_path = run_dir / TOP_BANNER_FILENAME
    final.convert("RGB").save(str(final_path), "PNG")
    print(f"\n[Done] 最终输出: {final_path}", flush=True)

    # 清理中间产物（保留最终 + 花字透明PNG + S2扩图）
    # s1_synthesized.png and s3_text_art_raw.png could be deleted
    # but we keep them for debugging. User can delete manually.


def _composite_rect_centered(bg: Image.Image, asset_path: Path,
                             rect: tuple, scale_k: float, label: str):
    """Paste asset into rect, centered, with fit scale."""
    x_min, x_max, y_min, y_max = rect
    rw = max(1, x_max - x_min)
    rh = max(1, y_max - y_min)

    art = Image.open(asset_path).convert("RGBA")
    # Trim transparent borders
    alpha = art.split()[-1]
    bbox = alpha.getbbox()
    if bbox:
        art = art.crop(bbox)
    aw, ah = art.size

    fit = min(rw / aw, rh / ah) * scale_k
    nw = max(1, int(round(aw * fit)))
    nh = max(1, int(round(ah * fit)))
    art = art.resize((nw, nh), Image.Resampling.LANCZOS)

    px = x_min + (rw - nw) // 2
    py = y_min + (rh - nh) // 2
    bg.paste(art, (px, py), art)
    print(f"  叠加 {label}: ({px},{py}) {nw}x{nh}", flush=True)


def _composite_logo(bg: Image.Image, logo_path: Path,
                    logo_rect: tuple, scale_k: float):
    """Paste logo into logo_rect (x, y, w, h), centered, with fit scale."""
    lx, ly, lw, lh = logo_rect

    logo = Image.open(logo_path).convert("RGBA")
    # Trim transparent
    alpha = logo.split()[-1]
    bbox = alpha.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    lw_a, lh_a = logo.size

    fit = min(lw / lw_a, lh / lh_a) * scale_k
    nw = max(1, int(round(lw_a * fit)))
    nh = max(1, int(round(lh_a * fit)))
    logo = logo.resize((nw, nh), Image.Resampling.LANCZOS)

    px = lx + (lw - nw) // 2
    py = ly + (lh - nh) // 2
    bg.paste(logo, (px, py), logo)
    print(f"  叠加 logo: ({px},{py}) {nw}x{nh}", flush=True)


if __name__ == "__main__":
    main()
