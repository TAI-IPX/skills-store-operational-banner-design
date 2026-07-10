#!/usr/bin/env python3
"""快速重组：用已有素材 + 新布局参数重新合成 Banner，验证布局修正。"""
from __future__ import annotations
from pathlib import Path
from PIL import Image
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SRC = ROOT / "output" / "hd_20260701_105637"
OUT = SRC
CANVAS_W, CANVAS_H = 3840, 1200

BG = SRC / "bg_final.jpg"
CHAR_MAP = {
    "center": SRC / "tone_center.png",
    "left": SRC / "tone_left.png",
    "right": SRC / "tone_right.png",
}
TITLE = SRC / "title_art.png"

# 新布局参数（与 stage2_layout_prompt.py 修复后一致）
# left=1740-290=1450, center=1740, right=1740+290+420=2450
# height: center=0.82*1200=984, left=0.80*1200=960, right=0.85*1200=1020
# z_order: left=2, right=1, center=0
LAYOUT_PARAMS = [
    {"role": "left",   "x_center": 1450, "y_bottom": CANVAS_H, "height": 960,  "z_order": 2},
    {"role": "right",  "x_center": 2450, "y_bottom": CANVAS_H, "height": 1020, "z_order": 1},
    {"role": "center", "x_center": 1740, "y_bottom": CANVAS_H, "height": 984, "z_order": 0, "head_align_canvas_x": 1920},
]


def paste_char(canvas, char_rgba, lp: dict):
    cw, ch = char_rgba.size
    target_h = lp["height"]
    if ch < 1:
        return

    bbox = char_rgba.split()[3].getbbox()
    if bbox:
        left, top, right, bottom = bbox
        char_cw = right - left
        char_ch = bottom - top
        if char_ch > 0:
            scale = target_h / float(char_ch)
            char_center_x = (left + right) / 2.0
            char_bottom_y = float(bottom)
        else:
            scale = target_h / float(ch)
            char_center_x = cw / 2.0
            char_bottom_y = float(ch)
    else:
        scale = target_h / float(ch)
        char_center_x = cw / 2.0
        char_bottom_y = float(ch)

    for _ in range(14):
        new_w = max(1, int(round(cw * scale)))
        new_h = max(1, int(round(ch * scale)))
        resized = char_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)

        if lp.get("head_align_canvas_x") is not None:
            cx = lp["head_align_canvas_x"] - char_center_x * scale + new_w // 2
            x = int(round(cx - new_w // 2))
        else:
            x = int(round(lp["x_center"] - char_center_x * scale))
        y = int(round(lp["y_bottom"] - char_bottom_y * scale))

        if x >= 0 and y >= 0 and x + new_w <= CANVAS_W and y + new_h <= CANVAS_H:
            canvas.paste(resized, (x, y), resized)
            return
        scale *= 0.995

    new_w = max(1, int(round(cw * scale)))
    new_h = max(1, int(round(ch * scale)))
    resized = char_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = int(round(lp["x_center"] - char_center_x * scale))
    y = int(round(lp["y_bottom"] - char_bottom_y * scale))
    src_x = max(0, -x); src_y = max(0, -y)
    dst_x = max(0, x); dst_y = max(0, y)
    src_w = min(new_w - src_x, CANVAS_W - dst_x)
    src_h = min(new_h - src_y, CANVAS_H - dst_y)
    if src_w > 0 and src_h > 0:
        patch = resized.crop((src_x, src_y, src_x + src_w, src_y + src_h))
        canvas.paste(patch, (dst_x, dst_y), patch)


def main():
    bg = Image.open(BG).convert("RGBA")
    if bg.size != (CANVAS_W, CANVAS_H):
        bg = bg.resize((CANVAS_W, CANVAS_H), Image.Resampling.LANCZOS)

    print(f"角色映射:")  # debug info not important
    for role in ("center", "left", "right"):
        p = CHAR_MAP[role]
        if p.is_file():
            im = Image.open(p)
            ch_mode = getattr(im, 'mode', 'unknown')
            ch_size = getattr(im, 'size', (0,0))
            print(f"  {role}: {p.name} {ch_size} {ch_mode}")
        else:
            print(f"  {role}: 文件不存在 {p}")

    # 按 z_order 从大到小合成（远→近）
    for lp in sorted(LAYOUT_PARAMS, key=lambda x: x["z_order"], reverse=True):
        role = lp["role"]
        p = CHAR_MAP.get(role)
        if p and p.is_file():
            char_img = Image.open(p).convert("RGBA")
            paste_char(bg, char_img, lp)
            print(f"  贴角色 {role}: x={lp['x_center']} h={lp['height']} z={lp['z_order']}")
        else:
            print(f"  跳过角色 {role}: 文件不存在")

    # 跳过 title_art（不需要合成艺术字）

    out = OUT / "recomposite_check.jpg"
    bg.convert("RGB").save(str(out), "JPEG", quality=95)
    print(f"\n输出: {out}")


if __name__ == "__main__":
    main()
