#!/usr/bin/env python3
"""
排行榜图片生成入口（由 run_full_with_custom_prompt.py -g 排行榜 路由调用，也可独立运行）

用法:
  py scripts/run_ranking.py --csv "input/ranking/7月拯救者榜单 - 30天.csv"
  py scripts/run_ranking.py --csv "input/ranking/榜单.csv" --theme gold --xingchengpt
  py scripts/run_ranking.py --csv "input/ranking/榜单.csv" --skip-icons --skip-bg
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from _paths import validate_paths, sanitize_dirname
validate_paths()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from _env import load_env, get_env_key

_ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_ALT",
    "GOOGLE_GEMINI_BASE_URL",
    "PACKY_API_KEY",
    "PACKY7S_API_KEY",
    "PACKY3S_API_KEY",
    "PACKYGPT_API_KEY",
    "MICUAPI_API_KEY",
    "MICUGEMINI_API_KEY",
    "MOXINGPT_API_KEY",
    "MOXINGEMINI_API_KEY",
    "MOXINGEMINI_BASE_URL",
    "XINGCHENGGPT_API_KEY",
    "XINGCHENGGPT_BASE_URL",
    "XINCHENGPT_API_KEY",
    "XINCHENGPT_BASE_URL",
    "XINGCHENGEMINI_API_KEY",
    "XINGCHENGEMINI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "BANNER_IMAGE_BACKEND",
    "BANNER_EDIT_BACKEND",
    "XINCHENGPT_SIZE",
    "XINCHENGPT_QUALITY",
)
load_env(_ENV_KEYS)

from _packy import apply_packy_backend

from scripts.ensure_python import get_python_exe
PYTHON_EXE = get_python_exe()

OUTPUT_DIR = ROOT / "output"
INPUT_DIR = ROOT / "input"
INPUT_RANKING_DIR = INPUT_DIR / "ranking"

from scripts.ranking.i18n import load, t as _t

# ── 主题默认背景 prompt ──
THEME_BG_PROMPTS = {
    "red": (
        "Dark crimson red gaming celebration banner background, absolutely no text. "
        "Golden fireworks explosions and sparkles scattered across a deep dark red sky. "
        "Luxurious prestigious esports award aesthetic. "
        "Wide panoramic, cinematic volumetric lighting, dark moody atmosphere."
    ),
    "dark": (
        "Dark black and gold gaming celebration banner background, absolutely no text. "
        "A majestic golden trophy cup centered at top with golden fireworks. "
        "Deep dark charcoal black gradient background. "
        "Luxurious prestigious esports award aesthetic. "
        "Wide panoramic, cinematic volumetric lighting."
    ),
    "green": (
        "Dark emerald green gaming celebration banner background, absolutely no text. "
        "A majestic golden trophy cup centered at top. "
        "Golden sparkles, light particles, subtle firework bursts. "
        "Deep dark green gradient background. "
        "Luxurious prestigious esports award ceremony aesthetic. "
        "Wide panoramic, cinematic volumetric lighting."
    ),
    "gold": (
        "Dark golden luxurious gaming celebration banner background, absolutely no text. "
        "A majestic golden trophy cup centered at top with radiant golden light rays. "
        "Rich golden fireworks, sparkles and light particles on deep dark amber brown sky. "
        "Warm golden amber gradient, prestigious esports award ceremony aesthetic. "
        "Wide panoramic, cinematic volumetric lighting, dark moody warm atmosphere."
    ),
    "blue": (
        "Dark deep navy blue gaming celebration banner background, absolutely no text. "
        "A majestic silver and cyan trophy cup centered at top with cool blue light rays. "
        "Electric blue fireworks, sparkles and light particles on deep dark midnight blue sky. "
        "Cool sapphire blue gradient, prestigious esports award ceremony aesthetic. "
        "Wide panoramic, cinematic volumetric lighting, dark moody cool atmosphere."
    ),
}

THIS_MONTH = str(datetime.now().month) + "月"
THIS_YEAR = str(datetime.now().year)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="PC游戏排行榜图片生成 — CSV→JSON+图标+背景+截图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  py scripts/run_ranking.py --csv input/ranking/榜单.csv --theme gold --xingchengpt
  py scripts/run_ranking.py --csv input/ranking/榜单.csv --skip-icons --skip-bg
        """,
    )
    ap.add_argument("--csv", default=None, help="CSV 数据文件路径（不传则自动取 input/ranking/ 下最新）")
    ap.add_argument("--theme", default="gold", choices=["red", "dark", "green", "gold", "blue"], help="主题色")
    ap.add_argument("--output-dir", dest="output_dir", default=None, help="输出目录")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"], help="语言")
    ap.add_argument("--skip-icons", action="store_true", help="跳过图标下载")
    ap.add_argument("--skip-bg", action="store_true", help="跳过 AI 背景生成（用 CSS 渐变兜底）")
    ap.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt")
    ap.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt")
    ap.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt")
    ap.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2")
    ap.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini")
    ap.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini")
    ap.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1")
    ap.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt")
    ap.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini")
    ap.add_argument("--packy7s", "-packy7s", action="store_true", dest="packy7s")
    ap.add_argument("--packy", "-packy", action="store_true", dest="packy")
    return ap.parse_args()


