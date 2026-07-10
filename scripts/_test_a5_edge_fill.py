"""测试 A5 替代方案：Pillow 边缘智能填充替代黑边"""
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

# 模拟场景: 取一张 bg.png 或 Clipboard 作为源图
src = Image.open(Path("input/Clipboard - 2026-06-01 10.00.56.png")).convert("RGB")
src_w, src_h = src.size
TARGET = (1976, 464)
canvas = Image.new("RGB", TARGET, (0, 0, 0))

# 缩放到覆盖画布宽度（保持比例）
scale = TARGET[0] / src_w
nw, nh = int(src_w * scale), int(src_h * scale)
scaled = src.resize((nw, nh), Image.Resampling.LANCZOS)
# 垂直居中
offset_y = (TARGET[1] - nh) // 2
canvas.paste(scaled, (0, offset_y))

arr = np.array(canvas)

# 检测黑色区域（顶部/底部黑边）
mask = np.max(arr, axis=-1) < 15
rows_black = np.mean(mask, axis=1) > 0.9
black_top = 0
while black_top < TARGET[1] and rows_black[black_top]:
    black_top += 1
black_bot = TARGET[1] - 1
while black_bot >= 0 and rows_black[black_bot]:
    black_bot -= 1

print(f"[A5 test] 黑边: top=0~{black_top}, bot={black_bot+1}~{TARGET[1]-1}", flush=True)

# 填充顶部黑边（从上往下延伸颜色）
if black_top > 0:
    for y in range(black_top - 1, -1, -1):
        arr[y] = arr[black_top]

# 填充底部黑边（从下往上延伸颜色）
if black_bot < TARGET[1] - 1:
    for y in range(black_bot + 1, TARGET[1]):
        arr[y] = arr[black_bot]

# 接缝处高斯模糊过渡
canvas2 = Image.fromarray(arr)
blurred = canvas2.filter(ImageFilter.GaussianBlur(radius=2))

# 只在接缝处应用模糊（保留主体区域清晰）
canvas2_np = np.array(canvas2)
blurred_np = np.array(blurred)
result_np = canvas2_np.copy()
for y in range(black_top - 5, black_top + 5):
    if 0 <= y < TARGET[1]:
        alpha = abs(y - black_top) / 5.0
        alpha = min(1.0, max(0.0, alpha))
        result_np[y] = (canvas2_np[y] * alpha + blurred_np[y] * (1 - alpha)).astype(np.uint8)
for y in range(black_bot - 4, black_bot + 6):
    if 0 <= y < TARGET[1]:
        alpha = abs(y - black_bot) / 5.0
        alpha = min(1.0, max(0.0, alpha))
        result_np[y] = (canvas2_np[y] * alpha + blurred_np[y] * (1 - alpha)).astype(np.uint8)

result = Image.fromarray(result_np)
out = Path("output/_test_a5_filled.png")
result.save(out, "PNG")
print(f"[A5 test] 完成: {out}", flush=True)
