#!/usr/bin/env python3
"""
HD 统一产线 — LZ 顶部 Banner 3840×1200（4 阶段）。

后端配置由 _packy.apply_packy_backend() 统一设置，本模块只读标准环境变量：
  Vision:  GEMINI_API_KEY + GOOGLE_GEMINI_BASE_URL + HD_VISION_BACKEND
  生图:    BANNER_IMAGE_BACKEND + OPENAI_API_KEY/OPENAI_BASE_URL (gpt-image-2)
           或 GEMINI_API_KEY (gemini t2i)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from _paths import validate_paths
validate_paths()


def run_hd_pipeline(
    image_paths: list[Path],
    prompt: str,
    out_dir: Path,
    *,
    main_title: str = "",
    subtitle: str = "",
    hero_first: bool = False,
    skip_cutout: bool = False,
    logo_path: Path | None = None,
) -> dict:
    """
    HD 4 阶段统一产线。
    后端环境变量由调用方（run_hd.py → _packy.apply_packy_backend）在调用前设置好。
    """
    image_backend = os.environ.get("BANNER_IMAGE_BACKEND", "gemini")
    has_gemini    = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    has_openai    = bool(os.environ.get("OPENAI_API_KEY", "").strip())

    print("=" * 60, flush=True)
    print(f"[hd] HD 4-Stage 产线启动", flush=True)
    print(f"[hd] 生图后端: {image_backend}", flush=True)
    print(f"[hd] Gemini key: {'已设置' if has_gemini else '未设置'}", flush=True)
    print(f"[hd] OpenAI key: {'已设置' if has_openai else '未设置'}", flush=True)
    print(f"[hd] 人物: {len(image_paths)} 张", flush=True)
    print(f"[hd] 输出: {out_dir}", flush=True)
    print("=" * 60, flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)

    # ═══ Stage 1: Vision 综合分析 ═══
    from scripts.hd.stage1_analyze import run_stage1
    stage1 = run_stage1(image_paths)

    # ═══ Stage 2: 排版 + Prompt ═══
    from scripts.hd.stage2_layout_prompt import run_stage2
    stage2 = run_stage2(
        stage1,
        prompt,
        main_title=main_title,
        subtitle=subtitle,
        hero_first=hero_first,
        image_paths=image_paths,
    )
    stage2["main_title"] = main_title
    stage2["subtitle"]   = subtitle

    # ═══ Stage 3: 合成 ═══
    from scripts.hd.stage3_compose import run_stage3
    stage3 = run_stage3(
        stage1,
        stage2,
        image_paths,
        out_dir,
        skip_cutout=skip_cutout,
        logo_path=logo_path,
    )

    # ═══ Stage 4: 验证 ═══
    from scripts.hd.stage4_validate import run_stage4
    result = run_stage4(stage3["final"])
    if not result["pass"]:
        print(f"\n[hd] Stage 4 未通过: {result['issues']}", flush=True)
        print("[hd] 已输出当前版本，请检查后手动调整", flush=True)

    print("\n" + "=" * 60, flush=True)
    print(f"[hd] 含文案: {stage3['final']}", flush=True)
    print(f"[hd] 无文案: {stage3['final_nc']}", flush=True)
    print("=" * 60, flush=True)

    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": result,
    }
