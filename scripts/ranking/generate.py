#!/usr/bin/env python3
"""
PC Ranking Image Generator
Usage: python generate.py <data.json> [output_dir]
"""
import json
import sys
import os
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from scripts.ranking.i18n import load, t as _t

# Windows console encoding fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_RANKING_DIR = Path(__file__).parent
RANKING_ASSETS = _RANKING_DIR.parent / "assets" / "ranking"

# ── 项目内 input/ranking 目录用于游戏图标 ──
PROJECT_ROOT = _RANKING_DIR.parent.parent
INPUT_RANKING_DIR = PROJECT_ROOT / "input" / "ranking"


THEMES = {
    "red": {
        "bg_top":       "#7B1818",
        "bg_mid":       "#5C0E0E",
        "bg_bottom":    "#2E0505",
        "list_bg":      "#1A0303",
        "accent":       "#C8900A",
        "title_from":   "#FFE89A",
        "title_to":     "#C8900A",
        "row_odd":      "#1F0D0D",
        "row_even":     "#261212",
        "row_border":   "rgba(200,144,10,0.12)",
        "row_name":     "#FFFFFF",
        "row_num":      "#FFFFFF",
        "row_dev":      "rgba(255,255,255,0.4)",
        "icon_border":       "#FFD700",
        "icon_border_light": "rgba(255,215,0,0.35)",
        "icon_bg":           "#3A3028",
        "badge_from":        "#FFD700",
        "badge_to":          "#C8900A",
        "badge_text":        "#1A0800",
        "title_mid":         "#D4A017",
        "subtitle":          "rgba(255,225,140,0.88)",
    },
    "dark": {
        "bg_top":       "#1E1A16",
        "bg_mid":       "#141210",
        "bg_bottom":    "#0A0806",
        "list_bg":      "#0A0806",
        "accent":       "#C8900A",
        "title_from":   "#FFE89A",
        "title_to":     "#C8900A",
        "row_odd":      "#161412",
        "row_even":     "#1C1916",
        "row_border":   "rgba(200,144,10,0.10)",
        "row_name":     "#FFFFFF",
        "row_num":      "#FFFFFF",
        "row_dev":      "rgba(255,255,255,0.4)",
        "icon_border":       "#C8900A",
        "icon_border_light": "rgba(200,144,10,0.30)",
        "icon_bg":           "#2A2520",
        "badge_from":        "#FFD700",
        "badge_to":          "#C8900A",
        "badge_text":        "#1A0800",
        "title_mid":         "#D4A017",
        "subtitle":          "rgba(255,225,140,0.88)",
    },
    "green": {
        "bg_top":       "#0D2B1A",
        "bg_mid":       "#091E12",
        "bg_bottom":    "#051509",
        "list_bg":      "#051509",
        "accent":       "#00D68F",
        "title_from":   "#88FFD4",
        "title_to":     "#00A86B",
        "row_odd":      "#0C1F14",
        "row_even":     "#10261A",
        "row_border":   "rgba(0,214,143,0.12)",
        "row_name":     "#FFFFFF",
        "row_num":      "#FFFFFF",
        "row_dev":      "rgba(255,255,255,0.4)",
        "icon_border":       "#00D68F",
        "icon_border_light": "rgba(0,214,143,0.30)",
        "icon_bg":           "#0F2A1C",
        "badge_from":        "#88FFD4",
        "badge_to":          "#00A86B",
        "badge_text":        "#0A1A12",
        "title_mid":         "#00B87A",
        "subtitle":          "rgba(140,255,210,0.88)",
    },
    "gold": {
        "bg_top":       "#2A1F0A",
        "bg_mid":       "#1C1506",
        "bg_bottom":    "#0F0B03",
        "list_bg":      "#0F0B03",
        "accent":       "#D4A017",
        "title_from":   "#FFE89A",
        "title_to":     "#C8900A",
        "row_odd":      "#1A1508",
        "row_even":     "#201A0C",
        "row_border":   "rgba(212,160,23,0.12)",
        "row_name":     "#FFFFFF",
        "row_num":      "#FFFFFF",
        "row_dev":      "rgba(255,255,255,0.4)",
        "icon_border":       "#D4A017",
        "icon_border_light": "rgba(212,160,23,0.30)",
        "icon_bg":           "#2A2210",
        "badge_from":        "#FFD700",
        "badge_to":          "#C8900A",
        "badge_text":        "#1A0800",
        "title_mid":         "#D4A017",
        "subtitle":          "rgba(255,225,140,0.88)",
    },
    "blue": {
        "bg_top":       "#0A1E3A",
        "bg_mid":       "#061428",
        "bg_bottom":    "#030A14",
        "list_bg":      "#030A14",
        "accent":       "#4DA6FF",
        "title_from":   "#A8D4FF",
        "title_to":     "#2B7FD4",
        "row_odd":      "#081828",
        "row_even":     "#0C2030",
        "row_border":   "rgba(77,166,255,0.12)",
        "row_name":     "#FFFFFF",
        "row_num":      "#FFFFFF",
        "row_dev":      "rgba(255,255,255,0.4)",
        "icon_border":       "#4DA6FF",
        "icon_border_light": "rgba(77,166,255,0.30)",
        "icon_bg":           "#0F2540",
        "badge_from":        "#A8D4FF",
        "badge_to":          "#2B7FD4",
        "badge_text":        "#061428",
        "title_mid":         "#3B9EFF",
        "subtitle":          "rgba(168,212,255,0.88)",
    },
}

