#!/usr/bin/env python3
"""
统一 .env 环境变量加载模块。

所有脚本通过此模块加载 .env，避免 11+ 处重复的手动解析代码。

用法:
    from _env import load_env, get_env_key

    load_env()                            # 加载所有 key
    load_env(("GEMINI_API_KEY", "PACKY_API_KEY"))  # 仅加载指定 key
    load_env(("GEMINI_API_KEY",), override=True)   # 覆盖已存在的环境变量

    key = get_env_key("PACKY_API_KEY")    # 读取单一 key（支持从 .env 回退）
    key = get_env_key("PACKY7S_API_KEY", "PACKY_API_KEY")  # 多个候选名，返回第一个非空
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = ROOT / ".env"
_ENV_CACHE: dict[str, str] | None = None


def _parse_env() -> dict[str, str]:
    """解析 .env 文件，返回 key -> value 字典。结果缓存以便重复调用。"""
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE

    _ENV_CACHE = {}
    if _ENV_FILE.is_file():
        with open(_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 剥离行内注释（# 及其后内容），但保留值中的引号内容
                if "#" in line:
                    _hash_idx = line.find("#")
                    # 检查 # 是否在引号外（简单的启发式：前面的引号数量为偶数）
                    _before = line[:_hash_idx]
                    if _before.count('"') % 2 == 0 and _before.count("'") % 2 == 0:
                        line = _before.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key:
                    _ENV_CACHE[key] = value
    return _ENV_CACHE


def load_env(keys: tuple[str, ...] | None = None, override: bool = False) -> None:
    """
    从 .env 加载环境变量到 os.environ。

    keys: 要加载的 key 白名单，None 表示加载全部
    override: 若 True，覆盖 os.environ 中已存在的值；默认 False（环境变量优先）
    """
    parsed = _parse_env()
    for k, v in parsed.items():
        if keys is not None and k not in keys:
            continue
        if not v:
            continue
        if override or k not in os.environ:
            os.environ[k] = v


def get_env_key(*keys: str, default: str | None = None) -> str | None:
    """
    读取环境变量，支持多个候选名和 .env 回退。

    优先顺序: os.environ > .env 文件
    多候选名时返回第一个非空的。
    """
    parsed = _parse_env()
    for key in keys:
        val = os.environ.get(key)
        if val:
            return val
        val = parsed.get(key)
        if val:
            return val
    return default
