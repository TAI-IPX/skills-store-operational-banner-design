#!/usr/bin/env python3
"""兼容存柄 — 委托给 lib/opencode_image_input。"""
import sys
from pathlib import Path

lib_dir = Path(__file__).resolve().parent.parent / "lib"
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))
from opencode_image_input import main

main()
