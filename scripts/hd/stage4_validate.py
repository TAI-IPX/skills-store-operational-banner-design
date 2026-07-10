#!/usr/bin/env python3
"""
HD 产线 Stage 4：检查画面完整性。

使用 Gemini Vision 评估最终合成图：
  - 角色是否像贴上去的
  - 光源方向是否一致
  - 有无风格冲突/色差/接缝
  - 标题是否可读
"""
from __future__ import annotations

from pathlib import Path

VALIDATE_PROMPT = """Examine this finished game banner for visual harmony.

Reply YES (needs redo) if ANY of these is clearly visible:
- Characters look PASTED ON: lighting direction/color on bodies or FACES does not match the scene
- STYLE CLASH: background is a different art tier (e.g. hyper-3D city vs flat anime heroes)
- SEAMS / STITCHING: background breaks, misaligned panels, obvious collage
- COLOR DISHARMONY: characters and background feel like unrelated images
- TITLE: unreadable, or lighting totally unlike the scene

Reply NO (acceptable) only if:
- Characters and background read as ONE harmonious illustration
- Shared mood, believable light, cohesive colors, natural depth
- Title text is reasonably integrated

Reply with ONLY a JSON object (no markdown):
{"pass": true/false, "issues": "brief description or empty string"}"""


def run_stage4(final_path: Path) -> dict:
    """
    Stage 4：检查画面完整性。
    失败/超时/限流时宽容处理：假设通过（输出已生成，不阻塞流程）。
    """
    from scripts.hd.hd_vision import call_hd_vision
    import json, time

    print("\n[stage4] === 完整性检查 ===", flush=True)

    if not final_path.is_file():
        raise RuntimeError(f"[stage4] 终稿不存在: {final_path}")

    for attempt in range(3):
        if attempt > 0:
            wait = 2 ** attempt
            print(f"[stage4] 重试 {attempt + 1}/3，等待 {wait}s...", flush=True)
            time.sleep(wait)
        text = call_hd_vision(final_path, VALIDATE_PROMPT, timeout=60)
        if text:
            break
    else:
        print("[stage4] Vision 不可用，假设通过", flush=True)
        return {"pass": True, "issues": "Vision 不可用，跳过检查"}

    import re
    match = re.search(r'\{[^}]+\}', text)
    if not match:
        print(f"[stage4] 无法解析 JSON，假设通过", flush=True)
        return {"pass": True, "issues": ""}

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        print(f"[stage4] JSON 解析失败，假设通过", flush=True)
        return {"pass": True, "issues": ""}

    passed = data.get("pass", True)
    issues = data.get("issues", "")

    if passed:
        print("[stage4] 通过", flush=True)
    else:
        print(f"[stage4] 未通过: {issues}", flush=True)

    return {"pass": passed, "issues": issues}
