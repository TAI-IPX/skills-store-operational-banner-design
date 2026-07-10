#!/usr/bin/env python3
"""
Prompt 库：每个 prompt 一个 JSON 文件，存放在本 skill 的 prompt_library/ 下。
提供：读全库、取 N 条示例（few-shot）、追加一条、生成下一 id。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_script_dir = Path(__file__).resolve().parent
_skill_root = _script_dir.parent
PROMPT_LIBRARY_DIR = _skill_root / "prompt_library"


def _ensure_dir() -> Path:
    PROMPT_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return PROMPT_LIBRARY_DIR


def load_all_entries() -> list[dict[str, Any]]:
    """读全库，按 created_at 降序（新的在前）。"""
    _ensure_dir()
    entries = []
    for f in PROMPT_LIBRARY_DIR.glob("*.json"):
        if f.stem.isdigit() or f.stem:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict) and "prompt" in data:
                        entries.append(data)
            except (json.JSONDecodeError, OSError):
                continue
    # 按 created_at 降序，无则排最后
    def _key(e: dict) -> str:
        return e.get("created_at") or ""

    entries.sort(key=_key, reverse=True)
    return entries


def get_examples(n: int = 5, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """
    取最多 n 条作为 few-shot 示例。
    若指定 tags，仅保留至少含其一标签的条目（无 tags 字段的条目也会保留）。
    """
    all_ent = load_all_entries()
    if tags:
        filtered = [
            e for e in all_ent
            if not e.get("tags") or any(t in e.get("tags", []) for t in tags)
        ]
        if filtered:
            all_ent = filtered
    return all_ent[:n]


def next_id() -> str:
    """生成下一个可用 id（现有数字 id 的最大值 + 1）。"""
    _ensure_dir()
    nums = []
    for f in PROMPT_LIBRARY_DIR.glob("*.json"):
        if f.stem.isdigit():
            nums.append(int(f.stem))
    return str(max(nums, default=0) + 1)


def add_entry(
    prompt: str,
    source: str = "AI生成",
    main_title: str = "",
    subtitle: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    id_: str | None = None,
) -> str:
    """
    追加一条到库，写入 {id}.json。
    返回写入的 id。
    """
    _ensure_dir()
    if id_ is None:
        id_ = next_id()
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    entry = {
        "id": id_,
        "prompt": prompt,
        "source": source,
        "main_title": main_title or "",
        "subtitle": subtitle or "",
        "tags": tags or [],
        "notes": notes or "",
        "created_at": created,
    }
    path = PROMPT_LIBRARY_DIR / f"{id_}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    return id_


def format_examples_for_prompt_optimizer(entries: list[dict[str, Any]]) -> str:
    """把若干条库条目格式化为「示例」文本，可拼进 prompt-optimizer 的 user 消息。"""
    if not entries:
        return ""
    lines = ["以下为优质文生图描述示例，请重点模仿其结构与描述方式（风格、色彩、元素、构图、细节、结尾等），写出同样高质量的描述：\n"]
    for e in entries:
        mt = e.get("main_title") or ""
        st = e.get("subtitle") or ""
        p = (e.get("prompt") or "").strip()
        lines.append(f"主标题：{mt}\n副标题：{st}\n描述：{p}\n")
    return "\n".join(lines)


def write_index_md() -> Path:
    """根据当前所有 JSON 条目生成 prompt_library/index.md，返回 index 文件路径。"""
    entries = load_all_entries()
    # 按 id 数字排序
    entries.sort(key=lambda e: int(e.get("id", "0")) if str(e.get("id", "0")).isdigit() else 0)
    index_path = PROMPT_LIBRARY_DIR / "index.md"
    lines = [
        "# Prompt 库索引",
        "",
        "| id | 主标题 | 副标题 | 标签 | 来源 | 日期 |",
        "|----|--------|--------|------|------|------|",
    ]
    for e in entries:
        eid = e.get("id", "")
        mt = (e.get("main_title") or "").replace("|", "\\|")
        st = (e.get("subtitle") or "—").replace("|", "\\|")
        tags = ", ".join(e.get("tags") or []) or "—"
        source = e.get("source") or "—"
        created = (e.get("created_at") or "")[:10] or "—"
        lines.append(f"| {eid} | {mt} | {st} | {tags} | {source} | {created} |")
    lines.extend([
        "",
        "*新增或修改 JSON 后，可在项目根运行 "
        "`python .claude/skills/banner-background-from-description/scripts/generate_prompt_library_index.py` 重新生成本索引。*",
    ])
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path
