#!/usr/bin/env python3
"""重新生成 title_art.png —— gpt-image-2 生图 + 饱和感知去白底 + 缩放 1080x328"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.request, urllib.error
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "output" / "hd_20260701_105637"
MAIN_TITLE = "七月开门红"
SUBTITLE = "领取拯救者周边专属好礼"

TITLE_ART_PROMPT = f""""{MAIN_TITLE}"游戏活动艺术字设计，副标题"{SUBTITLE}"

暖金+中国红风格，游戏宣传海报3D立体中文艺术字，
主标题大字突出居中，副标题小字在下方，
笔划清晰可辨，字形准确，有金属光泽或发光效果，
白色背景，无其他装饰物和角色，纯文字版式设计"""


def generate_via_gpt() -> Image.Image:
    key = os.environ.get("XINGCHENGGPT_API_KEY", "").strip()
    base = os.environ.get("XINGCHENGGPT_BASE_URL", os.environ.get("GOOGLE_GEMINI_BASE_URL", "https://api.centos.hk")).strip().rstrip("/")

    body = json.dumps({
        "model": "gpt-image-2",
        "prompt": TITLE_ART_PROMPT,
        "n": 1,
        "size": "1792x1024",
        "quality": "auto",
        "response_format": "b64_json",
    }).encode("utf-8")

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                f"{base}/v1/images/generations",
                data=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read().decode("utf-8"))
            b64 = data["data"][0]["b64_json"]
            img = Image.open(BytesIO(base64.b64decode(b64)))
            print(f"[regen] gpt-image-2 生成成功: {img.size} {img.mode}")
            return img
        except Exception as e:
            print(f"[regen] 尝试 {attempt}/3 失败: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError("gpt-image-2 所有重试均失败")


def remove_white_bg(img: Image.Image) -> Image.Image:
    """饱和感知去白底：亮度+饱和度双判断，保护彩色文字笔划"""
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    saturation = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)

    lo, hi = 220.0, 245.0
    white_ratio = np.clip((brightness - lo) / (hi - lo), 0.0, 1.0)
    sat_factor = np.clip(1.0 - saturation / 40.0, 0.0, 1.0)
    alpha_reduce = white_ratio * sat_factor

    orig_a = arr[:, :, 3]
    arr[:, :, 3] = np.clip(orig_a * (1.0 - alpha_reduce), 0, 255)

    result = Image.fromarray(arr.astype(np.uint8), "RGBA")
    print(f"[regen] 去白底完成")
    return result


def scale_to_canvas(img: Image.Image) -> Image.Image:
    """缩放入 1080x328，居中"""
    CANVAS = (1080, 328)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))

    bbox = img.split()[3].getbbox()
    if bbox:
        img = img.crop(bbox)

    iw, ih = img.size
    scale = min(CANVAS[0] * 0.95 / iw, CANVAS[1] * 0.95 / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (CANVAS[0] - nw) // 2
    y = (CANVAS[1] - nh) // 2
    canvas.paste(resized, (x, y), resized)
    print(f"[regen] 缩放到 {CANVAS}")
    return canvas


def main():
    print(f"[regen] Prompt:\n{TITLE_ART_PROMPT}\n")
    raw = generate_via_gpt()
    raw.save(OUT_DIR / "_title_raw.png")

    no_bg = remove_white_bg(raw)
    no_bg.save(OUT_DIR / "_title_no_bg.png")

    final = scale_to_canvas(no_bg)
    final.save(OUT_DIR / "title_art.png")
    print(f"[regen] 已保存 {OUT_DIR / 'title_art.png'}")

    # 深色底预览
    dark = Image.new("RGBA", final.size, (30, 30, 30, 255))
    dark.paste(final, (0, 0), final)
    dark.save(OUT_DIR / "_title_dark_preview.png")
    print(f"[regen] 深色预览已保存")


if __name__ == "__main__":
    main()
