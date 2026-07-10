#!/usr/bin/env python3
"""
Lovart 视觉理解封装：替代 gemini_subject_detect.py 中的 Vision 调用。
当 BANNER_IMAGE_BACKEND=lovart 时，由 gemini_subject_detect._call_vision_get_text 调用。
接口与 gemini_subject_detect 完全一致，内部用 Lovart chat 实现（中文 prompt）。
"""
import os
import sys
from pathlib import Path

# 确保 scripts 目录在 path 中
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from lovart_helper import get_client, get_project_id

# ── 中文 prompt 常量 ──────────────────────────────────────────────────

SUBJECT_PROMPT_BBOX_ZH = """这张图片将用作横版 Banner 背景。请识别图中的【主体】并返回其边界框。

主体定义：
1. 如果图中有人物或角色（真人、卡通角色、有脸的生物等），主体必须是该人物/角色——最大且最靠前景的那个。边界框必须完整包含整个身体：头部（含头发、发饰）、双手（含手指指尖）和主要视觉特征（如肩甲、丝带、装饰物）。不要裁掉头部、指尖或突出配件；留少量边距。框必须覆盖完整身形（全身或至少头、躯干、主要肢体）；不要只框手臂、脸部等局部。
2. 如果图中没有人物或角色，主体是最突出的【场景或物体组合】——最大、最靠前景、占据最多空间的那个。例如：带植物和工具的中心岛、摆有产品的桌子、载货车辆、建筑立面，或任何连贯的前景群组。框必须将整个视觉中心或前景群组作为一个整体包围；不要只选一个小物体（如单朵花或单个工具）。

请用四个 0 到 1 之间的数字回答，顺序为：x_min y_min x_max y_max。
x_min=左边缘，x_max=右边缘；y_min=上边缘，y_max=下边缘。
示例：0.2 0.1 0.8 0.9 表示主体横向占 20%~80%，纵向占 10%~90%。

只输出这四个数字，用空格或逗号分隔，不要其他文字。"""

SUBJECT_PROMPT_Y_ZH = """这张图片将用作横版 Banner 背景。请识别图中最突出的主体（最大、最靠前景的人物或物体）。忽略图片几何中心，关注视觉突出度。

请用一个 0 到 1 之间的数字回答：该主体中心的纵向位置比例（0=顶边，1=底边）。
示例：0.7 表示主体中心在图片下三分之一处。

只输出这一个数字，不要其他文字。"""

SUBJECT_PROMPT_XY_ZH = """这张图片将用作横版 Banner 背景。请识别图中最突出的主体（最大、最靠前景的人物或物体）。忽略图片几何中心，关注视觉突出度。

请用两个 0 到 1 之间的数字回答，用空格或逗号分隔：
第一个：主体中心的横向位置比例（0=左边，1=右边）
第二个：主体中心的纵向位置比例（0=顶边，1=底边）
示例：0.75 0.6 表示主体在右侧偏下。

只输出这两个数字，不要其他文字。"""

UNFILLED_BLANKS_PROMPT_ZH = """这张图片是一张 Banner，由主体贴图和背景延展合成。部分区域可能仍未填充（残留空白画布：纯黑或接近纯黑的条带，通常在边缘，与场景有明显边界）。其他深色或黑色区域可能是有意为之（如黑色背景、夜空、深色服装、阴影）。

这张图片是否有【未填充区域】（空白画布，不属于场景内容）？不要把有意的黑色/深色内容算作未填充。

只回答一个词：YES 或 NO。
YES = 有未填充的空白区域需要填充。
NO = 所有深色区域都是场景的一部分，图片已完整填充。"""

FILL_QUALITY_NEED_REFILL_PROMPT_ZH = """这张图片是通过在中心主体周围延展/填充空白区域生成的。中心区域是主体（如人物、物体），外围区域是生成的背景延展。

请检查两点：
1. 视觉连续性：中心主体区域和外围延展区域之间是否有明显的接缝、割裂或不连续？延展区域看起来是同一连续场景（相同风格、光照、透视），还是像拼贴/补丁？
2. 内容相关性：延展（填充）区域的内容是否自然延续了中心主体的场景（同一房间、同一环境、同一故事）？还是显示了不相关的内容（不同地点、不同风格、与主体毫无关联）？

只回答一个词：YES 或 NO。
YES = 需要重新填充：存在明显割裂/接缝，或延展内容与主体不相关。
NO = 图片连贯，无明显接缝，延展区域自然延续了主体场景。"""

A4_NEED_REFILL_UNFILLED_PROMPT_ZH = """这张图片是通过将中心主体贴到画布上，然后填充空白区域（纯黑或 RGB(0,0,1)）来延展场景生成的。

只检查一点：是否还有【未填充区域】？即：残留的空白画布、边缘或其他位置的纯黑或接近纯黑的条带，与场景有明显边界。不要把有意的深色内容（如夜空、阴影、深色服装）算作未填充。

只回答一个词：YES 或 NO。
YES = 有未填充区域（需要重新填充）。
NO = 图片已完整填充，无空白或黑色条带。"""

