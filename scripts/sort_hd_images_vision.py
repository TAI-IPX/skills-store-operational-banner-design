#!/usr/bin/env python3
"""
独立工具：仅用 Gemini Vision 将 3～5 张 HD 素材排序为「左→右、中间为主视觉」。
每行打印一个重排后的绝对路径，便于 shell 拼接到 run_hd_line --images。

用法:
  py -3 scripts/sort_hd_images_vision.py a.png b.png c.png
环境: 项目根目录 .env（GEMINI_API_KEY；若使用 Packy 则 PACKY7S_API_KEY=sk-...，与 run_hd_line 一致）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_GEM = ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"
if str(_GEM) not in sys.path:
    sys.path.insert(0, str(_GEM))

ENV_FILE = ROOT / ".env"


def _load_env() -> dict[str, str]:
    result: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return result
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and v:
                    result[k] = v
    return result


def _apply_packy_env(loaded: dict[str, str]) -> None:
    key = loaded.get("PACKY7S_API_KEY") or os.environ.get("PACKY7S_API_KEY", "")
    if key.startswith("sk-"):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.packyapi.com"
        os.environ["GEMINI_API_KEY"] = key


def main() -> None:
    paths = [str(Path(p).resolve()) for p in sys.argv[1:]]
    if not 3 <= len(paths) <= 5:
        print(
            "用法: py -3 scripts/sort_hd_images_vision.py <图1> <图2> <图3> [图4] [图5]",
            file=sys.stderr,
        )
        sys.exit(1)
    for p in paths:
        if not Path(p).is_file():
            print(f"Error: 文件不存在 {p}", file=sys.stderr)
            sys.exit(1)

    loaded = _load_env()
    for k, v in loaded.items():
        if k not in os.environ:
            os.environ[k] = v
    _apply_packy_env(loaded)

    import gemini_subject_detect as gsd  # noqa: E402

    sorted_paths = gsd.vision_sort_hd_image_layout_order(paths)
    if sorted_paths is None:
        sys.exit(1)
    for p in sorted_paths:
        print(p)


if __name__ == "__main__":
    main()
