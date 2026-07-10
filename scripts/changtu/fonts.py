#!/usr/bin/env python3
"""战报/活动长图本地字体加载：所有 Pillow 叠字必须经 load_font()，禁止系统默认字体。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import ImageFont

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_font_dir = os.environ.get("BATTLE_REPORT_FONT_DIR", "").strip()
if _env_font_dir:
    FONT_DIR = Path(_env_font_dir)
else:
    FONT_DIR = _PROJECT_ROOT / "fonts"

FONT_INSTALL_HINT = (
    "活动长图需要 4 种本地字体角色（display_bold / display_medium / body_regular / data_bold）。\n"
    f"请将对应 .otf 或 .ttf 文件放入 {FONT_DIR} 目录。\n"
    "也可通过环境变量指定路径：\n"
    "  BATTLE_REPORT_FONT_DISPLAY_BOLD=path/to/display-bold.otf\n"
    "  BATTLE_REPORT_FONT_DISPLAY_MEDIUM=path/to/display-medium.otf\n"
    "  BATTLE_REPORT_FONT_BODY=path/to/body-regular.otf\n"
    "  BATTLE_REPORT_FONT_DATA=path/to/data-bold.otf\n"
    "或设置 BATTLE_REPORT_FONT_DIR=path/to/dir 统一指定目录。"
)

def _system_font_search_paths() -> list[Path]:
    paths: list[Path] = []
    windir = Path("C:/Windows/Fonts")
    if windir.is_dir():
        paths.append(windir)
    for d in (Path.home() / "Library" / "Fonts", Path("/Library/Fonts"),
              Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if d.is_dir():
            paths.append(d)
    return paths

_ROLE_ENV = {
    "display_bold": "BATTLE_REPORT_FONT_DISPLAY_BOLD",
    "display_medium": "BATTLE_REPORT_FONT_DISPLAY_MEDIUM",
    "body_regular": "BATTLE_REPORT_FONT_BODY",
    "data_bold": "BATTLE_REPORT_FONT_DATA",
}

# 各角色优先文件名（见 docs/战报规范.md §4.3）
_ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "display_bold": (
        "display-bold.otf",
        "display-bold.ttf",
        "display_bold.otf",
    ),
    "display_medium": (
        "display-medium.otf",
        "display-medium.ttf",
        "display_medium.otf",
    ),
    "body_regular": (
        "body-regular.otf",
        "body-regular.ttf",
        "body_regular.otf",
    ),
    "data_bold": (
        "data-bold.otf",
        "data-bold.ttf",
        "data_bold.otf",
    ),
}

# 四角色可共用同一套设计稿字体时的兜底（仍在 battle-report 目录内）
_SHARED_FALLBACK_NAMES = (
    "造字工房启黑体(1).otf",
    "造字工房启黑体.otf",
    "造字工房启黑体(1).ttf",
    "造字工房启黑体.ttf",
)

_resolved_cache: dict[str, Path] = {}


def _pick_first_existing(names: tuple[str, ...]) -> Path | None:
    for name in names:
        p = FONT_DIR / name
        if p.is_file():
            return p
    return None


def _resolve_font_path(role: str) -> Path:
    if role in _resolved_cache and _resolved_cache[role].is_file():
        return _resolved_cache[role]

    env_key = _ROLE_ENV.get(role, "")
    if env_key:
        raw = os.environ.get(env_key, "").strip()
        if raw:
            p = Path(raw)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p
            if p.is_file():
                _resolved_cache[role] = p.resolve()
                return _resolved_cache[role]

    for names in (_ROLE_CANDIDATES.get(role, ()), _SHARED_FALLBACK_NAMES):
        hit = _pick_first_existing(names)
        if hit is not None:
            _resolved_cache[role] = hit.resolve()
            return _resolved_cache[role]

    for p in sorted(FONT_DIR.glob("*.otf")) + sorted(FONT_DIR.glob("*.ttf")):
        if p.is_file():
            _resolved_cache[role] = p.resolve()
            return _resolved_cache[role]

    for sys_dir in _system_font_search_paths():
        for p in sorted(sys_dir.glob("*.otf")) + sorted(sys_dir.glob("*.ttf")):
            if p.is_file():
                _resolved_cache[role] = p.resolve()
                return _resolved_cache[role]

    print(FONT_INSTALL_HINT, file=sys.stderr)
    sys.exit(1)


def load_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """加载战报指定角色字体；禁止回退 ImageFont.load_default()。"""
    if role not in _ROLE_ENV:
        raise ValueError(f"未知字体角色: {role}，允许: {', '.join(_ROLE_ENV)}")
    path = _resolve_font_path(role)
    return ImageFont.truetype(str(path), size)


def list_fonts() -> dict[str, str]:
    return {role: str(_resolve_font_path(role)) for role in _ROLE_ENV}


def ensure_fonts_ready() -> None:
    """合成前校验四角色字体均可加载。"""
    for role in _ROLE_ENV:
        _resolve_font_path(role)


def log_font_configuration() -> None:
    """打印当前战报叠字使用的本地字体路径。"""
    try:
        ensure_fonts_ready()
    except FileNotFoundError as exc:
        print(f"[战报/字体] 错误: {exc}", flush=True)
        raise
    print("[战报/字体] 全部叠字使用本地字体（scripts/assets/fonts/battle-report/）:", flush=True)
    paths = list_fonts()
    for role, path in paths.items():
        print(f"[战报/字体]   {role}: {path}", flush=True)
    data_p = paths.get("data_bold")
    disp_p = paths.get("display_bold")
    if data_p and disp_p and Path(data_p) == Path(disp_p):
        print(
            "[战报/字体] 提示: 数据数字与标题共用同一字体文件；"
            "若需区分请将 data-bold.otf 放入 battle-report 目录",
            flush=True,
        )