A4_NEED_REFILL_SEAMS_PROMPT_ZH = """这张图片是通过将中心主体贴到画布上，然后填充空白区域来延展场景生成的。中心是主体，外围是生成的背景延展。

只检查一点：是否有明显的【接缝、割裂或重复拼接】？即：中心主体区域和外围延展区域之间的可见边界线、色彩/风格突变、或明显的重复图案拼接痕迹。不要把正常的场景边界（如地平线、墙壁边缘）算作接缝。

只回答一个词：YES 或 NO。
YES = 有明显接缝/割裂/重复拼接（需要重新填充）。
NO = 整张图片是一个无缝场景，无明显边界或拼接痕迹。"""

A6B_SHOP_HEADER_SEAM_DETECT_PROMPT_ZH = """这张图片是最终的商店专题头图 Banner（1740×220 风格）——非常宽的横版裁切。请检查整张图片从左到右。

只检查一点：是否有明显的【接缝、割裂或重复拼接】？即：图片中某处出现明显的边界线、色彩/风格突变、或明显的重复图案拼接痕迹，使图片看起来像是由多段拼接而成。

只回答一个词：YES 或 NO。
YES = 有明显接缝/割裂/重复拼接（需要修复）。
NO = 整张图片视觉连贯，无明显拼接痕迹。"""

PROTRUSION_PROMPT_ZH = """这张图片是一张横版 Banner 裁切（如 3320×500）。顶部 40 像素将作为条带，用于展示主体"延伸"进入该区域的部分（如主体头顶、举起的手，或最大物体的顶部）。

请识别应放入该顶部条带的区域：通常是【主体】最靠近图片顶部的部分——如人物头部（含头发）、举起的手，或最突出物体的顶部。应为一个连续区域，在浅横条中展示时看起来自然。

请用四个 0 到 1 之间的数字回答，顺序为：x_min y_min x_max y_max。优先选择靠近顶部（y_min 较小）且与主体横向对齐的区域。
示例：0.3 0.0 0.7 0.15 表示图片顶部 15%，横向 30%~70%。

只输出这四个数字，用空格或逗号分隔，不要其他文字。"""


# ── prompt 映射：英文 prompt → 中文 prompt ────────────────────────────

def _map_prompt_to_zh(prompt_en: str) -> str:
    """根据英文 prompt 内容映射到对应的中文 prompt。"""
    p = prompt_en.strip()
    if "x_min, y_min, x_max, y_max" in p and "MAIN subject" in p:
        return SUBJECT_PROMPT_BBOX_ZH
    if "vertical position" in p and "one number" in p:
        return SUBJECT_PROMPT_Y_ZH
    if "two numbers" in p and "horizontal" in p:
        return SUBJECT_PROMPT_XY_ZH
    if "top 40 pixels" in p or "protrusion" in p.lower():
        return PROTRUSION_PROMPT_ZH
    if "shop special-topic header" in p or "1740" in p:
        return A6B_SHOP_HEADER_SEAM_DETECT_PROMPT_ZH
    if "VISUAL CONTINUITY" in p:
        return FILL_QUALITY_NEED_REFILL_PROMPT_ZH
    if "A4" in p and "seam" in p.lower():
        return A4_NEED_REFILL_SEAMS_PROMPT_ZH
    if "A4" in p and "UNFILLED" in p:
        return A4_NEED_REFILL_UNFILLED_PROMPT_ZH
    if "UNFILLED" in p and "YES or NO" in p:
        return UNFILLED_BLANKS_PROMPT_ZH
    # 兜底：直接用英文 prompt
    return p


# ── 核心调用函数 ──────────────────────────────────────────────────────

def _call_lovart_vision(image_path: str, prompt_en: str) -> str | None:
    """
    上传图片到 Lovart，发送视觉理解请求，返回文字回复。
    prompt_en: 原始英文 prompt（用于映射到对应中文 prompt）。
    """
    zh_prompt = _map_prompt_to_zh(prompt_en)

    client = get_client()
    project_id = get_project_id(client)

    # 上传图片
    try:
        cdn_url = client.upload_file(image_path)
    except Exception as e:
        print(f"[lovart vision] 上传图片失败: {e}", file=sys.stderr)
        return None

    # 发送请求（不指定 include_tools，让 agent 自由回复文字）
    try:
        result = client.chat(
            prompt=zh_prompt,
            project_id=project_id,
            attachments=[cdn_url],
            timeout=60,
            auto_create_project=False,
        )
    except Exception as e:
        print(f"[lovart vision] chat 请求失败: {e}", file=sys.stderr)
        return None

    if result.get("final_status") != "done":
        print(f"[lovart vision] 请求未完成，状态: {result.get('final_status')}", file=sys.stderr)
        return None

    # 提取文字回复
    for item in result.get("items", []):
        text = item.get("text", "").strip()
        if text:
            return text

    print("[lovart vision] 未找到文字回复", file=sys.stderr)
    return None

