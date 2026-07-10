#!/usr/bin/env python3
"""
生成气泡提示框 PNG，支持 1x / 1.5x / 2x / 3x 倍率输出。
形状完全还原 Figma SVG node-id=2680-43770。

用法：
    python scripts/generate_bubble.py --text "今天是周五"
    python scripts/generate_bubble.py --text "文案" --theme 粉色
    python scripts/generate_bubble.py --text "文案" --theme 粉色 --no-close
    python scripts/generate_bubble.py --text "文案" --output-dir output/bubble
    python scripts/generate_bubble.py --text "文案" --icon-path output/icon_rgba.png --icon-crop 331 181 1034 1022
    python scripts/generate_bubble.py --text "文案" --color-left 255,100,100 --text-color 130,20,77
"""
import argparse
import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

# 项目根目录（scripts/ 的上一级）
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

# ── Figma 精确规格（1x = SVG 原始尺寸）────────────────────────────
SVG_W   = 149.0   # 总宽149px（含边框）
# 主体高度 41px，尾巴尖端在 y=40.2，需要额外空间
# 用户要求：总高 48px，顶部 7px 空白
SVG_H = 48.0   # 总高改为 48px

# 主体边界（边框0.5px内缩），y 需要往上移 7px 腾出顶部空白
OFFSET_Y = 7.0
BODY_X1    = 148.5   # 右边界
BODY_X0    = 0.5     # 左边界
BODY_Y0    = 0.5 + OFFSET_Y   # 上边界 7.5
BODY_Y1    = 31.5 + OFFSET_Y  # 底边（尾巴起点）38.5
CORNER_R   = 8.5

# 尾巴坐标（绝对坐标，整体上移 7px）
TAIL_LEFT  = 15.9473
TAIL_RIGHT = 31.3418
TAIL_TIP_X = 20.5
TAIL_TIP_Y = 39.19 + 7.0  # 46.19

# 颜色
GRAD_LEFT  = (104, 164, 255)   # #68A4FF
GRAD_RIGHT = (255, 255, 255)   # #FFFFFF
GRAD_END_X = 114.0             # 背景渐变到此处变为纯白（SVG 坐标）
BORDER_GRAD_X0 = 38.0
BORDER_GRAD_X1 = 146.5         # 边框渐变终点
BORDER_RGB     = (213, 213, 213)

TEXT_COLOR  = (130, 20, 77)
TEXT_SIZE   = 13
CLOSE_COLOR = (180, 170, 175)
CLOSE_SIZE  = 11

FONT_BOLD   = "C:/Windows/Fonts/msyhbd.ttc"
FONT_NORMAL = "C:/Windows/Fonts/msyh.ttc"

THEMES = {
    "粉色": {"grad": (254, 166, 166), "text": (130, 20, 77)},    # #FEA6A6, #82144D
    "黄色": {"grad": (255, 229, 125), "text": (124, 55, 32)},   # #FFE57D, #7C3720
    "绿色": {"grad": (74, 208, 147), "text": (56, 110, 66)},   # #4AD093, #386E42
    "蓝色": {"grad": (104, 164, 255), "text": (38, 49, 95)},   # #68A4FF, #26315F（默认）
    "紫色": {"grad": (202, 148, 255), "text": (105, 5, 126)},  # #CA94FF, #69057E
}

# Icon 目标显示尺寸
ICON_W, ICON_H = 42, 48  # 画布尺寸（42 = ICON_X 4 + ICON_CONTENT_W 38，防止右侧截断）
ICON_CONTENT_W, ICON_CONTENT_H = 38, 38  # 内容尺寸
ICON_X, ICON_Y = 4, 0  # 位置
ICON_PATH = str(_SCRIPT_ROOT / "output/icon_rgba.png")

# 裁剪区域（rembg抠图后分析非透明区域获取），每次换 icon 需更新
ICON_CROP = (330, 179, 1034, 1022)  # 2026-05-07 黄色铃铛图标