PLACEHOLDER_COLORS = [
    "#C0392B", "#2980B9", "#27AE60", "#8E44AD", "#E67E22",
    "#16A085", "#2C3E50", "#D35400", "#1A5276", "#6C3483",
    "#0E6655", "#784212", "#5D6D7E", "#B7950B", "#922B21",
]


def placeholder_color(name: str) -> str:
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:4], 16)
    return PLACEHOLDER_COLORS[h % len(PLACEHOLDER_COLORS)]


def resolve_icon(icon_path, icon_base):
    if not icon_path:
        return None
    p = Path(icon_base) / icon_path if not Path(icon_path).is_absolute() else Path(icon_path)
    return str(p.absolute()) if p.exists() else icon_path


def build_podium(raw_top3: list, icon_base: Path = None) -> list:
    """Return top3 in podium display order: [No.2, No.1, No.3]."""
    by_rank = {item["rank"]: item for item in raw_top3}
    order = []
    for r in [2, 1, 3]:
        if r in by_rank:
            item = dict(by_rank[r])
            item.setdefault("placeholder_bg", placeholder_color(item["name"]))
            item.setdefault("is_new", False)
            item.setdefault("icon_path", None)
            if icon_base:
                item["icon_path"] = resolve_icon(item["icon_path"], icon_base)
            order.append(item)
    return order


def build_rankings(raw_rankings: list, icon_base: Path = None) -> list:
    rows = []
    for item in raw_rankings:
        row = dict(item)
        row.setdefault("placeholder_bg", placeholder_color(row["name"]))
        row.setdefault("icon_path", None)
        row.setdefault("trend", None)
        if icon_base:
            row["icon_path"] = resolve_icon(row["icon_path"], icon_base)
        rows.append(row)
    return sorted(rows, key=lambda x: x["rank"])


TITLE_FONT_NAME = "AlimamaShuHeiTi-Bold"


def find_title_font(assets_dir: Path = None):
    fonts_dir = (assets_dir or RANKING_ASSETS) / "fonts"
    if not fonts_dir.exists():
        return None
    for ext in ("ttf", "otf", "woff2", "woff"):
        target = fonts_dir / f"{TITLE_FONT_NAME}.{ext}"
        if target.exists():
            return str(target.absolute())
    for ext in ("*.ttf", "*.otf", "*.woff2", "*.woff"):
        found = list(fonts_dir.glob(ext))
        if found:
            return str(found[0].absolute())
    return None


def find_body_font(assets_dir: Path = None):
    fonts_dir = (assets_dir or RANKING_ASSETS) / "fonts"
    target = fonts_dir / "D-DINExp.otf"
    if target.exists():
        return str(target.absolute())
    return None


def resolve_crowns(assets_dir: Path) -> dict:
    crowns = {}
    for rank, fname in [(1, "crown_no1.png"), (2, "crown_no2.png"), (3, "crown_no3.png")]:
        p = assets_dir / "crowns" / fname
        if p.exists():
            crowns[f"crown_no{rank}"] = str(p.absolute())
    return crowns


