"""测试 A6b 替代方案：Pillow 接缝平滑"""
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

# 用最近一次 strip 产出测试
import glob
strips = sorted(glob.glob("output/商店日常_聚力高考护航_*/step1_strip_*.png"))
path = strips[-1] if strips else None
if not path:
    print("No strip output found, skipping")
    import sys; sys.exit(0)

src = Image.open(path).convert("RGB")
arr = np.array(src)
h, w = arr.shape[:2]
print(f"[A6b test] 输入: {w}x{h}", flush=True)

# 纵向扫描：每列平均亮度 vs 相邻列
col_means = np.mean(arr, axis=0)  # (w, 3)
col_brightness = np.mean(col_means, axis=1)  # (w,)
# 检测突变列（相邻差值 > 阈值）
diffs = np.abs(np.diff(col_brightness))
threshold = np.percentile(diffs, 95) * 2
suspect = np.where(diffs > threshold)[0]
print(f"[A6b test] 可疑接缝数: {len(suspect)}", flush=True)

if len(suspect) == 0:
    print("[A6b test] 无可疑接缝，跳过", flush=True)
    import sys; sys.exit(0)

# 对每个可疑列做模糊
result = arr.copy().astype(np.float32)
for col in suspect[:5]:  # 最多处理 5 处
    x0 = max(0, col - 10)
    x1 = min(w, col + 10)
    for x in range(x0, x1):
        alpha = 1.0 - abs(x - col) / 10.0
        alpha = max(0.0, min(1.0, alpha))
        blurred_col = np.mean(arr[:, max(0, x-3):min(w, x+4)], axis=1)
        result[:, x] = result[:, x] * (1 - alpha) + blurred_col * alpha

result = np.clip(result, 0, 255).astype(np.uint8)
out = Path("output/_test_a6b_smoothed.png")
Image.fromarray(result).save(out, "PNG")
print(f"[A6b test] 完成: {out}", flush=True)
