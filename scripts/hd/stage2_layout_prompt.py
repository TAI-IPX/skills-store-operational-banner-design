#!/usr/bin/env python3
"""
HD 产线 Stage 2：排版计算 + 背景 Prompt 生成。

输入：Stage 1 分析结果 + 用户参数
输出：layout_params + background_prompt
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

CANVAS_W, CANVAS_H = 3840, 1200
SAFE_ZONE = (820, 2660, 0, 1200)
SAFE_CENTER_X = (SAFE_ZONE[0] + SAFE_ZONE[1]) // 2  # 1740
CLUSTER_OFFSET_X = 290        # left 槽（1740-290=1450），靠近 center 减少可见面积→减轻左侧
RIGHT_SLOT_EXTRA_OUTWARD_X = 420  # right 槽（1740+290+420=2450），远离 center 增加可见面积→增强右侧
VISUAL_CENTER_X = CANVAS_W // 2  # 1920
HEIGHT_RATIOS = [0.82, 0.80, 0.85]  # center 缩小减占地，right 增大增强右侧
SLOT_ROLES = ("center", "left", "right")
ROLE_Z = {"center": 0, "left": 2, "right": 1}

BACKGROUND_PROMPT_TEMPLATE = """Generate a game activity banner BACKGROUND image.

=== CREATIVE DIRECTION (primary — follow this closely) ===
{user_prompt}

=== CHARACTER STYLE REFERENCE (secondary — adapt to match the creative direction above) ===
{style_block}

=== CANVAS RULES (technical) ===
- Ultra-wide horizontal panorama, aspect ratio 4:1 (4096×1024)
- NO characters, NO people, NO text, NO logos, NO watermarks
- Full bleed all edges: no letterbox, no black bars, no vertical seams
- Left third may be slightly darker/simpler for logo overlay
- Depth and atmospheric perspective encouraged
- Center-back ambient glow behind hero zone

Generate the background scene following the CREATIVE DIRECTION."""

TITLE_ART_PROMPT_TEMPLATE = """"{main_title}"游戏活动艺术字设计，副标题"{subtitle}"

{color_block}风格，游戏宣传海报3D立体中文艺术字，
主标题大字突出居中，副标题小字在下方，
笔划清晰可辨，字形准确，有金属光泽或霓虹发光效果，
白色背景，无其他装饰物和角色，纯文字版式设计"""


def _format_style_block(style: dict) -> str:
    lines = []
    for key in (
        "art_style", "rendering", "palette", "costume_colors",
        "accent_colors", "lighting", "world_setting", "environment",
        "mood", "bg_prompt_addendum",
    ):
        val = style.get(key, "")
        if val:
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


def run_stage2(
    stage1_result: dict,
    user_prompt: str,
    *,
    main_title: str = "",
    subtitle: str = "",
    hero_first: bool = False,
    image_paths: list[Path] | None = None,
) -> dict:
    """
    Stage 2：排版 + Prompt 生成。

    Args:
        stage1_result: Stage 1 的分析 JSON
        user_prompt: 用户背景描述 (-p)
        main_title: 主标题 (-m)
        subtitle: 副标题 (-s)
        hero_first: 首张固定中槽
        image_paths: 原始输入路径（hero_first 时需用）

    Returns:
        {
            "layout_params": [{path, x_center, y_bottom, height, z_order, role, cutout_index}, ...],
            "background_prompt": "...",
            "title_art_prompt": "..." or None,
        }
    """
    n = len(stage1_result["images"])
    style = stage1_result["style"]

    # ── 槽位分配 ──
    center_index = 0 if hero_first else stage1_result["center_index"]
    quality_order = stage1_result["quality_order"]

    if hero_first and image_paths:
        remaining = [i for i in range(n) if i != center_index]
        ordered_indices = [center_index] + remaining
    else:
        ordered_indices = [center_index]
        remaining = [i for i in quality_order if i != center_index]
        remaining.sort(key=lambda i: quality_order.index(i))
        ordered_indices.extend(remaining)
    ordered_indices = ordered_indices[:n]

    print(f"[stage2] 槽位顺序: {ordered_indices}", flush=True)

    # ── 几何排版 ──
    positions = [
        {"x_center": SAFE_CENTER_X, "y_bottom": CANVAS_H, "height": int(CANVAS_H * HEIGHT_RATIOS[0])},
        {"x_center": SAFE_CENTER_X - CLUSTER_OFFSET_X, "y_bottom": CANVAS_H, "height": int(CANVAS_H * HEIGHT_RATIOS[1])},
        {
            "x_center": SAFE_CENTER_X + CLUSTER_OFFSET_X + RIGHT_SLOT_EXTRA_OUTWARD_X,
            "y_bottom": CANVAS_H,
            "height": int(CANVAS_H * HEIGHT_RATIOS[2]),
        },
    ]

    layout_params = []
    for slot_i, (orig_idx, pos) in enumerate(zip(ordered_indices, positions[:n])):
        entry = {
            "x_center": pos["x_center"],
            "y_bottom": pos["y_bottom"],
            "height": pos["height"],
            "z_order": ROLE_Z[SLOT_ROLES[slot_i]],
            "role": SLOT_ROLES[slot_i],
            "cutout_index": orig_idx,
        }
        if SLOT_ROLES[slot_i] == "center":
            entry["head_align_canvas_x"] = VISUAL_CENTER_X
        layout_params.append(entry)
        print(
            f"[stage2] {SLOT_ROLES[slot_i]}: idx={orig_idx} "
            f"x={pos['x_center']} h={pos['height']} z={entry['z_order']}",
            flush=True,
        )

    # ── Prompt 生成 ──
    style_block = _format_style_block(style)
    bg_prompt = BACKGROUND_PROMPT_TEMPLATE.format(
        style_block=style_block,
        user_prompt=user_prompt.strip() or "game activity banner",
    )

    print(f"[stage2] 背景 prompt 长度: {len(bg_prompt)}", flush=True)

    title_prompt = None
    if main_title.strip():
        # 艺术字只传配色参考，避免角色描述误导模型生成人物
        color_block = "\n".join(
            f"{k}: {style.get(k, '')}"
            for k in ("palette", "accent_colors")
            if style.get(k, "").strip()
        )
        title_prompt = TITLE_ART_PROMPT_TEMPLATE.format(
            color_block=color_block or "vibrant game colors",
            main_title=main_title.strip(),
            subtitle=subtitle.strip(),
        )
        print(f"[stage2] 艺术字 prompt 长度: {len(title_prompt)}", flush=True)

    return {
        "layout_params": layout_params,
        "background_prompt": bg_prompt,
        "center_index": center_index,
        "style_block": style_block,
        "title_art_prompt": title_prompt,
    }