def _resolve_csv(args: argparse.Namespace) -> Path:
    if args.csv:
        p = Path(args.csv).resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"CSV 文件不存在: {p}")

    if INPUT_RANKING_DIR.is_dir():
        csv_files = sorted(INPUT_RANKING_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        if csv_files:
            print(f"[排行榜] 自动检测 CSV: {csv_files[0]}", flush=True)
            return csv_files[0]

    raise FileNotFoundError("未提供 --csv 参数且 input/ranking/ 下未找到 CSV 文件。")


def csv_to_json(csv_path: Path, theme: str, output_dir: Path, lang: str = "zh") -> Path:
    import csv
    loc = load(lang)

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    seen = {}
    for r in rows:
        name = r.get("游戏名称", "").strip()
        if not name or name in seen:
            continue
        try:
            rank = int(r.get("名次", "9999"))
        except (ValueError, TypeError):
            continue
        if rank <= 50:
            seen[name] = {
                "rank": rank,
                "name": name,
                "developer": r.get("厂商", "").strip(),
                "players": r.get("LZ显示玩家数量", r.get("玩家数量", "")).strip().strip('"'),
            }

    ranked = sorted(seen.values(), key=lambda x: x["rank"])[:20]

    top3 = []
    rankings = []
    for item in ranked:
        if item["rank"] <= 3:
            top3.append({
                "rank": item["rank"],
                "name": item["name"],
                "developer": item["players"],
                "is_new": False,
            })
        else:
            trend = None
            rankings.append({
                "rank": item["rank"],
                "name": item["name"],
                "developer": item["developer"],
                "trend": trend,
            })

    data = {
        "year": THIS_YEAR,
        "month": THIS_MONTH,
        "theme": theme,
        "hero_bg": "",
        "hero_bg_prompt": THEME_BG_PROMPTS.get(theme, THEME_BG_PROMPTS["gold"]),
        "overlay": {},
        "decorations": {"medal_style": "refstyle"},
        "footer_note": loc.get("default_footer_note", ""),
        "top3": top3,
        "rankings": rankings,
    }

    json_path = output_dir / "data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[排行榜] JSON 已生成: {json_path}", flush=True)
    return json_path


def fetch_game_icons(csv_path: Path, out_dir: Path, cache_path: Path = None) -> dict:
    from scripts.ranking.fetch_icons import fetch_icons
    return fetch_icons(str(csv_path), str(out_dir), str(cache_path) if cache_path else None)