# 浏览器弹泡旧规（画布 227×42px）
# SVG viewBox 0 0 221 37，内容 x=8~219 y=1~33
# 映射到画布：x 偏移 +6（icon 溢出），y 偏移 +2.5（垂直居中）
BROWSER_W = 227.0
BROWSER_H = 42.0
BROWSER_OFFSET_X = 6.0    # SVG→画布 x 偏移
BROWSER_OFFSET_Y = 4.0    # SVG→画布 y 偏移（垂直居中）
# 主体边界（SVG 坐标 + 偏移，0.5px 内缩对齐外描边）
BROWSER_BODY_X0 = 8.0  + BROWSER_OFFSET_X   # 14.0
BROWSER_BODY_X1 = 219.0 + BROWSER_OFFSET_X  # 225.0
BROWSER_BODY_Y0 = 1.0  + BROWSER_OFFSET_Y   # 3.5
BROWSER_BODY_Y1 = 33.0 + BROWSER_OFFSET_Y   # 35.5
BROWSER_CORNER_R = 6.0
# 箭头坐标（SVG 坐标 + 偏移）
# SVG 路径：左边 V22（下切点）→ 尖端 → L12（上切点）→ V7
# y=12 靠近顶部（上切点），y=22 靠近底部（下切点），尖端 y=17.028 居中
BROWSER_ARROW_ROOT_X = 8.0   + BROWSER_OFFSET_X   # 14.0
BROWSER_ARROW_Y_TOP  = 12.0  + BROWSER_OFFSET_Y   # 16.0  上切点（靠近顶部）
BROWSER_ARROW_Y_BOT  = 22.0  + BROWSER_OFFSET_Y   # 26.0  下切点（靠近底部）
BROWSER_ARROW_TIP_X  = 2.604 + BROWSER_OFFSET_X   # 8.604
BROWSER_ARROW_TIP_Y  = 18.028 + BROWSER_OFFSET_Y  # 22.028 尖端下移 1px
# 箭头尖端圆弧控制点（对应 SVG C 命令：C1.799 17.507 1.799 16.548 2.604 15.958）
BROWSER_ARROW_CP_DX  = -0.805  # 控制点相对尖端 x 的偏移（1.799 = 2.604 - 0.805）
# 关闭按钮（20×20px，右上圆角方块 + × 线条）
BROWSER_CLOSE_SIZE    = 20
BROWSER_CLOSE_CORNER  = 6
BROWSER_CLOSE_STROKE  = (213, 213, 213, 77)  # #D5D5D5 30%
BROWSER_CLOSE_LINE_W  = 1.11
# 文字（居中于 x=54~227 区间，中心 x=140.5）
BROWSER_TEXT_SIZE     = 16
BROWSER_TEXT_CENTER_X = 140.5
BROWSER_TEXT_CENTER_Y = 21.0
# Icon（x=9, y=0，尺寸 41×37）
BROWSER_ICON_W         = 41
BROWSER_ICON_H         = 37
BROWSER_ICON_CONTENT_W = 41
BROWSER_ICON_CONTENT_H = 37
BROWSER_ICON_X         = 9
BROWSER_ICON_Y         = 0

SCALES = [1, 1.5, 2, 3]


def detect_icon_bounds(image_path: str, max_size: int = 150) -> tuple:
    """
    自动检测 icon 图片的非透明区域边界，返回中心区域。
    max_size: 最大边长限制，默认 150px，避免 icon 太大导致缩放时被裁切。
    返回 (x1, y1, x2, y2) 裁剪坐标。
    """
    img = Image.open(image_path).convert("RGBA")
    arr = np.array(img)
    alpha = arr[:,:,3]
    coords = np.where(alpha > 0)
    if len(coords[0]) == 0:
        return (0, 0, img.width, img.height)
    y1, y2 = coords[0].min(), coords[0].max()
    x1, x2 = coords[1].min(), coords[1].max()

    # 计算中心并限制最大尺寸
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    half = max_size // 2
    x1_new = max(0, cx - half)
    y1_new = max(0, cy - half)
    x2_new = min(img.width, cx + half)
    y2_new = min(img.height, cy + half)
    return (x1_new, y1_new, x2_new, y2_new)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def qbez(p0, p1, p2, steps=20):
    """二次贝塞尔（SVG Q）"""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1-t)**2*p0[0] + 2*(1-t)*t*p1[0] + t**2*p2[0]
        y = (1-t)**2*p0[1] + 2*(1-t)*t*p1[1] + t**2*p2[1]
        pts.append((x, y))
    return pts


