#!/usr/bin/env python3
"""
战报装饰底图：优先调用 JimLiu/baoyu-skills 的 baoyu-image-gen（图生图或文生图；ref 为空时为 t2i）。

安装（一次性）：
  npx skills add jimliu/baoyu-skills -a cursor -s baoyu-image-gen

或设置 BATTLE_REPORT_BAOYU_IMAGE_GEN 指向 main.ts 绝对路径。

环境：复用项目 .env 的 GEMINI_API_KEY / GOOGLE_GEMINI_BASE_URL（Packy）→ baoyu Google 通道。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.battle_report.env_setup import load_dotenv, nano_image_model, setup_battle_report_env

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CANVAS_W = 1080


def _load_baoyu_env_files() -> None:
    for env_file in (
        Path.home() / ".baoyu-skills" / ".env",
        _PROJECT_ROOT / ".baoyu-skills" / ".env",
    ):
        if not env_file.is_file():
            continue
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k = k.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v.strip().strip("\"'")


def _sync_google_env_for_baoyu() -> None:
    """Packy / 战报 .env → baoyu-image-gen 的 Google 提供方变量。"""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key and not os.environ.get("GOOGLE_API_KEY", "").strip():
        os.environ["GOOGLE_API_KEY"] = key
    base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
    if base and not os.environ.get("GOOGLE_BASE_URL", "").strip():
        os.environ["GOOGLE_BASE_URL"] = base.rstrip("/")
    model = os.environ.get("BATTLE_REPORT_BAOYU_MODEL", "").strip()
    if not model:
        model = nano_image_model()
    if model and not os.environ.get("GOOGLE_IMAGE_MODEL", "").strip():
        os.environ["GOOGLE_IMAGE_MODEL"] = model


def resolve_baoyu_image_gen_main() -> Path | None:
    """定位 baoyu-image-gen/scripts/main.ts。"""
    explicit = os.environ.get("BATTLE_REPORT_BAOYU_IMAGE_GEN", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return p.resolve()
        skill_main = p / "scripts" / "main.ts"
        if skill_main.is_file():
            return skill_main.resolve()
    candidates = [
        _PROJECT_ROOT / ".baoyu-skills" / "baoyu-image-gen" / "scripts" / "main.ts",
        _PROJECT_ROOT / ".agents" / "skills" / "baoyu-image-gen" / "scripts" / "main.ts",
        _PROJECT_ROOT / ".cursor" / "skills" / "baoyu-image-gen" / "scripts" / "main.ts",
        Path.home() / ".baoyu-skills" / "baoyu-image-gen" / "scripts" / "main.ts",
        Path.home() / ".cursor" / "skills" / "baoyu-image-gen" / "scripts" / "main.ts",
        Path.home() / ".config" / "baoyu-skills" / "baoyu-image-gen" / "scripts" / "main.ts",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


def baoyu_image_gen_available() -> bool:
    setup_battle_report_env()
    main_ts = resolve_baoyu_image_gen_main()
    if not main_ts:
        return False
    bun = shutil.which("bun") or os.environ.get("BUN", "")
    if bun and Path(bun).exists():
        return True
    return shutil.which("npx") is not None


def _bun_runner() -> list[str]:
    bun = shutil.which("bun") or os.environ.get("BUN", "")
    if bun and Path(str(bun)).exists():
        return [str(bun)]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "bun"]
    return []


def run_baoyu_i2i(
    prompt: str,
    output_path: Path,
    *,
    ref_paths: list[Path],
    width: int = _CANVAS_W,
    height: int = 320,
    timeout: int = 360,
) -> Path | None:
    """
    baoyu-image-gen：有 --ref 为图生图，无 ref 为文生图 → 指定像素输出。
    """
    setup_battle_report_env()
    _load_baoyu_env_files()
    _sync_google_env_for_baoyu()

    main_ts = resolve_baoyu_image_gen_main()
    runner = _bun_runner()
    if not main_ts or not runner:
        print(
            "[战报/baoyu] 未找到 baoyu-image-gen（安装: "
            "npx skills add jimliu/baoyu-skills -s baoyu-image-gen）",
            flush=True,
        )
        return None

    refs = [p.resolve() for p in ref_paths if p and p.is_file()]

    out_path = output_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    provider = os.environ.get("BATTLE_REPORT_BAOYU_PROVIDER", "google").strip() or "google"
    model = os.environ.get("BATTLE_REPORT_BAOYU_MODEL", "").strip() or os.environ.get(
        "GOOGLE_IMAGE_MODEL", "",
    ).strip()

    cmd = runner + [str(main_ts), "--prompt", prompt, "--image", str(out_path)]
    for rp in refs:
        cmd.extend(["--ref", str(rp)])
    mode = "i2i" if refs else "t2i"
    cmd.extend(["--size", f"{max(256, width)}x{max(256, height)}", "--provider", provider, "--quality", "2k"])
    if model:
        cmd.extend(["--model", model])

    env = os.environ.copy()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(main_ts.parent.parent.parent),
            env=env,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            print(f"[战报/baoyu] 生成失败: {err[:800]}", flush=True)
            return None
        if not out_path.is_file():
            print("[战报/baoyu] 未写出输出文件", flush=True)
            return None
        model_tag = model or "default"
        print(
            f"[战报/baoyu] {mode} {provider}/{model_tag} → {out_path.name} ({width}×{height})",
            flush=True,
        )
        return out_path
    except subprocess.TimeoutExpired:
        print("[战报/baoyu] 生成超时", flush=True)
        return None
    except OSError as exc:
        print(f"[战报/baoyu] 调用异常: {exc}", flush=True)
        return None
