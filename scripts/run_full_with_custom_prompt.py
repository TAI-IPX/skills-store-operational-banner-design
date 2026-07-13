#!/usr/bin/env python3
"""
方案 A：一条命令跑完「Step 1 自定义描述生背景 + Step 2 多尺寸叠字」。

用法示例：
  python scripts/run_full_with_custom_prompt.py --description "开学季，清新校园风，书本与文具，浅蓝绿色调" --main-title "开学回血补给站" --subtitle "好物低至9.9" --group "商店日常" --model jimeng

  # 带参考图（即梦 i2i）：
  python scripts/run_full_with_custom_prompt.py --description "同上风格" --ref input/ref.png --main-title "主标题" --subtitle "副标题" -g "商店日常" --model jimeng

参数：
  --description      整段生图描述（Step 1 用）；与 --description-file 二选一
  --description-file  从 UTF-8 文件读取生图描述（可在 Cursor 中让 AI 根据主副标题生成后保存）
   仅主副标题时：默认不自动生成描述，需提供上述其一；若传 --prompt-engine 则用 prompt-engine 完整管线（6步推导+质检评分）调用 Gemini 生成；若传 --prompt-engine-claude 则用 Claude 生成
   --main-title   主标题（Step 2 叠字）；也可用 --main-title-file 从文件读取
   --subtitle     副标题（Step 2 叠字）；也可用 --subtitle-file 从文件读取
   --prompt-optimizer-template  确定性模板引擎（12种风格+10种构图，不调用LLM）
   --prompt-engine     未提供描述时用 prompt-engine 完整管线（PROMPT_SYSTEM .md）调用 Gemini 生成描述；6步推导+质检评分 (推荐)
   --prompt-engine-claude  同上，使用 Claude 作为推导引擎（更精准，需 ANTHROPIC_API_KEY）
  --ref / -i     可选，Step 1 参考图（即梦/Gemini 图生图）。-g 开放平台 且未传 -i 时自动使用 input/open_platform_style_ref.png（若存在）
  --group / -g   可选，可多次传入合并分组（如 -g LZ全部 -g 商店日常）；也可用 --group-file 每行一个分组
  --model / -M   可选，生图模型：jimeng / gemini / t8-gemini / t8-jimeng 等
  --jimeng-smart-ref  可选，即梦图生图时使用 3.0 智能参考（与 Web 端「智能参考」一致）
  --width / -W   可选，生图宽度（即梦等接口常用 1024，需与 --height 同时指定）
  --height / -H  可选，生图高度（即梦常用 1024）
"""
import argparse
import atexit
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 路径约束验证
from _paths import validate_paths, sanitize_dirname
validate_paths()

_current_run_dir: Path | None = None

def _cleanup_empty_run_dir() -> None:
    if _current_run_dir is not None and _current_run_dir.is_dir():
        try:
            if not any(_current_run_dir.iterdir()):
                _current_run_dir.rmdir()
        except OSError:
            pass

atexit.register(_cleanup_empty_run_dir)

# 从项目根 .env 加载 API 与后端配置，供本进程及 Step 1 子进程继承
from _env import load_env, get_env_key
_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_PROMPT_OPTIMIZER_MODEL",
    "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY",
    "PACKYGPT_API_KEY",
    "MICUAPI_API_KEY",
    "MICUGEMINI_API_KEY",
    "MOXINGPT_API_KEY",
    "MOXINGPT_BASE_URL",
    "MOXINGPT_MODEL",
    "MOXINGEMINI_API_KEY",
    "MOXINGEMINI_BASE_URL",
    "XINGCHENGGPT_API_KEY",
    "XINGCHENGGPT_BASE_URL",
    "XINGCHENGEMINI_API_KEY",
    "XINGCHENGEMINI1_API_KEY",
    "XINGCHENGEMINI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "CLAUDE_PROMPT_OPTIMIZER_MODEL",
    "ANTHROPIC_API_BASE_URL",
    "T8STAR_API_KEY",
    "BANNER_IMAGE_BACKEND",
    "T8STAR_IMAGE_MODEL",
    "T8STAR_BASE_URL",
)
load_env(_ENV_KEYS)

def _packy_base_url() -> str:
    """返回 Packy API 基址，优先环境变量"""
    return os.environ.get("GOOGLE_GEMINI_BASE_URL", "https://www.packyapi.com").strip()
sys.path.insert(0, str(ROOT))
from scripts.ensure_python import get_python_exe

PYTHON_EXE = get_python_exe()
OUTPUT_DIR = ROOT / "output"
STEP1_SCRIPT = ROOT / ".claude" / "skills" / "banner-background-from-description" / "scripts" / "generate_from_description.py"
STEP2_SCRIPT = ROOT / "scripts" / "run_all_presets.py"
# -g 开放平台 且未传 --ref 时使用的默认参考图（放一张开放平台风格 Banner 即可，用于图生图统一风格）
OPEN_PLATFORM_DEFAULT_REF = ROOT / "input" / "open_platform_style_ref.png"

_SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if _SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(_SPEC_SCRIPTS))
import spec as _spec


