#!/usr/bin/env python3
"""fetch_icons.py - lestore列表匹配 + 搜索兜底 + Steam裁剪备用

用法:
  py scripts/ranking/fetch_icons.py <csv_path> [--out-dir OUTDIR] [--cache CACHE_FILE]
"""

import csv
import os
import sys
import time
import base64
import json
import argparse
import requests
from pathlib import Path
from io import BytesIO
from PIL import Image
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

_SCRIPT_DIR = Path(__file__).parent
_RANKING_ASSETS = _SCRIPT_DIR.parent / "assets" / "ranking"
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_INPUT_RANKING = _PROJECT_ROOT / "input" / "ranking"

AES_KEY = b"65023EC4BA7420BB"
LIST_API = "https://lestore.lenovo.com/api/webstorecontents/class/class_apps_list"
SEARCH_API = "https://lestore.lenovo.com/api/webstorecontents/search/contents"
STEAM_URL = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{}/library_600x900.jpg"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

STEAM = {
    "CS2": 730, "永劫无间": 1049590, "崩坏：星穹铁道": 1287720,
    "鸣潮": 2141740, "原神": 1971870, "绝地求生": 578080,
    "解限机": 2452280, "黑神话：悟空": 2358720, "星露谷物语": 413150,
    "双人成行": 1426210, "Apex英雄": 1172470, "侠盗猎车手": 271590,
    "侠盗猎车手GTA5": 271590, "荒野大镖客2": 1174180, "我的世界": 2566080,
    "极限竞速：地平线4": 1293830, "极限竞速：地平线5": 1551360,
    "赛博朋克2077": 1091500, "求生之路2": 550, "炉石传说": 1465700,
    "练枪实验室/目标实验室": 714010, "泰拉瑞亚": 105600, "幻兽帕鲁": 1623730,
    "NBA 2K25": 2370310, "艾尔登法环": 1245620, "战地5": 1238810,
    "无限暖暖": 2506870, "城市：天际线": 255710, "地下城与勇士": 2483460,
    "文明6": 289070, "剑星": 2139460, "杀戮尖塔": 646570,
    "双影奇境": 2379780, "只狼:影逝二度": 814380, "猛兽派对": 1817190,
    "夏日狂想曲：乡间的难忘回忆": 1227890, "迷失森林": 242760,
    "极限国度": 1619420, "饥荒联机版": 322330, "森林之子": 1326470,
    "绝区零": 2406852,
}

STOP_WORDS = {"PC", "Pc", "pc", "模拟器", "国际服", "无限", "官方版", "官网版", "Steam", "版", "手游", "客户端", "完美世界版"}


def extract_keywords(name):
    raw = name.replace("：", " ").replace(":", " ").replace("/", " ").replace("、", " ")
    tokens = [t for t in raw.split() if t not in STOP_WORDS]
    clean = []
    for t in tokens:
        t = t.split("（")[0].split("(")[0].strip()
        if len(t) >= 2:
            clean.append(t)
    return clean


def match_target(target, gdict):
    if target in gdict:
        return target, gdict[target]
    kws = extract_keywords(target)
    if not kws:
        kws = [target[:3]]
    for name in gdict:
        if all(kw in name for kw in kws):
            return name, gdict[name]
    return None, None


def search_fallback(name):
    kws = extract_keywords(name)
    if not kws:
        kws = [name[:3]]
    try:
        r = requests.post(SEARCH_API, json={"data": aes_encrypt({"searchKey": name})}, headers=HEADERS, timeout=10)
        apps = r.json().get("data", {}).get("apps", [])
        for a in apps[:10]:
            sname, logo = a.get("softName", ""), a.get("logoFile", "")
            if not logo:
                continue
            if all(kw in sname for kw in kws):
                return sname, logo
    except Exception:
        pass
    return None, None


def aes_encrypt(body):
    raw = json.dumps(body, ensure_ascii=False).encode()
    c = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_KEY)
    return base64.b64encode(c.encrypt(pad(raw, 16))).decode()


def fetch_all_games():
    games = {}
    skip, limit = 0, 100
    while True:
        try:
            r = requests.post(LIST_API, json={"data": aes_encrypt({"code": "game", "id": 19, "limit": limit, "skip": skip, "tagId": -1})}, headers=HEADERS, timeout=15)
            data = r.json().get("data", {})
            for a in data.get("apps", []):
                n, l = a.get("softName", "").strip(), a.get("logoFile", "").strip()
                if n and l:
                    games[n] = l
            if skip + limit >= data.get("count", 0):
                break
            skip += limit
            time.sleep(0.3)
        except Exception as e:
            print("ERR: " + str(e))
            break
    return games


