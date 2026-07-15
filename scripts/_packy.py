#!/usr/bin/env python3
"""
统一 Packy 多后端 key 处理模块。

将 run_banner.py、run_full_with_custom_prompt.py、run_all_presets.py、
run_hd.py、run_from_a4.py 中重复的 ~50 行 Packy 处理逻辑抽取到此。

用法:
    from _packy import apply_packy_backend
    apply_packy_backend(args)  # args 是 argparse.Namespace
"""
import os
import sys
from _env import _ENV_FILE, _parse_env, get_env_key


def _packy_base_url() -> str:
    """返回 Packy API 基址，优先环境变量 GOOGLE_GEMINI_BASE_URL"""
    return os.environ.get("GOOGLE_GEMINI_BASE_URL", "https://www.packyapi.com").strip()


def apply_packy_backend(args, *, allow_packy3s: bool = True) -> None:
    """
    根据 args 中的 --packy / --packy7s / --packy3s / --packygpt / --moxingpt
    设置对应的 GOOGLE_GEMINI_BASE_URL、GEMINI_API_KEY、GEMINI_MODEL 等。

    allow_packy3s: 是否允许 --packy3s 参数（默认 True，run_banner.py 等不支持的可传 False）

    架构：Key 配置与生图后端选择分离。
      - Key 配置：各 --packy* flag 独立设置 GEMINI_API_KEY（不 return）
      - 生图后端：独立 if/elif 链选择 BANNER_IMAGE_BACKEND
    支持 --packygpt（生图） + --packy7s（编辑） 并行。

    Key 回退链（缺失专用 key 时不报错，自动回退）：
      --packy7s: PACKY7S_API_KEY → GEMINI_API_KEY
      --packy3s: PACKY3S_API_KEY → GEMINI_API_KEY_ALT
    """
    parsed = _parse_env()

    # ══════════════ 块1: Gemini 图像编辑 Key 配置 ══════════════
    # 各个 --packy* flag 只设置 GEMINI_API_KEY 和 GOOGLE_GEMINI_BASE_URL，不 return
    # 允许后续块2的 --packygpt 继续覆盖生图后端

    # --packy7s
    if getattr(args, "packy7s", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        p7s = get_env_key("PACKY7S_API_KEY", "GEMINI_API_KEY")
        if p7s and str(p7s).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(p7s).strip()
        else:
            print("Error: 使用 --packy7s 时请在 .env 中设置 PACKY7S_API_KEY 或 GEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --packy3s
    if allow_packy3s and getattr(args, "packy3s", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        p3s = get_env_key("PACKY3S_API_KEY", "GEMINI_API_KEY_ALT")
        if p3s and str(p3s).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(p3s).strip()
        else:
            print("Error: 使用 --packy3s 时请在 .env 中设置 PACKY3S_API_KEY 或 GEMINI_API_KEY_ALT（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --packy
    if getattr(args, "packy", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        packy_key = get_env_key("PACKY_API_KEY", "GEMINI_API_KEY")
        if packy_key and str(packy_key).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(packy_key).strip()
        else:
            print("Error: 使用 --packy 时请在 .env 中设置 PACKY_API_KEY 或 GEMINI_API_KEY（Packy 的 sk- 令牌）", file=sys.stderr)
            sys.exit(1)

    # --micugemini：通过 micuapi.ai 调用 Gemini，编辑走 micuapi.ai Gemini 兼容端点
    if getattr(args, "micugemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.micuapi.ai"
        mg_key = get_env_key("MICUGEMINI_API_KEY")
        if mg_key and str(mg_key).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(mg_key).strip()
        else:
            print("Error: 使用 --micugemini 时请在 .env 中设置 MICUGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --xingchengemini：通过 api.centos.hk 替换 Gemini Key 代理，编辑仍走 Gemini 原生 API（模型:gemini-3-pro-image-preview / gemini-3.1-flash-image-preview）
    if getattr(args, "xingchengemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk").strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview"
        os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"
        xcg_key = get_env_key("XINGCHENGEMINI_API_KEY")
        if xcg_key and str(xcg_key).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(xcg_key).strip()
        else:
            print("Error: 使用 --xingchengemini 时请在 .env 中设置 XINGCHENGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --xingchengemini1：XingchenGemini 多 Key 轮换 1 号（与 --xingchengemini 相同逻辑，使用 XINGCHENGEMINI1_API_KEY）
    if getattr(args, "xingchengemini1", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI1_BASE_URL", os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk")).strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview"
        os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"
        xcg1_key = get_env_key("XINGCHENGEMINI1_API_KEY")
        if xcg1_key and str(xcg1_key).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(xcg1_key).strip()
        else:
            print("Error: 使用 --xingchengemini1 时请在 .env 中设置 XINGCHENGEMINI1_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --moxingemini：通过 moxin.studio 替换 Gemini Key 代理，与 --moxingpt 组合时编辑走 chat/completions
    if getattr(args, "moxingemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = os.environ.get("MOXINGEMINI_MODEL", "[次]gemini-3.1-flash-image-preview,[次]gemini-3-pro-image")
        os.environ["GEMINI_VISION_MODEL"] = os.environ.get("MOXINGEMINI_VISION_MODEL", "[次]gemini-3.1-flash-image-preview,[次]gemini-3-pro-image-preview")
        mxg_key = get_env_key("MOXINGEMINI_API_KEY")
        if mxg_key and str(mxg_key).strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = str(mxg_key).strip()
        else:
            print("Error: 使用 --moxingemini 时请在 .env 中设置 MOXINGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # ══════════════ 块2: 生图后端选择 ══════════════
    # 优先级：--packygpt（gpt-image-2） > --packy*（Gemini 生图）
    # 不参与块1的 Key 配置，仅设置 BANNER_IMAGE_BACKEND 和 OPENAI_* 变量

    # --packygpt：OpenAI 兼容接口，gpt-image-2 生图；不覆写 GEMINI_API_KEY
    if getattr(args, "packygpt", False):
        packygpt_key = get_env_key("PACKYGPT_API_KEY")
        if packygpt_key and str(packygpt_key).strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = str(packygpt_key).strip()
            # 优先读 PACKYGPT_BASE_URL，回退到 GOOGLE_GEMINI_BASE_URL，最终默认 packyapi.com
            packygpt_base = (
                os.environ.get("PACKYGPT_BASE_URL", "").strip()
                or _packy_base_url()
            )
            os.environ["OPENAI_BASE_URL"] = packygpt_base
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["BANNER_IMAGE_BACKEND"] = "packygpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -packygpt 时请在 .env 中设置 PACKYGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --xingchengpt：通过 newapi.pro 调用 gpt-image-2，OpenAI 兼容接口
    elif getattr(args, "xingchengpt", False):
        xingchengpt_key = get_env_key("XINGCHENGGPT_API_KEY")
        if xingchengpt_key and str(xingchengpt_key).strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = str(xingchengpt_key).strip()
            xingchengpt_base = (
                os.environ.get("XINGCHENGGPT_BASE_URL", "").strip()
                or os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
                or "https://www.packyapi.com"
            )
            os.environ["OPENAI_BASE_URL"] = xingchengpt_base
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["XINGCHENGGPT_API_KEY"] = str(xingchengpt_key).strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "xingchengpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -xingchengpt 时请在 .env 中设置 XINGCHENGGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --xinchengpt：通过 api.centos.hk 调用 gpt-image-2，OpenAI 兼容接口
    elif getattr(args, "xinchengpt", False):
        xinchengpt_key = get_env_key("XINCHENGPT_API_KEY")
        if xinchengpt_key and str(xinchengpt_key).strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = str(xinchengpt_key).strip()
            xinchengpt_base = (
                os.environ.get("XINCHENGPT_BASE_URL", "").strip()
                or os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
                or "https://api.centos.hk"
            )
            os.environ["OPENAI_BASE_URL"] = xinchengpt_base
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["XINCHENGPT_API_KEY"] = str(xinchengpt_key).strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "xinchengpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -xinchengpt 时请在 .env 中设置 XINCHENGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --micugpt2：通过 micuapi.ai 调用 gpt-image-2，端点 /v1/chat/completions
    elif getattr(args, "micugpt2", False):
        micugpt2_key = get_env_key("MICUAPI_API_KEY")
        if micugpt2_key and str(micugpt2_key).strip().startswith("sk-"):
            os.environ["MICUAPI_API_KEY"] = str(micugpt2_key).strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -micugpt2 时请在 .env 中设置 MICUAPI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --micugemini：通过 micuapi.ai 调用 gemini-3-flash-preview-thinking，端点 /v1/chat/completions
    elif getattr(args, "micugemini", False):
        micugemini_key = get_env_key("MICUGEMINI_API_KEY")
        if micugemini_key and str(micugemini_key).strip().startswith("sk-"):
            os.environ["MICUGEMINI_API_KEY"] = str(micugemini_key).strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "micugemini"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -micugemini 时请在 .env 中设置 MICUGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --moxingpt：通过 moxin.studio 调用 gpt-image-2，NewAPI channel 连接
    elif getattr(args, "moxingpt", False):
        moxingpt_key = get_env_key("MOXINGPT_API_KEY")
        if moxingpt_key and str(moxingpt_key).strip().startswith("sk-"):
            os.environ["MOXINGPT_API_KEY"] = str(moxingpt_key).strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "moxingpt"
            if getattr(args, "moxingemini", False) or getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -moxingpt 时请在 .env 中设置 MOXINGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --moxingemini：块1已替换 GEMINI_API_KEY，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "moxingemini", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    # --xingchengemini1：块1已替换 GEMINI_API_KEY，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "xingchengemini1", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    # --xingchengemini：块1已替换 GEMINI_API_KEY，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "xingchengemini", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy7s", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy3s", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"
