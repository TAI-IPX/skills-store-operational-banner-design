#!/usr/bin/env python3
"""
HD 生产线主入口 (-hd)
用法:
  python scripts/run_hd.py -p "蓝天雪山奇幻植物..." [-g "LZ顶部banner"] [--packy7s]

流程:
  Step 0: 从 OpenCode 缓存提取图片（3张人物）
  Step 1: Gemini bbox 检测 → 裁切 → BiRefNet 抠图
  Step 2: Gemini 智能排版（95%/90%/88%）→ layout_ref.png
  Step 3: 主体完整性检测 + inpaint 补齐 + 统一光源
  Step 4: prompt 生成 4128×1024 背景 + 风格检查 → 3840×1200
  Step 5: 最终合成 + 割裂检测（不合格重试）→ LZ顶部banner 3840x1200.png
"""
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# 路径约束验证
from _paths import validate_paths
validate_paths()

from _env import load_env
_ENV_KEYS = (
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_VISION_MODEL",
    "GOOGLE_GEMINI_BASE_URL", "PACKY_API_KEY", "PACKY7S_API_KEY", "PACKY3S_API_KEY",
    "T8STAR_API_KEY", "BANNER_IMAGE_BACKEND", "T8STAR_IMAGE_MODEL", "T8STAR_BASE_URL",
    "XINGCHENGPT_API_KEY", "XINGCHENGGPT_API_KEY", "XINGCHENGPT_BASE_URL", "XINGCHENGGPT_BASE_URL",
    "XINGCHENGEMINI_API_KEY", "XINGCHENGEMINI_BASE_URL",
    "XINGCHENGEMINI1_API_KEY", "XINGCHENGEMINI1_BASE_URL",
    "MOXINGEMINI_API_KEY", "MOXINGEMINI_BASE_URL",
    "HD_VISION_BACKEND", "HD_VISION_GEMINI_FALLBACK",
)
load_env(_ENV_KEYS)


def _get_current_session_chain() -> list[str]:
    """获取当前 session 及其所有祖先 session 的 ID 列表。"""
    import subprocess
    import shutil
    try:
        _opencode = shutil.which("opencode-cli") or shutil.which("opencode")
        if not _opencode:
            _opencode = str(Path.home() / "AppData" / "Local" / "opencode" / "opencode-cli.exe")
        r = subprocess.run(
            [_opencode, "db",
             "SELECT id, parent_id FROM session ORDER BY time_created DESC LIMIT 20",
             "--format", "json"],
            capture_output=True, timeout=10,
        )
        rows = json.loads(r.stdout.decode("utf-8", errors="replace"))
        # 找最新 session，沿 parent_id 链向上
        if not rows:
            return []
        latest = rows[0]["id"]
        id_to_parent = {row["id"]: row.get("parent_id") for row in rows}
        chain = []
        cur = latest
        while cur:
            chain.append(cur)
            cur = id_to_parent.get(cur)
        return chain
    except Exception:
        return []


def _grab_images() -> list[tuple[str, bytes]]:
    from scripts.grab_opencode_image import extract_images_from_db, extract_images_from_cache, CACHE_DIR, _copy_locked, _find_cache_files
    import tempfile

    # 优先从 SQLite 数据库读取
    # 策略：在当前 session 链中，找最新一条有图片的消息
    session_chain = _get_current_session_chain()
    for session_id in session_chain:
        db_images = extract_images_from_db(session_id=session_id, latest_message_only=True)
        if db_images:
            seen: set = set()
            unique = []
            for fmt, data in db_images:
                h = hash(data[:512] + data[-512:])
                if h not in seen:
                    seen.add(h); unique.append((fmt, data))
            if unique:
                print(f"[HD] 从数据库 session={session_id[:20]} 提取到 {len(unique)} 张图片", file=sys.stderr)
                return unique

    # 回退：从 EBWebView 缓存文件扫描
    cache_files = _find_cache_files()
    if not cache_files:
        print(f"[error] 未找到 OpenCode 缓存文件: {CACHE_DIR}", file=sys.stderr); sys.exit(1)
    all_images: list[tuple[str, bytes]] = []
    for cf in cache_files:
        tmp_dir = Path(tempfile.mkdtemp(prefix="hd_"))
        tmp_copy = tmp_dir / "cache.bin"
        if not _copy_locked(cf, tmp_copy):
            continue
        images = extract_images_from_cache(tmp_copy)
        all_images.extend(images)
        try:
            tmp_copy.unlink(); tmp_dir.rmdir()
        except Exception:
            pass
    if not all_images:
        print("[error] 缓存中未找到图片", file=sys.stderr); sys.exit(1)
    seen: set = set()
    unique = []
    for fmt, data in all_images:
        h = hash(data[:512] + data[-512:])
        if h not in seen:
            seen.add(h); unique.append((fmt, data))
    return unique



