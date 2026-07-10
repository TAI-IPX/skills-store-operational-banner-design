# -*- coding: utf-8 -*-
"""One-off runner: remove people from open-platform banner. Paths in source avoid CLI encoding issues."""
from pathlib import Path

from gemini_image_edit import edit_image, INPAINT_REMOVE_PEOPLE_PROMPT

# Paths relative to repo root (run from skills-store-operational-banner-design)
ROOT = Path(__file__).resolve().parents[4]
INPUT = ROOT / "output" / "开放平台_天禧AI生态智能体合作招募_20260312_154523" / "开放平台banner 2560x496.png"
OUTPUT = ROOT / "output" / "开放平台_天禧AI生态智能体合作招募_20260312_154523" / "开放平台banner 2560x496_无人物.png"

if __name__ == "__main__":
    if not INPUT.exists():
        raise SystemExit(f"Input not found: {INPUT}")
    out = edit_image(str(INPUT), str(OUTPUT), INPAINT_REMOVE_PEOPLE_PROMPT)
    print("Saved:", out)
