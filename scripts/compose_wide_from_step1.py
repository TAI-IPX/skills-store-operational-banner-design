import sys
from pathlib import Path


def _read_first_line(p: Path) -> str:
    if not p.is_file():
        raise FileNotFoundError(str(p))
    txt = p.read_text(encoding="utf-8").strip()
    return (txt.splitlines()[0] if txt else "").strip()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="从 output/<子目录>/step1_wide.png 合成专题长图")
    ap.add_argument(
        "--dir",
        default="a5b_white_test",
        help="output 下的子目录名（默认 a5b_white_test）",
    )
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    sub = args.dir
    step1 = root / "output" / sub / "step1_wide.png"
    out = root / "output" / sub / "专题长图 3320x460.png"

    sys.path.insert(0, str(root / ".claude" / "skills" / "banner-composer" / "scripts"))
    sys.path.insert(0, str(root / ".claude" / "skills" / "banner-spec" / "scripts"))
    import spec
    from compose_banner import compose

    main_title = _read_first_line(root / "input" / "run_full_main_title.txt")
    subtitle = _read_first_line(root / "input" / "run_full_subtitle.txt")
    w, h = spec.PRESETS["wide"]

    out.parent.mkdir(parents=True, exist_ok=True)
    compose(str(step1), str(out), main_title, subtitle, width=w, height=h, use_ai_linebreak=True, logo_path=None)
    print(f"OK: {out}")


if __name__ == "__main__":
    main()