def cbez(p0, p1, p2, p3, steps=20):
    """三次贝塞尔（SVG C）"""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t**2*p2[0] + t**3*p3[0]
        y = (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def make_icon_image(scale: float, icon_path: str = None, icon_crop: tuple = None) -> Image.Image:
    """
    加载、裁剪、缩放 icon，返回 RGBA 画布（ICON_W*scale × ICON_H*scale）。
    icon_path: icon 文件路径，None 则使用全局 ICON_PATH
    icon_crop: (x1,y1,x2,y2) 裁剪区域，None 则不裁剪
    """
    _icon_path = icon_path if icon_path is not None else ICON_PATH
    _icon_crop = icon_crop if icon_crop is not None else ICON_CROP

    # 如果没有提供 icon_crop，自动检测非透明区域
    if icon_crop is None:
        try:
            detected = detect_icon_bounds(_icon_path)
            if detected:
                _icon_crop = detected
                print(f"[auto-detect] icon crop: {_icon_crop}")
        except Exception as e:
            print(f"[auto-detect] icon crop failed: {e}, using default ICON_CROP")

    icon_raw = Image.open(_icon_path).convert("RGBA")
    icon_cropped = icon_raw.crop(_icon_crop) if _icon_crop else icon_raw

    src_w, src_h = icon_cropped.size
    src_ratio = src_w / src_h
    content_w = round(ICON_CONTENT_W * scale)
    content_h = round(ICON_CONTENT_H * scale)
    content_ratio = content_w / content_h

    if src_ratio > content_ratio:
        new_w = content_w
        new_h = round(content_w / src_ratio)
    else:
        new_h = content_h
        new_w = round(content_h * src_ratio)

    icon_resized = icon_cropped.resize((new_w, new_h), Image.LANCZOS)

    canvas_w = round(ICON_W * scale)
    canvas_h = round(ICON_H * scale)
    icon_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    paste_x = round(ICON_X * scale)
    paste_y = round(ICON_Y * scale)
    icon_canvas.paste(icon_resized, (paste_x, paste_y), icon_resized)
    return icon_canvas


def make_bubble(text: str, scale: float, grad_color: tuple = None, text_color: tuple = None,
                with_icon: bool = True, with_close: bool = True,
                icon_path: str = None, icon_crop: tuple = None,
                use_browser: bool = False) -> Image.Image:
    s = scale
    _grad_color = grad_color if grad_color else GRAD_LEFT
    _text_color = text_color if text_color else TEXT_COLOR

    # 浏览器弹泡旧规 vs 商店弹泡（新/旧规）
    if use_browser:
        base_w = BROWSER_W
        base_h = BROWSER_H
        base_body_h = BROWSER_BODY_Y1 - BROWSER_BODY_Y0  # 32.0
        # 浏览器弹泡：固定宽度，不动态扩展
        actual_svg_w = BROWSER_W
        grad_end_x    = GRAD_END_X * (BROWSER_W / 149.0)
        border_grad_x1 = BORDER_GRAD_X1 * (BROWSER_W / 149.0)
    else:
        base_w = SVG_W
        base_h = SVG_H
        base_body_h = SVG_H - OFFSET_Y
        # ── 动态计算气泡宽度 ──────────────────────────────────────────
        # 先用 1x 字体测量文字宽度，再换算到实际 scale
        try:
            _font = ImageFont.truetype(FONT_BOLD, TEXT_SIZE)
        except OSError:
            _font = ImageFont.load_default()
        tb = _font.getbbox(text)
        text_w_1x = tb[2] - tb[0]
        # 43(文字起始) + text_w + 10(文字到×间距) + 8(×宽) + 8(×距右边框) + 1(边框)
        # 关闭按钮位置始终保留，只是绘制与否
        close_w = 8 + 8 + 10  # 26px
        needed_w = 43 + text_w_1x + close_w + 1
        # 动态计算宽度，与基础尺寸比较取较大值
        actual_svg_w = max(base_w, math.ceil(needed_w))
        # 等比移动渐变终止点
        ratio = actual_svg_w / base_w
        grad_end_x    = GRAD_END_X    * ratio
        border_grad_x1 = BORDER_GRAD_X1 * ratio

    cw = math.ceil(actual_svg_w * s)
    ch = math.ceil(base_h * s)

    def sx(v): return v * cw / actual_svg_w
    def sy(v): return v * ch / base_h

    SS = 4
    W, H = cw * SS, ch * SS

    def px(v): return sx(v) * SS
    def py(v): return sy(v) * SS

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # 右侧边界随宽度动态计算
    rx  = actual_svg_w - 0.5   # 右边界
    rx0 = rx - 8.5             # 右侧圆角切点
    rc1 = rx - 3.806           # 右侧控制点

    path = []

    if use_browser:
        # ── 浏览器弹泡旧规：还原 SVG node-id=2763-45077 ──────────
        # 画布 227×42，主体 x=14~225 y=3.5~35.5，箭头尖端 x=8.604 y=19.528
        bx0 = BROWSER_BODY_X0   # 14.0
        bx1 = BROWSER_BODY_X1   # 225.0
        by0 = BROWSER_BODY_Y0   # 3.5
        by1 = BROWSER_BODY_Y1   # 35.5
        r   = BROWSER_CORNER_R  # 6.0
        k   = r * 0.5523        # 贝塞尔圆角控制点偏移（≈3.314）
        ax  = BROWSER_ARROW_ROOT_X  # 14.0
        ayt = BROWSER_ARROW_Y_TOP   # 14.5  上切点
        ayb = BROWSER_ARROW_Y_BOT   # 24.5  下切点
        tip_x = BROWSER_ARROW_TIP_X # 8.604 尖端 x
        tip_y = BROWSER_ARROW_TIP_Y # 19.528 尖端中心 y
        cp_dx = BROWSER_ARROW_CP_DX # -0.805 圆弧控制点偏移

        # 起点：右上圆角左切点
        path.append((bx1 - r, by0))
        # 右上圆角
        path += cbez((bx1-r, by0), (bx1-r+k, by0), (bx1, by0+r-k), (bx1, by0+r))
        # 右边
        path.append((bx1, by1 - r))
        # 右下圆角
        path += cbez((bx1, by1-r), (bx1, by1-r+k), (bx1-r+k, by1), (bx1-r, by1))
        # 底边
        path.append((bx0 + r, by1))
        # 左下圆角
        path += cbez((bx0+r, by1), (bx0+r-k, by1), (bx0, by1-r+k), (bx0, by1-r))
        # 左边下段（到箭头下切点）
        path.append((ax, ayb))
        # 箭头下斜边到尖端下点
        path.append((tip_x, tip_y))
        # 箭头尖端圆弧（SVG: C1.799 17.507 1.799 16.548 2.604 15.958 + offset）
        path += cbez(
            (tip_x, tip_y),
            (tip_x + cp_dx, tip_y - 0.521),
            (tip_x + cp_dx, tip_y - 1.480),
            (tip_x, tip_y - 2.070)
        )
        # 箭头上斜边回切点
        path.append((ax, ayt))
        # 左边上段
        path.append((bx0, by0 + r))
        # 左上圆角
        path += cbez((bx0, by0+r), (bx0, by0+r-k), (bx0+r-k, by0), (bx0+r, by0))
        # 顶边回起点
        path.append((bx1 - r, by0))

    else:
        # ── 商店弹泡：圆角矩形 + 底部尾巴 ────────────────────────
        # 起点（右上圆角左切点）
        path.append((rx0, BODY_Y0))

        # 右上圆角
        path += cbez((rx0, BODY_Y0), (rc1, BODY_Y0), (rx, 4.30558 + OFFSET_Y), (rx, 9 + OFFSET_Y))

        # 右边垂直线
        path.append((rx, 23 + OFFSET_Y))

        # 右下圆角
        path += cbez((rx, 23 + OFFSET_Y), (rx, 27.6944 + OFFSET_Y), (rc1, BODY_Y1), (rx0, BODY_Y1))

        # 底边右段 → 尾巴右侧
        path.append((31.3418, 31.5 + OFFSET_Y))

        # 尾巴右侧圆弧
        path += cbez((31.3418, 31.5 + OFFSET_Y), (28.8033, 31.5 + OFFSET_Y), (26.4362, 32.7837 + OFFSET_Y), (25.0527, 34.9121 + OFFSET_Y))

        # 尾巴右斜边
        path.append((22.5957, 38.6924 + OFFSET_Y))

        # 尾巴尖端圆弧
        path += cbez((22.5957, 38.6924 + OFFSET_Y), (21.6098, 40.2091 + OFFSET_Y), (19.3902, 40.2091 + OFFSET_Y), (18.4043, 38.6924 + OFFSET_Y))

        # 尾巴左斜边
        path.append((15.9473, 34.9121 + OFFSET_Y))

        # 尾巴左侧圆弧
        path += cbez((15.9473, 34.9121 + OFFSET_Y), (14.5638, 32.7837 + OFFSET_Y), (12.1967, 31.5 + OFFSET_Y), (9.6582, 31.5 + OFFSET_Y))

        # 底边左段
        path.append((9, 31.5 + OFFSET_Y))

        # 左下圆角
        path += cbez((9, 31.5 + OFFSET_Y), (4.30558, 31.5 + OFFSET_Y), (0.5, 27.6944 + OFFSET_Y), (0.5, 23 + OFFSET_Y))

        # 左边垂直线
        path.append((0.5, 9 + OFFSET_Y))

        # 左上圆角
        path += cbez((0.5, 9 + OFFSET_Y), (0.5, 4.30558 + OFFSET_Y), (4.30558, 0.5 + OFFSET_Y), (9, 0.5 + OFFSET_Y))

        # 顶边回到起点
        path.append((rx0, BODY_Y0))

    poly = [(px(p[0]), py(p[1])) for p in path]
    poly_int = [(int(round(x)), int(round(y))) for x, y in poly]

    # ── 渐变填充（numpy 向量化，比逐列 draw.line 快 10x）──────────
    gend = px(grad_end_x)
    xs = np.arange(W, dtype=np.float32)
    t_arr = np.clip(xs / max(gend, 1), 0.0, 1.0)  # shape (W,)

    r = int(_grad_color[0]) + (255 - int(_grad_color[0])) * t_arr
    g = int(_grad_color[1]) + (255 - int(_grad_color[1])) * t_arr
    b = int(_grad_color[2]) + (255 - int(_grad_color[2])) * t_arr
    # grad_arr shape: (H, W, 4)
    grad_arr = np.zeros((H, W, 4), dtype=np.uint8)
    grad_arr[:, :, 0] = r.astype(np.uint8)
    grad_arr[:, :, 1] = g.astype(np.uint8)
    grad_arr[:, :, 2] = b.astype(np.uint8)
    grad_arr[:, :, 3] = 255
    grad_img = Image.fromarray(grad_arr, "RGBA")

    fill_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(fill_mask).polygon(poly_int, fill=255)
    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fill_layer.paste(grad_img, (0, 0), fill_mask)
    canvas = Image.alpha_composite(canvas, fill_layer)

    # 边框
    border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    stroke_w = SS   # 超采样后缩小 = 严格 1px
    # 边框：统一使用固定颜色 #D5D5D5，无渐变
    ImageDraw.Draw(border_layer).line(poly_int + [poly_int[0]],
                                      fill=BORDER_RGB + (255,), width=stroke_w)
    canvas = Image.alpha_composite(canvas, border_layer)

    img = canvas.resize((cw, ch), Image.LANCZOS)

    # 浏览器弹泡：添加 drop-shadow（向下 2px，#000000 10%，柔边）
    if use_browser:
        shadow_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        poly_small = [(int(round(px(p[0]) / SS)), int(round(py(p[1]) / SS))) for p in path]
        shadow_draw.polygon(poly_small, fill=(0, 0, 0, 26))  # 10% of 255 ≈ 26
        # 应用高斯模糊（柔边效果）
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2))
        # 向下偏移 2px
        shadow_offset = shadow_layer.transform(
            (cw, ch), Image.AFFINE, (1, 0, 0, 0, 1, -round(2 * s)), Image.BILINEAR
        )
        img = Image.alpha_composite(shadow_offset, img)

    # 文字
    draw = ImageDraw.Draw(img)
    if use_browser:
        text_size = max(8, round(BROWSER_TEXT_SIZE * s))
    else:
        text_size = max(8, round(TEXT_SIZE * s))
    try:
        font_text = ImageFont.truetype(FONT_BOLD, text_size)
    except OSError:
        font_text = ImageFont.load_default()

    body_h = sy(base_body_h)  # 主体高度

    # ── 关闭按钮 ──────────────────────────────────────────────────
    if with_close:
        if use_browser:
            # 浏览器弹泡关闭按钮：20×20 圆角方块（右上圆角）+ × 线条
            btn_size = round(BROWSER_CLOSE_SIZE * s)
            btn_x = round(sx(BROWSER_BODY_X1) - btn_size)  # 紧贴内容区右边界
            btn_y = round(sy(BROWSER_BODY_Y0))              # 对齐气泡顶部（右上角）
            btn_r = round(BROWSER_CLOSE_CORNER * s)
            btn_k = btn_r * 0.5523
            sc = BROWSER_CLOSE_STROKE  # (213,213,213,77)
            lw = max(1, round(BROWSER_CLOSE_LINE_W * s))

            # 外框路径（右上圆角，其余三角直角）
            # 顺序：左上→右上圆角→右下→左下→左上
            btn_path = []
            btn_path.append((btn_x, btn_y))                          # 左上（直角）
            btn_path.append((btn_x + btn_size - btn_r, btn_y))       # 右上圆角左切点
            btn_path += cbez(
                (btn_x + btn_size - btn_r, btn_y),
                (btn_x + btn_size - btn_r + btn_k, btn_y),
                (btn_x + btn_size, btn_y + btn_r - btn_k),
                (btn_x + btn_size, btn_y + btn_r)
            )
            btn_path.append((btn_x + btn_size, btn_y + btn_size))    # 右下（直角）
            # 左下圆角（与右上角相同的圆角逻辑）
            btn_path += cbez(
                (btn_x + btn_r, btn_y + btn_size),
                (btn_x + btn_r - btn_k, btn_y + btn_size),
                (btn_x, btn_y + btn_size - btn_r + btn_k),
                (btn_x, btn_y + btn_size - btn_r)
            )
            btn_path.append((btn_x, btn_y))                          # 回左上（直角）
            btn_poly = [(int(round(x)), int(round(y))) for x, y in btn_path]
            draw.line(btn_poly, fill=sc, width=max(1, round(0.5 * s)))

            # × 线条（线条区域在按钮内 pad=7px 处）
            pad = round(7 * s)
            x0, y0 = btn_x + pad, btn_y + pad
            x1, y1 = btn_x + btn_size - pad, btn_y + btn_size - pad
            draw.line([(x1, y0), (x0, y1)], fill=sc, width=lw)
            draw.line([(x0, y0), (x1, y1)], fill=sc, width=lw)
        else:
            # 商店弹泡关闭按钮：简单 × 图标
            # 关闭按钮垂直居中于整个画布
            content_right = sx(actual_svg_w - 0.5)
            icon_size = round(8 * s)
            lw = max(1, round(1.2 * s))
            icon_x = round(content_right - 8 * s - icon_size - lw / 2)
            icon_y = round((ch - icon_size) / 2)  # 垂直居中于整个画布
            draw.line([(icon_x, icon_y), (icon_x + icon_size, icon_y + icon_size)],
                      fill=CLOSE_COLOR, width=lw)
            draw.line([(icon_x + icon_size, icon_y), (icon_x, icon_y + icon_size)],
                      fill=CLOSE_COLOR, width=lw)

    # ── 文字绘制 ──────────────────────────────────────────────────
    if use_browser:
        # 文字左对齐，起始 x=54，右侧到关闭按钮左边界
        text_left   = sx(54.0)
        right_limit = sx(BROWSER_BODY_X1 - BROWSER_CLOSE_SIZE - 2)
        max_text_w  = right_limit - text_left

        display_text = text
        while len(display_text) > 0:
            tb = font_text.getbbox(display_text)
            if (tb[2] - tb[0]) <= max_text_w:
                break
            display_text = display_text[:-1]

        # 左对齐，垂直居中
        cy = round(sy(BROWSER_TEXT_CENTER_Y))
        tb = font_text.getbbox(display_text)
        th = tb[3] - tb[1]
        tx = round(text_left) - tb[0]
        ty = cy - th // 2 - tb[1]
        draw.text((tx, ty), display_text, font=font_text, fill=_text_color)
    else:
        # 商店弹泡（新规和旧规都是左对齐，起始 x=43）
        tb = font_text.getbbox(text)
        text_x = round(43 * s)
        # 文字垂直居中于整个画布
        text_y = (ch - (tb[3] - tb[1])) // 2 - tb[1]
        draw.text((text_x, text_y), text, font=font_text, fill=_text_color)

    # 叠加 icon
    if with_icon:
        try:
            if use_browser:
                # 浏览器弹泡 icon：42×37 内容，画布 42×42，位置 x=8, y=0
                _icon_path = icon_path if icon_path is not None else ICON_PATH
                _icon_crop = icon_crop if icon_crop is not None else ICON_CROP
                # 自动检测非透明区域
                if icon_crop is None:
                    try:
                        detected = detect_icon_bounds(_icon_path)
                        if detected:
                            _icon_crop = detected
                            print(f"[auto-detect] browser icon crop: {_icon_crop}")
                    except Exception:
                        pass
                icon_raw = Image.open(_icon_path).convert("RGBA")
                icon_cropped = icon_raw.crop(_icon_crop) if _icon_crop else icon_raw
                content_w = round(BROWSER_ICON_CONTENT_W * s)
                content_h = round(BROWSER_ICON_CONTENT_H * s)
                src_w, src_h = icon_cropped.size
                src_ratio = src_w / src_h
                content_ratio = content_w / content_h
                if src_ratio > content_ratio:
                    new_w = content_w
                    new_h = round(content_w / src_ratio)
                else:
                    new_h = content_h
                    new_w = round(content_h * src_ratio)
                icon_resized = icon_cropped.resize((new_w, new_h), Image.LANCZOS)
                canvas_w = round(BROWSER_ICON_W * s)
                canvas_h = round(BROWSER_ICON_H * s)
                icon_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
                # 内容顶部对齐，水平居中
                paste_x = (canvas_w - new_w) // 2
                paste_y = 0
                icon_canvas.paste(icon_resized, (paste_x, paste_y), icon_resized)
                img.paste(icon_canvas, (round(BROWSER_ICON_X * s), round(BROWSER_ICON_Y * s)), icon_canvas)
            else:
                icon_canvas = make_icon_image(scale, icon_path=icon_path, icon_crop=icon_crop)
                img.paste(icon_canvas, (0, 0), icon_canvas)
        except Exception as e:
            print("Warning: icon load error:", e)

    return img


