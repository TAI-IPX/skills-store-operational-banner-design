#!/usr/bin/env python3
"""i18n loader — reads locale JSON files from locales/."""
import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent / "locales"
SUPPORTED = {"zh", "en"}
_cache: dict[str, dict] = {}


def load(lang: str) -> dict:
    """Load a locale file. Fallback: zh."""
    lang = lang if lang in SUPPORTED else "zh"
    if lang not in _cache:
        path = LOCALES_DIR / f"{lang}.json"
        if path.exists():
            _cache[lang] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _cache[lang] = json.loads((LOCALES_DIR / "zh.json").read_text(encoding="utf-8"))
    return _cache[lang]


def t(lang: str, key: str, **kwargs) -> str:
    """Shortcut for CLI messages: t('en', 'cli.bg_saved', path='x.png', size=42)."""
    locale = load(lang)
    parts = key.split(".")
    val = locale
    for p in parts:
        val = val.get(p, key)
        if val is None:
            return key
    if isinstance(val, str) and kwargs:
        return val.format(**kwargs)
    return str(val) if not isinstance(val, str) else val
