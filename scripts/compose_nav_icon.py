#!/usr/bin/env python3
"""
手机商店导航栏icon 249x198 三层合成脚本

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
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return mask


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
                print(f"[nav_icon] Vision model '{model}' not available (HTTP {e.code}), trying next...", file=sys.stderr)
                continue
            print(f"[nav_icon] Vision attempt failed with model '{model}': {e}", file=sys.stderr)
        except Exception as e:
            print(f"[nav_icon] Vision attempt failed with model '{model}': {e}", file=sys.stderr)

    print(f"[nav_icon] Vision 分析失败 ({be['name']}): all models exhausted", file=sys.stderr)
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

    print(f"[nav_icon] Subject split detection failed ({be['name']})", file=sys.stderr)
    return {}


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
    print(f"[nav_icon] split preview: {output_path}", flush=True)


# ---------- 艺术字生成 ----------
def _build_text_art_prompt(title: str, vision_info: dict | None = None) -> str:
    """构建艺术字生成 prompt，融合 Vision 分析风格"""
    base = (
        f'Generate a transparent-background stylized Chinese text "{title}" as title art. '
        "The text should have a bold, eye-catching design with 3D depth, metallic gradient, "
        "and glowing outline effect. Clean typography, no background, isolated on pure white."
    )
    if vision_info:
        style = vision_info.get("style", "")
        mood = vision_info.get("mood", "")
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
                    print(f"[nav_icon] text-art moxin {model} success", flush=True)
                    return True
            except Exception as e:
                print(f"[nav_icon] moxin_images_api {model}: {e}", file=sys.stderr)

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
                    print(f"[nav_icon] text-art t2i {model} success", flush=True)
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
        print(f"[nav_icon] BiRefNet script not found: {extract_script}", file=sys.stderr)
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
            print(f"[nav_icon] BiRefNet 抠字完成: {image_path.name}", flush=True)
        else:
            print(f"[nav_icon] BiRefNet 抠字失败(rc={r.returncode})，保留原图", file=sys.stderr)
    except Exception as e:
        print(f"[nav_icon] BiRefNet 抠字异常: {e}", file=sys.stderr)
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
            print(f"[nav_icon] text art generated via {name}", flush=True)
            try:
                _birefnet_extract_text(raw_path)
            except Exception as e:
                print(f"[nav_icon] BiRefNet failed, using raw: {e}", file=sys.stderr)
            raw_path.rename(out_path)
            return out_path

    # 兜底：PIL 渲染
    print("[nav_icon] 所有后端不可用，回退 PIL 渲染", file=sys.stderr)
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
        print(f"[nav_icon] Vision: style={vision_info.get('style','')[:60]}...", flush=True)

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
        split_info = {"type": "unknown", "ratio": 0.45, "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}
    split_ratio = split_info.get("ratio", 0.45)
    stype = split_info.get("type", "?")
    key_parts = split_info.get("key_parts", "")
    print(f"[nav_icon] Subject: {stype}, ratio={split_ratio:.2f}, parts=({key_parts[:60]})", flush=True)

    # Debug: 在主体图上绘制 split 预览（红色框 = bbox，红色横线 = split_y）
    # 这里用的是 BiRefNet 抠图后的原始尺寸 subject（尚未画布缩放）
    _draw_split_preview(subject, split_info, work / "_split_preview_before.png")

    # 5. 主体缩放（方案C）：基于 bbox 动态 scale，bbox 完整落入圆的内切正方形
    bbox = split_info.get("bbox", {"x": 0, "y": 0, "w": 1, "h": 1})
    bx, by, bw, bh = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 1), bbox.get("h", 1)

    # 圆的内切正方形边长（系数 0.92 留边距）
    fit_size = int(RADIUS * 2 * 0.92)

    # bbox 退化兜底：检测失败时（w>0.9 且 h>0.9）改用固定 scale
    if bw > 0.9 and bh > 0.9:
        scale = CANVAS_H * 0.85 / subject.height
        print(f"[nav_icon] bbox 退化，使用固定 scale={scale:.3f}", flush=True)
    else:
        subj_bbox_w_px = max(1, bw * subject.width)
        subj_bbox_h_px = max(1, bh * subject.height)
        scale = fit_size / max(subj_bbox_w_px, subj_bbox_h_px)
        print(f"[nav_icon] bbox fit scale={scale:.3f}, fit_size={fit_size}px, bbox=({bx:.2f},{by:.2f},{bw:.2f},{bh:.2f})", flush=True)

    new_w = max(1, int(subject.width * scale))
    new_h = max(1, int(subject.height * scale))
    subject = subject.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # bbox 中心对齐圆心
    bbox_cx_px = int((bx + bw / 2) * new_w)
    bbox_cy_px = int((by + bh / 2) * new_h)
    subj_x = CENTER[0] - bbox_cx_px
    subj_y = CENTER[1] - bbox_cy_px

    # split_y = CANVAS_H：不做圆形裁切，主体完整显示
    split_y = CANVAS_H

    # 区域蒙版：split_y 之上保留原始 alpha，之下按圆形裁切
    circle_m = circle_mask(CANVAS_W, CANVAS_H, *CENTER, RADIUS)

    subj_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    subj_layer.paste(subject, (subj_x, subj_y), subject)

    # Debug: 在合成画布上绘制 split 预览
    _d = subj_layer.copy()
    _dbg_draw = ImageDraw.Draw(_d)
    _dbg_draw.line([(0, split_y), (CANVAS_W, split_y)], fill=(255, 0, 0, 255), width=2)
    _dbg_draw.text((4, split_y - 16), f"split_y={split_y} ratio={split_ratio:.2f}", fill=(255, 0, 0, 255))
    _dbg_bg = Image.new("RGBA", (CANVAS_W, CANVAS_H), (255, 255, 255, 255))
    _dbg_bg.alpha_composite(_d)
    _dbg_bg.save(work / "_split_preview_on_canvas.png", "PNG")

    subj_arr = np.array(subj_layer)
    circle_arr = np.array(circle_m, dtype=np.float32) / 255.0

    mult = np.ones((CANVAS_H, CANVAS_W), dtype=np.float32)
    mult[split_y:, :] = circle_arr[split_y:, :]

    subj_arr[:, :, 3] = (subj_arr[:, :, 3].astype(np.float32) * mult).astype(np.uint8)
    subj_layer = Image.fromarray(subj_arr, "RGBA")
    canvas.alpha_composite(subj_layer)

    # 5. 贴艺术字
    if text_art_prompt and not text_art_path:
        enriched_prompt = _build_text_art_prompt(text_art_prompt, vision_info)
        text_art_path = work / "title_art.png"
        generate_title_art_from_prompt(enriched_prompt, text_art_path)
        print(f"[nav_icon] 艺术字 prompt: {enriched_prompt[:100]}...", flush=True)

    if text_art_path:
        art_rgba_path = ensure_transparent_png(text_art_path, work)
        art = Image.open(art_rgba_path).convert("RGBA")

        # 缩放：宽度不超过圆直径的 80%
        max_art_w = int(RADIUS * 2 * 0.8)
        if art.width > max_art_w:
            art = art.resize((max_art_w, int(art.height * max_art_w / art.width)), Image.Resampling.LANCZOS)

        # 位置：水平居中，垂直在圆心下方 radius * 0.65
        art_x = CENTER[0] - art.width // 2
        art_y = CENTER[1] + int(RADIUS * TEXT_ART_Y_RATIO) - art.height // 2

        art_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        art_layer.paste(art, (art_x, art_y), art)
        canvas.alpha_composite(art_layer)

    # 6. 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"[output] {output_path}")


# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser(description="手机商店导航栏icon 249x198 合成")
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