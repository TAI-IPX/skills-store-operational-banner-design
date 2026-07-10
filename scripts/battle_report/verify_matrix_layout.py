#!/usr/bin/env python3
"""断言核心资源矩阵七行固定排版、自动归类与 Banner 顶裁（无需全量合成）。"""
from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from battle_report.compose_battle_report import (  # noqa: E402
    _build_flow_plan,
    _build_matrix_seven_row_plan,
    _matrix_portrait_pair_rows,
    _paste_section_banner_character,
)
from battle_report.section_assets import (  # noqa: E402
    _read_matrix_order_file,
    _resolve_matrix_groups,
    guess_store_or_lz,
    is_matrix_pair_vertical_slot,
    parse_section_folder,
)


def _make_png(path: Path, w: int, h: int, *, fill: tuple[int, int, int] = (128, 128, 128)) -> Path:
    Image.new("RGB", (w, h), fill).save(path)
    return path


def _plan_labels(plan: list[tuple[str, list[Path]]]) -> list[tuple[str, list[str]]]:
    return [(kind, [p.name for p in paths]) for kind, paths in plan]


def _assert_seven_row_core(labels: list[tuple[str, list[str]]]) -> None:
    assert labels[0] == ("pair", ["01.png", "02.png"]), labels[0]
    assert labels[1] == ("full", ["03.png"]), labels[1]
    assert labels[2] == ("triple", ["05.png", "06.png", "07.png"]), labels[2]
    assert labels[3] == ("full", ["04.png"]), labels[3]
    assert labels[-1] == ("full", ["08.png"]), labels[-1]


def verify_banner_top_crop() -> None:
    src = inspect.getsource(_paste_section_banner_character)
    assert "_paste_cover_in_box_top" in src, "character must use top cover"
    assert "_paste_cover_in_box_bottom" not in src, "character must not use bottom cover"


def verify_portrait_pair_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        tall = [
            _make_png(td / "a.png", 800, 1200),
            _make_png(td / "b.png", 800, 1200),
            _make_png(td / "c.png", 800, 1200),
        ]
        wide = _make_png(td / "w.png", 1200, 800)
        plan = _matrix_portrait_pair_rows(tall)
        assert plan == [("pair", tall[:2]), ("full", [tall[2]])]
        assert _matrix_portrait_pair_rows([wide]) == [("full", [wide])]


def verify_seven_row_synthetic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        (td / "order.txt").write_text(
            "# 长图\n08.png\n\n# 商店\n01.png\n\n# LZ\n02.png\n\n"
            "# 浏览器\n03.png\n04.png\n05.png\n06.png\n07.png\n\n"
            "# 拍摄\nphoto.jpg\n",
            encoding="utf-8",
        )
        paths = [
            _make_png(td / "01.png", 600, 899, fill=(250, 250, 250)),
            _make_png(td / "02.png", 600, 899, fill=(20, 20, 20)),
            _make_png(td / "03.png", 1296, 839),
            _make_png(td / "04.png", 1296, 839),
            _make_png(td / "05.png", 1296, 839),
            _make_png(td / "06.png", 1296, 839),
            _make_png(td / "07.png", 1296, 839),
            _make_png(td / "08.png", 2400, 600),
            _make_png(td / "photo.jpg", 1200, 900),
        ]
        assert is_matrix_pair_vertical_slot(paths[0])
        assert is_matrix_pair_vertical_slot(paths[1])
        name_groups = _read_matrix_order_file(td)
        assert name_groups is not None
        groups, _ = _resolve_matrix_groups(name_groups, paths, td)
        plan = _build_matrix_seven_row_plan(paths, groups)
        assert plan is not None
        labels = _plan_labels(plan)
        _assert_seven_row_core(labels)
        assert labels[4] == ("full", ["photo.jpg"]), labels[4]
        flow = _build_flow_plan(paths, matrix_groups=groups)
        assert _plan_labels(flow) == labels


def verify_desktop_seven_row_plan() -> None:
    folder = Path.home() / "Desktop/战报/核心资源矩阵"
    order_path = folder / "order.txt"
    if not order_path.is_file():
        print("[skip] desktop order.txt not found")
        return

    assets = parse_section_folder(folder, "核心资源矩阵", section_key="b")
    if not assets.matrix_groups:
        raise AssertionError("matrix_groups missing")

    plan = _build_flow_plan(assets.screenshots, matrix_groups=assets.matrix_groups)
    labels = _plan_labels(plan)
    _assert_seven_row_core(labels)
    assert len(labels) >= 7, labels
    print("desktop seven-row plan OK:", len(labels), "rows", labels)


def verify_guess_store_lz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        odd = _make_png(td / "03.png", 800, 1200)
        even = _make_png(td / "04.png", 800, 1200)
        assert guess_store_or_lz(odd) == "store"
        assert guess_store_or_lz(even) == "lz"


def main() -> int:
    verify_banner_top_crop()
    verify_portrait_pair_rows()
    verify_guess_store_lz()
    verify_seven_row_synthetic()
    verify_desktop_seven_row_plan()
    print("verify_matrix_layout: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
