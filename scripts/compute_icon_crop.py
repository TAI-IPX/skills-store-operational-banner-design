#!/usr/bin/env python3
"""
Compute a Cropping Box (ICON_CROP) for the current icon_rgba.png by
detecting the non-transparent region (alpha > thresh) and padding it.
Usage:
  python tools/compute_icon_crop.py [icon_path] [thresh] [pad]
Defaults: icon_path=output/icon_rgba.png, thresh=10, pad=8
Prints: NEW_ICON_CROP: x1 y1 x2 y2
"""
import sys
import numpy as np
from pathlib import Path
from PIL import Image

_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

def main():
    icon_path = sys.argv[1] if len(sys.argv) > 1 else str(_SCRIPT_ROOT / "output/icon_rgba.png")
    thresh = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    pad = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    img = Image.open(icon_path).convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    alpha = arr[:, :, 3]
    ys, xs = (alpha > thresh).nonzero()
    if xs.size == 0:
        print("NO_FG")
        sys.exit(1)
    x1, y1 = int(xs.min()), int(ys.min())
    x2, y2 = int(xs.max()), int(ys.max())
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img.width, x2 + pad)
    y2 = min(img.height, y2 + pad)
    print(f"NEW_ICON_CROP: {x1} {y1} {x2} {y2}")

if __name__ == "__main__":
    main()
