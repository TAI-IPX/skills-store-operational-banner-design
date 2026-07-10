#!/usr/bin/env python3
"""战报本地字体加载：所有 Pillow 叠字必须经 load_font()，禁止系统默认字体。"""
from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from PIL import ImageFont

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FONT_DIR = _PROJECT_ROOT / "scripts" / "assets" / "battle-report" / "fonts"

_ROLE_ENV = {
    "display_bold": "BATTLE_REPORT_FONT_DISPLAY_BOLD",
    "display_medium": "BATTLE_REPORT_FONT_DISPLAY_MEDIUM",
    "body_regular": "BATTLE_REPORT_FONT_BODY",
    "data_bold": "BATTLE_REPORT_FONT_DATA",
}

# 各角色优先文件名（见 docs/战报规范.md §4.3）——项目目录内自定义设计字体
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

# 系统字体角色候选名（按平台常见黑体系字体命名，优先联想启黑体/微软雅黑）
_SYSTEM_ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "display_bold": (
        "QiheiLenovo-60S.ttf", "msyhbd.ttc", "msyhbd.ttf", "simhei.ttf",
        "STXIHEI.TTF", "PingFang Bold.ttf", "SourceHanSansCN-Bold.otf",
    ),
    "display_medium": (
        "QiheiLenovo-60S.ttf", "msyh.ttc", "msyh.ttf", "simhei.ttf",
        "STXIHEI.TTF", "PingFang Medium.ttf", "SourceHanSansCN-Medium.otf",
    ),
    "body_regular": (
        "msyh.ttc", "msyh.ttf", "msyhl.ttc", "msyhl.ttf", "simhei.ttf",
        "PingFang Regular.ttf", "SourceHanSansCN-Regular.otf",
    ),
    "data_bold": (
        "QiheiLenovo-60S.ttf", "msyhbd.ttc", "msyhbd.ttf", "simhei.ttf",
        "STXIHEI.TTF", "PingFang Bold.ttf", "SourceHanSansCN-Bold.otf",
    ),
}


