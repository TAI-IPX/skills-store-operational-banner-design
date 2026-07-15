#!/usr/bin/env python3
"""
手机商店悬浮窗 249x198 三层合成脚本

结构：
1. 底层圆形：圆心在画布中心 (124, 99)，半径适配画布高度（保证整圆完整显示）
   填充：从主体提取主色 + Gemini Vision 分析 -> 径向渐变(中心主色 -> 边缘亮色)
2. 中层主体：透明 PNG，圆心对齐圆形圆心，底部被圆形裁切、顶部可超出
3. 上层艺术字：透明 PNG，GPT 生成 -> BiRefNet 抠图，位于圆形下半部，水平居中

支持：
- 主体/艺术字非透明时自动 BiRefNet 抠图
- 艺术字文本描述 -> 项目后端 (moxingpt/xingchengpt/packygpt) -> BiRefNet 抠图
- Gemini Vision 分析主体图（风格/色彩/主体描述 -> 优化配色与艺术字 prompt）
- 单独调用或通过 run_all_presets.py 分组调用
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "banner-background-from-image" / "scripts"))

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

# ---------- 加载 .env ----------
def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_dotenv()

# ---------- 常量 ----------
CANVAS_W, CANVAS_H = 249, 198
CENTER = (CANVAS_W // 2, CANVAS_H // 2)          # (124, 99)
RADIUS = int(CANVAS_H * 0.35)                   # 69px — 直径≤画布高70%，整圆完整可见
SUBJECT_SCALE = 1.0                             # 主体高度 = 圆直径 (240px)
TEXT_ART_Y_RATIO = 0.65                         # 圆心y + 半径 * 0.65


# ---------- 工具函数 ----------
def extract_dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """从非透明像素取主色（中位数更稳健）"""
    arr = np.array(img.convert("RGBA"))
    mask = arr[:, :, 3] > 10
    if not mask.any():
        return (30, 144, 255)  # 默认蓝
    rgb = arr[mask, :3]
    return tuple(map(int, np.median(rgb, axis=0)))


def make_radial_gradient(w: int, h: int, cx: int, cy: int, r: int, center_color: tuple, edge_color: tuple) -> Image.Image:
    """生成径向渐变圆形（RGBA），圆外透明"""
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for radius in range(r, 0, -1):
        ratio = radius / r
        color = tuple(int(center_color[i] * ratio + edge_color[i] * (1 - ratio)) for i in range(3))
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color + (255,))
    return grad


def circle_mask(w: int, h: int, cx: int, cy: int, r: int) -> Image.Image:
    """返回同尺寸单通道圆形蒙版（圆内255，外0）"""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([cx - r, cy - r, cx + r, cx + r], fill=255)
    return mask


def feathered_circle_mask(w: int, h: int, cx: int, cy: int, r: int, feather: int = 12) -> Image.Image:
    """
    返回带羽化边缘的圆形蒙版（单通道 L）。
    - 圆内 r-feather 以内：255（完全不透明）
    - r-feather 到 r 之间：线性渐变 255→0
    - 圆外：0
    """
    import math
    mask_arr = np.zeros((h, w), dtype=np.float32)
    y_idx, x_idx = np.ogrid[:h, :w]
    dist = np.sqrt((x_idx - cx) ** 2 + (y_idx - cy) ** 2)

    inner_r = max(1, r - feather)
    # 内部完全不透明
    mask_arr[dist <= inner_r] = 1.0
    # 羽化区域线性过渡
    feather_zone = (dist > inner_r) & (dist <= r)
    if feather_zone.any():
        mask_arr[feather_zone] = 1.0 - (dist[feather_zone] - inner_r) / feather
    # 外部保持 0
    return Image.fromarray((mask_arr * 255).astype(np.uint8), mode="L")


def auto_matte_birefnet(input_path: Path, output_path: Path) -> bool:
    """调用 BiRefNet 抠图，成功返回 True"""
    try:
        # 复用项目已有的 BiRefNet 模块
        from birefnet_matting import load_birefnet_matting, extract_alpha_pil
        model = load_birefnet_matting()
        img = Image.open(input_path).convert("RGB")
        alpha = extract_alpha_pil(img, model=model)
        rgba = img.convert("RGBA")
        rgba.putalpha(alpha)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rgba.save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"[warn] BiRefNet 抠图失败: {e}", file=sys.stderr)
        return False


def luminance_matte(img: Image.Image) -> Image.Image:
    """亮度蒙版兜底：自动检测底色深浅，反相做 alpha"""
    gray = img.convert("L")
    avg = np.array(gray).mean()
    alpha = gray.point(lambda x: 255 - x if avg > 128 else x)
    rgba = img.convert("RGBA")
    rgba.putalpha(alpha)
    return rgba


def ensure_transparent_png(input_path: Path, work_dir: Path) -> Path:
    """若已有透明通道直接返回；否则尝试 BiRefNet -> 亮度蒙版"""
    img = Image.open(input_path)
    if img.mode == "RGBA" and img.getchannel("A").getbbox():
        return input_path

    out = work_dir / f"{input_path.stem}_rgba.png"
    if auto_matte_birefnet(input_path, out):
        return out

    # 兜底
    rgba = luminance_matte(img)
    rgba.save(out, "PNG")
    print(f"[info] 使用亮度蒙版兜底: {out}", file=sys.stderr)
    return out


def crop_blank_and_scale(img: Image.Image, max_w: int, max_h: int, center_x: float, center_y: float) -> tuple[Image.Image, int, int]:
    """
    裁切透明边距，等比缩放至 max_w x max_h 内，图像中心对齐到 (center_x, center_y)。
    返回: (裁切后的图, 左上角 x, 左上角 y)
    """
    # 1. 裁切透明边距
    alpha = np.array(img.split()[-1])
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if rows.any() and cols.any():
        r0, r1 = np.where(rows)[0][[0, -1]]
        c0, c1 = np.where(cols)[0][[0, -1]]
        img = img.crop((c0, r0, c1 + 1, r1 + 1))

    # 2. 等比缩放到安全区内
    iw, ih = img.size
    scale = min(max_w / iw, max_h / ih, 1.0)
    new_w = max(1, int(iw * scale))
    new_h = max(1, int(ih * scale))
    if (new_w, new_h) != (iw, ih):
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 3. 计算左上角位置（图像中心对齐到安全区中心）
    left = int(round(center_x - new_w / 2))
    top = int(round(center_y - new_h / 2))

    return img, left, top


def render_text_art_pil(text: str, max_w: int, max_h: int, out_path: Path) -> Path:
    """PIL 简易渲染：白字 + 黑描边 -> 透明底 PNG（兜底方案，非书法效果）"""
    from PIL import ImageFont
    # 尝试加载微软雅黑 Bold
    font_path = None
    for p in [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", "/System/Library/Fonts/PingFang.ttc"]:
        if Path(p).exists():
            font_path = p
            break
    if not font_path:
        font_path = ImageFont.load_default()

    # 字号自适应
    font_size = 60
    font = ImageFont.truetype(font_path, font_size) if font_path != ImageFont.load_default() else ImageFont.load_default()

    # 计算文本尺寸
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 缩放以适配 max_w, max_h
    scale = min(max_w / tw, max_h / th, 1.0)
    font_size = max(12, int(font_size * scale))
    font = ImageFont.truetype(font_path, font_size) if font_path != ImageFont.load_default() else ImageFont.load_default()

    # 重新计算
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 创建透明画布
    pad = 8
    canvas = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # 描边：画 4 个方向偏移的黑字
    for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]:
        draw.text((pad + dx, pad + dy), text, font=font, fill=(0, 0, 0, 255))
    # 主字：白色
    draw.text((pad, pad), text, font=font, fill=(255, 215, 0, 255))  # 金色

    # 裁切透明边
    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG")
    return out_path


# ---------- Gemini Vision 分析 ----------
def _resolve_vision_backend() -> dict:
    """返回可用的 Vision 后端配置：{'key': str, 'base': str, 'models': [str]} 或空字典"""
    # 1) MoxinGemini
    key = os.environ.get("MOXINGEMINI_API_KEY", "").strip()
    if key:
        base = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").strip().rstrip("/")
        raw = os.environ.get("MOXINGEMINI_VISION_MODEL", "gemini-2.5-flash").strip()
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return {"key": key, "base": base, "models": models, "name": "moxingemini"}
    # 2) MicuGemini
    key = os.environ.get("MICUGEMINI_API_KEY", "").strip()
    if key:
        base = os.environ.get("MICUGEMINI_BASE_URL", "https://api.centos.hk").strip().rstrip("/")
        raw = os.environ.get("MICUGEMINI_MODEL", "gemini-3-pro-image-preview").strip()
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return {"key": key, "base": base, "models": models, "name": "micugemini"}
    # 3) 标准 Gemini
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        base = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip().rstrip("/")
        raw = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash").strip()
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return {"key": key, "base": base, "models": models, "name": "gemini"}
    return {}


def _analyze_subject_vision(subject_path: Path) -> dict:
    """
    用 Gemini Vision 分析主体图 -> 返回风格/色彩/描述。
    返回 {'style': str, 'colors': list[str], 'description': str, 'mood': str}，失败则返回空字典。
    """
    be = _resolve_vision_backend()
    if not be:
        return {}

    prompt = (
        "Analyze this image and return a JSON object with these keys:\n"
        '"style": the visual style (one sentence in Chinese)\n'
        '"colors": an array of 3-5 dominant hex colors like "#FF6B35"\n'
        '"description": brief description of the main subject (one sentence in Chinese)\n'
        '"mood": the atmosphere/mood (one sentence in Chinese)\n'
        "Return ONLY the JSON object, no markdown fences."
    )

    with open(subject_path, "rb") as f:
        raw = f.read()
    mime = "image/png" if subject_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    for model in be["models"]:
        try:
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]}],
                "max_tokens": 1024,
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {be['key']}",
            }
            api_url = f"{be['base']}/v1/chat/completions"
            req = urllib.request.Request(api_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not content:
                continue

            # 解析 JSON（可能包裹在 markdown 代码块中）
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            result = json.loads(content)
            return {
                "style": result.get("style", ""),
                "colors": result.get("colors", []),
                "description": result.get("description", ""),
                "mood": result.get("mood", ""),
            }
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                print(f"[floating_window] Vision model '{model}' not available (HTTP {e.code}), trying next...", file=sys.stderr)
                continue
            print(f"[floating_window] Vision attempt failed with model '{model}': {e}", file=sys.stderr)
        except Exception as e:
            print(f"[floating_window] Vision attempt failed with model '{model}': {e}", file=sys.stderr)

    print(f"[floating_window] Vision 分析失败 ({be['name']}): all models exhausted", file=sys.stderr)
    return {}


def _detect_subject_split(subject_path: Path) -> dict:
    """
    用 Gemini Vision 理解主体结构，返回分界比例 + 主体在图片内的边界框。
    返回值: {"type": str, "ratio": float, "bbox": {x,y,w,h}, "key_parts": str}
    失败返回空字典。
    - bbox: 归一化 0.0~1.0，x/y/w/h 描述主体在图片内的实际位置
    - key_parts: 关键部位描述（如 "head at y≈0.1, box rim at y≈0.48, base at y≈0.9"）
    """
    be = _resolve_vision_backend()
    if not be:
        return {}

    prompt = (
        "Look at this image. A subject will be placed on a circular icon background.\n"
        "1. Subject type: human, animal, cartoon_character, object, or logo.\n"
        '2. "bbox": normalized bounding box of the main subject in this image (x, y, w, h from 0.0 to 1.0).\n'
        '   Only include the actual subject pixels, not transparent background padding.\n'
        '3. "split_ratio": from top of subject (0.0) to bottom (1.0), where does the '
        '"upper part" (that should be free) transition to "lower part" (that sits inside the circle)?\n'
        "   Human: waist ~0.55, chest ~0.35. Animal: below-head ~0.30. Object: rim/border ~0.40.\n"
        '4. "key_parts": briefly describe key body parts and their approximate y-ratio.\n'
        'Return ONLY a JSON object: '
        '{"subject_type":"...","split_ratio":0.45,"bbox":{"x":0.1,"y":0.05,"w":0.8,"h":0.9},'
        '"key_parts":"head y≈0.1, waist y≈0.5, feet y≈0.9"}'
    )

    with open(subject_path, "rb") as f:
        raw = f.read()
    mime = "image/png" if subject_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    for model in be["models"]:
        try:
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]}],
                "max_tokens": 512,
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {be['key']}",
            }
            api_url = f"{be['base']}/v1/chat/completions"
            req = urllib.request.Request(api_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not content:
                continue

            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)
            result = json.loads(content)
            bbox = result.get("bbox", {})
            return {
                "type": result.get("subject_type", "unknown"),
                "ratio": max(0.05, min(0.95, float(result.get("split_ratio", 0.45)))),
                "bbox": {
                    "x": float(bbox.get("x", 0)),
                    "y": float(bbox.get("y", 0)),
                    "w": max(0.1, float(bbox.get("w", 1))),
                    "h": max(0.1, float(bbox.get("h", 1))),
                },
                "key_parts": result.get("key_parts", ""),
            }
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                continue
        except Exception:
            pass

    print(f"[floating_window] Subject split detection failed ({be['name']})", file=sys.stderr)
    return {}


def _detect_subject_split_birefnet(subject_path: Path) -> dict:
    """
    Vision 失败时的 BiRefNet 兜底：跑一次主体抠图，从 alpha 计算真实 bbox + split_ratio。
    返回同格式 dict：{"type", "ratio", "bbox", "key_parts"}，失败返回 {}。
    """
    try:
        # 延迟导入避免未安装时直接报错
        from .claude.skills.banner_background_from_image.scripts.birefnet_matting import extract_alpha_pil, load_birefnet_matting
    except ImportError:
        # 尝试相对路径导入（项目根目录下运行时）
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".claude" / "skills" / "banner-background-from-image" / "scripts"))
            from birefnet_matting import extract_alpha_pil, load_birefnet_matting
        except ImportError:
            print("[floating_window] BiRefNet fallback: module not available", file=sys.stderr)
            return {}

    try:
        img = Image.open(subject_path).convert("RGBA")
        model = load_birefnet_matting()
        alpha = extract_alpha_pil(img, model=model)
        # alpha 是 0-255，转为 numpy 计算 bbox
        arr = np.array(alpha)
        # 阈值：>10 视为前景
        rows = np.any(arr > 10, axis=1)
        cols = np.any(arr > 10, axis=0)
        if not rows.any() or not cols.any():
            print("[floating_window] BiRefNet fallback: empty alpha", file=sys.stderr)
            return {}

        r0, r1 = np.where(rows)[0][[0, -1]]
        c0, c1 = np.where(cols)[0][[0, -1]]
        h, w = arr.shape

        # 归一化 bbox
        bbox = {
            "x": float(c0) / w,
            "y": float(r0) / h,
            "w": float(c1 - c0 + 1) / w,
            "h": float(r1 - r0 + 1) / h,
        }

        # split_ratio：主体垂直中心相对于主体顶部的比例
        # 垂直中心 = (r0 + r1/2) / h，即主体中心在整图中的 y 归一化
        # split_ratio = (center_y - r0/h) / (r1/h - r0/h) = 0.5（主体中心）
        # 我们用主体中心作为分界，对应 split_ratio=0.5
        # 也可以用更保守的值（如 0.4）避免切到头部
        split_ratio = 0.5

        # 推断类型：根据宽高比
        aspect = bbox["w"] / bbox["h"] if bbox["h"] > 0 else 1
        if aspect > 1.3:
            stype = "object_wide"
        elif aspect < 0.7:
            stype = "object_tall"
        else:
            stype = "object"

        return {
            "type": stype,
            "ratio": split_ratio,
            "bbox": bbox,
            "key_parts": f"bbox_center_y={bbox['y'] + bbox['h']/2:.2f}",
        }
    except Exception as e:
        print(f"[floating_window] BiRefNet fallback error: {e}", file=sys.stderr)
        return {}


def crop_blank_and_scale(art: Image.Image, safe_w: int, safe_h: int, center_x: float, center_y: float) -> tuple[Image.Image, int, int]:
    """
    裁切透明空白、等比缩放到安全区、返回(处理后的图, 放置x, 放置y)
    """
    # 1. 检测非透明像素边界
    arr = np.array(art)
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 0, axis=1)
    cols = np.any(alpha > 0, axis=0)
    if not rows.any() or not cols.any():
        return art, 0, 0
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    art = art.crop((c0, r0, c1 + 1, r1 + 1))

    # 2. 等比缩放适应安全区
    scale = min(safe_w / art.width, safe_h / art.height)
    new_w = max(1, int(art.width * scale))
    new_h = max(1, int(art.height * scale))
    art = art.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 3. 计算放置位置：图像中心对齐安全区中心
    x = int(center_x - new_w / 2)
    y = int(center_y - new_h / 2)
    return art, x, y


def _draw_split_preview(subject_rgba: Image.Image, split_info: dict, output_path: Path) -> None:
    """
    在主体 RGBA 图上绘制 split 预览：红色方框 = 主体 bbox，红色横线 = split_y。
    保存到 output_path。
    """
    preview = subject_rgba.copy()
    # 铺白底以便看清
    bg = Image.new("RGBA", preview.size, (255, 255, 255, 255))
    bg.alpha_composite(preview)
    draw = ImageDraw.Draw(bg)

    w, h = preview.size
    bbox = split_info.get("bbox", {"x": 0, "y": 0, "w": 1, "h": 1})
    ratio = split_info.get("ratio", 0.45)

    # 红色框出主体 bbox
    rx = int(bbox["x"] * w)
    ry = int(bbox["y"] * h)
    rw = int(bbox["w"] * w)
    rh = int(bbox["h"] * h)
    draw.rectangle([rx, ry, rx + rw, ry + rh], outline=(255, 0, 0, 255), width=2)

    # 红色横线标注 split_y
    split_px = int(ratio * h)
    draw.line([(0, split_px), (w, split_px)], fill=(255, 0, 0, 255), width=2)

    # 标注文字
    label = f"split_ratio={ratio:.2f}  type={split_info.get('type','?')}"
    draw.text((4, 2), label, fill=(255, 0, 0, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(output_path, "PNG")
    print(f"[floating_window] split preview: {output_path}", flush=True)


# ---------- 艺术字生成 ----------
def _build_text_art_prompt(title: str, vision_info: dict | None = None) -> str:
    """构建艺术字生成 prompt，融合 Vision 分析风格。
    铁律：禁止白色/近白色填充、禁止重复文字、必须透明背景。
    """
    base = (
        f'Stylized Chinese title art text: "{title}". '
        "Render the text EXACTLY ONCE as a single line — do NOT duplicate, repeat, "
        "shadow-copy, or show multiple versions of the text. "
        "Bold 3D lettering with vivid saturated colors: gold, orange, red, or colorful gradient. "
        "NEVER use white or near-white (#fff, #eee, light grey) for text fill, stroke, or glow. "
        "Strong glowing outline in a complementary dark or saturated color. "
        "Pure transparent background — absolutely no white fill, no background rectangle, "
        "no white glow, no shadow copy. Isolated text characters only."
    )
    if vision_info:
        style = vision_info.get("style", "")
        mood = vision_info.get("mood", "")
        colors = vision_info.get("colors", [])
        if colors:
            color_hint = ", ".join(colors[:3])
            base += f" Use these colors from the subject palette (avoid white): {color_hint}."
        if style:
            base += f" Match the visual style: {style}."
        if mood:
            base += f" Atmosphere: {mood}."
    return base


def _generate_text_art_t2i(prompt: str, out_path: Path, key: str, base: str, model_str: str = "gpt-image-2") -> bool:
    """调用项目后端生成艺术字图片，支持逗号分隔多模型按序重试，成功返回 True"""
    models = [m.strip() for m in model_str.split(",") if m.strip()]
    for model in models:
        img_bytes = None
        # 尝试使用 moxingpt_images_api（如果可用且 base 匹配 moxin）
        if "moxin" in base:
            try:
                from moxingpt_images_api import generate_image as _moxin_t2i
                out = _moxin_t2i(prompt, str(out_path), model=model)
                if out and Path(str(out)).is_file():
                    print(f"[floating_window] text-art moxin {model} success", flush=True)
                    return True
            except Exception as e:
                print(f"[floating_window] moxin_images_api {model}: {e}", file=sys.stderr)

        # 备选：标准 OpenAI 兼容 /v1/images/generations
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "quality": "auto",
            "response_format": "b64_json",
        }).encode()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        url = f"{base.rstrip('/')}/v1/images/generations"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=180) as resp:
                    result = json.loads(resp.read())
                b64 = None
                for item in (result.get("data") or []):
                    b64 = item.get("b64_json")
                    if b64: break
                    img_url = item.get("url")
                    if img_url:
                        img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(img_req, timeout=60) as r:
                            b64 = base64.standard_b64encode(r.read()).decode("ascii")
                        break
                if b64:
                    img = Image.open(BytesIO(base64.b64decode(b64)))
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    img.save(out_path, "PNG")
                    print(f"[floating_window] text-art t2i {model} success", flush=True)
                    return True
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    break  # model not available on this endpoint
                if attempt < 1:
                    time.sleep(4)
            except Exception:
                if attempt < 1:
                    time.sleep(2)
    return False


def _birefnet_extract_text(image_path: Path) -> Path:
    """
    对艺术字图运行 BiRefNet 抠图（子进程调用 extract_subject_birefnet.py，与 HD 管线一致）。
    使用 --alpha-threshold 0.3 --no-binarize 保留柔和笔划边缘。
    BiRefNet 失败时保留原图（不中断流程）。
    """
    extract_script = ROOT / "scripts" / "extract_subject_birefnet.py"
    if not extract_script.is_file():
        print(f"[floating_window] BiRefNet script not found: {extract_script}", file=sys.stderr)
        return image_path

    tmp = image_path.parent / f"_br_{image_path.stem}.png"
    try:
        r = subprocess.run(
            [sys.executable, str(extract_script),
             str(image_path), "--output", str(tmp),
             "--alpha-threshold", "0.3",
             "--no-binarize"],
            capture_output=True, timeout=120,
        )
        if r.returncode == 0 and tmp.is_file():
            import shutil
            shutil.move(str(tmp), str(image_path))
            print(f"[floating_window] BiRefNet 抠字完成: {image_path.name}", flush=True)
        else:
            print(f"[floating_window] BiRefNet 抠字失败(rc={r.returncode})，保留原图", file=sys.stderr)
    except Exception as e:
        print(f"[floating_window] BiRefNet 抠字异常: {e}", file=sys.stderr)
    finally:
        try: tmp.unlink(missing_ok=True)
        except: pass
    return image_path


def generate_title_art_from_prompt(prompt: str, out_path: Path) -> Path:
    """
    文本描述 -> Art Text 透明 PNG
    优先：项目后端 (moxingpt > xingchengpt > packygpt) t2i -> BiRefNet 抠图
    兜底：PIL 简易渲染
    """
    work = out_path.parent
    work.mkdir(parents=True, exist_ok=True)

    # 后端列表：(name, env_key_prefix, base_url, model)
    backends = [
        ("moxingpt", "MOXINGPT", "https://www.moxin.studio", "gpt-image-2-base64"),
        ("xingchengpt", "XINGCHENGGPT", "https://api.centos.hk", "gpt-image-2"),
        ("packygpt", "PACKYGPT", "https://www.packyapi.com", "gpt-image-2"),
    ]

    for name, prefix, url, model in backends:
        key = os.environ.get(f"{prefix}_API_KEY", "").strip()
        if not key:
            continue
        base = os.environ.get(f"{prefix}_BASE_URL", url).strip()
        model_env = os.environ.get(f"{prefix}_MODEL", model).strip()
        raw_path = work / f"_text_art_raw_{name}.png"
        if _generate_text_art_t2i(prompt, raw_path, key, base, model_env):
            print(f"[floating_window] text art generated via {name}", flush=True)
            try:
                _birefnet_extract_text(raw_path)
            except Exception as e:
                print(f"[floating_window] BiRefNet failed, using raw: {e}", file=sys.stderr)
            raw_path.rename(out_path)
            return out_path

    # 兜底：PIL 渲染
    print("[floating_window] 所有后端不可用，回退 PIL 渲染", file=sys.stderr)
    import re
    text = re.sub(r'[，。！？、；：\u201c\u201d\u2018\u2019\s]+$', '', prompt)
    text = re.split(r'[，。！？、；：\s]', text)[-1]
    if not text:
        text = "游戏中心"
    return render_text_art_pil(text, int(RADIUS * 2 * 0.8), RADIUS, out_path)


# ---------- 主合成 ----------
def compose(
    subject_path: Path,
    output_path: Path,
    text_art_path: Path | None = None,
    text_art_prompt: str | None = None,
) -> None:
    work = output_path.parent / "_work_nav"
    work.mkdir(parents=True, exist_ok=True)

    # 0. Gemini Vision 分析主体图（风格/色彩/描述）
    vision_info = _analyze_subject_vision(subject_path)
    if vision_info:
        print(f"[floating_window] Vision: style={vision_info.get('style','')[:60]}...", flush=True)

    # 1. 确保主体透明 PNG
    subj_rgba_path = ensure_transparent_png(subject_path, work)
    subject = Image.open(subj_rgba_path).convert("RGBA")

    # 2. 提取主色做圆形渐变（Vision 优先，其次中位数）
    if vision_info and vision_info.get("colors"):
        # 取 Vision 推荐的前两个颜色
        colors = vision_info["colors"]
        if len(colors) >= 2:
            dom_color = tuple(int(colors[0].lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
            edge_color = tuple(int(colors[1].lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
        else:
            dom_color = tuple(int(colors[0].lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
            edge_color = tuple(min(255, int(c * 1.3)) for c in dom_color)
    else:
        dom_color = extract_dominant_color(subject)
        edge_color = tuple(min(255, int(c * 1.3)) for c in dom_color)

    # 3. 画底层圆形
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    circle_grad = make_radial_gradient(CANVAS_W, CANVAS_H, *CENTER, RADIUS, dom_color, edge_color)
    canvas.alpha_composite(circle_grad)

    # 4. Gemini 检测主体结构（bbox + split_ratio）
    split_info = _detect_subject_split(subject_path)
    if not split_info:
        print("[floating_window] Vision split failed, trying BiRefNet fallback...", flush=True)
        # Vision 失败时，用 BiRefNet 抠图得到的 alpha 计算真实 bbox
        split_info = _detect_subject_split_birefnet(subject_path)
    if not split_info:
        split_info = {"type": "unknown", "ratio": 0.45, "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    split_ratio = split_info.get("ratio", 0.45)
    stype = split_info.get("type", "?")
    key_parts = split_info.get("key_parts", "")
    print(f"[floating_window] Subject: {stype}, ratio={split_ratio:.2f}, parts=({key_parts[:60]})", flush=True)

    # Debug: 在主体图上绘制 split 预览（红色框 = bbox，红色横线 = split_y）
    # 这里用的是 BiRefNet 抠图后的原始尺寸 subject（尚未画布缩放）
    _draw_split_preview(subject, split_info, work / "_split_preview_before.png")

    # 5. tight-crop 去透明边距（防止原图含大量透明边距导致 scale 极小，如 8192×8192 的 PNG）
    arr_tc = np.array(subject)
    alpha_tc = arr_tc[:, :, 3]
    rows_tc = np.any(alpha_tc > 10, axis=1)
    cols_tc = np.any(alpha_tc > 10, axis=0)
    if rows_tc.any() and cols_tc.any():
        r0_tc, r1_tc = np.where(rows_tc)[0][[0, -1]]
        c0_tc, c1_tc = np.where(cols_tc)[0][[0, -1]]
        subject = subject.crop((c0_tc, r0_tc, c1_tc + 1, r1_tc + 1))
        print(f"[floating_window] tight-crop: {arr_tc.shape[1]}x{arr_tc.shape[0]} → {subject.width}x{subject.height}", flush=True)

    # 自适应缩放：根据主体宽高比选择约束轴，确保主体不过度超出画布
    # 主体 bbox 中心对齐圆心，底部被圆形遮罩裁切，顶部自由溢出
    target_h_cap = CANVAS_H  # 最大高度 = 画布高
    target_h_floor = int(RADIUS * 1.6)  # ~110px 下限

    aspect = subject.width / subject.height
    if aspect >= 1.0:
        # 宽图/方图：以宽度为约束轴（两侧各允许溢出 20px）
        target_w = CANVAS_W + 40
        scale = target_w / subject.width
        new_w = target_w
        new_h = max(1, int(subject.height * scale))
        # 宽图高度也要在合理范围内
        if new_h > target_h_cap:
            scale = target_h_cap / subject.height
            new_h = target_h_cap
            new_w = max(1, int(subject.width * scale))
        elif new_h < target_h_floor:
            scale = target_h_floor / subject.height
            new_h = target_h_floor
            new_w = max(1, int(subject.width * scale))
    else:
        # 高图/竖图：以高度为约束轴
        target_h = max(target_h_floor, min(target_h_cap, int(RADIUS * 2 * 1.2)))
        scale = target_h / subject.height
        new_h = target_h
        new_w = max(1, int(subject.width * scale))

    subject = subject.resize((new_w, new_h), Image.Resampling.LANCZOS)
    print(f"[floating_window] aspect={aspect:.2f}, scale={scale:.3f}, resized={new_w}x{new_h}", flush=True)

    # 定位：主体 bbox 中心对齐圆心，水平居中，垂直居中
    # 底部做 alpha 渐变淡出（不依赖圆形遮罩），顶部自由展示
    subj_x = CENTER[0] - new_w // 2
    subj_y = CENTER[1] - new_h // 2

    subj_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    subj_layer.paste(subject, (subj_x, subj_y), subject)

    # Debug 预览
    _d = subj_layer.copy()
    _dbg_draw = ImageDraw.Draw(_d)
    _dbg_bg = Image.new("RGBA", (CANVAS_W, CANVAS_H), (255, 255, 255, 255))
    _dbg_bg.alpha_composite(_d)
    _dbg_bg.save(work / "_split_preview_on_canvas.png", "PNG")

    # split_y：将 split_ratio 映射到缩放后主体在画布上的像素位置
    # split_ratio=0: 主体顶端, =1: 主体底端
    split_y_raw = subj_y + int(new_h * split_ratio)
    # 夹在圆心 ± RADIUS//2 范围内，防止极端值
    split_y = max(CENTER[1] - RADIUS // 2, min(CENTER[1] + RADIUS // 2, split_y_raw))
    split_y = max(1, min(CANVAS_H - 2, split_y))

    # 圆形底部
    circle_bottom = CENTER[1] + RADIUS  # 99 + 69 = 168

    subj_arr = np.array(subj_layer)
    h, w = subj_arr.shape[:2]

    # === 渐变遮罩：只作用于圆外区域 ===
    # 圆内保持完全不透明，圆外 y=74-142 区间渐变淡出
    circle_m = np.array(circle_mask(CANVAS_W, CANVAS_H, *CENTER, RADIUS), dtype=np.float32) / 255.0
    
    # 1. 渐变遮罩：y < 74 = 1.0, y = 74-142 = 渐变 1.0→0, y > 142 = 0
    gradient = np.zeros((h, w), dtype=np.float32)
    fade_start, fade_end = 74, 142
    gradient[:fade_start, :] = 1.0  # y < 74 = 1.0
    grad = np.linspace(1.0, 0.0, fade_end - fade_start + 1, dtype=np.float32)
    gradient[fade_start:fade_end + 1, :] = grad[:, None]
    # y > 142 保持 0（已初始化为 0）

    # 2. 圆形遮罩：用距离公式严格判定（圆内 = 1.0，圆外/边界 = 0）
    cy_arr, cx_arr = np.ogrid[:h, :w]
    dist_arr = np.sqrt((cx_arr - CENTER[0])**2 + (cy_arr - CENTER[1])**2)
    circle_mask_arr = np.where(dist_arr < RADIUS, 1.0, 0.0)

    # 3. 合并：圆内保持 1.0，圆外应用渐变
    final_mask = np.where(circle_mask_arr == 1.0, 1.0, gradient)

    # 4. y > fade_end 圆外强制置 0（修复左下角主体露出问题）
    final_mask[fade_end + 1:, :] = circle_mask_arr[fade_end + 1:, :]
    
    # 4. 应用 mask 到 alpha 通道
    subj_arr[:, :, 3] = (subj_arr[:, :, 3].astype(np.float32) * final_mask).astype(np.uint8)
    subj_layer = Image.fromarray(subj_arr, "RGBA")

    # Debug: 保存应用 mask 后的主体层
    subj_layer.save(work / "_split_preview_subj_masked.png", "PNG")
    print(f"[floating_window] fade={fade_start}~{fade_end} (outside circle only)", flush=True)

    canvas.alpha_composite(subj_layer)

    # 5. 贴艺术字
    if text_art_prompt and not text_art_path:
        enriched_prompt = _build_text_art_prompt(text_art_prompt, vision_info)
        text_art_path = work / "title_art.png"
        generate_title_art_from_prompt(enriched_prompt, text_art_path)
        print(f"[floating_window] 艺术字 prompt: {enriched_prompt[:100]}...", flush=True)

    if text_art_path:
        art_rgba_path = ensure_transparent_png(text_art_path, work)
        art = Image.open(art_rgba_path).convert("RGBA")

        # 艺术字安全区：x=40-209, y=126-179
        ART_SAFE_X_MIN, ART_SAFE_X_MAX = 40, 209
        ART_SAFE_Y_MIN, ART_SAFE_Y_MAX = 126, 179
        ART_SAFE_CENTER_X = (ART_SAFE_X_MIN + ART_SAFE_X_MAX) / 2  # 124.5
        ART_SAFE_CENTER_Y = (ART_SAFE_Y_MIN + ART_SAFE_Y_MAX) / 2  # 152.5
        ART_SAFE_W = ART_SAFE_X_MAX - ART_SAFE_X_MIN  # 169
        ART_SAFE_H = ART_SAFE_Y_MAX - ART_SAFE_Y_MIN  # 53

        # 裁切空白、等比缩放、中心对齐安全区
        art, art_x, art_y = crop_blank_and_scale(art, ART_SAFE_W, ART_SAFE_H, ART_SAFE_CENTER_X, ART_SAFE_CENTER_Y)

        art_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        art_layer.paste(art, (art_x, art_y), art)
        canvas.alpha_composite(art_layer)

    # 6. 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"[output] {output_path}")


# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(description="手机商店悬浮窗 249x198 合成")
    parser.add_argument("--subject", "-S", required=True, help="主体图片路径（自动抠图）")
    parser.add_argument("--text-art", "-T", default=None, help="艺术字透明 PNG 路径")
    parser.add_argument("--text-art-prompt", "-P", default=None, help="艺术字文本描述（走生成管线）")
    parser.add_argument("--output", "-o", required=True, help="输出 PNG 路径")
    args = parser.parse_args()

    compose(
        subject_path=Path(args.subject),
        output_path=Path(args.output),
        text_art_path=Path(args.text_art) if args.text_art else None,
        text_art_prompt=args.text_art_prompt,
    )


if __name__ == "__main__":
    main()