def generate(data_file: str, output_dir: str = None, lang: str = "zh",
             assets_dir: str = None, icon_base: str = None):
    _assets = Path(assets_dir) if assets_dir else RANKING_ASSETS
    _icon_base = Path(icon_base) if icon_base else None
    loc = load(lang)

    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    year = str(data.get("year", "2026"))
    month = data.get("month", loc.get("default_month", "X月"))

    subtitle = loc["subtitle"].replace("{year}", year)
    title_text = loc["title"].replace("{month}", month)

    theme = THEMES.get(data.get("theme", "red"), THEMES["red"])
    podium = build_podium(data.get("top3", []), _icon_base)
    rankings = build_rankings(data.get("rankings", []), _icon_base)

    env = Environment(loader=FileSystemLoader(str(_assets)))
    template = env.get_template("template.html")

    hero_bg_rel = data.get("hero_bg")
    hero_bg = None
    bg_path = None
    if hero_bg_rel:
        bg_path = Path(hero_bg_rel)
        if not bg_path.exists():
            bg_path = _assets / hero_bg_rel
        if not bg_path.exists() and output_dir:
            bg_path = Path(output_dir) / hero_bg_rel
        if not bg_path.exists():
            bg_path = None
    if not bg_path:
        bg_path = _assets / "hero_bg.png"
    if bg_path.exists():
            b64 = base64.b64encode(bg_path.read_bytes()).decode()
            suffix = bg_path.suffix.lower()
            mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
            if suffix == ".gif":
                mime = "image/gif"
            hero_bg = f"data:{mime};base64,{b64}"

    overlay = data.get("overlay", {})
    title_font = find_title_font(_assets)
    title_font_format = "truetype"
    if title_font:
        suffix = Path(title_font).suffix.lstrip(".")
        title_font_format = {"ttf": "truetype", "otf": "opentype", "woff2": "woff2", "woff": "woff"}.get(suffix, "truetype")

    body_font = find_body_font(_assets)
    body_font_format = "opentype"

    decorations = data.get("decorations", {})
    medal_style = decorations.get("medal_style", "")
    medals = {}
    medal_map = {}
    if medal_style:
        medal_dir = _assets / "medals"
        for tier, rank in [("gold", 1), ("silver", 2), ("bronze", 3)]:
            key = f"medal_{tier}"
            for fname in [f"{medal_style}_{tier}.png", f"{tier}.png"]:
                fp = medal_dir / fname
                if fp.exists():
                    b64 = base64.b64encode(fp.read_bytes()).decode()
                    data_url = f"data:image/png;base64,{b64}"
                    medals[key] = data_url
                    medal_map[rank] = data_url
                    break
        for fname in ["corner_badge.png"]:
            fp = medal_dir / fname
            if fp.exists():
                b64 = base64.b64encode(fp.read_bytes()).decode()
                medals["medal_corner"] = f"data:image/png;base64,{b64}"
                break

    crowns = resolve_crowns(_assets)

    html = template.render(
        year=year,
        month=month,
        theme=theme,
        podium=podium,
        rankings=rankings,
        hero_bg=hero_bg,
        overlay=overlay,
        medals=medals,
        medal_map=medal_map,
        medal_style=medal_style,
        title_font=title_font,
        title_font_format=title_font_format,
        body_font=body_font,
        body_font_format=body_font_format,
        crown_no1=crowns.get("crown_no1", ""),
        crown_no2=crowns.get("crown_no2", ""),
        crown_no3=crowns.get("crown_no3", ""),
        subtitle=subtitle,
        title=title_text,
        html_lang=loc["html_lang"],
        logo_text=loc["logo_text"],
        badge_new=loc["badge_new"],
        footer_note=data.get(
            "footer_note",
            loc.get("default_footer_note", ""),
        ),
    )

    temp_html = _assets / "_temp_render.html"
    temp_html.write_text(html, encoding="utf-8")

    if output_dir is None:
        output_dir = str(PROJECT_ROOT / "output")
    os.makedirs(output_dir, exist_ok=True)

    base_name = loc["output_filename"].replace("{year}", str(year)).replace("{month}", month)
    stem, ext = os.path.splitext(base_name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stem}_{ts}{ext}"
    output_path = Path(output_dir) / filename

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 800})
        page.goto(f"file://{temp_html.absolute()}")
        page.wait_for_timeout(800)
        height = page.evaluate("document.documentElement.scrollHeight")
        page.set_viewport_size({"width": 1080, "height": height})
        page.wait_for_timeout(200)
        page.screenshot(path=str(output_path), full_page=True, type="jpeg", quality=95)
        browser.close()

    temp_html.unlink()
    print(_t(lang, "cli.generate_complete", path=output_path))
    return str(output_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate.py <data.json> [output_dir] [--lang zh|en] [--assets-dir ASSETS] [--icon-base ICON_DIR]")
        sys.exit(1)

    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lang = "zh"
    assets_dir = None
    icon_base = None
    for i, a in enumerate(sys.argv[1:]):
        if a.startswith("--lang="):
            lang = a.split("=", 1)[1]
        elif a == "--lang":
            lang = sys.argv[i + 2]
        elif a.startswith("--assets-dir="):
            assets_dir = a.split("=", 1)[1]
        elif a == "--assets-dir":
            assets_dir = sys.argv[i + 2]
        elif a.startswith("--icon-base="):
            icon_base = a.split("=", 1)[1]
        elif a == "--icon-base":
            icon_base = sys.argv[i + 2]

    data_file = _args[0] if _args else None
    output_dir = _args[1] if len(_args) > 1 else None
    if not data_file:
        print("Usage: python generate.py <data.json> [output_dir] [--lang zh|en]")
        sys.exit(1)

    generate(data_file, output_dir, lang, assets_dir=assets_dir, icon_base=icon_base)
