#!/usr/bin/env python3
"""
战报 KV 视觉：Gemini / Nano 图生图（.env GEMINI_API_KEY + Packy base URL）。

**默认定稿（BATTLE_REPORT_NANO_BANANA=1）**  
小 Banner 底图：优先 **MICU** 文生图（`MICU_API_KEY`），可回退 baoyu / nano-banana / Packy；**无字、无人物**，再由 Pillow 本地叠字 + 透明 PNG 角色：
- 头图数据区：**程序化 ai_stage 舞台** + 本地叠字（默认不生成/不复用 `hero_data_kv_bg`、`ai_hero_data.png`）
- `banner_kv_b/c/d.png` — 小 Banner 栏条底

勿用整图 AI 人物/写字模式，除非显式调试：`BATTLE_REPORT_AI_KV_FULL=1`、
`BATTLE_REPORT_NANO_STYLE_REF=strip`（会复用带人物的 ai_* 条带，非当前规范）。

`BATTLE_REPORT_NANO_STYLE_REF=0`（推荐）：小 Banner 底图 **文生图**，仅用 KV 取色 theme 描述风格，**不把 KV 图作 i2i 参考**；
小 Banner 刷新：`BATTLE_REPORT_NANO_BANANA_REFRESH=1`。
`BATTLE_REPORT_NANO_BANANA_REFRESH=1`：强制重生成底图。
`BATTLE_REPORT_NANO_QUALITY=fast|high`（见 docs/战报取色方案.md §2.2.1）
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from scripts.battle_report.env_setup import nano_image_model, setup_battle_report_env

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CANVAS_W = 1080
SECTION_BANNER_H = 280
SECTION_BANNER_AI_H = 280
HERO_DATA_BG_H = 440
HERO_DATA_AI_STRIP_H = 380

_GEMINI_BG_NO_FIGURES = (
    "Absolutely NO characters, NO people, NO humanoids, NO animals, NO pets, "
    "NO wildlife, NO birds, NO fish, NO insects, NO creatures, NO monsters, "
    "NO dragons, NO portraits, NO faces, NO hands, NO silhouettes, NO figurines, "
    "NO mascots, NO cosplay, NO NPCs. "
    "ONLY abstract background: gradients, light streaks, particles, texture — nothing alive."
)
_SECTION_BANNER_BG_ONLY = (
    "Generate ONLY a plain decorative section-header backdrop (wallpaper / UI plate). "
    "The image must look empty — as if characters will be pasted on later in Photoshop. "
    "Do NOT illustrate any person or animal even in the distance or as blur."
)
_GEMINI_BG_NO_TEXT = (
    "NO text, NO letters, NO numbers, NO digits, NO Chinese characters, "
    "NO metallic 3D typography, NO statistics, NO exposure/download mockups, "
    "NO logos, NO watermark, NO UI mockups, NO screenshot frames, "
    "NO trapezoid panels or picture frames around empty areas."
)


@dataclass
class BattleReportVisuals:
    mode: str | None = None  # "full" | "hybrid" | "hybrid_strip" | "decor"
    nano_dir: Path | None = None
    hero_data_strip: Path | None = None
    section_banners: dict[str, Path] = field(default_factory=dict)


def _ensure_env() -> None:
    setup_battle_report_env()


def hero_data_image_enabled() -> bool:
    """
    头图数据区是否文生图（整图条带或 hero_data_kv_bg 底图）。
    默认 False：程序化 ai_stage 舞台 + 本地叠字，不生图、不复用 AI 缓存。
    BATTLE_REPORT_HERO_DATA_IMAGE=1 时开启。
    """
    _ensure_env()
    explicit = os.environ.get("BATTLE_REPORT_HERO_DATA_IMAGE", "").strip().lower()
    if explicit in ("0", "false", "no", "off", "prog", "programmatic"):
        return False
    if explicit in ("1", "true", "yes", "micu", "ai", "image"):
        return is_enabled()
    return False


def section_banner_image_enabled() -> bool:
    """
    小 Banner 是否走 MICU/Gemini 文生图底图。
    默认 False：用 KV 取色程序化底（参考 NTE 栏头格局，不出图）。
  BATTLE_REPORT_SECTION_BANNER_IMAGE=1 或 micu 时开启生图。
    """
    _ensure_env()
    explicit = os.environ.get("BATTLE_REPORT_SECTION_BANNER_IMAGE", "").strip().lower()
    if explicit in ("0", "false", "no", "off", "prog", "programmatic"):
        return False
    if explicit in ("1", "true", "yes", "micu", "ai", "image"):
        return is_enabled()
    return False


def is_enabled() -> bool:
    """有 MICU_API_KEY（或回退 GEMINI_API_KEY）时默认开启；BATTLE_REPORT_NANO_BANANA=0 可关闭。"""
    _ensure_env()
    flag = os.environ.get("BATTLE_REPORT_NANO_BANANA", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    if os.environ.get("MICU_API_KEY", "").strip():
        return True
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def is_kv_ai_full_mode() -> bool:
    """整图 AI 写字：中文画在图里（需显式 BATTLE_REPORT_AI_KV_FULL=1）。"""
    if not is_enabled():
        return False
    return os.environ.get("BATTLE_REPORT_AI_KV_FULL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def is_kv_ai_hybrid_mode() -> bool:
    """混合模式（默认）：Nano 生成底图 + Pillow 叠标题/数据/角色。"""
    return is_enabled() and not is_kv_ai_full_mode()


def should_refresh() -> bool:
    return os.environ.get("BATTLE_REPORT_NANO_BANANA_REFRESH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _style_ref_env() -> str:
    """strip=复用 114707 整图条带；i2i=仅生图时双参考；0=关闭；空=auto。"""
    return os.environ.get("BATTLE_REPORT_NANO_STYLE_REF", "").strip().lower()


def style_ref_strip_assets_ready(out_dir: Path) -> bool:
    if not out_dir.is_dir():
        return False
    if not (out_dir / "ai_hero_data.png").is_file():
        return False
    return all((out_dir / f"ai_banner_{k}.png").is_file() for k in ("b", "c", "d"))


def use_style_ref_strip_mode(out_dir: Path | None) -> bool:
    """仅显式 strip/114707 时复用 ai_* 整图条带；默认定稿为无字底图。"""
    if not is_kv_ai_hybrid_mode() or not out_dir:
        return False
    mode = _style_ref_env()
    if mode in ("strip", "cache", "114707"):
        return style_ref_strip_assets_ready(out_dir)
    return False


def use_style_ref_i2i(out_dir: Path | None) -> bool:
    if not is_kv_ai_hybrid_mode() or not out_dir:
        return False
    mode = _style_ref_env()
    if mode in ("0", "false", "no", "off", "strip", "cache", "114707"):
        return False
    if mode in ("i2i", "regen"):
        return True
    return (out_dir / "ai_hero_data.png").is_file() or any(
        (out_dir / f"ai_banner_{k}.png").is_file() for k in ("b", "c", "d")
    )


def _style_ref_section_path(out_dir: Path, section_key: str) -> Path | None:
    p = out_dir / f"ai_banner_{section_key}.png"
    return p if p.is_file() else None


def _style_ref_hero_path(out_dir: Path) -> Path | None:
    p = out_dir / "ai_hero_data.png"
    return p if p.is_file() else None


def _nano_banana_exe() -> tuple[Path | str | None, list[str]]:
    skills_dir = _PROJECT_ROOT / ".claude" / "skills"
    cli_ts = skills_dir / "nano-banana-2-skill-check" / "src" / "cli.ts"
    if cli_ts.is_file():
        bun = shutil.which("bun") or os.environ.get("BUN", "bun")
        return (bun, [str(cli_ts)])
    exe = os.environ.get("NANO_BANANA_EXE", "").strip()
    if exe and Path(exe).is_file():
        return (Path(exe), [])
    home = Path.home()
    for p in (home / ".bun" / "bin" / "nano-banana", home / ".bun" / "bin" / "nano-banana.exe"):
        if p.is_file():
            return (p, [])
    return (None, [])


def nano_banana_available() -> bool:
    _ensure_env()
    if not _nano_banana_exe()[0]:
        return False
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return True
    return (Path.home() / ".nano-banana" / ".env").is_file()


def decor_image_backend() -> str:
    """
    装饰底图后端：xingchengpt | packygpt | micugpt2 | micu | baoyu | nano-banana | gemini。
    优先读取 BATTLE_IMAGE_BACKEND 环境变量，其次按可用性自动检测。
    """
    # 优先检查 BANNER_IMAGE_BACKEND（与主生图管线一致）
    img_be = os.environ.get("BANNER_IMAGE_BACKEND", "").strip().lower()
    if img_be in ("xingchengpt", "packygpt", "micugpt2", "xinchengpt"):
        return img_be

    explicit = os.environ.get("BATTLE_REPORT_IMAGE_BACKEND", "").strip().lower()
    if explicit in ("micu", "micuapi"):
        return "micu"
    if explicit in ("baoyu", "baoyu-image-gen"):
        return "baoyu"
    if explicit in ("nano-banana", "nano", "nano_banana"):
        return "nano-banana"
    if explicit in ("gemini", "packy"):
        return "gemini"
    from scripts.battle_report.baoyu_image_gen import baoyu_image_gen_available
    from scripts.battle_report.micu_image_gen import micu_available

    if micu_available():
        return "micu"
    if baoyu_image_gen_available():
        return "baoyu"
    if nano_banana_available():
        return "nano-banana"
    return "gemini"


def _run_gemini_i2i_fallback(
    prompt: str,
    output_path: Path,
    *,
    ref_paths: list[Path],
    width: int,
    height: int,
) -> Path | None:
    """Packy/Gemini 图生图（banner-background-from-description 同源 API）。"""
    refs = [p for p in ref_paths if p and p.is_file()]
    if not refs:
        return None
    _ensure_env()
    try:
        import sys

        skill_scripts = _PROJECT_ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts"
        if str(skill_scripts) not in sys.path:
            sys.path.insert(0, str(skill_scripts))
        from generate_from_description import _generate_image_gemini_i2i
    except ImportError as exc:
        print(f"[战报/gemini] 无法加载图生图模块: {exc}", flush=True)
        return None

    tmp = output_path.parent / f"_tmp_gemini_{output_path.stem}.png"
    result = _generate_image_gemini_i2i(prompt, str(refs[0]), str(tmp))
    if not result or not tmp.is_file():
        print("[战报/gemini] 图生图失败", flush=True)
        return None
    from PIL import Image

    out = Image.open(tmp).convert("RGB")
    if out.size != (width, height):
        out = _fit_cover(out, width, height)
    out.save(output_path, "PNG")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"[战报/gemini] Packy/Gemini i2i → {output_path.name} ({width}×{height})", flush=True)
    return output_path


def _run_decor_i2i(
    prompt: str,
    output_path: Path,
    *,
    ref_paths: list[Path],
    width: int,
    height: int,
    aspect: str = "21:9",
    timeout: int = 360,
) -> Path | None:
    """战报装饰底图：baoyu-image-gen → nano-banana → Gemini i2i。"""
    backend = decor_image_backend()
    # xingchengpt / packygpt / micugpt2 为 t2i 后端，i2i 直接回退 Gemini
    if backend in ("xingchengpt", "packygpt", "micugpt2", "xinchengpt"):
        return _run_gemini_i2i_fallback(
            prompt, output_path, ref_paths=ref_paths, width=width, height=height,
        )
    if backend == "baoyu":
        from scripts.battle_report.baoyu_image_gen import run_baoyu_i2i

        p = run_baoyu_i2i(
            prompt, output_path, ref_paths=ref_paths, width=width, height=height, timeout=timeout,
        )
        if p:
            return p
        print("[战报] baoyu 失败，尝试回退 nano-banana / Gemini", flush=True)
    if backend in ("nano-banana", "nano") or nano_banana_available():
        p = _run_nano_banana_i2i(
            prompt, output_path, ref_paths=ref_paths, aspect=aspect, timeout=timeout,
        )
        if p:
            with Image.open(p) as im:
                if im.size != (width, height):
                    _fit_cover(im, width, height).save(output_path, "PNG")
            return output_path
        print("[战报] nano-banana 失败，尝试回退 Gemini API", flush=True)
    return _run_gemini_i2i_fallback(
        prompt, output_path, ref_paths=ref_paths, width=width, height=height,
    )


def _run_gemini_t2i_fallback(
    prompt: str,
    output_path: Path,
    *,
    width: int,
    height: int,
) -> Path | None:
    """文生图：仅 prompt，无 KV 参考图。"""
    _ensure_env()
    try:
        import sys

        skill_scripts = _PROJECT_ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts"
        if str(skill_scripts) not in sys.path:
            sys.path.insert(0, str(skill_scripts))
        from generate_from_description import generate_image
    except ImportError as exc:
        print(f"[战报/gemini] 无法加载文生图模块: {exc}", flush=True)
        return None

    tmp = output_path.parent / f"_tmp_gemini_t2i_{output_path.stem}.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        generate_image(prompt, str(tmp), backend="gemini", width=width, height=height)
    except SystemExit:
        return None
    if not tmp.is_file():
        return None
    from PIL import Image

    Image.open(tmp).convert("RGB").save(output_path, "PNG")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"[战报/gemini] t2i(KV风格色板) → {output_path.name} ({width}×{height})", flush=True)
    return output_path


def _run_nano_banana_t2i(
    prompt: str,
    output_path: Path,
    *,
    aspect: str = "21:9",
    timeout: int = 240,
) -> Path | None:
    """nano-banana 文生图：不传 -r 参考图。"""
    exe, prefix_args = _nano_banana_exe()
    if not exe:
        return None
    out_path = output_path.resolve()
    out_dir = out_path.parent
    out_stem = out_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    _ensure_env()
    model = nano_image_model()
    cmd = [str(exe)] + prefix_args + [
        prompt,
        "-o", out_stem,
        "-d", str(out_dir),
        "-s", "2K",
        "-a", aspect,
        "-m", model,
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
            env=os.environ.copy(),
        )
        if r.returncode != 0:
            print(f"[战报/nano] t2i 生成失败: {r.stderr or r.stdout}", flush=True)
            return None
        gen = out_dir / f"{out_stem}.png"
        if not gen.is_file():
            return None
        if gen.resolve() != out_path.resolve():
            shutil.copy2(gen, out_path)
        return out_path
    except subprocess.TimeoutExpired:
        print("[战报/nano] t2i 生成超时", flush=True)
        return None
    except Exception as exc:
        print(f"[战报/nano] t2i 调用异常: {exc}", flush=True)
        return None


def _run_decor_style_bg(
    prompt: str,
    output_path: Path,
    *,
    width: int,
    height: int,
    aspect: str = "21:9",
    timeout: int = 360,
) -> Path | None:
    """小 Banner 等：仅参照 KV 取色风格（文生图），不把 KV 图作为 i2i 输入。"""
    backend = decor_image_backend()
    # xingchengpt / packygpt / micugpt2 — gpt-image-2 兼容后端（t2i only）
    if backend in ("xingchengpt", "packygpt", "micugpt2", "xinchengpt"):
        from scripts.changtu.micu_image_gen import run_micu_t2i

        p = run_micu_t2i(
            prompt, output_path, width=width, height=height, timeout=timeout,
        )
        if p:
            return p
        # t2i 失败，回退 Gemini
        print(f"[战报/{backend}] t2i 失败，回退 Gemini", flush=True)
        return _run_gemini_t2i_fallback(prompt, output_path, width=width, height=height)
    if backend == "micu":
        from scripts.battle_report.micu_image_gen import run_micu_t2i

        p = run_micu_t2i(
            prompt, output_path, width=width, height=height, timeout=timeout,
        )
        if p:
            return p
        micu_only = os.environ.get("BATTLE_REPORT_IMAGE_BACKEND", "").strip().lower() in (
            "micu",
            "micuapi",
        )
        if micu_only:
            print("[战报/MICU] 小 Banner 生图失败（已设 BATTLE_REPORT_IMAGE_BACKEND=micu，不回退）", flush=True)
            return None
        print("[战报/MICU] 生图失败，尝试回退 baoyu / nano-banana / Gemini", flush=True)
    if backend == "baoyu":
        from scripts.battle_report.baoyu_image_gen import run_baoyu_i2i

        p = run_baoyu_i2i(
            prompt, output_path, ref_paths=[], width=width, height=height, timeout=timeout,
        )
        if p:
            return p
        print("[战报] baoyu t2i 失败，尝试回退 nano-banana / Gemini", flush=True)
    if backend in ("nano-banana", "nano") or nano_banana_available():
        p = _run_nano_banana_t2i(prompt, output_path, aspect=aspect, timeout=timeout)
        if p:
            if Image.open(p).size != (width, height):
                _fit_cover(Image.open(p), width, height).save(output_path, "PNG")
            return output_path
        print("[战报] nano-banana t2i 失败，尝试回退 Gemini", flush=True)
    return _run_gemini_t2i_fallback(prompt, output_path, width=width, height=height)


def _run_nano_banana_i2i(
    prompt: str,
    output_path: Path,
    *,
    ref_paths: list[Path],
    aspect: str = "21:9",
    timeout: int = 240,
) -> Path | None:
    exe, prefix_args = _nano_banana_exe()
    if not exe:
        print("[战报/nano] 未找到 nano-banana（需 bun + nano-banana-2-skill-check 或 NANO_BANANA_EXE）", flush=True)
        return None
    refs = [p.resolve() for p in ref_paths if p and p.is_file()]
    if not refs:
        print("[战报/nano] 未提供有效参考图", flush=True)
        return None
    out_path = output_path.resolve()
    out_dir = out_path.parent
    out_stem = out_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    _ensure_env()
    model = nano_image_model()
    cmd = [str(exe)] + prefix_args + [prompt]
    for rp in refs:
        cmd.extend(["-r", str(rp)])
    cmd.extend(
        [
            "-o",
            out_stem,
            "-d",
            str(out_dir),
            "-s",
            "2K",
            "-a",
            aspect,
            "-m",
            model,
        ]
    )
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
            env=os.environ.copy(),
        )
        if r.returncode != 0:
            print(f"[战报/nano] 生成失败: {r.stderr or r.stdout}", flush=True)
            return None
        gen = out_dir / f"{out_stem}.png"
        if not gen.is_file():
            return None
        if gen.resolve() != out_path.resolve():
            shutil.copy2(gen, out_path)
        return out_path
    except subprocess.TimeoutExpired:
        print("[战报/nano] 生成超时", flush=True)
        return None
    except Exception as exc:
        print(f"[战报/nano] 调用异常: {exc}", flush=True)
        return None


def _fit_cover(img: Image.Image, width: int, height: int) -> Image.Image:
    src = img.convert("RGB")
    sw, sh = src.size
    scale = max(width / sw, height / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - width) // 2
    top = (nh - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _fit_contain(
    img: Image.Image,
    width: int,
    height: int,
    fill: tuple[int, int, int] = (18, 20, 24),
) -> Image.Image:
    """等比缩放入画布，不裁切（小 Banner / 数据区缓存用）。"""
    src = img.convert("RGB")
    sw, sh = src.size
    scale = min(width / sw, height / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (width, height), fill)
    out.paste(resized, ((width - nw) // 2, (height - nh) // 2))
    return out


def _fit_width_rgb(img: Image.Image, width: int = CANVAS_W) -> Image.Image:
    if img.width == width:
        return img.convert("RGB")
    ratio = width / max(1, img.width)
    h = max(1, int(img.height * ratio))
    return img.convert("RGB").resize((width, h), Image.Resampling.LANCZOS)


def _theme_bright_hex(theme: dict) -> tuple[str, str]:
    p = theme.get("accent_bright") or theme.get("accent_primary", "#83B652")
    s = theme.get("accent_bright_alt") or theme.get("accent_secondary", "#4883B9")
    return str(p), str(s)


def _kv_style_palette_clause(theme: dict) -> str:
    """从 KV 取色的 theme JSON 描述风格；不把 KV 位图作为生图输入。"""
    primary, secondary = _theme_bright_hex(theme)
    bg = theme.get("bg_page", "#12141a")
    card = theme.get("bg_card_dark", "#0a0c10")
    return (
        "Style and palette extracted from the same mobile game's KV key art "
        "(color grading reference ONLY — do NOT paste, crop, trace, or composite the KV photograph). "
        f"Page tone {bg}, deep card {card}, vivid accents {primary} and {secondary}."
    )


def _analyze_kv_style(kv_path: Path, out_dir: Path) -> dict:
    """调用 Gemini Vision 分析 KV 的画风/构图/光源/氛围/母题，每次都重新生成。"""
    cache = out_dir / "kv_style.json"

    from scripts.battle_report.hero_design import call_vision_with_images

    prompt = """You are a game art style analyst. Analyze this KV key visual image and output ONLY a JSON object (no markdown, no explanation):

