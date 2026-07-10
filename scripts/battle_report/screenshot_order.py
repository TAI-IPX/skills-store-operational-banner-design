#!/usr/bin/env python3
"""
战报区块截图智能排序：MICU Vision（默认）或 Gemini Vision。

BATTLE_REPORT_AI_SCREENSHOT_ORDER=1 时，在无 order.txt 前提下按附图叙事顺序排列。
缓存：{区块文件夹}/.battle_report_cache/ai_screenshot_order.json
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from scripts.battle_report.hero_design import call_vision_with_images
from scripts.battle_report.env_setup import setup_battle_report_env

_THUMB_MAX_SIDE = 480
_MAX_VISION_SHOTS = 12

_SECTION_HINTS: dict[str, str] = {
    "核心资源矩阵": (
        "本区块常见叙事：双榜/双列(01+02 等高、左右与满宽行对齐) → 满宽横图(03) → "
        "满宽(04) → 三列(05+06+07 与 01+02 同缝、左右贴齐、等比缩放) → 满宽(08)。"
    ),
    "联动活动火热开启": (
        "本区块常见：邮件(左)+活动(右)并排，等高；"
        "两图整体等比缩放至与满宽行同宽，完整显示不裁切。"
    ),
    "玩家真实好评": (
        "本区块常见：2×2 评论卡矩阵，按时间线或热度从高到低；"
        "若难区分，保持文件名数字顺序。"
    ),
}


def is_ai_screenshot_order_enabled() -> bool:
    setup_battle_report_env()
    return os.environ.get("BATTLE_REPORT_AI_SCREENSHOT_ORDER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def should_refresh_order() -> bool:
    return os.environ.get("BATTLE_REPORT_SCREENSHOT_ORDER_REFRESH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _order_cache_path(folder: Path) -> Path:
    return folder / ".battle_report_cache" / "ai_screenshot_order.json"


def _section_hint(keyword: str) -> str:
    for key, hint in _SECTION_HINTS.items():
        if key in keyword or keyword in key:
            return hint
    return "按战报从上到下叙事：先总览/榜单，再细节，再收尾。"


def _load_cached_order(folder: Path, paths: list[Path]) -> list[Path] | None:
    cache = _order_cache_path(folder)
    if not cache.is_file() or should_refresh_order():
        return None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names = data.get("order")
    if not isinstance(names, list):
        return None
    by_name = {p.name: p for p in paths}
    by_stem = {p.stem: p for p in paths}
    ordered: list[Path] = []
    used: set[Path] = set()
    for entry in names:
        if not isinstance(entry, str):
            continue
        p = by_name.get(entry) or by_stem.get(entry)
        if p and p not in used:
            ordered.append(p)
            used.add(p)
    for p in sorted(paths, key=lambda x: x.name):
        if p not in used:
            ordered.append(p)
    if len(ordered) != len(paths):
        return None
    return ordered


def _vision_order_source() -> str:
    from scripts.battle_report.hero_design import last_vision_source

    return f"{last_vision_source()}_vision"


def _save_cached_order(folder: Path, order_names: list[str], *, keyword: str) -> None:
    cache = _order_cache_path(folder)
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "order": order_names,
        "section": keyword,
        "source": _vision_order_source(),
    }
    cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_order_json(text: str, paths: list[Path]) -> list[str] | None:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    order = obj.get("order")
    if not isinstance(order, list):
        return None
    valid_names = {p.name for p in paths}
    names: list[str] = []
    for item in order:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name in valid_names and name not in names:
            names.append(name)
    if len(names) != len(paths):
        return None
    return names


def _build_order_prompt(keyword: str, paths: list[Path]) -> str:
    file_lines = "\n".join(f"- {p.name}" for p in paths)
    hint = _section_hint(keyword)
    return f"""你是手游战报长图的内容编排顾问。区块标题：「{keyword}」。

附图顺序：第 1 张为 KV 风格参考（仅看色调，不参与排序）；其后每张为待排序截图，与下列文件名一一对应（按发送顺序）：
{file_lines}

编排提示：{hint}

请根据截图**画面内容**（榜单、邮件、活动页、评论卡等）决定从上到下的叙事顺序，使读者阅读顺畅。
可结合文件名中的数字编号，但若画面逻辑与编号冲突，以内容为准。

只输出 JSON，不要 markdown：
{{"order":["文件名1","文件名2",...]}}
必须包含且仅包含以上 {len(paths)} 个文件名。"""


def ai_order_screenshots(
    paths: list[Path],
    *,
    folder: Path,
    keyword: str,
    kv_path: Path | None,
) -> tuple[list[Path], str] | None:
    """
    Vision 排序。成功返回 (ordered_paths, order_source)；失败返回 None。
    """
    if len(paths) <= 1:
        return paths, "filename"

    cached = _load_cached_order(folder, paths)
    if cached is not None:
        print(f"[战报] 截图排序({keyword}): 缓存 ai_screenshot_order.json", flush=True)
        src = "micu_vision_cache"
        try:
            data = json.loads(_order_cache_path(folder).read_text(encoding="utf-8"))
            if data.get("source", "").startswith("gemini"):
                src = "gemini_vision_cache"
        except (OSError, json.JSONDecodeError):
            pass
        return cached, src

    if not is_ai_screenshot_order_enabled():
        return None

    if not kv_path or not kv_path.is_file():
        print(f"[战报] 截图排序({keyword}): 跳过（无 KV 参考图）", flush=True)
        return None

    vision_paths = paths[:_MAX_VISION_SHOTS]
    if len(paths) > _MAX_VISION_SHOTS:
        print(
            f"[战报] 截图排序({keyword}): 仅 Vision 前 {_MAX_VISION_SHOTS} 张，"
            f"其余 {len(paths) - _MAX_VISION_SHOTS} 张接在末尾（文件名序）",
            flush=True,
        )

    image_paths = [kv_path, *vision_paths]
    prompt = _build_order_prompt(keyword, vision_paths)
    text = call_vision_with_images(prompt, image_paths, thumb_max=_THUMB_MAX_SIDE)
    names = _parse_order_json(text or "", vision_paths)
    if not names:
        print(f"[战报] 截图排序({keyword}): Vision 未返回有效 JSON，回退文件名序", flush=True)
        return None

    tail = sorted(
        [p for p in paths if p.name not in names],
        key=lambda x: x.name,
    )
    full_names = names + [p.name for p in tail]
    by_name = {p.name: p for p in paths}
    ordered = [by_name[n] for n in full_names]

    tag = _vision_order_source()
    _save_cached_order(folder, full_names, keyword=keyword)
    print(
        f"[战报] 截图排序({keyword}): {tag} → "
        f"{', '.join(p.name for p in ordered)}",
        flush=True,
    )
    return ordered, tag