def main():
    parser = argparse.ArgumentParser(description="HD 4-Stage 产线: LZ 顶部 Banner 3840x1200")
    parser.add_argument("--prompt", "-p", default="game activity banner", help="背景描述")
    parser.add_argument("--group", "-g", default="LZ顶部banner", help="规范分组")
    parser.add_argument("--hd", "-hd", action="store_true", help="HD 专属管线标记")
    parser.add_argument("--input", "-i", nargs="+", dest="input_paths", metavar="IMAGE",
                        help="人物图路径（3 张）。未传时从 OpenCode 缓存提取。")

    parser.add_argument("--packy", action="store_true"); parser.add_argument("--packy7s", action="store_true")
    parser.add_argument("--packy3s", action="store_true"); parser.add_argument("--gemini", action="store_true")
    parser.add_argument("--packygpt", "-packygpt", action="store_true", dest="packygpt")
    parser.add_argument("--micugpt2", "-micugpt2", action="store_true", dest="micugpt2")
    parser.add_argument("--micugemini", "-micugemini", action="store_true", dest="micugemini")
    parser.add_argument("--moxingpt", "-moxingpt", action="store_true", dest="moxingpt")
    parser.add_argument("--moxingemini", "-moxingemini", action="store_true", dest="moxingemini")
    parser.add_argument("--xingchengpt", "-xingchengpt", action="store_true", dest="xingchengpt")
    parser.add_argument("--xinchengpt", "-xinchengpt", action="store_true", dest="xinchengpt")
    parser.add_argument("--xingchengemini", "-xingchengemini", action="store_true", dest="xingchengemini")
    parser.add_argument("--xingchengemini1", "-xingchengemini1", action="store_true", dest="xingchengemini1")

    parser.add_argument("--skip-cutout", action="store_true", help="跳过抠图，直接使用原图")
    parser.add_argument("--hero-first", action="store_true", help="首张固定中槽")
    parser.add_argument("--title-art-main", "-m", default="", help="主标题")
    parser.add_argument("--title-art-sub", "-s", default="", help="副标题")
    parser.add_argument("--logo", "-l", default=None, help="Logo 图片路径，粘贴到 LOGO_RECT 区域")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="输出目录")
    args = parser.parse_args()

    # xingchengemini1：直接设 GEMINI_API_KEY，后续复用 Gemini 流程
    if args.xingchengemini1:
        key1 = os.environ.get("XINGCHENGEMINI1_API_KEY", "").strip()
        if key1:
            base1 = os.environ.get("XINGCHENGEMINI1_BASE_URL", "").strip() or "https://api.centos.hk"
            os.environ["GEMINI_API_KEY"] = key1
            os.environ["GOOGLE_GEMINI_BASE_URL"] = base1
            if not os.environ.get("GEMINI_VISION_MODEL"):
                os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"

    from _packy import apply_packy_backend
    apply_packy_backend(args)
    # centos.hk 自动走 hd_vision.py 内置 OpenAI-compat Vision（_is_centos_hk 检测）
    # 只需设正确的 GEMINI_VISION_MODEL
    if args.xingchengemini1:
        os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-pro-preview"
    elif args.xingchengemini:
        os.environ["GEMINI_VISION_MODEL"] = "gemini-3.1-flash-image-preview"

    image_paths: list[Path] = []
    if args.input_paths:
        for raw_path in args.input_paths:
            p = Path(raw_path.lstrip("@"))
            if not p.is_absolute(): p = ROOT / p
            if not p.is_file(): print(f"[error] 找不到文件: {p}", file=sys.stderr); sys.exit(1)
            image_paths.append(p.resolve())

    out_dir = args.output_dir
    if out_dir is None:
        out_dir = ROOT / "output" / f'hd_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    elif not out_dir.is_absolute(): out_dir = ROOT / out_dir
    out_dir = out_dir.resolve(); out_dir.mkdir(parents=True, exist_ok=True)

    if not image_paths:
        raw_images = _grab_images()
        if len(raw_images) < 1: print("[error] 至少需要 1 张人物图", file=sys.stderr); sys.exit(1)
        input_dir = out_dir / "input"; input_dir.mkdir(exist_ok=True)
        for i, (fmt, data) in enumerate(raw_images[:5]):
            ext = "jpg" if fmt == "jpeg" else fmt
            p = input_dir / f"img_{i}.{ext}"; p.write_bytes(data)
            image_paths.append(p)

    if len(image_paths) < 1: print("[error] 至少需要 1 张人物图", file=sys.stderr); sys.exit(1)

    print(f"[HD] 输入 {len(image_paths)} 张:", flush=True)
    for i, p in enumerate(image_paths): print(f"  [{i}] {p.name}", flush=True)
    print(f"[HD] 输出: {out_dir}", flush=True)
    print(f"[HD] BANNER_IMAGE_BACKEND: {os.environ.get('BANNER_IMAGE_BACKEND', '(未设置)')}", flush=True)

    from scripts.hd.pipeline import run_hd_pipeline
    logo_path = None
    if args.logo:
        lp = Path(args.logo.lstrip("@"))
        if not lp.is_absolute():
            lp = ROOT / lp
        if not lp.is_file():
            print(f"[error] 找不到 logo 文件: {lp}", file=sys.stderr); sys.exit(1)
        logo_path = lp.resolve()
    elif image_paths:
        # 未指定 --logo 时，从 --input 中按文件名匹配
        LOGO_KEYWORDS = ("logo",)
        for p in image_paths[:]:
            if any(k in p.stem.lower() for k in LOGO_KEYWORDS):
                logo_path = p
                image_paths.remove(p)
                print(f"[HD] 自动识别 Logo: {p.name}", flush=True)
                break
    result = run_hd_pipeline(
        image_paths=image_paths, prompt=args.prompt, out_dir=out_dir,
        main_title=args.title_art_main, subtitle=args.title_art_sub,
        hero_first=args.hero_first,
        skip_cutout=args.skip_cutout,
        logo_path=logo_path,
    )

    print(f"\n终稿含文案: {result['stage3']['final']}")
    print(f"终稿无文案: {result['stage3']['final_nc']}")


if __name__ == "__main__":
    main()