{
  "art_style": "选择最匹配的一项: realistic / anime / cyberpunk / guofeng_chinese / painterly / Q_style / sci_fi / fantasy / minimalist / dark_gothic / pop_art / cel_shaded",
  "composition": "选择最匹配的一项: center_focus / asymmetric_left / asymmetric_right / symmetric / diagonal / scattered / radial / rule_of_thirds",
  "lighting": "选择最匹配的一项: bottom_spotlight / side_rim_light / soft_diffuse / hard_key_light / neon_glow / volumetric_god_rays / dramatic_chiaroscuro / flat_even",
  "mood": "选择最匹配的一项: epic_heroic / dark_mysterious / joyful_celebration / serene_narrative / intense_battle / futuristic_tech / magical_fantasy / cute_playful",
  "motifs": ["列出 2-5 个视觉母题，如 crystal, magic_circle, fire, tech_lines, ink_wash, neon_grid, particle_splash, energy_beam, hologram, smoke, water_ripple, mechanical_gear, feather, nebula"],
  "color_mood": "选择最匹配的一项: warm_gold_orange / cool_blue_purple / high_saturation_clash / muted_earth / monochrome / pastel_soft / neon_dark / split_complementary",
  "depth_style": "选择最匹配的一项: shallow_bokeh / deep_atmospheric / flat_graphic / layered_parallax"
}"""

    text = call_vision_with_images(prompt, [kv_path], thumb_max=0)
    style_info: dict = {}
    if text:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                style_info = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    if not style_info:
        style_info = {
            "art_style": "fantasy",
            "composition": "center_focus",
            "lighting": "soft_diffuse",
            "mood": "epic_heroic",
            "motifs": [],
            "color_mood": "warm_gold_orange",
            "depth_style": "shallow_bokeh",
        }
        print("[战报/style] Vision 未返回有效 JSON，使用默认风格描述", flush=True)
    else:
        if cache.is_file():
            c1 = cache.with_suffix(".json.1")
            c2 = cache.with_suffix(".json.2")
            if c2.is_file():
                c2.unlink(missing_ok=True)
            if c1.is_file():
                c1.rename(c2)
            cache.rename(c1)
        cache.write_text(json.dumps(style_info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[战报/style] KV 风格分析: art={style_info.get('art_style')} "
            f"compo={style_info.get('composition')} light={style_info.get('lighting')} "
            f"mood={style_info.get('mood')} motifs={style_info.get('motifs')}",
            flush=True,
        )

    return style_info


def _style_info_to_clause(info: dict) -> str:
    """将 Vision 风格分析 dict 转为 prompt 注入子句。"""
    if not info:
        return ""
    parts = []
    mapping = {
        "art_style": {
            "realistic": "photorealistic cinematic render",
            "anime": "Japanese anime / cel animation art style",
            "cyberpunk": "cyberpunk neon-drenched aesthetic",
            "guofeng_chinese": "Chinese guofeng ink-painting fusion style",
            "painterly": "painterly concept art with visible brush strokes",
            "Q_style": "chibi Q-style cute proportions",
            "sci_fi": "sci-fi futuristic technology aesthetic",
            "fantasy": "high fantasy epic illustration",
            "minimalist": "minimalist clean geometric design",
            "dark_gothic": "dark gothic Victorian ornate style",
            "pop_art": "pop art bold graphic comic style",
            "cel_shaded": "cel-shaded toon render style",
        },
        "composition": {
            "center_focus": "strong center-weighted composition with radial energy",
            "asymmetric_left": "asymmetric layout with visual weight on the left",
            "asymmetric_right": "asymmetric layout with visual weight on the right",
            "symmetric": "perfectly symmetrical balanced composition",
            "diagonal": "dynamic diagonal sweep across the frame",
            "scattered": "scattered elements with organic flow",
            "radial": "radial burst expanding from center",
            "rule_of_thirds": "classic rule-of-thirds placement",
        },
        "lighting": {
            "bottom_spotlight": "dramatic floor spotlight / uplight with dark vignette",
            "side_rim_light": "strong rim light from the side, character silhouettes",
            "soft_diffuse": "soft diffuse ambient light, gentle shadows",
            "hard_key_light": "harsh directional key light with crisp shadows",
            "neon_glow": "vibrant neon / bioluminescent glow effects",
            "volumetric_god_rays": "volumetric god rays / crepuscular light beams",
            "dramatic_chiaroscuro": "high-contrast chiaroscuro light-dark drama",
            "flat_even": "flat even illumination, minimal shadows",
        },
        "mood": {
            "epic_heroic": "epic heroic cinematic atmosphere",
            "dark_mysterious": "dark mysterious foreboding tension",
            "joyful_celebration": "joyful festive celebration energy",
            "serene_narrative": "serene calm narrative tranquility",
            "intense_battle": "intense battle combat action",
            "futuristic_tech": "futuristic high-tech digital vibe",
            "magical_fantasy": "magical enchanting fantasy wonder",
            "cute_playful": "cute playful lighthearted charm",
        },
        "color_mood": {
            "warm_gold_orange": "warm gold-amber-orange dominant palette",
            "cool_blue_purple": "cool blue-cyan-purple dominant palette",
            "high_saturation_clash": "high-saturation color clash pop palette",
            "muted_earth": "muted earthy desaturated tones",
            "monochrome": "monochromatic single-hue scheme",
            "pastel_soft": "soft pastel dreamy palette",
            "neon_dark": "dark background with neon accent pops",
            "split_complementary": "split-complementary dual-color scheme",
        },
        "depth_style": {
            "shallow_bokeh": "shallow depth of field with bokeh blur",
            "deep_atmospheric": "deep atmospheric perspective with fog layers",
            "flat_graphic": "flat graphic depth with minimal perspective",
            "layered_parallax": "multi-layered parallax depth with foreground/midground/background separation",
        },
    }
    for key, label_map in mapping.items():
        val = info.get(key, "")
        if val and val in label_map:
            parts.append(label_map[val])

    motifs = info.get("motifs", [])
    if motifs:
        parts.append(f"visual motifs: {', '.join(str(m) for m in motifs)}")

    return "; ".join(parts) if parts else ""


def _section_banner_full_prompt(
    theme: dict,
    *,
    section_key: str,
    title: str,
    char_side: str,
) -> str:
    bright_p, bright_s = _theme_bright_hex(theme)
    side = "left" if char_side == "left" else "right"
    text_side = "right" if char_side == "left" else "left"
    return (
        "Design a complete horizontal game section header banner as one finished poster, "
        "strictly matching the reference KV color mood, lighting, and fantasy art style. "
        f"Vivid accent colors {bright_p} and {bright_s}, high contrast, not muddy or grey. "
        f"Large game character on the {side}, dynamic pose, can extend slightly above the banner top. "
        f"On the {text_side}, render the section title in bold Chinese: 「{title}」 "
        "with diagonal color blocks and splash energy behind the text. "
        "Chapter-header layout like premium mobile game KV extensions, cinematic rim light. "
        "All Chinese text must be clear and readable. "
        "NO watermark, NO extra logos beyond game style, NO UI screenshots."
    )


def _hero_data_full_prompt(
    theme: dict,
    *,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
) -> str:
    bright_p, bright_s = _theme_bright_hex(theme)
    stat_lines = []
    if stats:
        for label, value in stats:
            stat_lines.append(f"「{value}」 next to smaller label 「{label.strip('：:')}」")
    stats_desc = "; ".join(stat_lines) if stat_lines else "large white statistics numbers"
    launch = f"Chinese launch line 「{bar_text}」 as a small pill banner on top. " if bar_text.strip() else ""
    return (
        "Design a complete lower data showcase strip for a game battle report, "
        "same universe and palette as the reference KV image. "
        f"{launch}"
        f"Hero monument data poster: {stats_desc}, huge white numbers with floor spotlight and long shadows. "
        f"Vivid rim lights {bright_p} and {bright_s}, dark cinematic stage, strong bottom-center glow. "
        "Epic mobile game launch billboard aesthetic, asymmetric depth, high contrast highlights. "
        "Render all Chinese text clearly as part of the artwork. "
        "NO watermark, NO unrelated logos, NO UI mockups."
    )


_SECTION_MOOD: dict[str, str] = {
    "b": "core resources matrix battle-report chapter",
    "c": "collaboration event hype chapter",
    "d": "player praise testimonials chapter",
}


def _section_banner_decor_prompt(
    theme: dict, section_key: str, *, section_title: str = "", style_info: dict | None = None,
) -> str:
    mood = _SECTION_MOOD.get(section_key, "battle-report section")
    title_hint = (
        f" (section theme: {section_title}, do NOT render this title)" if section_title.strip() else ""
    )
    palette = _kv_style_palette_clause(theme)
    style_clause = _style_info_to_clause(style_info or {})
    style_hint = f" Art direction: {style_clause}." if style_clause else ""
    return (
        f"{_SECTION_BANNER_BG_ONLY} "
        "Ultra-wide horizontal mobile game battle-report section header strip, PURE BACKGROUND PLATE. "
        f"{palette} "
        f"Abstract painterly game UI backdrop in that palette: rim glow, diagonal streaks, "
        f"splatter energy, soft depth — {mood}{title_hint}.{style_hint} "
        "Uniform decorative background across the entire strip — no left/right color split, "
        "no reserved text zones, no tinting differences between halves. "
        "Original abstract design; NOT a crop or edit of the KV photograph. "
        f"{_GEMINI_BG_NO_FIGURES} {_GEMINI_BG_NO_TEXT}"
    )


def _hero_data_bg_mood_clause(
    *, bar_text: str = "", stats: list[tuple[str, str]] | None = None,
) -> str:
    """构图氛围提示（禁止在图内生成文案/数字）。"""
    parts = [
        "one unified launch+metrics module plate: top zone for LOCAL launch headline overlay",
        "bottom zone on the SAME panel for LOCAL statistics (exposure/download) overlay",
        "no horizontal divider or separate cards between headline and metrics",
    ]
    if bar_text.strip():
        parts.append(
            "mood of campaign kickoff ribbon energy (do NOT render Chinese launch copy)"
        )
    if stats:
        parts.append(
            "mood of epic exposure/download billboard scale (do NOT render numbers or labels)"
        )
    return "; ".join(parts)


def _hero_data_bg_prompt(
    theme: dict,
    *,
    bar_text: str = "",
    stats: list[tuple[str, str]] | None = None,
    style_info: dict | None = None,
) -> str:
    primary, secondary = _theme_bright_hex(theme)
    mood = _hero_data_bg_mood_clause(bar_text=bar_text, stats=stats)
    style_clause = _style_info_to_clause(style_info or {})
    style_hint = f" Art direction: {style_clause}." if style_clause else ""
    return (
        "Wide cinematic mobile game battle-report unified LAUNCH+DATA module background ONLY — "
        f"{mood}.{style_hint} "
        "Soft abstract floor, volumetric light, rim glow; edges fade into darkness. "
        "NO frames, borders, trapezoids, picture-in-picture boxes, metallic 3D typography. "
        "Same universe and color grading as reference KV game key visual. "
        f"Accent rim mood {primary} and {secondary}. "
        f"{_GEMINI_BG_NO_FIGURES} {_GEMINI_BG_NO_TEXT}"
    )


def _hero_data_bg_style_ref_prompt(
    theme: dict,
    *,
    bar_text: str = "",
    stats: list[tuple[str, str]] | None = None,
    style_info: dict | None = None,
) -> str:
    primary, secondary = _theme_bright_hex(theme)
    mood = _hero_data_bg_mood_clause(bar_text=bar_text, stats=stats)
    style_clause = _style_info_to_clause(style_info or {})
    style_hint = f" Art direction: {style_clause}." if style_clause else ""
    return (
        "Use the FIRST reference only for abstract floor glow and color mood — "
        "DELETE every character, frame, panel, border, and ALL text/numbers. "
        "Match game KV style of the SECOND reference. "
        f"{mood}.{style_hint} "
        f"Rim mood {primary} and {secondary}; smooth edges. "
        f"{_GEMINI_BG_NO_FIGURES} {_GEMINI_BG_NO_TEXT}"
    )


def ensure_ai_section_banner(
    kv_path: Path,
    theme: dict,
    *,
    section_key: str,
    title: str,
    char_side: str,
    out_dir: Path,
) -> Path | None:
    out = out_dir / f"ai_banner_{section_key}.png"
    if out.is_file() and not should_refresh():
        return out
    tmp = out_dir / f"_nano_ai_banner_{section_key}.png"
    prompt = _section_banner_full_prompt(
        theme, section_key=section_key, title=title, char_side=char_side,
    )
    if _run_nano_banana_i2i(prompt, tmp, ref_paths=[kv_path], aspect="21:9") is None:
        return None
    _fit_cover(Image.open(tmp), CANVAS_W, SECTION_BANNER_AI_H).save(out, "PNG")
    print(f"[战报/nano] AI 小 Banner ({section_key}): {out.name} · {title}", flush=True)
    return out


def ensure_ai_hero_data_strip(
    kv_path: Path,
    theme: dict,
    *,
    bar_text: str,
    stats: list[tuple[str, str]] | None,
    out_path: Path,
) -> Path | None:
    if out_path.is_file() and not should_refresh():
        return out_path
    tmp = out_path.parent / "_nano_ai_hero_data.png"
    prompt = _hero_data_full_prompt(theme, bar_text=bar_text, stats=stats)
    if _run_nano_banana_i2i(prompt, tmp, ref_paths=[kv_path], aspect="16:9") is None:
        return None
    _fit_cover(Image.open(tmp), CANVAS_W, HERO_DATA_AI_STRIP_H).save(out_path, "PNG")
    print(f"[战报/nano] AI 数据区整图: {out_path.name}", flush=True)
    return out_path


def ensure_section_banner_bg(
    _kv_path: Path,
    theme: dict,
    section_key: str,
    out_dir: Path,
    *,
    section_title: str = "",
    style_info: dict | None = None,
) -> Path | None:
    """小 Banner 底图：KV 风格色板 + 文生图；不传入 KV 位图作参考。"""
    out = out_dir / f"banner_kv_{section_key}.png"
    if out.is_file() and not should_refresh():
        return out
    tmp = out_dir / f"_nano_raw_banner_{section_key}.png"
    prompt = _section_banner_decor_prompt(
        theme, section_key, section_title=section_title, style_info=style_info,
    )
    if _run_decor_style_bg(
        prompt,
        tmp,
        width=CANVAS_W,
        height=SECTION_BANNER_AI_H,
        aspect="21:9",
    ) is None:
        return None
    raw = Image.open(tmp).convert("RGB")
    if raw.size != (CANVAS_W, SECTION_BANNER_AI_H):
        raw = _fit_cover(raw, CANVAS_W, SECTION_BANNER_AI_H)
    raw.save(out, "PNG")
    be = decor_image_backend()
    tag = "MICU" if be == "micu" else be
    print(
        f"[战报/{tag}] 小 Banner 底图 b/c/d · {section_key} "
        f"(KV风格/t2i/1080×{SECTION_BANNER_AI_H}): {out.name}",
        flush=True,
    )
    return out


def ensure_hero_data_bg(
    kv_path: Path,
    theme: dict,
    out_path: Path,
    *,
    bar_text: str = "",
    stats: list[tuple[str, str]] | None = None,
    style_info: dict | None = None,
) -> Path | None:
    if out_path.is_file() and not should_refresh():
        return out_path
    tmp = out_path.parent / "_nano_raw_hero_data.png"
    style_ref = _style_ref_hero_path(out_path.parent)
    if style_ref and use_style_ref_i2i(out_path.parent):
        prompt = _hero_data_bg_style_ref_prompt(theme, bar_text=bar_text, stats=stats, style_info=style_info)
        refs = [style_ref, kv_path]
        tag = "114707+KV"
    else:
        prompt = _hero_data_bg_prompt(theme, bar_text=bar_text, stats=stats, style_info=style_info)
        refs = [kv_path]
        tag = "KV"
    if _run_decor_i2i(
        prompt,
        tmp,
        ref_paths=refs,
        width=CANVAS_W,
        height=HERO_DATA_BG_H,
        aspect="16:9",
    ) is None:
        return None
    Image.open(tmp).convert("RGB").save(out_path, "PNG")
    print(f"[战报/decor] 数据区底图({tag}/无字/一体模块): {out_path.name}", flush=True)
    return out_path


def prepare_visual_assets(
    assets_dir: Path,
    kv_path: Path,
    theme: dict,
    *,
    section_specs: list[tuple[str, str, str]] | None = None,
    bar_text: str = "",
    stats: list[tuple[str, str]] | None = None,
) -> BattleReportVisuals:
    """
    合成前生成视觉资产。
    section_specs: [(key, 中文标题, char_side), ...] 例如 ("b", "核心资源矩阵", "left")
    """
    empty = BattleReportVisuals()
    if not is_enabled():
        return empty
    if not nano_banana_available() and not os.environ.get("MICU_API_KEY", "").strip() and not os.environ.get("GEMINI_API_KEY", "").strip():
        print(
            "[战报/nano] 已设 BATTLE_REPORT_NANO_BANANA=1 但未配置 MICU_API_KEY / GEMINI / nano-banana",
            flush=True,
        )
        return empty

    out_dir = assets_dir / ".battle_report_nano"
    out_dir.mkdir(parents=True, exist_ok=True)

    if is_kv_ai_full_mode():
        print(
            "[战报/nano] 模式: KV 纯 AI 小 Banner（数据区默认程序绘制，不生图）",
            flush=True,
        )
        banners: dict[str, Path] = {}
        specs = section_specs or [
            ("b", "核心资源矩阵", "left"),
            ("c", "联动活动火热开启", "right"),
            ("d", "玩家真实好评", "left"),
        ]
        for key, title, side in specs:
            p = ensure_ai_section_banner(
                kv_path, theme, section_key=key, title=title, char_side=side, out_dir=out_dir,
            )
            if p:
                banners[key] = p
        hero_strip = None
        if hero_data_image_enabled():
            hero_strip = ensure_ai_hero_data_strip(
                kv_path,
                theme,
                bar_text=bar_text,
                stats=stats,
                out_path=out_dir / "ai_hero_data.png",
            )
        if not banners and not hero_strip:
            print("[战报/nano] KV 纯 AI 生成失败，将回退程序绘制", flush=True)
            return empty
        return BattleReportVisuals(
            mode="full",
            nano_dir=out_dir,
            hero_data_strip=hero_strip,
            section_banners=banners,
        )

    if use_style_ref_strip_mode(out_dir):
        banners = {
            k: p
            for k in ("b", "c", "d")
            if (p := _style_ref_section_path(out_dir, k)) is not None
        }
        print(
            "[战报/nano] 数据区: 本地分色字体（无底色块）；小 Banner 可复用 ai_banner_*",
            flush=True,
        )
        return BattleReportVisuals(
            mode="hybrid",
            nano_dir=out_dir,
            section_banners=banners,
        )

    if not section_banner_image_enabled():
        banners: dict[str, Path] = {}
        for key in ("b", "c", "d"):
            cached = out_dir / f"banner_kv_{key}.png"
            if cached.is_file() and not should_refresh():
                banners[key] = cached
        if banners:
            names = ", ".join(f"{k}={p.name}" for k, p in sorted(banners.items()))
            print(f"[战报] 小 Banner: 复用缓存底图（{names}），不重新生图", flush=True)
        else:
            print(
                "[战报] 小 Banner: KV 炫彩程序化底（斜切分区）+ 标题衬底 + 透明角色，不生图",
                flush=True,
            )
        return BattleReportVisuals(mode="hybrid", nano_dir=out_dir, section_banners=banners)

    from scripts.battle_report.env_setup import log_api_backend

    log_api_backend()
    be = decor_image_backend()
    print(
        f"[战报/decor] 模式: {be} 生成 KV 游戏风底图（无字无人物）"
        "+ 本地字体叠标题 + 透明 PNG 主K",
        flush=True,
    )
    # 风格分析：Gemini Vision 分析 KV 画风/构图/光源/氛围
    style_info = _analyze_kv_style(kv_path, out_dir)
    specs = section_specs or [
        ("b", "核心资源矩阵", "left"),
        ("c", "联动活动火热开启", "right"),
        ("d", "玩家真实好评", "left"),
    ]
    banners: dict[str, Path] = {}
    for key, title, _side in specs:
        p = ensure_section_banner_bg(
            kv_path, theme, key, out_dir, section_title=title, style_info=style_info,
        )
        if p:
            banners[key] = p
    return BattleReportVisuals(
        mode="hybrid",
        nano_dir=out_dir,
        section_banners=banners,
    )


def resolve_or_create_hero_data_bg(
    kv_path: Path,
    theme: dict,
    nano_dir: Path | None,
    *,
    bar_text: str = "",
    stats: list[tuple[str, str]] | None = None,
    style_info: dict | None = None,
) -> Path | None:
    """数据区无字底图；默认关闭，仅 BATTLE_REPORT_HERO_DATA_IMAGE=1 时生成/复用缓存。"""
    if not hero_data_image_enabled() or not is_kv_ai_hybrid_mode() or not nano_dir:
        return None
    # 尝试加载缓存的风格分析
    if style_info is None:
        cache = nano_dir / "kv_style.json"
        if cache.is_file():
            try:
                style_info = json.loads(cache.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    for name in ("hero_data_kv_bg.png", "hero_data_bg.png"):
        p = nano_dir / name
        if p.is_file() and not should_refresh():
            return p
    return ensure_hero_data_bg(
        kv_path,
        theme,
        nano_dir / "hero_data_kv_bg.png",
        bar_text=bar_text,
        stats=stats,
        style_info=style_info,
    )


def ai_hero_strip_height(path: Path | None) -> int:
    if not path or not path.is_file():
        return 0
    with Image.open(path) as im:
        w, h = im.size
        if w <= 0:
            return 0
        return max(1, int(h * CANVAS_W / w))
