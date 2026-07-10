"""检查源图边缘是否存在白边/边框"""
import sys
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    print("Requires Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"

IMAGES = [
    "Image 1222798.jpeg.png",
    "Image 1222804.jpeg.png",
    "Image 1222805.jpeg.png",
    "Image 1222809.jpeg.png",
    "Image 1222813.jpeg.png",
    "Image 1222814.jpeg.png",
    "矩形 1 拷贝 5.png",
    "矩形 1 拷贝 7.png",
]

def check_source_edges(img_path):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    pixels = img.load()

    # Check top/bottom/left/right 1px strips
    edges = {
        "top": [(x, 0) for x in range(w)],
        "bottom": [(x, h-1) for x in range(w)],
        "left": [(0, y) for y in range(h)],
        "right": [(w-1, y) for y in range(h)],
    }

    results = {}
    for ename, ecoords in edges.items():
        white_count = 0
        near_white = 0
        total = len(ecoords)
        for x, y in ecoords:
            r, g, b, a = pixels[x, y]
            if r == 255 and g == 255 and b == 255:
                white_count += 1
            elif r > 245 and g > 245 and b > 245:
                near_white += 1
        pct = (white_count + near_white) / total * 100
        results[ename] = (pct, white_count, near_white, total)

    return results

def main():
    for img_name in IMAGES:
        img_path = INPUT_DIR / img_name
        if not img_path.exists():
            print(f"SKIP: {img_name}")
            continue
        results = check_source_edges(img_path)
        w, h = Image.open(img_path).size
        print(f"\n{img_name} ({w}x{h}):")
        for edge, (pct, wc, nw, total) in results.items():
            if pct > 10:
                print(f"  {edge:>6}: {pct:.0f}% white ({wc+nw}/{total}) ⚠️")
            elif pct > 0:
                print(f"  {edge:>6}: {pct:.0f}% white ({wc+nw}/{total})")
            else:
                print(f"  {edge:>6}: clean")

if __name__ == "__main__":
    main()
