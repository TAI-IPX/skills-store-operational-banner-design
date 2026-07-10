#!/usr/bin/env python3
"""
Prompt Engine Optimizer — Step 0: 用 PROMPT_SYSTEM .md 作为 system prompt，
调用 LLM 执行完整 6 步管道，提取最终 Prompt 供后续生图流程使用。

支持 Gemini (默认) 和 Claude 后端。
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
PROMPT_SYSTEM_PATH = _script_dir.parent / "PROMPT_SYSTEM .md"
CACHE_DIR = Path("output/cache/prompt_engine")

SYSTEM_INSTRUCTION_BANNER_ADDENDUM = """

## 十三、Banner 背景图专项约束（运营活动主线，自动激活）

当前任务是为 **横幅 Banner 背景图** 生成 Prompt。规则自动覆盖本章全部规则：

1. **场景类型固定为 banner_bg**：画面不出现标题文字、副标题、CTA 按钮、品牌名等营销排版。场景内装饰性文字（便签、涂鸦、标签、书本暗纹等）正常保留。
2. **压字区与主体动态可分离**：
   - 主体可居中、偏左或偏右放置，构图不再为"右侧 1/3 留白"硬性让位；
   - 画面可充满动态（爆破、辐射、能量场、冲击波），张力优先；
   - 压字区由后续合成层叠加决定，画面构图不再为压字让位。