def main():
    # 新调用方式：py scripts/generate_bubble.py "文案" 浏览器弹泡旧规 紫色
    # 兼容旧调用：py scripts/generate_bubble.py --text "文案" --浏览器弹泡旧规 --theme 紫色
    parser = argparse.ArgumentParser(description="生成气泡提示框 PNG")
    parser.add_argument("text", nargs="?", default=None, help="气泡内显示的文字")
    parser.add_argument("bubble_type", nargs="?", 
                        choices=["浏览器弹泡旧规", "商店弹泡", "商店弹泡新规", "商店弹泡旧规", "浏览器弹泡新规"], 
                        help="气泡类型")
    parser.add_argument("theme", nargs="?", default=None, help="主题色")
    parser.add_argument("--text", dest="text_option", default=None, help="文案（旧方式）")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    parser.add_argument("--no-split", action="store_true", help="合并导出 icon 和气泡")
    parser.add_argument("--no-close", action="store_true", help="不显示关闭按钮")
    parser.add_argument("--icon-path", default=None, help="icon 图片路径")
    parser.add_argument("--icon-crop", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"),
                        default=None, help="icon 裁剪区域")
    parser.add_argument("--color-left", default=None, metavar="R,G,B", help="背景渐变左色")
    parser.add_argument("--text-color", default=None, metavar="R,G,B", help="文字颜色")
    parser.add_argument("--浏览器弹泡旧规", dest="use_browser_flag", action="store_true", 
                        help="浏览器弹泡旧规（旧方式）")
    parser.add_argument("--theme", dest="theme_option", default=None, help="主题色（旧方式）")
    args = parser.parse_args()

    # 解析文案（新方式优先：位置参数，其次旧方式：--text）
    final_text = args.text if args.text else args.text_option if args.text_option else None
    if not final_text:
        parser.error("请输入文案，例如：py scripts/generate_bubble.py '今天上班' 浏览器弹泡旧规 紫色")

    # 解析气泡类型（新方式优先：位置参数，其次旧方式：--浏览器弹泡旧规）
    # 商店弹泡新规：use_browser=False, use_close=True
    # 商店弹泡旧规：use_browser=False, use_close=False
    # 浏览器弹泡旧规：use_browser=True, use_close=True
    # 浏览器新规：use_browser=False, use_close=True, use_split=False (合并导出)
    use_browser = False
    use_close = True  # 默认
    use_split = True  # 默认分开导出
    
    if args.bubble_type == "浏览器弹泡旧规":
        use_browser = True
        use_close = True
    elif args.bubble_type == "商店弹泡新规":
        use_browser = False
        use_close = True
    elif args.bubble_type == "商店弹泡旧规":
        use_browser = False
        use_close = False
    elif args.bubble_type == "商店弹泡":
        use_browser = False
        use_close = True
    elif args.bubble_type == "浏览器弹泡新规":
        use_browser = False  # 使用商店新规的形状
        use_close = True     # 有关闭按钮
        use_split = False    # 默认合并导出 icon 和气泡
    
    # 兼容旧方式：--浏览器弹泡旧规
    if args.use_browser_flag:
        use_browser = True
        use_close = True

    # 解析主题色（位置参数优先，其次旧方式 --theme，最后默认蓝色）
    theme_name = args.theme if args.theme else "蓝色"
    if args.theme_option:
        theme_name = args.theme_option

    # 解析主题色数据
    theme_data = THEMES.get(theme_name, THEMES["蓝色"])
    grad_color = theme_data["grad"]
    text_color = theme_data["text"]

    # 命令行颜色覆盖主题色
    if args.color_left:
        try:
            grad_color = tuple(int(v.strip()) for v in args.color_left.split(","))
        except ValueError:
            parser.error("--color-left 格式错误，应为 R,G,B，例如 255,100,100")
    if args.text_color:
        try:
            text_color = tuple(int(v.strip()) for v in args.text_color.split(","))
        except ValueError:
            parser.error("--text-color 格式错误，应为 R,G,B，例如 130,20,77")

    # icon 参数
    icon_path = args.icon_path  # None 则 make_icon_image 内部使用全局 ICON_PATH
    icon_crop = tuple(args.icon_crop) if args.icon_crop else None  # None 则使用全局 ICON_CROP

    # 解析导出方式
    # 浏览器弹泡新规默认合并导出（不可通过 --no-split 切换）
    if args.bubble_type == "浏览器弹泡新规":
        use_split = False  # 强制合并
    else:
        use_split = not args.no_split
    # use_close 已在上面根据 bubble_type 设置，此处允许 --no-close 覆盖
    if args.no_close:
        use_close = False
    # 浏览器弹泡旧规默认有关闭按钮，除非显式指定 --no-close
    if use_browser:
        use_close = True  # 默认有关闭按钮

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else _SCRIPT_ROOT / f"output/bubble_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    scale_names = {1: "@100", 1.5: "@150", 2: "@200", 3: "@300"}
    if use_browser:
        prefix = "浏览器弹泡旧规-"
    elif args.bubble_type == "浏览器弹泡新规":
        prefix = "浏览器弹泡新规-"
    elif not use_close:
        prefix = "旧规-"
    else:
        prefix = "新规-"
    for scale in SCALES:
        if use_split:
            # 分开导出：先输出纯气泡（bg），再单独输出 icon
            img = make_bubble(final_text, scale, grad_color, text_color,
                              with_icon=use_browser, with_close=use_close,
                              icon_path=icon_path, icon_crop=icon_crop,
                              use_browser=use_browser)
            name = "{}bg-{}{}.png".format(prefix, final_text, scale_names[scale])
            path = out_dir / name
            img.save(path, "PNG")
            print("OK {}  ({}x{})".format(name, img.width, img.height))

            # 单独导出 icon（仅非浏览器弹泡）
            if not use_browser:
                try:
                    icon_canvas = make_icon_image(scale, icon_path=icon_path, icon_crop=icon_crop)
                    name = "{}icon-{}{}.png".format(prefix, final_text, scale_names[scale])
                    path = out_dir / name
                    icon_canvas.save(path, "PNG")
                    print("OK {}  ({}x{})".format(name, icon_canvas.width, icon_canvas.height))
                except Exception as e:
                    print("Warning: icon export error:", e)
        else:
            # 合并导出（--no-split）
            img = make_bubble(final_text, scale, grad_color, text_color,
                              with_icon=True, with_close=use_close,
                              icon_path=icon_path, icon_crop=icon_crop,
                              use_browser=use_browser)
            name = "{}bg-{}{}.png".format(prefix, final_text, scale_names[scale])
            path = out_dir / name
            img.save(path, "PNG")
            print("OK {}  ({}x{})".format(name, img.width, img.height))

    print("\nOutput directory: {}".format(out_dir.resolve()))


if __name__ == "__main__":
    main()
