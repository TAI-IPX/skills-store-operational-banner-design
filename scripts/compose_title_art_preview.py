#!/usr/bin/env python3
"""Compose preview: background + transparent title art PNG by spec title_art_rect."""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Requires Pillow. Install: pip install Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SPEC_SCRIPTS = ROOT / ".claude" / "skills" / "banner-spec" / "scripts"
if SPEC_SCRIPTS.is_dir():
    sys.path.insert(0, str(SPEC_SCRIPTS))
import spec as _spec

PRESETS = _spec.PRESETS
get_layout = _spec.get_layout


def _alpha_trim(img: Image.Image) -> Image.Image:
    """Trim fully transparent border for stable fit behavior."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("title art image is fully transparent")
    return img.crop(bbox)


def compose_title_art_preview(
    background_path: str,
    title_art_path: str,
    output_path: str,
    *,
    width: int,
    height: int,
    preset_name: str | None = None,
    rect: tuple[int, int, int, int] | None = None,
    fit_scale: float | None = None,
) -> Path:
    """Paste title art into rect center with fit scale."""
    layout = get_layout(width, height, preset_name)
    use_rect = rect or layout.get("title_art_rect")
    if not use_rect:
        raise ValueError("layout has no title_art_rect; please pass --rect")
    x_min, x_max, y_min, y_max = use_rect
    rw = max(1, x_max - x_min)
    rh = max(1, y_max - y_min)

    scale_k = float(fit_scale if fit_scale is not None else layout.get("title_art_fit_scale", 1.0))
    if scale_k <= 0:
        raise ValueError("fit_scale must be > 0")

    bg = Image.open(background_path).convert("RGB")
    if bg.size != (width, height):
        bg = bg.resize((width, height), Image.Resampling.LANCZOS)

    art = _alpha_trim(Image.open(title_art_path).convert("RGBA"))
    aw, ah = art.size
    fit = min(rw / aw, rh / ah) * scale_k
    nw = max(1, int(round(aw * fit)))
    nh = max(1, int(round(ah * fit)))
    art = art.resize((nw, nh), Image.Resampling.LANCZOS)

    px = x_min + (rw - nw) // 2
    py = y_min + (rh - nh) // 2
    bg_rgba = bg.convert("RGBA")
    bg_rgba.paste(art, (px, py), art)

    out = Path(output_path)
    if not out.suffix:
        out = out.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    bg_rgba.convert("RGB").save(str(out), "PNG")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compose preview from background + transparent title art PNG."
    )
    parser.add_argument("background", help="Background image path")
    parser.add_argument("title_art", help="Transparent title art PNG path")
    parser.add_argument("output", help="Output preview path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS), default="legend_top_banner_3840")
    group.add_argument("--width", "-W", type=int, help="Canvas width (use with --height)")
    parser.add_argument("--height", "-H", type=int, help="Canvas height (use with --width)")
    parser.add_argument(
        "--rect",
        nargs=4,
        type=int,
        metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"),
        help="Override title art rect",
    )
    parser.add_argument("--fit-scale", type=float, default=None, help="Override fit scale, e.g. 0.95")
    args = parser.parse_args()

    if args.width is not None and args.height is not None:
        width, height = args.width, args.height
        preset_name = None
    else:
        width, height = PRESETS[args.preset]
        preset_name = args.preset

    rect = tuple(args.rect) if args.rect else None
    out = compose_title_art_preview(
        args.background,
        args.title_art,
        args.output,
        width=width,
        height=height,
        preset_name=preset_name,
        rect=rect,
        fit_scale=args.fit_scale,
    )
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