def _system_font_dirs() -> tuple[Path, ...]:
    system = platform.system()
    if system == "Windows":
        win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        return (win_dir / "Fonts",)
    if system == "Darwin":
        return (
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        )
    # Linux / other
    return (
        Path("/usr/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
    )


_resolved_cache: dict[str, Path] = {}


def _pick_first_existing(base: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        p = base / name
        if p.is_file():
            return p
    return None


def _pick_first_existing_system(names: tuple[str, ...]) -> Path | None:
    """在系统字体目录内查找候选名；Linux 目录支持递归查找。"""
    for base in _system_font_dirs():
        if not base.is_dir():
            continue
        hit = _pick_first_existing(base, names)
        if hit is not None:
            return hit
        # Linux 字体常按厂商分子目录存放，需递归
        if platform.system() not in ("Windows", "Darwin"):
            for name in names:
                for p in base.rglob(name):
                    if p.is_file():
                        return p
    return None


def set_font_family(name: str) -> None:
    """根据用户指定字体名扫描系统字体目录，命中后复写全部 4 角色缓存。

    匹配策略（依次尝试，返回最佳匹配）：
    1) TTF name table Family/Full name 包含候选子串
    2) 文件名包含候选子串
    候选子串：全名 → 去除厂商前缀 → 中文 2-3 字 N-gram
    评分：匹配子串越长 → 得分越高；文件名匹配加权
    """
    if not name or not name.strip():
        return
    name = name.strip()

    def _is_chinese(c: str) -> bool:
        return '\u4e00' <= c <= '\u9fff'

    foundry_prefixes = ["造字工房", "方正", "汉仪", "华文", "文鼎", "蒙纳"]
    stripped = name
    for fp in foundry_prefixes:
        if name.startswith(fp):
            stripped = name[len(fp):]
            break
    candidates = [name, stripped]
    ch_chars = ''.join(c for c in name if _is_chinese(c))
    for n in (3, 2):
        for i in range(len(ch_chars) - n + 1):
            candidates.append(ch_chars[i:i + n])
    # 中文常见 pinyin 映射，用于匹配文件名中的拉丁拼写
    _PINYIN: dict[str, str] = {
        '启': 'qi', '黑': 'hei', '体': 'ti', '元': 'yuan',
        '工': 'gong', '房': 'fang', '正': 'zheng', '造': 'zao', '字': 'zi',
        '汉': 'han', '仪': 'yi', '文': 'wen', '鼎': 'ding', '华': 'hua',
        '蒙': 'meng', '纳': 'na', '联': 'lian', '想': 'xiang', '楷': 'kai',
        '宋': 'song', '圆': 'yuan', '粗': 'cu', '细': 'xi', '中': 'zhong',
        '简': 'jian', '繁': 'fan', '书': 'shu', '雅': 'ya',
    }
    if ch_chars:
        py = ''.join(_PINYIN.get(c, '') for c in ch_chars)
        if len(py) >= 3:
            candidates.append(py)
        # 也加入去掉"体"字的拼音（如启黑体→qihei）
        core_chars = ch_chars.rstrip('体')
        if len(core_chars) >= 2 and core_chars != ch_chars:
            py_core = ''.join(_PINYIN.get(c, '') for c in core_chars)
            if len(py_core) >= 3:
                candidates.append(py_core)
    # 对 stripped（去掉厂商前缀后的名称）也生成拼音候选
    stripped_chars = ''.join(c for c in stripped if _is_chinese(c))
    if stripped_chars and stripped_chars != ch_chars:
        py_s = ''.join(_PINYIN.get(c, '') for c in stripped_chars)
        if len(py_s) >= 3:
            candidates.append(py_s)
        core_s = stripped_chars.rstrip('体')
        if len(core_s) >= 2 and core_s != stripped_chars:
            py_core_s = ''.join(_PINYIN.get(c, '') for c in core_s)
            if len(py_core_s) >= 3:
                candidates.append(py_core_s)
    seen = set()
    candidates = [c for c in candidates if len(c) >= 2 and not (c in seen or seen.add(c))]

    # 收集所有匹配，按分数排序取最佳
    scored: list[tuple[int, int, Path, bool]] = []  # (name_table_score, filename_score, path, is_project)

    def _scan_dir(base: Path, is_project: bool) -> None:
        if not base.is_dir():
            return
        for f in list(base.glob("*.ttf")) + list(base.glob("*.otf")) + list(base.glob("*.ttc")):
            fn = f.stem.lower()
            fn_score = 0
            for c in candidates:
                if c.lower() in fn:
                    fn_score = max(fn_score, len(c))
                    if fn_score >= len(stripped) * 0.7:
                        break

            nt_score = 0
            try:
                from fontTools.ttLib import TTFont  # type: ignore
                tt = TTFont(str(f))
                for record in tt["name"].names:
                    try:
                        text = record.toUnicode().lower()
                    except Exception:
                        # 中文名称可能编码异常，用 str() 回退
                        text = str(record).lower()
                    if record.nameID in (1, 4, 16, 21):
                        for c in candidates:
                            if c.lower() in text:
                                nt_score = max(nt_score, len(c))
                                if nt_score >= len(stripped) * 0.7:
                                    break
            except Exception:
                pass

            if nt_score or fn_score:
                scored.append((nt_score, fn_score, f, is_project))

    # 先扫项目字体目录（优先级高），再扫系统字体
    _scan_dir(FONT_DIR, is_project=True)
    for base in _system_font_dirs():
        _scan_dir(base, is_project=False)

    if not scored:
        raise FileNotFoundError(
            f"未找到匹配字体 \"{name}\"。已扫描 {', '.join(str(d) for d in [FONT_DIR] + list(_system_font_dirs()))}，"
            f"候选子串: {candidates[:8]}。请检查字体是否已安装"
        )

    # 排序：项目字体优先，其次文件名高分，再次 name table 高分
    scored.sort(key=lambda x: (x[3], x[1], x[0]), reverse=True)
    matched = scored[0][2]

    resolved = matched.resolve()
    _resolved_cache["display_bold"] = resolved
    _resolved_cache["display_medium"] = resolved
    _resolved_cache["body_regular"] = resolved
    _resolved_cache["data_bold"] = resolved
    print(f"[战报/字体] set_font_family(\"{name}\") → {matched.name} (共 {len(scored)} 个匹配)", flush=True)


def _resolve_font_path(role: str) -> Path:
    if role in _resolved_cache and _resolved_cache[role].is_file():
        return _resolved_cache[role]

    # 1. 环境变量显式覆盖（最高优先级）
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

    # 2. 系统字体扫描（本机已安装字体优先，无需手动拷贝到项目目录）
    sys_hit = _pick_first_existing_system(_SYSTEM_ROLE_CANDIDATES.get(role, ()))
    if sys_hit is not None:
        _resolved_cache[role] = sys_hit.resolve()
        return _resolved_cache[role]

    # 3. 项目目录内自定义设计字体（备用）
    for names in (_ROLE_CANDIDATES.get(role, ()), _SHARED_FALLBACK_NAMES):
        hit = _pick_first_existing(FONT_DIR, names)
        if hit is not None:
            _resolved_cache[role] = hit.resolve()
            return _resolved_cache[role]

    if FONT_DIR.is_dir():
        for p in sorted(FONT_DIR.glob("*.otf")) + sorted(FONT_DIR.glob("*.ttf")):
            if p.is_file():
                _resolved_cache[role] = p.resolve()
                return _resolved_cache[role]

    raise FileNotFoundError(
        f"战报本地字体未找到（role={role}）。已扫描系统字体目录 "
        f"({', '.join(str(d) for d in _system_font_dirs())}) 及项目目录 {FONT_DIR}，均未命中。"
        f"请安装中文黑体系字体（如微软雅黑/联想启黑体），或将字体放入 {FONT_DIR}，"
        f"见 docs/战报规范.md §4"
    )


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
    print("[战报/字体] 全部叠字使用本地字体（系统优先 → 项目目录备用）:", flush=True)
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
