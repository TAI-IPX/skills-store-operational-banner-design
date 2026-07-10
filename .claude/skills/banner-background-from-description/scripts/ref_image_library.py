#!/usr/bin/env python3
"""
参考图库：存放风格/构图参考图及元数据，用于辅助写 prompt。
图片存于 ref_image_library/images/，元数据存于 ref_image_library/refs.json。
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_script_dir = Path(__file__).resolve().parent
_skill_root = _script_dir.parent
REF_IMAGE_LIBRARY_DIR = _skill_root / "ref_image_library"
IMAGES_DIR = REF_IMAGE_LIBRARY_DIR / "images"
REFS_JSON = REF_IMAGE_LIBRARY_DIR / "refs.json"


def _ensure_dirs() -> Path:
    REF_IMAGE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return REF_IMAGE_LIBRARY_DIR


def _load_refs() -> list[dict[str, Any]]:
    """读取 refs.json，不存在或空则返回 []。"""
    _ensure_dirs()
    if not REFS_JSON.is_file():
        return []
    try:
        with open(REFS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_refs(entries: list[dict[str, Any]]) -> None:
    """写入 refs.json。"""
    _ensure_dirs()
    with open(REFS_JSON, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def load_all_entries() -> list[dict[str, Any]]:
    """读全库，按 created_at 降序（新的在前）。"""
    entries = _load_refs()
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return entries


def get_entries_by_tags(tags: list[str]) -> list[dict[str, Any]]:
    """按标签筛选：仅保留至少含其一标签的条目。"""
    all_ent = _load_refs()
    if not tags:
        return all_ent
    return [
        e for e in all_ent
        if e.get("tags") and any(t in e.get("tags", []) for t in tags)
    ]


def next_id() -> str:
    """生成下一个可用 id（现有 id 最大值 + 1）。"""
    entries = _load_refs()
    nums = []
    for e in entries:
        i = e.get("id", "")
        if str(i).isdigit():
            nums.append(int(i))
    return str(max(nums, default=0) + 1)


def add_entry(
    image_path: str | Path,
    caption: str = "",
    tags: list[str] | None = None,
    prompt_id: str = "",
    id_: str | None = None,
) -> str:
    """
    将图片加入参考图库：复制到 images/{id}.{ext}，并追加元数据到 refs.json。
    返回写入的 id。
    """
    _ensure_dirs()
    src = Path(image_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"图片不存在: {src}")

    ext = src.suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"

    if id_ is None:
        id_ = next_id()
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    image_filename = f"{id_}{ext}"
    dest = IMAGES_DIR / image_filename
    shutil.copy2(src, dest)

    entry = {
        "id": id_,
        "image": image_filename,
        "caption": (caption or "").strip(),
        "tags": tags or [],
        "prompt_id": (prompt_id or "").strip(),
        "created_at": created,
    }
    entries = _load_refs()
    entries.append(entry)
    _save_refs(entries)
    return id_


def get_image_path(entry: dict[str, Any]) -> Path | None:
    """根据条目返回库内图片绝对路径；文件不存在则返回 None。"""
    fn = entry.get("image")
    if not fn:
        return None
    p = IMAGES_DIR / fn
    return p if p.is_file() else None


def write_index_md() -> Path:
    """根据 refs.json 生成 ref_image_library/index.md。"""
    entries = _load_refs()
    entries.sort(key=lambda e: int(e.get("id", "0")) if str(e.get("id", "0")).isdigit() else 0)
    index_path = REF_IMAGE_LIBRARY_DIR / "index.md"
    lines = [
        "# 参考图库索引",
        "",
        "| id | caption | 标签 | 关联 prompt_id | 日期 |",
        "|----|--------|------|----------------|------|",
    ]
    for e in entries:
        eid = e.get("id", "")
        cap = (e.get("caption") or "").replace("|", "\\|")[:60]
        tags = ", ".join(e.get("tags") or []) or "—"
        pid = (e.get("prompt_id") or "").strip() or "—"
        created = (e.get("created_at") or "")[:10] or "—"
        lines.append(f"| {eid} | {cap} | {tags} | {pid} | {created} |")
    lines.extend([
        "",
        "*新增参考图请运行 "
        "`python .claude/skills/banner-background-from-description/scripts/upload_ref_image.py --image <路径> --caption \"...\" --tags \"a,b\"`。*",
    ])
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path
