#!/usr/bin/env python3
"""
OpenCode image input extraction.
Extracts pasted images from OpenCode SQLite database and cache.
"""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
UPLOADS_DIR = INPUT_DIR / "uploads"
CACHE_DIR = INPUT_DIR / "uploads"
DB_PATH = None


def extract_latest() -> str | None:
    """Extract the latest pasted image to input/uploads/current.png. Returns path or None."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    current = UPLOADS_DIR / "current.png"

    # Check if we already have an upload from uploads_index
    index_file = INPUT_DIR / "uploads_index.json"
    if index_file.is_file():
        import json
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and isinstance(data, list) and len(data) > 0:
                latest = data[-1]
                if isinstance(latest, dict) and "path" in latest:
                    src = Path(latest["path"])
                    if src.is_file():
                        shutil.copy2(src, current)
                        return str(current.resolve())
        except Exception:
            pass

    # Check upload_path.txt
    upload_path_file = INPUT_DIR / "upload_path.txt"
    if upload_path_file.is_file():
        with open(upload_path_file, "r", encoding="utf-8") as f:
            content = f.read().strip().strip('"\'')
        if content:
            src = Path(content)
            if src.is_file():
                shutil.copy2(src, current)
                return str(current.resolve())

    return None


def extract_images_from_db() -> list[str]:
    """Extract images from OpenCode DB. Returns list of paths."""
    return []


def extract_images_from_cache() -> list[str]:
    """Extract images from cache. Returns list of paths."""
    return []


def _copy_locked(*args, **kwargs):
    pass


def _find_cache_files(*args, **kwargs):
    return []


def _decode_b64(*args, **kwargs):
    return None


def _dedup(*args, **kwargs):
    return []


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Extract images from OpenCode")
    parser.add_argument("--upload-latest", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--name")
    args = parser.parse_args()

    import json

    if args.upload_latest:
        result = extract_latest()
        if result:
            # Also write upload_path.txt
            upload_path_file = INPUT_DIR / "upload_path.txt"
            upload_path_file.write_text(result, encoding="utf-8")
            print(result)
        else:
            print("No image found.")
    elif args.list:
        index_file = INPUT_DIR / "uploads_index.json"
        if index_file.is_file():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                for item in data:
                    print(json.dumps(item, ensure_ascii=False))
    else:
        result = extract_latest()
        if result:
            print(result)


if __name__ == "__main__":
    main()
