#!/usr/bin/env python3
"""
Lovart AI 后端封装：文生图(t2i)、图生图(i2i)、outpaint、inpaint、upscale。
依赖 scripts/agent_skill.py（Lovart 官方零依赖客户端）。
凭证从项目根 .env 读取：LOVART_ACCESS_KEY、LOVART_SECRET_KEY。
"""
import os
import sys
import json
import shutil
import time
from pathlib import Path

# 从项目根 .env 加载凭证
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
_LOVART_ENV_KEYS = (
    "LOVART_ACCESS_KEY",
    "LOVART_SECRET_KEY",
    "LOVART_PROJECT_ID",
    "LOVART_PREFER_MODELS",
    "LOVART_UNLIMITED_TIMEOUT",
    "LOVART_FAST_TIMEOUT",
    "LOVART_BASE_URL",
    "LOVART_INSECURE_SSL",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "https_proxy",
    "http_proxy",
)
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            if _k in _LOVART_ENV_KEYS and _v.strip().strip('"\''):
                # .env 优先：始终覆盖系统环境变量（避免旧 key 残留）
                os.environ[_k] = _v.strip().strip('"\'')

# agent_skill.py 与本文件同目录
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

try:
    from agent_skill import AgentSkill, AgentSkillError, LocalState
except ImportError:
    print(
        "[lovart] 未找到 agent_skill.py，请确认 scripts/agent_skill.py 存在。\n"
        "可从 https://github.com/lovartai/lovart-skill 下载。",
        file=sys.stderr,
    )
    sys.exit(1)

# ── 配置 ─────────────────────────────────────────────────────────────

LOVART_BASE_URL = os.environ.get("LOVART_BASE_URL", "https://lgw.lovart.ai").rstrip("/")
LOVART_UNLIMITED_TIMEOUT = int(os.environ.get("LOVART_UNLIMITED_TIMEOUT", "120"))
LOVART_FAST_TIMEOUT = int(os.environ.get("LOVART_FAST_TIMEOUT", "600"))
LOVART_FORCE_FAST = os.environ.get("LOVART_FORCE_FAST", "1").strip().lower() == "1"

# 默认偏好模型（逗号分隔）
_DEFAULT_PREFER_MODELS = "generate_image_seedream_v4,generate_image_nano_banana_pro"

# outpaint/inpaint 默认 prompt（中文，明确要求输出图片）
OUTPAINT_PROMPT = (
    "请对这张图片进行扩图（outpaint）：向左右两侧及上下延展，使画面填满更宽的横版画布。"
    "保持原有风格、光照和场景内容，新增区域与原图无缝融合。"
    "请直接输出扩展后的图片。"
)
INPAINT_REMOVE_TEXT_PROMPT = (
    "这张图片将用作 Banner 背景。请去除图片上所有叠加的文字、Logo、纯色色块、模糊遮罩、按钮、UI 控件和徽章。"
    "用周围场景内容自然填充被去除的区域。"
    "不要添加任何新文字或图形。输出图片尺寸必须与输入完全一致。"
    "请直接输出处理后的图片。"
)


def _get_keys() -> tuple[str, str]:
    ak = os.environ.get("LOVART_ACCESS_KEY", "").strip()
    sk = os.environ.get("LOVART_SECRET_KEY", "").strip()
    if not ak or not sk:
        print(
            "Error: LOVART_ACCESS_KEY 和 LOVART_SECRET_KEY 未设置。\n"
            "请在项目根 .env 中添加：\n"
            "  LOVART_ACCESS_KEY=ak_xxx\n"
            "  LOVART_SECRET_KEY=sk_xxx\n"
            "获取密钥：https://www.lovart.ai（头像菜单 → AK/SK 管理）",
            file=sys.stderr,
        )
        sys.exit(1)
    return ak, sk


def _ensure_proxy():
    """若 HTTPS_PROXY 未设置，尝试从 Windows 注册表读取系统代理并注入到环境变量。"""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if enabled:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if server and ":" in server:
                proxy_url = f"http://{server}"
                os.environ["HTTPS_PROXY"] = proxy_url
                os.environ["HTTP_PROXY"] = proxy_url
    except Exception:
        pass


def get_client() -> AgentSkill:
    _ensure_proxy()
    ak, sk = _get_keys()
    return AgentSkill(
        base_url=LOVART_BASE_URL,
        access_key=ak,
        secret_key=sk,
        timeout=max(LOVART_UNLIMITED_TIMEOUT, LOVART_FAST_TIMEOUT),
    )


def get_project_id(client: AgentSkill) -> str:
    """
    获取项目 ID：优先 LOVART_PROJECT_ID 环境变量，
    其次 ~/.lovart/state.json active_project，
    最后自动创建名为 banner-background 的新项目并保存。
    """
    # 1. 环境变量
    pid = os.environ.get("LOVART_PROJECT_ID", "").strip()
    if pid:
        return pid
    # 2. 本地状态
    state = LocalState()
    pid = state.get_project_id()
    if pid:
        return pid
    # 3. 创建新项目
    print("[lovart] 创建新项目 banner-background ...", flush=True)
    pid = client.create_project()
    state.add_project(pid, "banner-background")
    print(f"[lovart] 新项目已创建: {pid}", flush=True)
    return pid