def fetch_steam_icon(appid):
    try:
        r = requests.get(STEAM_URL.format(appid), headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code != 200 or len(r.content) < 2048:
            return None
        img = Image.open(BytesIO(r.content))
        w, h = img.size
        if h > w:
            img = img.crop((0, 0, w, w))
        else:
            left = (w - h) // 2
            img = img.crop((left, 0, left + h, h))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None


def download_url(url, path, data=None):
    try:
        if data:
            with open(path, "wb") as f:
                f.write(data)
            return True
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200 and len(r.content) > 1024:
            with open(path, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


def safe_fn(name):
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name


def read_top_from_csv(path, n):
    g = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                rank = int(r["名次"])
            except Exception:
                continue
            if rank <= n and rank not in g:
                g[rank] = r["游戏名称"].strip()
    return [g[r] for r in sorted(g)]


def gen_verify_html(records, out_dir):
    rows = ""
    for rec in records:
        fn = rec["file"]
        cls = "bad" if rec.get("bad") else "ok"
        src = rec.get("source", "")
        matched = rec.get("matched", "") or ""
        rows += '<tr class="{}"><td>{}</td><td><img src="{}" width="64" height="64"></td><td><b>{}</b></td><td>{}</td><td>{}</td></tr>\n'.format(
            cls, rec["rank"], fn, rec["name"], matched, src)

    html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Icon Verify</title>\n'
    html += '<style>body{font-family:Microsoft YaHei,sans-serif;padding:20px;background:#1a1a2e;color:#eee}\n'
    html += 'table{border-collapse:collapse;width:100%}th{background:#16213e;padding:10px 12px;text-align:left}\n'
    html += 'td{padding:8px 12px;border-bottom:1px solid #333}.bad{background:#3e1a1a}\n'
    html += 'img{border-radius:8px;object-fit:cover}b{font-size:15px}</style></head><body>\n'
    html += '<h2>Icon Verify - ' + str(len(records)) + ' games</h2>\n'
    html += '<table><tr><th>#</th><th>Icon</th><th>Game</th><th>Matched</th><th>Source</th></tr>\n'
    html += rows
    html += '</table></body></html>'
    with open(os.path.join(out_dir, "icon_verify.html"), "w", encoding="utf-8") as f:
        f.write(html)


def fetch_icons(csv_path, out_dir, cache_path=None):
    os.makedirs(out_dir, exist_ok=True)

    if cache_path is None:
        cache_path = str(_INPUT_RANKING / "lestore_games.json")
    cache_path = Path(cache_path)

    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            all_games = json.load(f)
        print("从缓存加载 {} 款 lestore 游戏".format(len(all_games)))
    else:
        print("获取 lestore 游戏列表...")
        all_games = fetch_all_games()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(all_games, f, ensure_ascii=False, indent=2)
        print("共 {} 款，已缓存到 {}".format(len(all_games), cache_path))

    top_n = 50
    games = read_top_from_csv(csv_path, top_n)
    records = []
    failed = []
    ok = 0
    results = {}

    for i, name in enumerate(games, 1):
        fn = safe_fn(name)
        rec = {"rank": i, "name": name, "file": "", "source": "", "matched": "", "bad": False}

        print("[{:02d}] {}".format(i, name), end=" ... ", flush=True)

        matched, logo = match_target(name, all_games)
        if matched:
            rec["matched"] = matched
            if matched != name:
                rec["bad"] = True
            ext = os.path.splitext(logo.split("?")[0])[-1] or ".png"
            if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                ext = ".png"
            out_name = fn + ext
            path = os.path.join(out_dir, out_name)
            if download_url(logo, path):
                rec["file"] = out_name
                rec["source"] = "lestore:list"
                print("OK list -> {}".format(matched))
                ok += 1
                records.append(rec)
                results[name] = out_name
                continue

        matched, logo = search_fallback(name)
        time.sleep(0.3)
        if matched:
            rec["matched"] = matched
            if matched != name:
                rec["bad"] = True
            ext = os.path.splitext(logo.split("?")[0])[-1] or ".png"
            if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                ext = ".png"
            out_name = fn + ext
            path = os.path.join(out_dir, out_name)
            if download_url(logo, path):
                rec["file"] = out_name
                rec["source"] = "lestore:search"
                print("OK search -> {}".format(matched))
                ok += 1
                records.append(rec)
                results[name] = out_name
                continue

        appid = STEAM.get(name)
        if appid:
            data = fetch_steam_icon(appid)
            if data:
                sf = fn + ".jpg"
                path = os.path.join(out_dir, sf)
                if download_url("", path, data=data):
                    rec["file"] = sf
                    rec["source"] = "steam:cropped"
                    rec["matched"] = "Steam appid={}".format(appid)
                    print("OK steam -> appid={}".format(appid))
                    ok += 1
                    records.append(rec)
                    results[name] = sf
                    continue

        print("FAIL")
        rec["bad"] = True
        records.append(rec)
        failed.append(name)

    if failed:
        fp = os.path.join(out_dir, "failed.txt")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(failed))
        print("\nFAILED {}: {}".format(len(failed), ", ".join(failed)))

    gen_verify_html(records, out_dir)
    print("\n完成: {}/{}, icon_verify.html 已生成".format(ok, len(games)))
    return results


def main():
    from pathlib import Path as P
    parser = argparse.ArgumentParser(description="批量下载游戏图标")
    parser.add_argument("csv_path", help="CSV 数据文件路径")
    parser.add_argument("--out-dir", default=None, help="图标输出目录")
    parser.add_argument("--cache", default=None, help="lestore 游戏列表缓存文件")
    args = parser.parse_args()

    out_dir = args.out_dir or "output/icons"
    fetch_icons(args.csv_path, out_dir, args.cache)


if __name__ == "__main__":
    main()
