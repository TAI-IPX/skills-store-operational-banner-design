"""PC浏览器push 圆角边缘白边质量检查"""
import sys
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    print("Requires Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "output" / "PC浏览器push_批量_20260612_114256"

def check_corners(img_path, radius, label):
    """采样四个圆角区域的像素，检查白边/色边问题"""
    img = Image.open(img_path)
    if img.mode != "RGBA":
        return None
    w, h = img.size
    pixels = img.load()

    issues = []
    # 采样 4 个角的外缘（角半径范围外的像素）
    corners = {
        "TL": (0, 0, radius, radius),           # 左上
        "TR": (w - radius, 0, w, radius),        # 右上
        "BL": (0, h - radius, h, radius),        # 左下
        "BR": (w - radius, h - radius, w, h),    # 右下
    }

    for cname, (x1, y1, x2, y2) in corners.items():
        white_pixels = 0
        total_pixels = 0
        high_luma_transition = 0  # alpha 0-90% 但 RGB 亮度 > 200
        for y in range(y1, y2):
            for x in range(x1, x2):
                r, g, b, a = pixels[x, y]
                total_pixels += 1
                if a < 10:
                    # 透明区域有亮色残留 → 白边风险
                    if r > 240 and g > 240 and b > 240:
                        white_pixels += 1
                # 半透明过渡区有高亮 RGB → 色边风险
                if 10 <= a <= 200:
                    luma = 0.299 * r + 0.587 * g + 0.114 * b
                    if luma > 200:
                        high_luma_transition += 1

        if total_pixels > 0:
            wp_ratio = white_pixels / total_pixels
            ht_ratio = high_luma_transition / total_pixels
            if wp_ratio > 0.005 or ht_ratio > 0.01:
                issues.append(f"  {cname}: white={wp_ratio:.3%} trans_luma_hi={ht_ratio:.3%}")

    # 全局透明残留检查（画布四周最外缘 1px）
    edge_white = 0
    edge_total = 0
    for x in range(w):
        for y in [0, h-1]:
            r, g, b, a = pixels[x, y]
            if a < 10:
                edge_total += 1
                if r > 240 and g > 240 and b > 240:
                    edge_white += 1
    for y in range(1, h-1):
        for x in [0, w-1]:
            r, g, b, a = pixels[x, y]
            if a < 10:
                edge_total += 1
                if r > 240 and g > 240 and b > 240:
                    edge_white += 1
    edge_status = "clean"
    if edge_total > 0 and edge_white / max(edge_total, 1) > 0.3:
        edge_status = f"WARN: {edge_white}/{edge_total} edge px white"

    return issues, edge_status

def main():
    results = []
    for sub_dir in sorted(BATCH_DIR.iterdir()):
        if not sub_dir.is_dir():
            continue
        name = sub_dir.name
        for img_file in sorted(sub_dir.glob("PC浏览器push*.png")):
            fname = img_file.name
            # Determine radius based on filename
            if "@150" in fname:
                radius = 12
            elif "@200" in fname:
                radius = 16
            elif "@300" in fname:
                radius = 24
            elif "112x112" in fname or "push112x112" in fname:
                radius = 20
            else:
                radius = 8  # base @1x

            res = check_corners(img_file, radius, f"{name}/{fname}")
            if res is None:
                results.append((f"{name}/{fname}", "SKIP", "not RGBA"))
                continue
            issues, edge_status = res

            if issues or "WARN" in edge_status:
                status = "ISSUE"
                for iss in issues:
                    print(f"[ISSUE] {name}/{fname} r={radius}px {iss}", flush=True)
                if "WARN" in edge_status:
                    print(f"[EDGE]  {name}/{fname} r={radius}px {edge_status}", flush=True)
            else:
                status = "OK"
            results.append((f"{name}/{fname}", status, f"r={radius}"))

    # Summary
    ok = sum(1 for _, s, _ in results if s == "OK")
    issue = sum(1 for _, s, _ in results if s == "ISSUE")
    skip = sum(1 for _, s, _ in results if s == "SKIP")
    print(f"\n{'='*50}")
    print(f"总计: {len(results)} 个输出 | OK: {ok} | 问题: {issue} | 跳过: {skip}")
    if issue > 0:
        print("存在白边/色边问题，见上方 [ISSUE] 行")
        return 1
    print("所有输出圆角边缘质量合格")
    return 0

if __name__ == "__main__":
    sys.exit(main())