def get_prefer_models(prefer_models: list[str] | None = None) -> dict | None:
    """
    构建 prefer_models 参数（传给 AgentSkill.chat 的 prefer_models 字段）。
    prefer_models: 工具名列表，如 ["generate_image_seedream_3_0"]。
    返回 {"IMAGE": [...]} 格式，或 None（使用 Lovart 默认）。
    """
    raw = prefer_models
    if raw is None:
        env_raw = os.environ.get("LOVART_PREFER_MODELS", _DEFAULT_PREFER_MODELS).strip()
        raw = [m.strip() for m in env_raw.split(",") if m.strip()] if env_raw else []
    if not raw:
        return None
    return {"IMAGE": raw}


def _chat_with_mode_fallback(
    client: AgentSkill,
    project_id: str,
    prompt: str,
    attachments: list[str] | None = None,
    prefer_models: dict | None = None,
    include_tools: list[str] | None = None,
) -> dict:
    """
    先用 unlimited 模式（免费，可能排队），超时后自动切换 fast 模式（消耗积分）。
    返回 result dict；pending_confirmation 时返回 {"final_status": "pending_confirmation"}。
    """
    # 强制 fast 模式
    if LOVART_FORCE_FAST:
        try:
            client.set_mode(unlimited=False)
            client.timeout = LOVART_FAST_TIMEOUT
            result = client.chat(
                prompt=prompt,
                project_id=project_id,
                attachments=attachments,
                prefer_models=prefer_models,
                include_tools=include_tools,
                auto_create_project=False,
            )
            if result.get("final_status") == "pending_confirmation":
                print("[lovart] 操作需要确认（pending_confirmation），已跳过。", file=sys.stderr)
                return {"final_status": "pending_confirmation"}
            return result
        except AgentSkillError as e:
            print(f"[lovart] fast 模式失败: {e.message}", file=sys.stderr)
            raise

    # unlimited 模式
    try:
        client.set_mode(unlimited=True)
    except AgentSkillError as e:
        print(f"[lovart] set_mode(unlimited) 失败: {e.message}，继续尝试...", file=sys.stderr)

    client.timeout = LOVART_UNLIMITED_TIMEOUT
    try:
        result = client.chat(
            prompt=prompt,
            project_id=project_id,
            attachments=attachments,
            prefer_models=prefer_models,
            include_tools=include_tools,
            auto_create_project=False,
        )
        if result.get("final_status") == "pending_confirmation":
            print("[lovart] 操作需要确认（pending_confirmation），已跳过。", file=sys.stderr)
            return {"final_status": "pending_confirmation"}
        if result.get("final_status") == "done":
            return result
        # timeout / abort → 切换 fast 模式
        print(f"[lovart] unlimited 模式状态: {result.get('final_status')}，切换 fast 模式...", file=sys.stderr)
    except AgentSkillError as e:
        print(f"[lovart] unlimited 模式失败: {e.message}，切换 fast 模式...", file=sys.stderr)

    # fast 模式
    try:
        client.set_mode(unlimited=False)
    except AgentSkillError as e:
        print(f"[lovart] set_mode(fast) 失败: {e.message}", file=sys.stderr)

    client.timeout = LOVART_FAST_TIMEOUT
    result = client.chat(
        prompt=prompt,
        project_id=project_id,
        attachments=attachments,
        prefer_models=prefer_models,
        include_tools=include_tools,
        auto_create_project=False,
    )
    if result.get("final_status") == "pending_confirmation":
        print("[lovart] fast 模式操作需要确认（pending_confirmation），已跳过。", file=sys.stderr)
        return {"final_status": "pending_confirmation"}
    return result