def generate_hero_bg(data: dict, output_path: Path, config: dict, lang: str = "zh") -> str:
    import requests
    import base64 as b64
    loc = load(lang)
    theme_name = data.get("theme", "gold")
    prompt = data.get("hero_bg_prompt") or THEME_BG_PROMPTS.get(theme_name, THEME_BG_PROMPTS["gold"])

    print(_t(lang, "cli.generating_bg"))
    print(f"   Prompt: {prompt[:80]}...")

    body = {
        "model": config["api_model"],
        "prompt": prompt,
        "n": 1,
        "size": config.get("size", "auto"),
        "quality": config.get("quality", "auto"),
    }

    resp = requests.post(
        f"{config['api_base']}/images/generations",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=180,
    )

    if resp.status_code != 200:
        print(_t(lang, "cli.api_error", code=resp.status_code, message=resp.text[:300]))
        return ""

    item = resp.json()["data"][0]

    if "b64_json" in item:
        img_bytes = b64.b64decode(item["b64_json"])
    elif "url" in item:
        img_bytes = requests.get(item["url"], timeout=60).content
    else:
        print(_t(lang, "cli.unknown_format", keys=list(item.keys())))
        return ""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(img_bytes)
    print(_t(lang, "cli.bg_saved", path=output_path, size=len(img_bytes) // 1024))
    return str(output_path.name)


def _get_image_config() -> dict:
    api_key = (get_env_key("XINCHENGPT_API_KEY") or get_env_key("XINGCHENGGPT_API_KEY") or "")
    api_base = (os.environ.get("XINCHENGPT_BASE_URL", "").strip()
                or os.environ.get("XINGCHENGGPT_BASE_URL", "").strip()
                or "https://api.centos.hk/v1")
    return {
        "api_key": api_key,
        "api_base": api_base,
        "api_model": "gpt-image-2",
        "size": os.environ.get("XINCHENGPT_SIZE", "auto"),
        "quality": os.environ.get("XINCHENGPT_QUALITY", "auto"),
    }


def main() -> None:
    args = parse_args()
    apply_packy_backend(args)

    lang = args.lang
    theme = args.theme
    csv_path = _resolve_csv(args)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else OUTPUT_DIR / f"排行榜_{THIS_YEAR}_{THIS_MONTH}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)

    icons_dir = output_dir / "icons"
    icons_dir.mkdir(exist_ok=True)

    cache_path = INPUT_RANKING_DIR / "lestore_games.json"

    print(f"[排行榜] CSV: {csv_path}", flush=True)
    print(f"[排行榜] 主题: {theme}", flush=True)
    print(f"[排行榜] 输出: {output_dir}", flush=True)

    # Step 1: CSV → JSON
    json_path = csv_to_json(csv_path, theme, output_dir, lang)

    # Step 2: Icon download
    icon_results = {}
    if not args.skip_icons:
        try:
            icon_results = fetch_game_icons(csv_path, icons_dir, cache_path)
            print(f"[排行榜] 图标下载完成: {len(icon_results)} 个", flush=True)
        except Exception as e:
            print(f"[排行榜] 图标下载失败（不阻塞流程）: {e}", flush=True)

    # Update JSON with icon paths
    if icon_results:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("top3", []) + data.get("rankings", []):
            name = item["name"]
            if name in icon_results:
                item["icon_path"] = icon_results[name]
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Step 3: Background generation
    bg_path = output_dir / "hero_bg.png"
    if not args.skip_bg:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        config = _get_image_config()
        if config["api_key"]:
            try:
                generate_hero_bg(data, bg_path, config, lang)
            except Exception as e:
                print(f"[排行榜] 背景生成失败（将用 CSS 渐变兜底）: {e}", flush=True)
        else:
            print("[排行榜] 未配置 API Key，跳过背景生成（将用 CSS 渐变兜底）", flush=True)

    # Update JSON with absolute hero_bg path
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    if bg_path.is_file():
        data["hero_bg"] = str(bg_path.resolve())
    else:
        data["hero_bg"] = ""
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Step 4: Render screenshot
    from scripts.ranking.generate import generate, RANKING_ASSETS
    assets_dir = str(RANKING_ASSETS)
    icon_base = str(icons_dir)
    output_path = generate(
        str(json_path),
        output_dir=str(output_dir),
        lang=lang,
        assets_dir=assets_dir,
        icon_base=icon_base,
    )
    print(f"[排行榜] 已输出: {output_path}", flush=True)


if __name__ == "__main__":
    main()
