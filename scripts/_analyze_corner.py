"""深入分析圆角边缘问题：检查过渡区 RGB 是否与相邻实体区匹配"""
import sys
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    print("Requires Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "output" / "PC浏览器push_批量_20260612_114256"

# 挑几个代表性的详细分析
SAMPLES = [
    ("Image 1222798.jpeg", "PC浏览器push_20260612_114259.png", 8, "TR"),
    ("Image 1222809.jpeg", "PC浏览器push112x112_20260612_114257.png", 20, "TL"),
    ("Image 1222814.jpeg", "PC浏览器push_20260612_114256.png", 8, "TR"),
]

def analyze_corner(img_path, radius, corner):
    img = Image.open(img_path)
    w, h = img.size
    pixels = img.load()

    if corner == "TL":
        x1, y1, x2, y2 = 0, 0, radius * 2 + 1, radius * 2 + 1
    elif corner == "TR":
        x1, y1, x2, y2 = w - radius * 2 - 1, 0, w, radius * 2 + 1
    else:
        x1, y1, x2, y2 = 0, 0, w, h

    print(f"\n=== {img_path.name}  {corner}角 r={radius} ===")
    print(f"  {'x':>3} {'y':>3} {'R':>3} {'G':>3} {'B':>3} {'A':>3} {'luma':>4} {'type'}")

    # 取角落区域的扩展区域做分析
    samples = []
    for y in range(y1, min(y2, h)):
        for x in range(x1, min(x2, w)):
            r, g, b, a = pixels[x, y]
            luma = 0.299 * r + 0.587 * g + 0.114 * b
            if a == 0:
                ptype = "transparent"
            elif a == 255:
                ptype = "opaque"
            else:
                ptype = "transition"
            samples.append((x, y, r, g, b, a, luma, ptype))

    # 打印透明像素（alpha=0）
    transparent = [s for s in samples if s[7] == "transparent"]
    if transparent:
        print(f"\n  透明像素 (alpha=0) — 共 {len(transparent)} 个:")
        for s in transparent[:5]:
            print(f"  {s[0]:>3} {s[1]:>3} {s[2]:>3} {s[3]:>3} {s[4]:>3} {s[5]:>3} {s[6]:>4.0f} {s[7]}")

    # 打印过渡像素
    transition = [s for s in samples if s[7] == "transition"]
    if transition:
        print(f"\n  过渡像素 (0<alpha<255) — 共 {len(transition)} 个:")
        for s in sorted(transition, key=lambda x: x[5]):  # sort by alpha
            print(f"  {s[0]:>3} {s[1]:>3} {s[2]:>3} {s[3]:>3} {s[4]:>3} {s[5]:>3} {s[6]:>4.0f} {s[7]}")

    # 检查：过渡区像素与最近的不透明像素的颜色差异
    if transition:
        # 找到最近的不透明像素的RGB
        opaque_near = [(s[2], s[3], s[4]) for s in samples if s[7] == "opaque"]
        if opaque_near:
            # 简化：取所有不透明像素的平均RGB
            avg_r = sum(o[0] for o in opaque_near) / len(opaque_near)
            avg_g = sum(o[1] for o in opaque_near) / len(opaque_near)
            avg_b = sum(o[2] for o in opaque_near) / len(opaque_near)
            print(f"\n  不透明区域平均RGB: ({avg_r:.0f}, {avg_g:.0f}, {avg_b:.0f})")

            # 检查每个过渡像素的颜色偏移
            color_shifts = []
            for s in transition:
                dr = abs(s[2] - avg_r)
                dg = abs(s[3] - avg_g)
                db = abs(s[4] - avg_b)
                color_shifts.append((s[5], dr + dg + db))

            if color_shifts:
                max_shift = max(cs[1] for cs in color_shifts)
                print(f"  过渡像素最大颜色偏移: {max_shift:.0f} (RGB差值之和)")
                if max_shift > 100:
                    print(f"  ⚠️ 过渡区颜色与实体区不匹配！可能存在色边")

def main():
    for sub_name, fname, radius, corner in SAMPLES:
        img_path = BATCH_DIR / sub_name / fname
        if img_path.exists():
            analyze_corner(img_path, radius, corner)

if __name__ == "__main__":
    main()
