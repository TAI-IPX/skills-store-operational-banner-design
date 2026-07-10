#!/usr/bin/env python3
"""根据 prompt_library/*.json 重新生成 prompt_library/index.md。"""
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

import prompt_library as pl

if __name__ == "__main__":
    out = pl.write_index_md()
    print(f"已写入: {out}", flush=True)
