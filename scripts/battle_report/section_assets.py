#!/usr/bin/env python3
"""战报区块文件夹：小 Banner 栏头图 / 内容截图 / 纯参考图，并解析排序。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# 小 Banner 人物/动物：透明底 PNG 放区块文件夹下子目录（优先于栏头自动抠图）
_KEYWORD_SECTION_KEY: dict[str, str] = {
    "核心资源矩阵": "b",
    "联动活动火热开启": "c",
    "玩家真实好评": "d",
}

# 小 Banner 人物主 K：各区块文件夹内与文件夹同名的 PNG（非 01/02 截图）
SECTION_CHARACTER_KEYWORDS: tuple[str, ...] = tuple(_KEYWORD_SECTION_KEY.keys())

_SECTION_CHAR_SUBDIRS: tuple[str, ...] = (
    "小banner",
    "小Banner",
    "小 banner",
    "角色",
    "characters",
    "banner_characters",
)

# 合成时作为栏头贴图（设计按 KV 导出）
_BANNER_FILENAMES = {
    "banner.png",
    "section_banner.png",
    "小banner.png",
    "栏头.png",
}


@dataclass
class SectionFolderAssets:
    folder: Path
    keyword: str
    banner_image: Path | None = None
    """`小banner/` 等子目录内的透明底角色/动物 PNG。"""
    character_png: Path | None = None
    screenshots: list[Path] = field(default_factory=list)
    design_refs: list[Path] = field(default_factory=list)
    order_source: str = "filename"


def _natural_sort_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.stem.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _is_design_reference_only(path: Path) -> bool:
    """仅「设计参考」类文件名，不参与合成（与同名小 banner 成品区分）。"""
    stem = path.stem
    return stem in ("设计稿", "设计参考", "layout_ref", "mockup", "参考")


def _is_numbered_content_png(path: Path) -> bool:
    """内容区编号截图（01.png 等），不可当作小 Banner 人物。"""
    stem = path.stem.strip()
    return stem.isdigit() or bool(re.fullmatch(r"\d+[a-zA-Z]?", stem))


def png_has_transparent_alpha(path: Path) -> bool:
    """PNG 是否含有效透明通道（用于判断直用或走抠图）。"""
    return _png_has_transparent_alpha(path)


def keyword_character_png_path(folder: Path, keyword: str) -> Path | None:
    """`{区块文件夹名}.png` 人物/动物主 K（透明直用，不透明则合成时抠图）。"""
    if not keyword or not folder.is_dir():
        return None
    p = folder / f"{keyword}.png"
    if p.is_file() and _is_keyword_character_png(p, keyword):
        return p
    return None


def _is_keyword_character_png(path: Path, keyword: str) -> bool:
    """与文件夹同名的 PNG = 人物/动物主 K（非编号内容截图）。"""
    if not keyword or path.stem != keyword or path.suffix.lower() != ".png":
        return False
    return not _is_numbered_content_png(path)


def _is_section_title_banner(path: Path, keyword: str) -> bool:
    """与区块文件夹同名的非透明栏头成品（如 核心资源矩阵.jpg 整栏图）。"""
    if not keyword or path.stem != keyword:
        return False
    if path.suffix.lower() == ".png" and _png_has_transparent_alpha(path):
        return False
    return True


def _is_banner_asset(path: Path) -> bool:
    name = path.name.lower()
    if name in _BANNER_FILENAMES:
        return True
    stem = path.stem.lower()
    if stem.startswith("banner_") or "小banner" in stem or stem.endswith("_banner"):
        return True
    return False


def _section_character_filenames(section_key: str) -> tuple[str, ...]:
    key = section_key.lower().strip()
    return (
        f"section_{key}_character.png",
        f"section_{key}角色.png",
        f"{key}_character.png",
        "角色.png",
        "character.png",
        "人物.png",
        "动物.png",
    )


def _png_has_transparent_alpha(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as im:
            rgba = im.convert("RGBA")
            lo, hi = rgba.getchannel("A").getextrema()
            return lo < 248 and hi > 8
    except OSError:
        return False


def resolve_section_character_png(
    folder: Path,
    section_key: str,
    *,
    keyword: str = "",
) -> Path | None:
    """人物/动物主 K：优先 `{区块名}.png`（如 核心资源矩阵/核心资源矩阵.png），其次 小banner/。"""
    if not folder.is_dir():
        return None
    kw_char = keyword_character_png_path(folder, keyword)
    if kw_char is not None:
        return kw_char
    sub_candidates: list[Path] = []
    for sub_name in _SECTION_CHAR_SUBDIRS:
        sub = folder / sub_name
        if not sub.is_dir():
            continue
        for p in sorted(sub.iterdir(), key=_natural_sort_key):
            if not p.is_file() or p.name.startswith(".") or p.suffix.lower() != ".png":
                continue
            if _png_has_transparent_alpha(p):
                sub_candidates.append(p)
    preferred = {n.lower() for n in _section_character_filenames(section_key)}
    for p in sub_candidates:
        if p.name.lower() in preferred:
            return p
    if len(sub_candidates) == 1:
        return sub_candidates[0]
    if sub_candidates:
        return max(sub_candidates, key=lambda x: x.stat().st_size)
    for name in _section_character_filenames(section_key):
        flat = folder / name
        if flat.is_file() and _png_has_transparent_alpha(flat):
            return flat
    return None


def _pick_banner_image(candidates: list[Path], keyword: str) -> Path | None:
    if not candidates:
        return None
    by_name = {c.name.lower(): c for c in candidates}
    for preferred in ("section_banner.png", "banner.png", "小banner.png", "栏头.png"):
        if preferred in by_name:
            return by_name[preferred]
    for c in candidates:
        if c.stem == keyword:
            return c
    return max(candidates, key=lambda x: x.stat().st_size)


def _read_order_file(folder: Path) -> list[str] | None:
    for name in ("order.txt", "排序.txt", "screenshots.txt"):
        p = folder / name
        if not p.is_file():
            continue
        names: list[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            names.append(line.split("#")[0].strip())
        return names if names else None
    return None


def _order_paths(paths: list[Path], folder: Path) -> tuple[list[Path], str]:
    order_names = _read_order_file(folder)
    if not order_names:
        return sorted(paths, key=_natural_sort_key), "filename"

    by_name = {p.name: p for p in paths}
    by_stem = {p.stem: p for p in paths}
    ordered: list[Path] = []
    used: set[Path] = set()
    for entry in order_names:
        p = by_name.get(entry) or by_stem.get(entry)
        if p and p not in used:
            ordered.append(p)
            used.add(p)
    for p in sorted(paths, key=_natural_sort_key):
        if p not in used:
            ordered.append(p)
    return ordered, "order.txt"


def section_key_for_keyword(keyword: str) -> str:
    return _KEYWORD_SECTION_KEY.get(keyword, keyword[:1].lower() if keyword else "b")


def parse_section_folder(
    folder: Path,
    keyword: str,
    *,
    kv_path: Path | None = None,
    section_key: str | None = None,
) -> SectionFolderAssets:
    """读取文件夹内全部图片并分类；截图默认全部纳入（不截断张数）。"""
    assets = SectionFolderAssets(folder=folder, keyword=keyword)
    if not folder.is_dir():
        return assets

    raw_images: list[Path] = []
    for p in folder.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        raw_images.append(p)

    banner_candidates: list[Path] = []
    screenshots: list[Path] = []

    for p in raw_images:
        if _is_design_reference_only(p):
            assets.design_refs.append(p)
            continue
        if _is_keyword_character_png(p, keyword) or (
            keyword and p.stem == keyword and p.suffix.lower() == ".png"
        ):
            continue
        if _is_numbered_content_png(p):
            screenshots.append(p)
            continue
        if _is_section_title_banner(p, keyword) or _is_banner_asset(p):
            banner_candidates.append(p)
            continue
        screenshots.append(p)

    assets.banner_image = _pick_banner_image(banner_candidates, keyword)
    sk = (section_key or section_key_for_keyword(keyword)).lower()
    assets.character_png = resolve_section_character_png(folder, sk, keyword=keyword)

    assets.screenshots, assets.order_source = _order_paths(screenshots, folder)
    if _read_order_file(folder) is None and kv_path is not None:
        try:
            from scripts.battle_report.screenshot_order import (
                ai_order_screenshots,
                is_ai_screenshot_order_enabled,
            )

            if is_ai_screenshot_order_enabled():
                ai_result = ai_order_screenshots(
                    assets.screenshots,
                    folder=folder,
                    keyword=keyword,
                    kv_path=kv_path,
                )
                if ai_result is not None:
                    assets.screenshots, assets.order_source = ai_result
        except Exception as exc:
            print(f"[战报] 截图排序异常，回退文件名序: {exc}", flush=True)
    return assets
