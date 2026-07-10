#!/usr/bin/env python3
"""战报合成：加载项目 .env；小 Banner 装饰生图默认 MICU（可选回退 Packy/Gemini）。"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path.cwd()


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip().strip("\"'")


def load_dotenv() -> None:
    """项目根 .env → ~/.nano-banana/.env（已存在的环境变量不覆盖）。"""
    for env_file in (_PROJECT_ROOT / ".env", Path.home() / ".nano-banana" / ".env"):
        _load_env_file(env_file)


# shell export 优先于 .env（即使 load_lz_micu_title_env(override=True) 也不覆盖）
_LZ_MICU_SHELL_PRIORITY_KEYS = frozenset({"LZ_MICU_TITLE_GEMINI_FALLBACK"})


def load_lz_micu_title_env(*, override: bool = False) -> None:
    """从项目 .env 加载 LZ_MICU_TITLE_* / LZ_MICU_KEEP_TITLE_*（默认不覆盖 shell）。"""
    path = _PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    extra_keys = {"HD_VISION_GEMINI_FALLBACK"}
    prefixes = ("LZ_MICU_TITLE_", "LZ_MICU_KEEP_TITLE", "LZ_MICU_TITLE_TEXT_")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" not in line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in extra_keys and not any(k.startswith(p) for p in prefixes):
                continue
            v = v.strip().strip("\"'")
            if not v:
                continue
            if k in _LZ_MICU_SHELL_PRIORITY_KEYS and k in os.environ:
                continue
            if override or k not in os.environ:
                os.environ[k] = v
    if os.environ.get("LZ_MICU_TITLE_NO_GEMINI", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        os.environ["HD_VISION_GEMINI_FALLBACK"] = "0"


def is_packy_backend() -> bool:
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
    if "packyapi.com" in base:
        return True
    flag = os.environ.get("BATTLE_REPORT_PACKY", "").strip().lower()
    return flag in ("1", "true", "yes")


def apply_packy_env() -> None:
    """Packy：确保 base URL + sk- 令牌；优先 PACKY_API_KEY / PACKY7S_API_KEY。"""
    if is_packy_backend() or os.environ.get("PACKY_API_KEY", "").strip().startswith("sk-"):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key.startswith("sk-"):
        for name in ("PACKY_API_KEY", "PACKY7S_API_KEY", "GEMINI_API_KEY_ALT"):
            cand = os.environ.get(name, "").strip()
            if cand.startswith("sk-"):
                os.environ["GEMINI_API_KEY"] = cand
                break

    if os.environ.get("GEMINI_API_KEY", "").strip().startswith("sk-"):
        if not os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip():
            os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"


_NANO_QUALITY_MODELS = {
    "fast": "gemini-2.5-flash-image",
    "high": "gemini-3-pro-image-preview",
}


def nano_image_model() -> str:
    """
    Nano 图生图模型（数据区 / 小 Banner 无字底图）。

    优先级：BATTLE_REPORT_NANO_MODEL > BATTLE_REPORT_NANO_QUALITY(fast|high)
    > Packy 的 PACKY_GEMINI_IMAGE_MODELS / GEMINI_MODEL > 默认 2.5-flash-image。
    """
    explicit = os.environ.get("BATTLE_REPORT_NANO_MODEL", "").strip()
    if explicit:
        return explicit.split(",")[0].strip()
    quality = os.environ.get("BATTLE_REPORT_NANO_QUALITY", "").strip().lower()
    if quality in _NANO_QUALITY_MODELS:
        return _NANO_QUALITY_MODELS[quality]
    if is_packy_backend():
        for name in ("PACKY_GEMINI_IMAGE_MODELS", "GEMINI_MODEL"):
            raw = os.environ.get(name, "").strip()
            if raw:
                return raw.split(",")[0].strip()
    return "gemini-2.5-flash-image"


def log_api_backend() -> None:
    from .micu_image_gen import micu_available

    micu_key = os.environ.get("MICU_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not micu_available() and not gemini_key:
        print(
            "[战报] 未配置 MICU_API_KEY（小 Banner 无 AI 底图时将使用程序色块）",
            flush=True,
        )
        return
    nano_flag = os.environ.get("BATTLE_REPORT_NANO_BANANA", "").strip().lower()
    if nano_flag not in ("0", "false", "no", "off") and nano_flag not in ("1", "true", "yes"):
        if micu_available():
            model = os.environ.get("MICU_MODEL", "gpt-image-2").strip()
            url = os.environ.get("MICU_API_URL", "https://www.micuapi.ai/v1/images/generations").strip()
            print(f"[战报] 已配置 MICU → 小 Banner 无字底图（{model}）+ 本地叠字", flush=True)
            print(f"[战报] API: MICU ({url})", flush=True)
            return
        print("[战报] 已配置 GEMINI_API_KEY → 小 Banner 底图回退 Packy/Gemini", flush=True)
    if micu_available():
        model = os.environ.get("MICU_MODEL", "gpt-image-2").strip()
        print(f"[战报] API: MICU · 模型 {model}", flush=True)
        order_flag = os.environ.get("BATTLE_REPORT_AI_SCREENSHOT_ORDER", "").strip().lower()
        if order_flag in ("1", "true", "yes"):
            vmodel = os.environ.get("MICU_VISION_MODEL", "gpt-4o").strip() or "gpt-4o"
            print(f"[战报] 截图排序: MICU Vision ({vmodel})", flush=True)
        return
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
    if "packyapi.com" in base:
        model = nano_image_model()
        print(f"[战报] API: Packy ({base}) · 回退模型 {model}", flush=True)
    elif base:
        print(f"[战报] API: {base}", flush=True)
    else:
        print("[战报] API: Google Gemini（回退）", flush=True)


_env_logged = False


def setup_battle_report_env() -> None:
    global _env_logged
    load_dotenv()
    apply_packy_env()
    if not _env_logged:
        log_api_backend()
        _env_logged = True
