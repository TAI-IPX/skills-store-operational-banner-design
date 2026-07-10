#!/usr/bin/env python3
"""
[兼容存根] 原有功能已合并到 lib/opencode_image_input。
此文件保留所有导出函数供 run_hd.py 等旧代码导入，新代码请使用 opencode_image_input。
"""
import sys
from pathlib import Path

lib_dir = Path(__file__).resolve().parent.parent / "lib"
if str(lib_dir) not in sys.path:
    sys.path.insert(0, str(lib_dir))
from opencode_image_input import (
    extract_images_from_db,
    extract_images_from_cache,
    CACHE_DIR,
    _copy_locked,
    _find_cache_files,
    DB_PATH,
    _decode_b64,
    _dedup,
)

__all__ = [
    "extract_images_from_db",
    "extract_images_from_cache",
    "CACHE_DIR",
    "_copy_locked",
    "_find_cache_files",
    "DB_PATH",
    "_decode_b64",
    "_dedup",
]

if __name__ == "__main__":
    print("grab_opencode_image.py 已合并到 lib/opencode_image_input，请改用：")
    print("  py lib/opencode_image_input.py [--upload-latest|--list|--name ...]")