def _download_first_image(result: dict, output_path: str) -> Path | None:
    """从 result 中下载第一张图片到 output_path，返回 Path 或 None。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    dl = AgentSkill.download_artifacts(result, output_dir=str(out.parent), prefix="lovart_tmp")
    images = [d for d in dl if d.get("type") == "image" and d.get("local_path")]
    if not images:
        print("[lovart] 结果中未找到图片。", file=sys.stderr)
        return None
    src = Path(images[0]["local_path"])
    if src.resolve() != out.resolve():
        shutil.copy2(src, out)
        try:
            src.unlink()
        except OSError:
            pass
    return out


# ── 公开接口 ──────────────────────────────────────────────────────────

def generate_t2i(
    prompt: str,
    output_path: str,
    prefer_models: list[str] | None = None,
) -> Path | None:
    """文生图：prompt → Lovart Agent → 下载第一张图到 output_path。"""
    client = get_client()
    project_id = get_project_id(client)
    pm = get_prefer_models(prefer_models)
    print(f"[lovart t2i] 发送请求，项目: {project_id[:12]}...", flush=True)
    result = _chat_with_mode_fallback(client, project_id, prompt, prefer_models=pm)
    if result.get("final_status") != "done":
        print(f"[lovart t2i] 生成失败，状态: {result.get('final_status')}", file=sys.stderr)
        return None
    return _download_first_image(result, output_path)


def generate_i2i(
    prompt: str,
    ref_image: str,
    output_path: str,
    prefer_models: list[str] | None = None,
) -> Path | None:
    """图生图：上传参考图 + prompt → Lovart Agent → 下载第一张图。"""
    ref_path = Path(ref_image).resolve()
    if not ref_path.is_file():
        print(f"[lovart i2i] 参考图不存在: {ref_path}", file=sys.stderr)
        return None
    client = get_client()
    project_id = get_project_id(client)
    print(f"[lovart i2i] 上传参考图: {ref_path.name} ...", flush=True)
    try:
        cdn_url = client.upload_file(str(ref_path))
    except AgentSkillError as e:
        print(f"[lovart i2i] 上传失败: {e.message}", file=sys.stderr)
        return None
    pm = get_prefer_models(prefer_models)
    print(f"[lovart i2i] 发送请求，项目: {project_id[:12]}...", flush=True)
    result = _chat_with_mode_fallback(
        client, project_id, prompt, attachments=[cdn_url], prefer_models=pm
    )
    if result.get("final_status") != "done":
        print(f"[lovart i2i] 生成失败，状态: {result.get('final_status')}", file=sys.stderr)
        return None
    return _download_first_image(result, output_path)


def edit_outpaint(
    image_path: str,
    output_path: str,
    prompt: str = OUTPAINT_PROMPT,
) -> Path | None:
    """Outpaint：上传图片，要求 Lovart 向外延展填充。"""
    img_path = Path(image_path).resolve()
    if not img_path.is_file():
        print(f"[lovart outpaint] 图片不存在: {img_path}", file=sys.stderr)
        return None
    client = get_client()
    project_id = get_project_id(client)
    print(f"[lovart outpaint] 上传图片: {img_path.name} ...", flush=True)
    try:
        cdn_url = client.upload_file(str(img_path))
    except AgentSkillError as e:
        print(f"[lovart outpaint] 上传失败: {e.message}", file=sys.stderr)
        return None
    result = _chat_with_mode_fallback(
        client, project_id, prompt,
        attachments=[cdn_url],
    )
    if result.get("final_status") != "done":
        print(f"[lovart outpaint] 失败，状态: {result.get('final_status')}", file=sys.stderr)
        return None
    return _download_first_image(result, output_path)


def edit_inpaint(
    image_path: str,
    output_path: str,
    prompt: str = INPAINT_REMOVE_TEXT_PROMPT,
) -> Path | None:
    """Inpaint/去文字：上传图片，要求 Lovart 去除文字/水印并填充。"""
    img_path = Path(image_path).resolve()
    if not img_path.is_file():
        print(f"[lovart inpaint] 图片不存在: {img_path}", file=sys.stderr)
        return None
    client = get_client()
    project_id = get_project_id(client)
    print(f"[lovart inpaint] 上传图片: {img_path.name} ...", flush=True)
    try:
        cdn_url = client.upload_file(str(img_path))
    except AgentSkillError as e:
        print(f"[lovart inpaint] 上传失败: {e.message}", file=sys.stderr)
        return None
    result = _chat_with_mode_fallback(
        client, project_id, prompt,
        attachments=[cdn_url],
    )
    if result.get("final_status") != "done":
        print(f"[lovart inpaint] 失败，状态: {result.get('final_status')}", file=sys.stderr)
        return None
    return _download_first_image(result, output_path)


def edit_upscale(
    image_path: str,
    output_path: str,
) -> Path | None:
    """Upscale：上传图片，要求 Lovart 超分放大。"""
    img_path = Path(image_path).resolve()
    if not img_path.is_file():
        print(f"[lovart upscale] 图片不存在: {img_path}", file=sys.stderr)
        return None
    client = get_client()
    project_id = get_project_id(client)
    print(f"[lovart upscale] 上传图片: {img_path.name} ...", flush=True)
    try:
        cdn_url = client.upload_file(str(img_path))
    except AgentSkillError as e:
        print(f"[lovart upscale] 上传失败: {e.message}", file=sys.stderr)
        return None
    result = _chat_with_mode_fallback(
        client, project_id, "upscale this image",
        attachments=[cdn_url],
        include_tools=["upscale_image"],
    )
    if result.get("final_status") != "done":
        print(f"[lovart upscale] 失败，状态: {result.get('final_status')}", file=sys.stderr)
        return None
    return _download_first_image(result, output_path)
