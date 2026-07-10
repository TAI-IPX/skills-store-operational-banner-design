#!/usr/bin/env python3
"""
多图输入给 micugpt2 (gpt-image-2) 合成 Banner（可复用模板）。

用法:
  py scripts/synthesize_multi_subject_banner.py <角色1.png> <角色2.png> <角色3.png>
  py scripts/synthesize_multi_subject_banner.py <角色1.png> <角色2.png> <角色3.png> --layout <排版参考.png>
  py scripts/synthesize_multi_subject_banner.py <角色1.png> <角色2.png> <角色3.png> --output <输出.png>

固定模板:
  - 排版参考: input/ScreenShot_2026-05-28_115434_989.png（可通过 --layout 覆盖）
  - 合成指令: 三角色交叠并排 + 赛博朋克都市夜背景 + 16:10

依赖:
  - scripts/micugpt2_images_api.py    chat_completions_image（统一重试/代理/响应解析）
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from micugpt2_images_api import chat_completions_image

# ── 加载 .env ────────────────────────────────────────────────
env_file = ROOT / ".env"
for line in env_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v

API_KEY = os.environ.get("MICUAPI_API_KEY", "").strip()
if not API_KEY.startswith("sk-"):
    print("Error: MICUAPI_API_KEY 未设置或格式不正确", file=sys.stderr)
    sys.exit(1)

# ── 命令行参数 ─────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="micugpt2 多图合成 Banner（可复用模板）")
parser.add_argument("char1", help="角色1（左位）图片路径")
parser.add_argument("char2", help="角色2（中位）图片路径")
parser.add_argument("char3", help="角色3（右位）图片路径")
parser.add_argument("-HD", "--template", dest="template_name", default=None,
                    help="指定的模板名（如 活动1），对应 scripts/synthesize_templates.json")
parser.add_argument("--layout", default=None,
                    help="排版参考图路径（默认: input/layout_template.png；-HD 时由模板配置覆盖）")
parser.add_argument("--output", default=None,
                    help="输出路径（默认: output/<模板名>_<时间戳>.png）")
parser.add_argument("--width", type=int, default=None, help="目标宽度（默认 1920；-HD 时由模板配置覆盖）")
parser.add_argument("--height", type=int, default=None, help="目标高度（默认 1200；-HD 时由模板配置覆盖）")
parser.add_argument("--background", default=None, help="背景参考图路径（可选，用于指定背景风格）")
args = parser.parse_args()

# ── 模板解析 ─────────────────────────────────────────────────
template_config = None
if args.template_name:
    templates_file = ROOT / "scripts" / "synthesize_templates.json"
    if templates_file.is_file():
        templates = json.loads(templates_file.read_text(encoding="utf-8"))
        raw = args.template_name
        if raw.isdigit():
            raw = f"活动{raw}"
        template_config = templates.get(raw)
        if not template_config:
            print(f"Error: 模板不存在: {args.template_name}", file=sys.stderr)
            print(f"可用模板: {', '.join(templates.keys())}", file=sys.stderr)
            sys.exit(1)
        if args.width is None:
            args.width = template_config.get("width", 1920)
        if args.height is None:
            args.height = template_config.get("height", 1200)
        if args.layout is None:
            layout_path = ROOT / template_config.get("layout", "")
            if layout_path.is_file():
                args.layout = str(layout_path)
        print(f"使用模板: {args.template_name} ({template_config.get('description', '')})")

# 最终回退
if args.width is None:
    args.width = 1920
if args.height is None:
    args.height = 1200

# ── 校验输入 ─────────────────────────────────────────────────
char_images = [
    Path(args.char1).resolve(),
    Path(args.char2).resolve(),
    Path(args.char3).resolve(),
]
for i, p in enumerate(char_images, 1):
    if not p.is_file():
        print(f"Error: 角色图{i} 不存在: {p}", file=sys.stderr)
        sys.exit(1)

layout_image = Path(args.layout).resolve() if args.layout else (
    ROOT / "input" / "layout_template.png"
)
if not layout_image.is_file():
    print(f"Error: 排版参考图不存在: {layout_image}", file=sys.stderr)
    sys.exit(1)

background_image = Path(args.background).resolve() if args.background else None
if args.background and not background_image.is_file():
    print(f"Error: 背景参考图不存在: {background_image}", file=sys.stderr)
    sys.exit(1)

if args.output:
    output_path = Path(args.output).resolve()
else:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.template_name + "_" if args.template_name else "synthesized_"
    output_path = ROOT / "output" / f"{prefix}{ts}.png"

output_path.parent.mkdir(parents=True, exist_ok=True)

W, H = args.width, args.height

# ── Prompt 模板 ────────────────────────────────────────────────
_total_images = 5 if background_image else 4
_bg_ref_text = ""
if background_image:
    _bg_ref_text = f"\nImage 5 is a BACKGROUND STYLE REFERENCE — use this to determine the background style, color palette, lighting mood, and atmosphere. Match the background closely to this reference."
PROMPT = f"""You are an expert banner compositing AI. I will give you {_total_images} reference images:

Images 1-3 contain three different game characters.
Image 4 is a PRECISE SPATIAL TEMPLATE — a blurred version of the target composition showing exact character positions, sizes, overlap relationships, and background layout. Use this as a rigid composition guide.{_bg_ref_text}

Your task:
1. Create a SINGLE cohesive banner image at exactly {W}x{H} pixels ({W/H:.1f}:1 aspect ratio). The three characters combined should occupy the middle 1/3 of the frame width, centered in the image. Leave breathing room on both sides for the background.
2. Place all THREE characters from images 1-3 into the EXACT positions shown in the spatial template (Image 4):
   - Match each character's position, scale, and overlap depth precisely to the template
   - The overlap zones shown in the template are your exact guide for how characters interlock
3. Keep each character's appearance, clothing, pose, and dynamics EXACTLY as they are - do not change them
4. The background should match the style, color palette, lighting mood and atmosphere from the reference. Use Image 4 for spatial background layout and Image 5 for visual style.
5. Unify the lighting and color palette across all three characters to make them look like they belong in the same scene
6. The style should be high-quality game splash art / CG illustration, consistent dramatic lighting

Output the final banner image. Do not add any text or logo overlay."""

# ── 收集输入图片 ─────────────────────────────────────────────
images_to_send = char_images + [layout_image]
labels = ["角色1(左)", "角色2(中)", "角色3(右)", "排版参考"]
if background_image:
    images_to_send.append(background_image)
    labels.append("背景参考")

for i, (img_path, label) in enumerate(zip(images_to_send, labels), 1):
    sz = Image.open(str(img_path)).size
    print(f"  图{i} [{label}]: {img_path.name} {sz[0]}x{sz[1]}")

# ── 发送请求（统一 chat_completions_image） ─────────────────
print(f"\n发送 {len(images_to_send)} 张图到 micugpt2 (gpt-image-2)...")
print(f"目标: {W}x{H} ({W/H:.1f}:1) 三角色交叠并排 Banner")
print("等待响应（最长 300s，3 次重试）...")

img_bytes = chat_completions_image(
    [str(p) for p in images_to_send],
    PROMPT,
    timeout=300,
    max_retries=3,
    max_dim=1024,
)
if not img_bytes:
    print(f"\n[FAIL] API 全部 3 次重试均未返回图片", file=sys.stderr)
    sys.exit(1)

output_path.write_bytes(img_bytes)
result_img = Image.open(str(output_path))
print(f"\n[OK] 已保存: {output_path} ({result_img.size[0]}x{result_img.size[1]})")
