#!/usr/bin/env python3
from PIL import Image
import sys
from pathlib import Path

_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

def main():
    icon_path = sys.argv[1] if len(sys.argv) > 1 else str(_SCRIPT_ROOT / "output/icon_rgba.png")
    thresh = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    pad = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    img = Image.open(icon_path).convert("RGBA")
    alpha = img.split()[-1]
    # create a binary mask where alpha > thresh
    mask = alpha.point(lambda p: 255 if p > thresh else 0)
    bbox = mask.getbbox()
    if bbox is None:
        print("NO_FG")
        sys.exit(1)
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(img.width, x2 + pad)
    y2 = min(img.height, y2 + pad)
    print(f"NEW_ICON_CROP: {x1} {y1} {x2} {y2}")

if __name__ == "__main__":
    main()
