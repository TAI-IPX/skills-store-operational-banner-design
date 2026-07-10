"""测试 A4 v2：Pillow 从主体边缘色扩展填充 4096×1024，多频段混合去拼接感"""
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

SRC = Path("input/Clipboard - 2026-06-01 10.00.56.png")
OUT = Path("output/_test_a4_v2.png")
TARGET = (4096, 1024)
SAFE_RATIO = 0.85  # 主体占安全区 85%
SEAM_BLEND = 120   # 接缝羽化宽度 px

subject = Image.open(SRC).convert("RGB")
sw, sh = subject.size
tw, th = TARGET
print(f"[v2] 源图: {sw}x{sh}", flush=True)

# === Step 1: 采样四边颜色 ===
arr = np.array(subject, dtype=np.float32)
edge_w = max(1, min(sw, sh) // 30)
left_color   = arr[:, :edge_w].reshape(-1, 3).mean(axis=0).astype(np.int32)
right_color  = arr[:, -edge_w:].reshape(-1, 3).mean(axis=0).astype(np.int32)
top_color    = arr[:edge_w, :].reshape(-1, 3).mean(axis=0).astype(np.int32)
bottom_color = arr[-edge_w:, :].reshape(-1, 3).mean(axis=0).astype(np.int32)
print(f"[v2] 边缘色 L={left_color} R={right_color} T={top_color} B={bottom_color}", flush=True)

# === Step 2: 缩放主体到安全区 ===
safe_w, safe_h = int(tw * SAFE_RATIO), int(th * SAFE_RATIO)
scale = min(safe_w / sw, safe_h / sh)
nw, nh = int(sw * scale), int(sh * scale)
scaled = subject.resize((nw, nh), Image.Resampling.LANCZOS)
sx = (tw - nw) // 2
sy = (th - nh) // 2
print(f"[v2] 主体缩放: {nw}x{nh} 画布: {tw}x{th} offset: ({sx},{sy})", flush=True)

# === Step 3: 贴主体 + 扩展填充 ===
canvas = np.zeros((th, tw, 3), dtype=np.float32)
canvas[sy:sy+nh, sx:sx+nw] = np.array(scaled, dtype=np.float32)

# 主体 mask (0=扩展区, 1=主体)
mask = np.zeros((th, tw), dtype=np.float32)
mask[sy:sy+nh, sx:sx+nw] = 1.0

# 距离变换：每个像素到主体边缘的像素距离
from scipy.ndimage import distance_transform_edt
dist = distance_transform_edt(1 - mask)

# 对每个像素，判断它靠近哪一边
y_coords, x_coords = np.mgrid[0:th, 0:tw].astype(np.float32)
# 左边：x < sx → 用 left_color
# 右边：x > sx+nw → 用 right_color
# 上边：y < sy → 用 top_color
# 下边：y > sy+nh → 用 bottom_color
# 角落：混合两边

left_w = (x_coords < sx).astype(np.float32)
right_w = (x_coords > sx + nw).astype(np.float32)
top_w = (y_coords < sy).astype(np.float32)
bottom_w = (y_coords > sy + nh).astype(np.float32)

# 扩展色 = 加权边缘色（角区域双向混合）
expand_color = np.zeros_like(canvas)
expand_color += left_w[:, :, None] * left_color[None, None, :]
expand_color += right_w[:, :, None] * right_color[None, None, :]
expand_color += top_w[:, :, None] * top_color[None, None, :]
expand_color += bottom_w[:, :, None] * bottom_color[None, None, :]
total_w = left_w + right_w + top_w + bottom_w + 1e-6
expand_color /= total_w[:, :, None]

# 距离衰减：越远越暗（模拟自然渐变）
max_dist = max(tw, th) * 0.6
dist_factor = np.clip(dist / max_dist, 0, 1)
# 加微量随机变化模拟纹理
np.random.seed(42)
noise = np.random.normal(0, 3, (th, tw, 3)).astype(np.float32)

filled = canvas.copy()
expand_area = mask < 0.5
blend_factor = dist_factor[expand_area]
filled[expand_area] = expand_color[expand_area] * (1 - blend_factor[:, None]) + expand_color[expand_area] * blend_factor[:, None] * 0.85
filled[expand_area] += noise[expand_area] * np.clip(blend_factor[:, None] * 0.5, 0, 1)

filled_img = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8))

# === Step 4: 多频段混合 ===
lp = filled_img.filter(ImageFilter.GaussianBlur(radius=80))
bp1 = Image.fromarray(np.clip(
    np.array(filled_img, dtype=np.float32) - np.array(lp, dtype=np.float32) + 128, 0, 255
).astype(np.uint8))

# 主体 mask 羽化
mask_f = mask.copy()
mask_dist = np.clip(dist / SEAM_BLEND, 0, 1)
mask_f = mask_f + (1 - mask_f) * mask_dist
mask_blur = Image.fromarray((mask_f * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=SEAM_BLEND/4))
mask_smooth = np.array(mask_blur, dtype=np.float32) / 255.0

# 背景层 = LP + 0.3 * BP1_detail（只给低频，不抢焦点）
lp_arr = np.array(lp, dtype=np.float32)
bp1_arr = np.clip(np.array(bp1, dtype=np.float32) - 128, -128, 128)
bg_layer = lp_arr + bp1_arr * 0.3

# 混合
result = canvas * mask_smooth[:, :, None] + bg_layer * (1 - mask_smooth[:, :, None])
result = np.clip(result, 0, 255).astype(np.uint8)

# === Step 5: 接缝处加宽羽化 ===
result_img = Image.fromarray(result)
seam_blur = result_img.filter(ImageFilter.GaussianBlur(radius=SEAM_BLEND // 4))
seam_arr = np.array(seam_blur, dtype=np.float32)
result_arr = np.array(result_img, dtype=np.float32)
mask_seam = np.clip(np.abs(mask_smooth - 0.5) * 2, 0, 1)
final = result_arr * (1 - mask_seam[:, :, None]) + seam_arr * mask_seam[:, :, None]
final = np.clip(final, 0, 255).astype(np.uint8)

Image.fromarray(final).save(OUT, "PNG")
print(f"[v2] 完成: {OUT}", flush=True)