3. **运营活动主线**：本 Banner 默认用于运营活动场景，画面张力与氛围感为第一优先级。默认风格走 B（堆叠轰炸式），默认调色高对比高饱和。
4. **输出长度**：最终 Prompt 控制在 150～350 字（较旧版放宽 50 字以承载张力词库），精简但信息密度高，每个词都有视觉对应。
5. **末尾约束**：Prompt 结尾标注「画面无标题文字，张力强，氛围感强烈」。
"""


def load_system_prompt() -> str:
    if not PROMPT_SYSTEM_PATH.is_file():
        raise FileNotFoundError(f"System prompt 文件不存在: {PROMPT_SYSTEM_PATH}")
    content = PROMPT_SYSTEM_PATH.read_text(encoding="utf-8")
    return content + SYSTEM_INSTRUCTION_BANNER_ADDENDUM


def build_user_message(main_title: str, subtitle: str, examples_text: str = "") -> str:
    user_text = (
        f"主标题：{main_title.strip()}\n副标题：{subtitle.strip()}\n\n"
        "请根据以上主副标题，按 6 步管道执行完整推导，"
        "输出【信息解析卡】→【风格与构图选择】→【主体推导】"
        "→【最终 Prompt】→【二次优化摘要】→【Prompt 评分卡】。"
        "最终 Prompt 末尾必须标注「画面无标题文字，张力强，氛围感强烈」。"
    )
    if examples_text:
        user_text = examples_text + "\n---\n本次任务：\n" + user_text
    return user_text


def extract_final_prompt(llm_output: str) -> str | None:
    m = re.search(r'【修正版\s*Prompt】\s*\n(.*?)(?=\n(?:#{1,3}\s|【|$))', llm_output, re.DOTALL)
    if m:
        return m.group(1).strip()

    m = re.search(r'【最终\s*Prompt】\s*\n(.*?)(?=\n(?:#{1,3}\s|【|$))', llm_output, re.DOTALL)
    if m:
        return m.group(1).strip()

    lines = llm_output.split("\n")
    candidates = [
        l.strip()
        for l in lines
        if len(l.strip()) > 50
        and not l.strip().startswith("#")
        and not l.strip().startswith("【")
        and not l.strip().startswith("```")
    ]
    if candidates:
        return candidates[-1]

    return None


def _gemini_call(key: str, models: list[str], body: dict) -> str:
    sys.path.insert(0, str(_script_dir.parent.parent / "banner-background-from-description" / "scripts"))
    import generate_from_description as _gfd

    last_err = None
    for model in models:
        for attempt in range(3):
            try:
                data = _gfd._prompt_optimizer_request(key, model, body)
                candidates = data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts") or []
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
                last_err = RuntimeError("prompt-engine: Gemini 未返回内容")
            except urllib.error.HTTPError as e:
                print(f"[prompt-engine] model={model} API {e.code}", file=sys.stderr)
                last_err = e
                if e.code in (401, 403, 404):
                    break
                if e.code == 500 and attempt < 2:
                    time.sleep(5)
                    continue
                if attempt >= 2:
                    break
            except urllib.error.URLError as e:
                print(f"[prompt-engine] model={model} 网络错误: {e.reason}", file=sys.stderr)
                last_err = e
                break
    raise RuntimeError("prompt-engine: 所有 Gemini 模型均失败") from last_err


def _claude_call(api_key: str, system_prompt: str, user_message: str) -> str:
    sys.path.insert(0, str(_script_dir.parent.parent / "banner-background-from-description" / "scripts"))
    import generate_from_description as _gfd

    model = os.environ.get("CLAUDE_PROMPT_OPTIMIZER_MODEL", "claude-3-5-sonnet-20241022").strip()
    body = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.7,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    last_err = None
    for attempt in range(3):
        try:
            data = _gfd._anthropic_messages_request(api_key, body)
            blocks = data.get("content") or []
            text = ""
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    text += b["text"]
            text = text.strip()
            if text:
                return text
            last_err = RuntimeError("prompt-engine: Claude 未返回文本")
        except urllib.error.HTTPError as e:
            print(f"[prompt-engine claude] API {e.code}", file=sys.stderr)
            last_err = e
            if e.code in (401, 403):
                break
            if e.code in (429, 529) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if attempt >= 2:
                break
        except urllib.error.URLError as e:
            print(f"[prompt-engine claude] 网络错误: {e.reason}", file=sys.stderr)
            last_err = e
            break
    raise RuntimeError("prompt-engine: Claude 调用失败") from last_err


def _cache_key(params: dict) -> str:
    raw = "|".join(str(params.get(k, "")) for k in [
        "main_title", "subtitle", "mood", "style_override",
        "tone_override", "composition_override", "light_override",
        "subject_override", "brand_tier", "含文字版", "person"
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_get(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _cache_put(key: str, params: dict, description: str, full_text: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    payload = {
        "key": key,
        "params": params,
        "description": description,
        "full_text": full_text,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": "PROMPT_SYSTEM v3.0",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_clear() -> int:
    if not CACHE_DIR.exists():
        return 0
    count = sum(1 for _ in CACHE_DIR.glob("*.json"))
    shutil.rmtree(CACHE_DIR)
    return count


def prompt_engine_optimize(
    main_title: str,
    subtitle: str,
    backend: str = "gemini",
    examples_text: str = "",
    save_trace: bool = False,
    trace_dir: str | None = None,
    no_change_prompt: bool = False,
    person: str = "",
    mood: str = "",
    style_override: str = "",
    tone_override: str = "",
    composition_override: str = "",
    light_override: str = "",
    subject_override: str = "",
    brand_tier: str = "",
    含文字版: bool = False,
    clear_cache: bool = False,
) -> tuple[str, str]:
    if clear_cache:
        n = _cache_clear()
        print(f"[prompt-engine] 已清理 {n} 个缓存文件 ({CACHE_DIR})", flush=True)
        return ("", "")

    if person and person not in ("realistic",):
        raise ValueError(
            f"prompt-engine: person 参数仅支持 'realistic' 或留空，收到 '{person}'。"
        )

    params = {
        "main_title": main_title,
        "subtitle": subtitle,
        "mood": mood,
        "style_override": style_override,
        "tone_override": tone_override,
        "composition_override": composition_override,
        "light_override": light_override,
        "subject_override": subject_override,
        "brand_tier": brand_tier,
        "含文字版": bool(含文字版),
        "person": person,
    }
    key = _cache_key(params)
    cached = _cache_get(key)

    if cached and no_change_prompt:
        print(
            f"[prompt-engine] 缓存命中 {key[:8]}，已复用上次 Prompt（{cached.get('created_at', '?')}）",
            flush=True,
        )
        return cached.get("description", ""), cached.get("full_text", "")

    if cached and not no_change_prompt:
        print(
            f"[prompt-engine] 缓存命中 {key[:8]}，但未指定不改prompt，按 6 步管道重新生成"
            f"（上次：{cached.get('created_at', '?')}）",
            flush=True,
        )

    system_prompt = load_system_prompt()
    user_message = build_user_message(main_title, subtitle, examples_text)

    if backend == "claude":
        sys.path.insert(0, str(_script_dir.parent.parent / "banner-background-from-description" / "scripts"))
        import generate_from_description as _gfd
        api_key = _gfd.get_anthropic_api_key()
        full_text = _claude_call(api_key, system_prompt, user_message)
    else:
        sys.path.insert(0, str(_script_dir.parent.parent / "banner-background-from-description" / "scripts"))
        import generate_from_description as _gfd
        key_g = _gfd.get_api_key()
        models = []
        for m in (
            os.environ.get("GEMINI_PROMPT_OPTIMIZER_MODEL"),
            os.environ.get("GEMINI_MODEL"),
            "gemini-3-flash-preview",
        ):
            if m and m.strip() and m not in models:
                models.append(m.strip())
        body = {
            "contents": [{"parts": [{"text": system_prompt + "\n\n" + user_message}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }
        full_text = _gemini_call(key_g, models, body)

    description = extract_final_prompt(full_text)
    if not description:
        raise RuntimeError(
            "prompt-engine: 无法从 LLM 输出中提取最终 Prompt。"
            "请检查 LLM 是否按 6 步管道格式输出了【最终 Prompt】段。"
        )

    _cache_put(key, params, description, full_text)
    print(f"[prompt-engine] 已写入缓存 {key[:8]} ({CACHE_DIR / f'{key}.json'})", flush=True)

    if save_trace and trace_dir:
        trace_path = Path(trace_dir) / "prompt_engine_trace.md"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(full_text, encoding="utf-8")
        print(f"[prompt-engine] 完整推导已保存到 {trace_path}", flush=True)

    return description, full_text


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="prompt-engine CLI: 单独调用 LLM 推导最终 Prompt（带缓存）"
    )
    parser.add_argument("-m", "--main-title", required=True, help="主标题")
    parser.add_argument("-s", "--subtitle", default="", help="副标题")
    parser.add_argument("--backend", choices=["gemini", "claude"], default="gemini")
    parser.add_argument("--no-change-prompt", action="store_true", help="复用上次 Prompt（命中缓存时跳过 LLM）")
    parser.add_argument("--person", default="", help="人物覆写：realistic / 留空")
    parser.add_argument("--mood", default="", help="mood 模式：plain / 留空")
    parser.add_argument("--clear-cache", action="store_true", help="清理所有缓存")
    parser.add_argument("--output", help="输出 Prompt 到指定文件")
    args = parser.parse_args()

    if args.clear_cache:
        n = _cache_clear()
        print(f"[prompt-engine] 已清理 {n} 个缓存文件")
        return

    desc, _ = prompt_engine_optimize(
        main_title=args.main_title,
        subtitle=args.subtitle,
        backend=args.backend,
        no_change_prompt=args.no_change_prompt,
        person=args.person,
        mood=args.mood,
    )
    print("---")
    print(desc)
    if args.output:
        Path(args.output).write_text(desc, encoding="utf-8")
        print(f"[prompt-engine] 已写入 {args.output}")


if __name__ == "__main__":
    _main()