def main() -> None:
    global _current_run_dir
    parser = argparse.ArgumentParser(
        description="方案 A：一条命令执行 Step 1 自定义描述生背景 + Step 2 多尺寸叠字",
    )
    parser.add_argument("--description", default=None, help="整段生图描述（与 --description-file 二选一）")
    parser.add_argument("--description-file", dest="description_file", default=None, help="从 UTF-8 文件读取生图描述")
    parser.add_argument("--main-title", "-m", default=None, dest="main_title", help="主标题（与 --main-title-file 二选一）")
    parser.add_argument("--main-title-file", dest="main_title_file", default=None, help="从 UTF-8 文件读取主标题（一行）")
    parser.add_argument("--subtitle", "-s", default="", dest="subtitle", help="副标题")
    parser.add_argument("--subtitle-file", dest="subtitle_file", default=None, help="从 UTF-8 文件读取副标题（一行）；覆盖 -s")
    parser.add_argument("--ref", "-i", dest="ref", default=None, help="可选：Step 1 参考图路径（即梦 i2i）；开放平台相关分组且无 -i 时可用默认参考图")
    parser.add_argument(
        "--group",
        "-g",
        dest="genre_groups",
        action="append",
        default=None,
        help="场景分组，可重复传入合并，如 -g LZ全部 -g 开放平台banner2560*496",
    )
    parser.add_argument(
        "--group-file",
        dest="group_file",
        default=None,
        help="从 UTF-8 文件读取分组名，每行一个（与命令行 -g 合并）",
    )
    parser.add_argument(
        "--model",
        "-M",
        dest="model",
        default=None,
        help="生图模型 jimeng / gemini / t8-gemini / t8-jimeng 等",
    )
    parser.add_argument("--packy", "-packy", action="store_true", dest="packy", help="使用 Packy API 作为 Gemini 后端（需 .env 中 GOOGLE_GEMINI_BASE_URL 或 PACKY_API_KEY）")
    parser.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s", help="使用 Packy7s 专用 key 作为 Gemini 后端（需 .env 中 PACKY7S_API_KEY）")
    parser.add_argument("--packy3s", "-packy3s", action="store_true", dest="packy3s", help="使用 Packy3s 专用 key 作为 Gemini 后端（需 .env 中 PACKY3S_API_KEY）")
    parser.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt", help="使用 PackyGPT 专用 key 调用 gpt-image-2（需 .env 中 PACKYGPT_API_KEY）")
    parser.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2", help="使用 MicuAPI 专用 key 调用 gpt-image-2（需 .env 中 MICUAPI_API_KEY，端点 /v1/chat/completions）")
    parser.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini", help="使用 MicuAPI 专用 key 调用 gemini-3-flash-preview-thinking（需 .env 中 MICUGEMINI_API_KEY，端点 /v1/chat/completions）")
    parser.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini", help="使用 XingchenGemini 专用 key 调用 gemini-3.1-flash-image-preview（需 .env 中 XINGCHENGEMINI_API_KEY，端点 /v1/chat/completions）")
    parser.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1", help="使用 XingchenGemini 多 Key 轮换 1 号 key（需 .env 中 XINGCHENGEMINI1_API_KEY）")
    parser.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt", help="使用 MoxinGPT 专用 key 调用 gpt-image-2（需 .env 中 MOXINGPT_API_KEY，端点 /v1/images/generations）")
    parser.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini", help="使用 MoxinGemini 专用 key 调用 Gemini（需 .env 中 MOXINGEMINI_API_KEY，与 --moxingpt 组合时编辑走 chat/completions）")
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt", help="使用 XingchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINGCHENGGPT_API_KEY，端点 /v1/images/generations）")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt", help="使用 XinchenGPT 专用 key 调用 gpt-image-2（需 .env 中 XINCHENGPT_API_KEY，端点 /v1/images/generations）")
    parser.add_argument("--prompt-optimizer-template", action="store_true", dest="prompt_optimizer_template", help="未提供描述时用确定性模板引擎根据主副标题生成描述（12种风格+10种构图，不调用LLM）")
    parser.add_argument("--mode", default="auto", choices=("auto", "product", "campaign", "collection"), dest="mode", help="场景模式（仅 --prompt-optimizer-template 时有效；auto=自动检测）")
    parser.add_argument("--subject", default="", dest="subject", help="手动指定主体视觉描述（仅 --prompt-optimizer-template 时有效；覆盖自动推导）")
    parser.add_argument("--prompt-format", default="compact", choices=("compact", "full"), dest="prompt_format", help="Prompt 格式: compact=~300字自然语言（nano-banana/Gemini） / full=~2400字约束式（gpt-image-2）")
    parser.add_argument("--prompt-engine", action="store_true", dest="prompt_engine", help="未提供描述时用 prompt-engine 完整管线（PROMPT_SYSTEM .md）调用 Gemini 生成描述；6步推导+质检评分，质量更高")
    parser.add_argument("--prompt-engine-claude", action="store_true", dest="prompt_engine_claude", help="同上，但使用 Anthropic Claude 作为推导引擎（需 ANTHROPIC_API_KEY）")
    parser.add_argument("--jimeng-smart-ref", action="store_true", dest="jimeng_smart_ref", help="即梦图生图时使用 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致")
    parser.add_argument("--text-art", default=None, dest="text_art", metavar="DESC", help="文字艺术字描述（走独立管线：生图→BiRefNet抠图→粘贴到 text_art_rect）")
    parser.add_argument("--dialog", default=None, dest="dialog", metavar="DESC", help="对话框描述（走独立管线：生图→BiRefNet抠图→粘贴到 dialog_rect）")
    parser.add_argument("--skip-remove-text", action="store_true", dest="skip_remove_text", help="跳过 A1 去干扰（Gemini remove-text），图生图时建议传入")
    parser.add_argument("--width", "-W", type=int, default=None, help="可选：生图宽度（需与 --height 同时指定）")
    parser.add_argument("--height", "-H", type=int, default=None, help="可选：生图高度")
    parser.add_argument("--kv", default=None, dest="kv", help="KV 图路径（-g 活动长图 / -g 战报 时有效；战报场景有 KV 则跳过 Step 1）")
    parser.add_argument("--font-title", default=None, dest="font_title", help="活动长图标题字体路径（-g 活动长图 时有效）")
    parser.add_argument("--font-yahei", default=None, dest="font_yahei", help="活动长图微软雅黑路径")
    parser.add_argument("--event-date", default=None, dest="event_date", help="活动时间（-g 活动长图 时有效）")
    parser.add_argument("--event-desc", default=None, dest="event_desc", help="参与方式描述（-g 活动长图 时有效）")
    parser.add_argument("--prize-dir", default=None, dest="prize_dir", help="奖品图片目录（-g 活动长图 时有效）")
    parser.add_argument("--prize-order", default=None, dest="prize_order", help="奖品顺序，| 分隔文件名关键词")
    parser.add_argument("--rules", default=None, dest="rules", help="规则文案，| 分隔多条（-g 活动长图 时有效）")
    parser.add_argument("--kv-scene", default=None, dest="kv_scene", help="KV画面描述，用于AI生成延续背景")
    parser.add_argument("--game-name", default=None, dest="game_name", help="游戏名称（用于AI prompt）")
    parser.add_argument("--game-style", default=None, dest="game_style", help="游戏风格描述（用于AI prompt）")
    parser.add_argument("--section1", default=None, dest="section1", help="第一区块标题（默认：福利活动）")
    parser.add_argument("--section2", default=None, dest="section2", help="第二区块标题（默认：活动规则）")
    parser.add_argument("--report-dir", default=None, dest="report_dir",
                        help="战报素材目录路径（-g 战报 时有效；不填则从 input/uploads/ 自动构建）")
    parser.add_argument("--bar-text", default=None, dest="bar_text", help="烽火条文案（-g 战报 时有效）")
    parser.add_argument("--stat-exposure", default=None, dest="stat_exposure", help="曝光数据文字（-g 战报 时有效）")
    parser.add_argument("--stat-download", default=None, dest="stat_download", help="下载数据文字（-g 战报 时有效）")
    parser.add_argument("--stat-group", action="append", default=None, dest="stat_groups",
                        help="多组数据模块，格式 '标题|标签1|值1|标签2|值2'，可重复指定（-g 战报 时有效）")
    parser.add_argument("--font-family", default=None, dest="font_family",
                        help="指定字体名称，扫描系统字体目录匹配（-g 战报 时有效，如 '造字工房启黑体'）")
    parser.add_argument("--no-stats", action="store_true", dest="no_stats", help="隐藏战报数据指标（-g 战报 时有效）")
    parser.add_argument("--ranking-csv", default=None, dest="ranking_csv",
                        help="排行榜 CSV 数据文件路径（-g 排行榜 时有效）")
    parser.add_argument("--ranking-theme", default=None, dest="ranking_theme",
                        choices=["red", "dark", "green", "gold", "blue"], help="排行榜主题色（-g 排行榜 时有效，默认 gold）")
    # 邮件长图专用参数
    parser.add_argument("--method-dir", default=None, dest="method_dir", help="EVENT02 参与方法截图目录（-g 邮件长图 时有效）")
    parser.add_argument("--method-desc", default=None, dest="method_desc", help="EVENT02 参与方法文字，| 分隔多段（-g 邮件长图 时有效）")
    parser.add_argument("--history-dir", default=None, dest="history_dir", help="EVENT03 往期中奖截图目录（-g 邮件长图 时有效）")
    parser.add_argument("--history-order", default=None, dest="history_order", help="EVENT03 往期中奖排序关键词，| 分隔（-g 邮件长图 时有效）")
    parser.add_argument("--intro-text", default=None, dest="intro_text", help="EVENT04 游戏介绍正文（-g 邮件长图 时有效）")
    args = parser.parse_args()

    # ══════════════ 块1: Gemini 图像编辑 Key 配置 ══════════════
    # 独立 if 块（非 elif），允许多个 flag 同时生效
    # Key 回退链：专用 key → GEMINI_API_KEY / GEMINI_API_KEY_ALT

    if getattr(args, "packy7s", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        p7s = get_env_key("PACKY7S_API_KEY", "GEMINI_API_KEY")
        if p7s and p7s.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = p7s.strip()
        else:
            print("Error: 使用 -packy7s 时请在 .env 中设置 PACKY7S_API_KEY 或 GEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "packy3s", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        p3s = get_env_key("PACKY3S_API_KEY", "GEMINI_API_KEY_ALT")
        if p3s and p3s.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = p3s.strip()
        else:
            print("Error: 使用 -packy3s 时请在 .env 中设置 PACKY3S_API_KEY 或 GEMINI_API_KEY_ALT（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "packy", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = _packy_base_url()
        packy_key = get_env_key("PACKY_API_KEY", "GEMINI_API_KEY")
        if packy_key and packy_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = packy_key.strip()
        else:
            print("Error: 使用 --packy 时请在 .env 中设置 PACKY_API_KEY 或 GEMINI_API_KEY（Packy 的 sk- 令牌）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "micugemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = "https://www.micuapi.ai"
        mg_key = get_env_key("MICUGEMINI_API_KEY")
        if mg_key and mg_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = mg_key.strip()
        else:
            print("Error: 使用 -micugemini 时请在 .env 中设置 MICUGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xingchengemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk").strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview"
        os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"
        xcg_key = get_env_key("XINGCHENGEMINI_API_KEY")
        if xcg_key and xcg_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = xcg_key.strip()
        else:
            print("Error: 使用 -xingchengemini 时请在 .env 中设置 XINGCHENGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "xingchengemini1", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("XINGCHENGEMINI1_BASE_URL", os.environ.get("XINGCHENGEMINI_BASE_URL", "https://api.centos.hk")).strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-image-preview,gemini-3-pro-image-preview"
        if not os.environ.get("GEMINI_VISION_MODEL"):
            os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"
        xcg1_key = get_env_key("XINGCHENGEMINI1_API_KEY")
        if xcg1_key and xcg1_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = xcg1_key.strip()
        else:
            print("Error: 使用 -xingchengemini1 时请在 .env 中设置 XINGCHENGEMINI1_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "moxingemini", False):
        os.environ["GOOGLE_GEMINI_BASE_URL"] = os.environ.get("MOXINGEMINI_BASE_URL", "https://www.moxin.studio").strip()
        if not os.environ.get("GEMINI_MODEL"):
            os.environ["GEMINI_MODEL"] = os.environ.get("MOXINGEMINI_MODEL", "[特价次卡]gemini-3.1-pro-preview,[次]gemini-3-pro-image")
        os.environ["GEMINI_VISION_MODEL"] = os.environ.get("MOXINGEMINI_VISION_MODEL", "[特价次卡]gemini-3.1-pro-preview,[特价次卡]gemini-3.1-pro-preview-think,[特价次卡]gemini-2.5-pro")
        mxg_key = get_env_key("MOXINGEMINI_API_KEY")
        if mxg_key and mxg_key.strip().startswith("sk-"):
            os.environ["GEMINI_API_KEY"] = mxg_key.strip()
        else:
            print("Error: 使用 -moxingemini 时请在 .env 中设置 MOXINGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # ══════════════ 块2: 生图后端选择 ══════════════
    # --packygpt 优先（gpt-image-2），--micugpt2 其次，--packy* 回退 Gemini 生图
    if getattr(args, "packygpt", False):
        packygpt_key = get_env_key("PACKYGPT_API_KEY")
        if packygpt_key and packygpt_key.strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = packygpt_key.strip()
            os.environ["OPENAI_BASE_URL"] = _packy_base_url()
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["BANNER_IMAGE_BACKEND"] = "packygpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -packygpt 时请在 .env 中设置 PACKYGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    elif getattr(args, "xingchengpt", False):
        xingchengpt_key = get_env_key("XINGCHENGGPT_API_KEY")
        if xingchengpt_key and xingchengpt_key.strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = xingchengpt_key.strip()
            xingchengpt_base = (
                os.environ.get("XINGCHENGGPT_BASE_URL", "").strip()
                or os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
                or _packy_base_url()
            )
            os.environ["OPENAI_BASE_URL"] = xingchengpt_base
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["XINGCHENGGPT_API_KEY"] = xingchengpt_key.strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "xingchengpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -xingchengpt 时请在 .env 中设置 XINGCHENGGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    elif getattr(args, "xinchengpt", False):
        xinchengpt_key = get_env_key("XINCHENGPT_API_KEY")
        if xinchengpt_key and xinchengpt_key.strip().startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = xinchengpt_key.strip()
            xinchengpt_base = (
                os.environ.get("XINCHENGPT_BASE_URL", "").strip()
                or os.environ.get("GOOGLE_GEMINI_BASE_URL", "").strip()
                or "https://api.centos.hk"
            )
            os.environ["OPENAI_BASE_URL"] = xinchengpt_base
            os.environ["OPENAI_MODEL"] = "gpt-image-2"
            os.environ["XINCHENGPT_API_KEY"] = xinchengpt_key.strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "xinchengpt"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -xinchengpt 时请在 .env 中设置 XINCHENGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    elif getattr(args, "micugpt2", False):
        micugpt2_key = get_env_key("MICUAPI_API_KEY")
        if micugpt2_key and micugpt2_key.strip().startswith("sk-"):
            os.environ["MICUAPI_API_KEY"] = micugpt2_key.strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "micugpt2"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -micugpt2 时请在 .env 中设置 MICUAPI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    elif getattr(args, "micugemini", False):
        micugemini_key = get_env_key("MICUGEMINI_API_KEY")
        if micugemini_key and micugemini_key.strip().startswith("sk-"):
            os.environ["MICUGEMINI_API_KEY"] = micugemini_key.strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "micugemini"
            if getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -micugemini 时请在 .env 中设置 MICUGEMINI_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --xingchengemini1：块1已替换 GEMINI_API_KEY+GOOGLE_GEMINI_BASE_URL，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "xingchengemini1", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    # --xingchengemini：块1已替换 GEMINI_API_KEY+GOOGLE_GEMINI_BASE_URL，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "xingchengemini", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "moxingpt", False):
        moxingpt_key = get_env_key("MOXINGPT_API_KEY")
        if moxingpt_key and moxingpt_key.strip().startswith("sk-"):
            os.environ["MOXINGPT_API_KEY"] = moxingpt_key.strip()
            os.environ["BANNER_IMAGE_BACKEND"] = "moxingpt"
            if getattr(args, "moxingemini", False) or getattr(args, "xingchengemini1", False) or getattr(args, "xingchengemini", False) or getattr(args, "packy7s", False) or getattr(args, "packy", False):
                os.environ["BANNER_EDIT_BACKEND"] = "gemini"
        else:
            print("Error: 使用 -moxingpt 时请在 .env 中设置 MOXINGPT_API_KEY（且以 sk- 开头）", file=sys.stderr)
            sys.exit(1)

    # --moxingemini：块1已替换 GEMINI_API_KEY+GOOGLE_GEMINI_BASE_URL，块2设 BANNER_IMAGE_BACKEND=gemini 走原生 API
    elif getattr(args, "moxingemini", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy7s", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy3s", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    elif getattr(args, "packy", False):
        os.environ["BANNER_IMAGE_BACKEND"] = "gemini"

    # 先解析主标题、副标题（Step 2 叠字与 run_dir 命名必需；仅主副标题时也用于描述生成）
    if args.main_title_file:
        pt = Path(args.main_title_file).resolve()
        if not pt.is_file():
            print(f"Error: 主标题文件不存在: {pt}", file=sys.stderr)
            sys.exit(1)
        main_title = pt.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    elif args.main_title:
        main_title = args.main_title
    else:
        print("Error: 请提供 --main-title 或 --main-title-file。", file=sys.stderr)
        sys.exit(1)

    if args.subtitle_file:
        ps = Path(args.subtitle_file).resolve()
        if ps.is_file():
            subtitle = ps.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        else:
            subtitle = args.subtitle or ""
    else:
        subtitle = args.subtitle or ""

    groups: list[str] = []
    if getattr(args, "genre_groups", None):
        for _g in args.genre_groups:
            _g = (_g or "").strip()
            if _g:
                groups.append(_g)
    if args.group_file:
        pg = Path(args.group_file).resolve()
        if pg.is_file():
            for line in pg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    groups.append(line)

    # -g 战报 早退分支：当 KV 可用时，跳过描述推导 + Step 1 + Step 1b/1c，直接路由到 run_battle_report.py
    _battle_report_kv = None
    if "战报" in groups:
        # 检测 KV 来源：--kv > --ref/-i > --report-dir 内 KV.jpg
        if getattr(args, "kv", None) and Path(args.kv).is_file():
            _battle_report_kv = Path(args.kv)
        elif args.ref and Path(args.ref).resolve().is_file():
            _battle_report_kv = Path(args.ref).resolve()
        elif getattr(args, "report_dir", None):
            _rd = Path(args.report_dir)
            for _candidate in ("KV.jpg", "KV.png", "KV.jpeg", "KV.webp"):
                _p = _rd / _candidate
                if _p.is_file():
                    _battle_report_kv = _p
                    break
            # 也检查 assets_dir/KV.jpg（report_dir 可能直接指向素材根）
            if _battle_report_kv is None:
                for _candidate in ("KV.jpg", "KV.png", "KV.jpeg", "KV.webp"):
                    _p = _rd / "assets" / _candidate
                    if _p.is_file():
                        _battle_report_kv = _p
                        break
        # input/uploads/current.png 不作为战报 KV 来源（用户需显式指定）
        if _battle_report_kv:
            print(f"[方案 A] 战报早退: 检测到 KV={_battle_report_kv.name}，跳过描述推导 + Step 1，直接进入战报合成",
                  flush=True)
            # 跳过描述推导 → 跳过 Step 1 → 跳过 Step 1b/1c/1d → 直接路由
            _skip_to_battle_report = True
        else:
            print("[方案 A] 战报: 未检测到 KV，仍需 Step 1 生图生成 KV", flush=True)
            _skip_to_battle_report = False
    else:
        _skip_to_battle_report = False

    # -g 排行榜 永远早退：无需文生图背景，跳过 Step 1
    RANKING_GROUP = "排行榜"
    has_ranking = RANKING_GROUP in groups
    if has_ranking:
        print("[方案 A] 排行榜早退: 跳过描述推导 + Step 1，直接进入排行榜合成", flush=True)

    # -g 邮件长图 早退：有 KV 时跳过描述推导 + Step 1
    _email_poster_kv = None
    if "邮件长图" in groups:
        if getattr(args, "kv", None) and Path(args.kv).is_file():
            _email_poster_kv = Path(args.kv)
        elif args.ref and Path(args.ref).resolve().is_file():
            _email_poster_kv = Path(args.ref).resolve()
        if _email_poster_kv:
            print(f"[方案 A] 邮件长图早退: 检测到 KV={_email_poster_kv.name}，跳过描述推导 + Step 1",
                  flush=True)
        else:
            print("[方案 A] 邮件长图: 未检测到 KV，仍需 Step 1 生图生成 KV", flush=True)

    _skip_step1 = _skip_to_battle_report or has_ranking or (_email_poster_kv is not None)

    if not _skip_step1:
        # 描述来源：文件 / 参数 / 或仅主副标题且传入 --prompt-engine / --prompt-optimizer-template 时自动生成（否则期望由 Cursor 等「自己的模型」产出后以文件传入）
        _engine_trace = None
        if args.description_file:
            path = Path(args.description_file).resolve()
            if not path.is_file():
                print(f"Error: 描述文件不存在: {path}", file=sys.stderr)
                sys.exit(1)
            description = path.read_text(encoding="utf-8").strip()
        elif args.description:
            description = args.description
        elif (
            getattr(args, "prompt_optimizer_template", False)
            or getattr(args, "prompt_engine", False)
            or getattr(args, "prompt_engine_claude", False)
        ):
            opt_count = sum([
                getattr(args, "prompt_optimizer_template", False),
                getattr(args, "prompt_engine", False),
                getattr(args, "prompt_engine_claude", False),
            ])
            if opt_count > 1:
                print("Error: --prompt-optimizer-template / --prompt-engine / --prompt-engine-claude 请三选一。", file=sys.stderr)
                sys.exit(1)
            use_template = getattr(args, "prompt_optimizer_template", False)
            use_engine = getattr(args, "prompt_engine", False)
            use_engine_claude = getattr(args, "prompt_engine_claude", False)
            if use_engine or use_engine_claude:
                label = "Anthropic Claude" if use_engine_claude else "Gemini"
            else:
                label = "确定性模板引擎（12风格+10构图）"
            mode_label = "prompt-engine 完整管线" if (use_engine or use_engine_claude) else "prompt-optimizer-template"
            print(
                f"[方案 A] 未提供描述，根据主副标题用 {label} {mode_label} 生成文生图描述...",
                flush=True,
            )
            sys.path.insert(0, str(STEP1_SCRIPT.parent))
            import generate_from_description as _gfd
            _engine_trace = None
            try:
                if use_engine or use_engine_claude:
                    backend = "claude" if use_engine_claude else "gemini"
                    description, full_trace = _gfd.prompt_optimizer_engine(
                        main_title, subtitle or "",
                        backend=backend,
                        save_trace=False,
                    )
                    _engine_trace = full_trace
                else:
                    description = _gfd.prompt_optimizer_template(
                        main_title, subtitle or "",
                        mode=getattr(args, "mode", "auto"),
                        subject_override=getattr(args, "subject", ""),
                        prompt_format=getattr(args, "prompt_format", "compact"),
                    )
            except RuntimeError as e:
                print(f"Error: {mode_label} 失败: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"[方案 A] {mode_label} 生成描述: {description[:80]}...", flush=True)
            if use_engine or use_engine_claude:
                print(f"[方案 A] prompt-engine 完整推导: {len(_engine_trace)} 字符", flush=True)
        else:
            print(
                "Error: 未提供描述。请使用 --description 或 --description-file 传入；或传入 --prompt-optimizer-template / --prompt-engine / --prompt-engine-claude 生成描述。",
                file=sys.stderr,
            )
            sys.exit(1)

        if not STEP1_SCRIPT.is_file():
            print(f"Error: Step 1 脚本不存在: {STEP1_SCRIPT}", file=sys.stderr)
            sys.exit(1)
        if not STEP2_SCRIPT.is_file():
            print(f"Error: Step 2 脚本不存在: {STEP2_SCRIPT}", file=sys.stderr)
            sys.exit(1)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # 先创建当次输出目录（与 run_all_presets 命名一致），bg.png 写入该目录内
        genre_label = sanitize_dirname("+".join(groups)) if groups else "all"
        title_safe = sanitize_dirname(main_title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = OUTPUT_DIR / f"{genre_label}_{title_safe}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _current_run_dir = run_dir
        step1_bg_path = run_dir / "bg.png"

        # 按分组自动追加风格描述片段（GENRE_STYLE_PROMPT），去重后拼入 Step 1 prompt
        _style_seen: set[str] = set()
        _gsp = getattr(_spec, "GENRE_STYLE_PROMPT", {})
        for _gn in groups:
            _frag = _gsp.get(_gn or "", "")
            if _frag and _frag not in _style_seen:
                _style_seen.add(_frag)
                description = description.rstrip() + _frag
                print(f"[方案 A] 已追加分组 {_gn!r} 的风格描述到 Step 1 prompt", flush=True)

        # 仅当分组名恰好为「开放平台」且无 --ref 时使用默认参考图（单规格别名不自动 i2i，以免束缚即梦创意）
        ref_to_use = Path(args.ref).resolve() if args.ref else None
        _open_ref = ref_to_use is None and OPEN_PLATFORM_DEFAULT_REF.is_file() and any(
            (x or "").strip() == "开放平台" for x in groups
        )
        if _open_ref:
            ref_to_use = OPEN_PLATFORM_DEFAULT_REF.resolve()
            print(f"[方案 A] 使用开放平台默认参考图: {ref_to_use}", flush=True)
        if ref_to_use is not None and not ref_to_use.is_file():
            print(f"Error: 参考图不存在: {ref_to_use}", file=sys.stderr)
            sys.exit(1)

        # 将本次使用的 prompt 写入输出目录，便于日后查看
        (run_dir / "prompt.txt").write_text(description, encoding="utf-8")
        if _engine_trace is not None:
            (run_dir / "prompt_engine_trace.md").write_text(_engine_trace, encoding="utf-8")
            print(f"[方案 A] prompt-engine 完整推导已保存到 {run_dir / 'prompt_engine_trace.md'}", flush=True)

        # Step 1: generate_from_description.py  description  output  [-i ref] [--width W] [--height H] [--model M]
        cmd1 = [
            PYTHON_EXE,
            str(STEP1_SCRIPT),
            description,
            str(step1_bg_path),
        ]
        if ref_to_use:
            cmd1.extend(["--reference-image", str(ref_to_use)])
        if args.width is not None and args.height is not None:
            cmd1.extend(["--width", str(args.width), "--height", str(args.height)])
        elif args.model and args.model.strip().lower() == "jimeng":
            # 即梦默认输出 3024×1296，直接产出无字背景图
            cmd1.extend(["--width", "3024", "--height", "1296"])
        elif groups:
            # 使用标准生图比例，不再强约束到具体画布像素
            # 下游 Step 2 对各预设做 cover-scale 适配
            # BANNER_BG_SIZE 环境变量可覆盖（格式：WxH，如 1024x640）
            _bg_size = os.environ.get("BANNER_BG_SIZE", "").strip()
            _gw = _gh = None
            if _bg_size:
                _parts = _bg_size.lower().split("x")
                if len(_parts) == 2 and _parts[0].isdigit() and _parts[1].isdigit():
                    _gw, _gh = int(_parts[0]), int(_parts[1])
                else:
                    print(f"  ⚠ BANNER_BG_SIZE 格式无效 '{_bg_size}'，应为 WxH（如 1024x640），使用默认值", file=sys.stderr)
            if _gw is None:
                _gw, _gh = 1920, 600   # 所有后端统一 1920×600
            cmd1.extend(["--width", str(_gw), "--height", str(_gh)])
        if args.model:
            cmd1.extend(["--model", args.model])
        if getattr(args, "jimeng_smart_ref", False):
            cmd1.append("--jimeng-smart-ref")

        # 使用 t8star 相关模型时需 T8STAR_API_KEY（.env 中取消注释并填写）
        if args.model and args.model.strip().lower() in ("t8-gemini", "t8-jimeng") and not os.environ.get("T8STAR_API_KEY"):
            print("Error: 使用 -M t8-gemini 需在项目根 .env 中设置 T8STAR_API_KEY（去掉行首 # 并填入 token，见 .env.example）", file=sys.stderr)
            sys.exit(1)
        env = os.environ.copy()
        print("[方案 A] Step 1: 根据描述生成背景...", flush=True)
        r1 = subprocess.run(cmd1, cwd=str(ROOT), env=env)
        if r1.returncode != 0:
            print("Step 1 失败，已终止。", file=sys.stderr)
            sys.exit(r1.returncode)

        # Step 1 产出 run_dir/bg.png（即梦图生图最终产物在带时间戳目录内）
        if not step1_bg_path.is_file():
            print(f"Error: Step 1 未产出文件: {step1_bg_path}", file=sys.stderr)
            sys.exit(1)
        print(f"[方案 A] Step 1 完成: {step1_bg_path}", flush=True)

        # Step 1b: 文字艺术字独立管线（生图 → 亮度蒙版 → 透明 PNG）
        text_art_rgba_path = None
        if getattr(args, "text_art", None):
            # 取第一个分组的第一个预设尺寸作为目标画布，查询 TEXT_ART_ZONE 获取艺术字区域
            _first_group = groups[0] if groups else None
            _first_preset = _spec.GENRE_PRESETS.get(_first_group, [None])[0] if _first_group else None
            if _first_preset and _first_preset in _spec.PRESETS:
                _cw, _ch = _spec.PRESETS[_first_preset]
                _ta_zone = _spec.TEXT_ART_ZONE_BY_CANVAS.get((_cw, _ch))
            else:
                _ta_zone = None
            if _ta_zone:
                _ta_w = _ta_zone[1] - _ta_zone[0]  # x_max - x_min
                _ta_h = _ta_zone[3] - _ta_zone[2]  # y_max - y_min
                print(f"[方案 A] Step 1b: 生成文字艺术字 ({_ta_w}×{_ta_h})...", flush=True)

                # 1. 用 Gemini/PackyGPT 按原生尺寸生图（1024×640，零裁剪，文字完整）
                text_art_bg_path = run_dir / "text_art_raw.png"
                cmd_ta = [
                    PYTHON_EXE,
                    str(STEP1_SCRIPT),
                    args.text_art,
                    str(text_art_bg_path),
                    "--width", "1024",
                    "--height", "640",
                ]
                r_ta = subprocess.run(cmd_ta, cwd=str(ROOT), env=env)
                if r_ta.returncode != 0 or not text_art_bg_path.is_file():
                    print("Warning: 文字艺术字生图失败，跳过。", file=sys.stderr)
                else:
                    # 2. 亮度蒙版处理（白底黑字艺术字：白色→透明，黑色→保留）
                    text_art_rgba_path = run_dir / "text_art_rgba.png"
                    try:
                        from PIL import Image as _PILImage
                        import numpy as _np
                        ta_img = _PILImage.open(text_art_bg_path).convert("RGBA")
                        gray = ta_img.convert("L")
                        avg = _np.array(gray).mean()
                        # 浅底深字(avg>128)→白底透明黑字留；深底浅字→黑底透明白字留
                        alpha = gray.point(lambda x: 255 - x) if avg > 128 else gray.point(lambda x: x)
                        ta_img.putalpha(alpha)
                        ta_img.save(str(text_art_rgba_path), "PNG")
                        print(f"[方案 A] Step 1b 完成 (亮度蒙版, avg={avg:.0f}): {text_art_rgba_path}", flush=True)
                    except Exception as _e:
                        print(f"Warning: 亮度蒙版处理失败 ({_e})，使用原图。", file=sys.stderr)
                        text_art_rgba_path = text_art_bg_path
            else:
                print("Warning: 当前分组未配置 TEXT_ART_ZONE，跳过文字艺术字。", file=sys.stderr)

        # Step 1c: 对话框横幅生成
        # - 传了 --dialog "prompt" → PackyGPT 生图（原有逻辑）
        # - 未传 --dialog → 从背景图 dialog_rect 区域自动取色，程序化绘制六边形横幅
        dialog_rgba_path = None
        _first_group = groups[0] if groups else None
        _first_preset = _spec.GENRE_PRESETS.get(_first_group, [None])[0] if _first_group else None
        if _first_preset and _first_preset in _spec.PRESETS:
            _cw, _ch = _spec.PRESETS[_first_preset]
            _d_zone = _spec.DIALOG_ZONE_BY_CANVAS.get((_cw, _ch))
        else:
            _d_zone = None

        if _d_zone:
            _d_w = _d_zone[1] - _d_zone[0]
            _d_h = _d_zone[3] - _d_zone[2]
            _dialog_banner_script = ROOT / "scripts" / "generate_dialog_banner.py"

            if getattr(args, "dialog", None):
                # 有 prompt → PackyGPT 生图
                print(f"[方案 A] Step 1c: 生成对话框 ({_d_w}×{_d_h})...", flush=True)
                dialog_bg_path = run_dir / "dialog_raw.png"
                cmd_d = [
                    PYTHON_EXE, str(STEP1_SCRIPT),
                    args.dialog, str(dialog_bg_path),
                    "--width", str(_d_w), "--height", str(_d_h),
                ]
                r_d = subprocess.run(cmd_d, cwd=str(ROOT), env=env)
                if r_d.returncode != 0 or not dialog_bg_path.is_file():
                    print("Warning: 对话框生图失败，跳过。", file=sys.stderr)
                else:
                    dialog_rgba_path = dialog_bg_path
                    print(f"[方案 A] Step 1c 完成: {dialog_rgba_path}", flush=True)

            elif _dialog_banner_script.is_file() and step1_bg_path.is_file():
                # 无 prompt → 从背景图自动取色，程序化绘制
                print(f"[方案 A] Step 1c: 从背景图取色生成六边形横幅 ({_d_w}×{_d_h})...", flush=True)
                dialog_bg_path = run_dir / "dialog_raw.png"
                cmd_d = [
                    PYTHON_EXE, str(_dialog_banner_script),
                    "--bg", str(step1_bg_path),
                    "--region", str(_d_zone[0]), str(_d_zone[2]), str(_d_zone[1]), str(_d_zone[3]),
                    "--width", str(_d_w), "--height", str(_d_h),
                    "--output", str(dialog_bg_path),
                ]
                r_d = subprocess.run(cmd_d, cwd=str(ROOT), env=env)
                if r_d.returncode != 0 or not dialog_bg_path.is_file():
                    print("Warning: 对话框横幅生成失败，跳过。", file=sys.stderr)
                else:
                    dialog_rgba_path = dialog_bg_path
                    print(f"[方案 A] Step 1c 完成: {dialog_rgba_path}", flush=True)
    else:
        # 战报早退：跳过描述推导 + Step 1，但需确保路由所需变量存在
        _engine_trace = None
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        genre_label = sanitize_dirname("+".join(groups)) if groups else "all"
        title_safe = sanitize_dirname(main_title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = OUTPUT_DIR / f"{genre_label}_{title_safe}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _current_run_dir = run_dir
        step1_bg_path = run_dir / "bg.png"
        ref_to_use = Path(args.ref).resolve() if args.ref else None
        env = os.environ.copy()

    # Step 2: -g 活动长图 → run_changtu.py，-g 商店移动端日常 → run_mobile_presets.py，-g 战报 → run_battle_report.py，-g 排行榜 → run_ranking.py，-g 邮件长图 → run_email_poster.py，其余 → run_all_presets.py
    CHANGTU_SCRIPT = ROOT / "scripts" / "run_changtu.py"
    CHANGTU_GROUP = "活动长图"
    MOBILE_SCRIPT = ROOT / "scripts" / "run_mobile_presets.py"
    MOBILE_GROUP = "商店移动端日常"
    BATTLE_REPORT_SCRIPT = ROOT / "scripts" / "run_battle_report.py"
    BATTLE_REPORT_GROUP = "战报"
    RANKING_SCRIPT = ROOT / "scripts" / "run_ranking.py"
    RANKING_GROUP = "排行榜"
    EMAIL_POSTER_SCRIPT = ROOT / "scripts" / "run_email_poster.py"
    EMAIL_POSTER_GROUP = "邮件长图"
    has_changtu = CHANGTU_GROUP in groups
    has_mobile = MOBILE_GROUP in groups
    has_battle_report = BATTLE_REPORT_GROUP in groups
    has_ranking = RANKING_GROUP in groups
    has_email_poster = EMAIL_POSTER_GROUP in groups
    desktop_groups = [g for g in groups if g not in (CHANGTU_GROUP, MOBILE_GROUP, BATTLE_REPORT_GROUP, RANKING_GROUP, EMAIL_POSTER_GROUP)]

    env2 = env.copy()

    if has_battle_report:
        # 1. 确定 KV 图：优先 --ref/-i，其次 --kv，再次 Step 1 生成的 bg.png
        report_kv = None
        if getattr(args, "kv", None):
            report_kv = Path(args.kv)
        elif ref_to_use and ref_to_use.is_file():
            report_kv = ref_to_use
        elif step1_bg_path.is_file():
            report_kv = step1_bg_path

        # 2. 素材目录：--report-dir 优先，否则从 input/uploads/ 构建临时目录
        report_materials_dir = None
        report_materials_is_temp = False
        if getattr(args, "report_dir", None):
            report_materials_dir = Path(args.report_dir)
        else:
            _input_uploads = ROOT / "input" / "uploads"
            if _input_uploads.is_dir():
                report_materials_dir = run_dir / "_report_materials"
                report_materials_dir.mkdir(exist_ok=True)
                report_materials_is_temp = True
                _screenshots_dir = report_materials_dir / "战报截图"
                _screenshots_dir.mkdir(exist_ok=True)
                _img_count = 0
                for _p in sorted(_input_uploads.iterdir()):
                    if not _p.is_file() or _p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                        continue
                    if _p.name == "current.png" and not _p.stat().st_size:
                        continue
                    _dest = _screenshots_dir / _p.name
                    import shutil as _shutil
                    _shutil.copy2(_p, _dest)
                    _img_count += 1
                if _img_count:
                    print(f"[方案 A] 已从 input/uploads/ 构建战报素材目录: {report_materials_dir} ({_img_count} 张)",
                          flush=True)
                else:
                    report_materials_is_temp = False
                    report_materials_dir = None

        if not report_materials_dir or (not report_materials_dir.is_dir() and not report_materials_is_temp):
            print("[方案 A] 战报: 素材目录为空，跳过。提示: 上传截图到对话框，或通过 --report-dir 指定素材目录",
                  file=sys.stderr)
        else:
            print("[方案 A] Step 2: 战报长图合成（run_battle_report.py）...", flush=True)
            cmd_br = [
                PYTHON_EXE, str(BATTLE_REPORT_SCRIPT),
                str(report_materials_dir),
                "-m", main_title,
                "-s", subtitle,
                "--output-dir", str(run_dir.resolve()),
            ]
            if report_kv and report_kv.is_file():
                cmd_br.extend(["--kv", str(report_kv)])
            bar_text_val = getattr(args, "bar_text", None)
            if bar_text_val:
                cmd_br.extend(["--bar-text", str(bar_text_val)])
            if getattr(args, "stat_exposure", None):
                cmd_br.extend(["--stat-exposure", str(args.stat_exposure)])
            if getattr(args, "stat_download", None):
                cmd_br.extend(["--stat-download", str(args.stat_download)])
            if getattr(args, "stat_groups", None):
                for sg in args.stat_groups:
                    cmd_br.extend(["--stat-group", str(sg)])
            if getattr(args, "font_family", None):
                cmd_br.extend(["--font-family", str(args.font_family)])
            if getattr(args, "no_stats", False):
                cmd_br.append("--no-stats")
            if getattr(args, "packygpt", False):
                cmd_br.append("--packygpt")
            if getattr(args, "micugpt2", False):
                cmd_br.append("--micugpt2")
            if getattr(args, "micugemini", False):
                cmd_br.append("--micugemini")
            if getattr(args, "xingchengemini", False):
                cmd_br.append("--xingchengemini")
            if getattr(args, "xingchengemini1", False):
                cmd_br.append("--xingchengemini1")
            if getattr(args, "xingchengpt", False):
                cmd_br.append("--xingchengpt")
            if getattr(args, "xinchengpt", False):
                cmd_br.append("--xinchengpt")
            if getattr(args, "moxingpt", False):
                cmd_br.append("--moxingpt")
            if getattr(args, "moxingemini", False):
                cmd_br.append("--moxingemini")
            if getattr(args, "packy7s", False):
                cmd_br.append("--packy7s")
            elif getattr(args, "packy", False):
                cmd_br.append("--packy")
            r_br = subprocess.run(cmd_br, cwd=str(ROOT), env=env2)
            if r_br.returncode != 0:
                print("Step 2（战报）失败。", file=sys.stderr)
                sys.exit(r_br.returncode)

    if has_ranking:
        ranking_csv = getattr(args, "ranking_csv", None)
        ranking_theme = getattr(args, "ranking_theme", None)
        print("[方案 A] Step 2: 排行榜合成（run_ranking.py）...", flush=True)
        cmd_rk = [
            PYTHON_EXE, str(RANKING_SCRIPT),
            "--output-dir", str(run_dir.resolve()),
        ]
        if ranking_csv:
            cmd_rk.extend(["--csv", str(ranking_csv)])
        if ranking_theme:
            cmd_rk.extend(["--theme", ranking_theme])
        if getattr(args, "packygpt", False):
            cmd_rk.append("--packygpt")
        if getattr(args, "micugpt2", False):
            cmd_rk.append("--micugpt2")
        if getattr(args, "micugemini", False):
            cmd_rk.append("--micugemini")
        if getattr(args, "xingchengemini", False):
            cmd_rk.append("--xingchengemini")
        if getattr(args, "xingchengemini1", False):
            cmd_rk.append("--xingchengemini1")
        if getattr(args, "xingchengpt", False):
            cmd_rk.append("--xingchengpt")
        if getattr(args, "xinchengpt", False):
            cmd_rk.append("--xinchengpt")
        if getattr(args, "moxingpt", False):
            cmd_rk.append("--moxingpt")
        if getattr(args, "moxingemini", False):
            cmd_rk.append("--moxingemini")
        if getattr(args, "packy7s", False):
            cmd_rk.append("--packy7s")
        elif getattr(args, "packy", False):
            cmd_rk.append("--packy")
        r_rk = subprocess.run(cmd_rk, cwd=str(ROOT), env=env2)
        if r_rk.returncode != 0:
            print("Step 2（排行榜）失败。", file=sys.stderr)
            sys.exit(r_rk.returncode)

    if has_changtu:
        cmd_ct = [
            PYTHON_EXE, str(CHANGTU_SCRIPT),
            "-m", main_title,
            "-s", subtitle,
            "--output-dir", str(run_dir.resolve()),
            "--font-title", str(getattr(args, "font_title", None) or "fonts/title.otf"),
        ]
        for _gn in groups:
            if _gn == CHANGTU_GROUP:
                continue
        if ref_to_use and ref_to_use.is_file():
            cmd_ct.extend(["--kv", str(ref_to_use)])
        if getattr(args, "event_date", None):
            cmd_ct.extend(["--event-date", args.event_date])
        if getattr(args, "event_desc", None):
            cmd_ct.extend(["--event-desc", args.event_desc])
        if getattr(args, "prize_dir", None):
            cmd_ct.extend(["--prize-dir", args.prize_dir])
        if getattr(args, "prize_order", None):
            cmd_ct.extend(["--prize-order", args.prize_order])
        if getattr(args, "rules", None):
            cmd_ct.extend(["--rules", args.rules])
        if getattr(args, "kv_scene", None):
            cmd_ct.extend(["--kv-scene", args.kv_scene])
        if getattr(args, "game_name", None):
            cmd_ct.extend(["--game-name", args.game_name])
        if getattr(args, "game_style", None):
            cmd_ct.extend(["--game-style", args.game_style])
        if getattr(args, "section1", None):
            cmd_ct.extend(["--section1", args.section1])
        if getattr(args, "section2", None):
            cmd_ct.extend(["--section2", args.section2])
        if getattr(args, "font_title", None):
            cmd_ct.extend(["--font-title", args.font_title])
        if getattr(args, "font_yahei", None):
            cmd_ct.extend(["--font-yahei", args.font_yahei])
        if getattr(args, "packygpt", False):
            cmd_ct.append("--packygpt")
        if getattr(args, "micugpt2", False):
            cmd_ct.append("--micugpt2")
        if getattr(args, "micugemini", False):
            cmd_ct.append("--micugemini")
        if getattr(args, "xingchengemini", False):
            cmd_ct.append("--xingchengemini")
        if getattr(args, "xingchengemini1", False):
            cmd_ct.append("--xingchengemini1")
        if getattr(args, "moxingpt", False):
            cmd_ct.append("--moxingpt")
        if getattr(args, "moxingemini", False):
            cmd_ct.append("--moxingemini")
        if getattr(args, "xingchengpt", False):
            cmd_ct.append("--xingchengpt")
        if getattr(args, "xinchengpt", False):
            cmd_ct.append("--xinchengpt")
        if getattr(args, "packy7s", False):
            cmd_ct.append("--packy7s")
        elif getattr(args, "packy", False):
            cmd_ct.append("--packy")
        print("[方案 A] Step 2: 活动长图合成（run_changtu.py）...", flush=True)
        r_ct = subprocess.run(cmd_ct, cwd=str(ROOT), env=env2)
        if r_ct.returncode != 0:
            print("Step 2（活动长图）失败。", file=sys.stderr)
            sys.exit(r_ct.returncode)

    if has_email_poster:
        cmd_ep = [
            PYTHON_EXE, str(EMAIL_POSTER_SCRIPT),
            "-m", main_title,
            "-s", subtitle,
            "--output-dir", str(run_dir.resolve()),
            "--font-title", str(getattr(args, "font_title", None) or "fonts/title.otf"),
        ]
        if ref_to_use and ref_to_use.is_file():
            cmd_ep.extend(["--kv", str(ref_to_use)])
        elif getattr(args, "kv", None):
            cmd_ep.extend(["--kv", args.kv])
        if getattr(args, "event_date", None):
            cmd_ep.extend(["--event-date", args.event_date])
        if getattr(args, "event_desc", None):
            cmd_ep.extend(["--event-desc", args.event_desc])
        if getattr(args, "prize_dir", None):
            cmd_ep.extend(["--prize-dir", args.prize_dir])
        if getattr(args, "prize_order", None):
            cmd_ep.extend(["--prize-order", args.prize_order])
        if getattr(args, "method_dir", None):
            cmd_ep.extend(["--method-dir", args.method_dir])
        if getattr(args, "method_desc", None):
            cmd_ep.extend(["--method-desc", args.method_desc])
        if getattr(args, "history_dir", None):
            cmd_ep.extend(["--history-dir", args.history_dir])
        if getattr(args, "history_order", None):
            cmd_ep.extend(["--history-order", args.history_order])
        if getattr(args, "intro_text", None):
            cmd_ep.extend(["--intro-text", args.intro_text])
        if getattr(args, "font_title", None):
            cmd_ep.extend(["--font-title", args.font_title])
        if getattr(args, "font_yahei", None):
            cmd_ep.extend(["--font-yahei", args.font_yahei])
        if getattr(args, "packygpt", False):
            cmd_ep.append("--packygpt")
        if getattr(args, "micugpt2", False):
            cmd_ep.append("--micugpt2")
        if getattr(args, "micugemini", False):
            cmd_ep.append("--micugemini")
        if getattr(args, "xingchengemini", False):
            cmd_ep.append("--xingchengemini")
        if getattr(args, "xingchengemini1", False):
            cmd_ep.append("--xingchengemini1")
        if getattr(args, "moxingpt", False):
            cmd_ep.append("--moxingpt")
        if getattr(args, "moxingemini", False):
            cmd_ep.append("--moxingemini")
        if getattr(args, "xingchengpt", False):
            cmd_ep.append("--xingchengpt")
        if getattr(args, "xinchengpt", False):
            cmd_ep.append("--xinchengpt")
        if getattr(args, "packy7s", False):
            cmd_ep.append("--packy7s")
        elif getattr(args, "packy", False):
            cmd_ep.append("--packy")
        print("[方案 A] Step 2: 邮件长图合成（run_email_poster.py）...", flush=True)
        r_ep = subprocess.run(cmd_ep, cwd=str(ROOT), env=env2)
        if r_ep.returncode != 0:
            print("Step 2（邮件长图）失败。", file=sys.stderr)
            sys.exit(r_ep.returncode)

    if desktop_groups or (not has_mobile and not has_changtu and not has_battle_report and not has_ranking and not has_email_poster):
        cmd2 = [
            PYTHON_EXE, str(STEP2_SCRIPT),
            str(step1_bg_path.resolve()),
            "--main-title", main_title,
            "--subtitle", subtitle,
            "--output-dir", str(run_dir.resolve()),
        ]
        if ref_to_use or getattr(args, "skip_a4_outpaint", False):
            cmd2.append("--skip-a4-outpaint")
        if getattr(args, "skip_remove_text", False):
            cmd2.append("--skip-remove-text")
        for _gn in desktop_groups if has_mobile else groups:
            cmd2.extend(["--genre", _gn])
        if getattr(args, "packygpt", False):
            cmd2.append("-packygpt")
        if getattr(args, "micugpt2", False):
            cmd2.append("-micugpt2")
        if getattr(args, "micugemini", False):
            cmd2.append("-micugemini")
        if getattr(args, "xingchengemini", False):
            cmd2.append("-xingchengemini")
        if getattr(args, "xingchengemini1", False):
            cmd2.append("-xingchengemini1")
        if getattr(args, "moxingpt", False):
            cmd2.append("-moxingpt")
        if getattr(args, "moxingemini", False):
            cmd2.append("-moxingemini")
        if getattr(args, "xingchengpt", False):
            cmd2.append("-xingchengpt")
        if getattr(args, "xinchengpt", False):
            cmd2.append("-xinchengpt")
        if getattr(args, "packy7s", False):
            cmd2.append("-packy7s")
        elif getattr(args, "packy", False):
            cmd2.append("-packy")
        if text_art_rgba_path and text_art_rgba_path.is_file():
            cmd2.extend(["--text-art", str(text_art_rgba_path.resolve())])
        if dialog_rgba_path and dialog_rgba_path.is_file():
            cmd2.extend(["--dialog", str(dialog_rgba_path.resolve())])
        print("[方案 A] Step 2: 多尺寸叠字合成（run_all_presets.py）...", flush=True)
        r2 = subprocess.run(cmd2, cwd=str(ROOT), env=env2)
        if r2.returncode != 0:
            print("Step 2（桌面端）失败。", file=sys.stderr)
            sys.exit(r2.returncode)

    if has_mobile:
        cmd_m = [
            PYTHON_EXE, str(MOBILE_SCRIPT),
            str(step1_bg_path.resolve()),
            "-m", main_title,
            "-s", subtitle,
            "--output-dir", str(run_dir.resolve()),
        ]
        if getattr(args, "packygpt", False):
            cmd_m.append("--packygpt")
        if getattr(args, "micugpt2", False):
            cmd_m.append("--micugpt2")
        if getattr(args, "micugemini", False):
            cmd_m.append("--micugemini")
        if getattr(args, "xingchengemini", False):
            cmd_m.append("--xingchengemini")
        if getattr(args, "xingchengemini1", False):
            cmd_m.append("--xingchengemini1")
        if getattr(args, "moxingpt", False):
            cmd_m.append("--moxingpt")
        if getattr(args, "moxingemini", False):
            cmd_m.append("--moxingemini")
        if getattr(args, "xingchengpt", False):
            cmd_m.append("--xingchengpt")
        if getattr(args, "xinchengpt", False):
            cmd_m.append("--xinchengpt")
        if getattr(args, "packy7s", False):
            cmd_m.append("--packy7s")
        if text_art_rgba_path and text_art_rgba_path.is_file():
            cmd_m.extend(["--text-art", str(text_art_rgba_path.resolve())])
        if dialog_rgba_path and dialog_rgba_path.is_file():
            cmd_m.extend(["--dialog", str(dialog_rgba_path.resolve())])
        print("[方案 A] Step 2: 移动端管线（run_mobile_presets.py）...", flush=True)
        r_m = subprocess.run(cmd_m, cwd=str(ROOT), env=env2)
        if r_m.returncode != 0:
            print("Step 2（移动端）失败。", file=sys.stderr)
            sys.exit(r_m.returncode)

    print("[方案 A] 全部完成。", flush=True)

    # 列出本次输出目录下所有文件，方便在 IDE 文件树未刷新时确认产物
    files = sorted(run_dir.glob("*")) if run_dir.is_dir() else []
    if files:
        print(f"\n本次输出目录（{run_dir}）：")
        for f in files:
            if f.is_file():
                size_kb = f.stat().st_size / 1024
                print(f"  {f.name}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
