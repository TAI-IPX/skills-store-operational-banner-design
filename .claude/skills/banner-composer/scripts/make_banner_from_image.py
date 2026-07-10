#!/usr/bin/env python3
"""
One-shot: from image + main title + subtitle → single output file in output/.
Runs prepare_background (banner-background-from-image) to a temp file, then compose_banner,
then deletes the temp file, so output/ only contains the final composed banner.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Python 解释器以 ensure_python 解析为准
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent
sys.path.insert(0, str(_project_root))
from scripts.ensure_python import get_python_exe
PYTHON_EXE = get_python_exe()

# Resolve paths: this script is in banner-composer/scripts; prepare_background is sibling skill under skills/
def _prepare_script() -> Path:
    script_dir = Path(__file__).resolve().parent  # .../banner-composer/scripts
    skills_dir = script_dir.parent.parent        # .../skills
    return skills_dir / "banner-background-from-image" / "scripts" / "prepare_background.py"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-shot: image → banner with title and subtitle. Output: single file in output/ (no intermediate)."
    )
    parser.add_argument("input", help="Source image path")
    parser.add_argument(
        "output",
        nargs="?",
        default="banner_final.png",
        help="Output path or filename (default: banner_final.png in output/)",
    )
    parser.add_argument("--main-title", "-m", required=True, help="Main title text")
    parser.add_argument("--subtitle", "-s", default="", help="Subtitle text (single line)")
    parser.add_argument("--no-ai-linebreak", action="store_true", help="Main title: fixed 8-char break")
    parser.add_argument("--remove-text", action="store_true", help="Remove text/watermarks from image first (Gemini)")
    parser.add_argument("--no-auto-subject", action="store_true", help="Disable auto subject detection for crop")
    group = parser.add_mutually_exclusive_group()
    from spec import PRESETS
    _valid_presets = list(PRESETS.keys()) if PRESETS else ["default", "wide", "strip"]
    group.add_argument("--preset", "-p", choices=_valid_presets, default="default")
    group.add_argument("--width", "-W", type=int)
    parser.add_argument("--height", "-H", type=int)
    args = parser.parse_args()

    prepare_script = _prepare_script()
    if not prepare_script.is_file():
        print(
            f"Error: prepare_background.py not found at {prepare_script}. Ensure banner-background-from-image skill is present.",
            file=sys.stderr,
        )
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        temp_bg = f.name
    try:
        # Step 1: prepare background to temp file（使用指定 Python）
        cmd_prepare = [PYTHON_EXE, str(prepare_script), args.input, temp_bg]
        if args.width is not None and args.height is not None:
            cmd_prepare += ["--width", str(args.width), "--height", str(args.height)]
        else:
            cmd_prepare += ["--preset", args.preset]
        if args.remove_text:
            cmd_prepare.append("--remove-text")
        if args.no_auto_subject:
            cmd_prepare.append("--no-auto-subject")
        r1 = subprocess.run(cmd_prepare)
        if r1.returncode != 0:
            sys.exit(r1.returncode)

        # Step 2: compose (import to get preset dimensions and compose)
        from compose_banner import PRESETS, compose, _resolve_output_path

        if args.width is not None and args.height is not None:
            width, height = args.width, args.height
        else:
            width, height = PRESETS[args.preset]

        compose(
            temp_bg,
            args.output,
            args.main_title,
            args.subtitle,
            width=width,
            height=height,
            use_ai_linebreak=not args.no_ai_linebreak,
        )
        out_path, _ = _resolve_output_path(args.output)
        print(f"Saved: {out_path}")
    finally:
        if os.path.isfile(temp_bg):
            try:
                os.unlink(temp_bg)
            except OSError:
                pass


if __name__ == "__main__":
    main()
