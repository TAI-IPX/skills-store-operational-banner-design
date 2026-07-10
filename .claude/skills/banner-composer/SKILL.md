---
name: banner-composer
description: Compose banner images from a background image, main title, and subtitle according to fixed layout rules (canvas size, typography, positions, line breaks, gradient overlay). Use when the user needs to generate or assemble a single banner asset with text overlay, preset dimensions (default 1976×464 or other presets), Microsoft YaHei typography, and optional gradient mask. Does not create backgrounds from scratch—use with banner-background-from-image or banner-background-from-description for the background.
license: Complete terms in LICENSE.txt
---

# Banner Composer

Compose one banner image: paste a background, apply gradient overlay, then draw main title and subtitle with fixed typography and line-break rules. Output is a single PNG.

## When to use

- User provides (or has) a background image and wants a banner with main + subtitle text.
- User specifies canvas size (or preset name), main title, and optional subtitle.
- Output must follow the spec: 微软雅黑 main/subtitle, fixed positions, 8-char / 14-char line breaks, gradient overlay.

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Canvas size | No (default 1976×464) | Width×height or preset name from [presets](references/presets.md). |
| Background image | Yes | Path to image file; will be scaled/cropped to canvas. |
| Main title | Yes | Text for main title; wraps at 8th character. |
| Subtitle | No | Text for subtitle; wraps at 14th character. |
| Output path | Yes | Filename or path; default dir `./output/`. Format: default `.png`, or `.jpg`. |

Optional overrides (e.g. font paths, colors) can be passed to the script when needed; see script help and [spec](references/spec.md).

## Workflow

1. Resolve canvas size: use preset from [references/presets.md](references/presets.md) or explicit width×height (default 1976×464).
2. Load and fit background to canvas (scale/crop as needed).
3. Apply gradient overlay per [references/spec.md](references/spec.md) (1270×464, black→transparent, 30% opacity).
4. Draw main title per spec (font, size, position, 8-char wrap); compute subtitle Y as main-title bottom + 24px.
5. Draw subtitle per spec (font, size, 80% opacity, 14-char wrap).
6. Save to the given output path (default dir `./output/`; format PNG or JPG from extension).

## 与背景 Skill 联用时的输出

- **一键只出一张图**：使用 `scripts/make_banner_from_image.py`（原图 + 主标题 + 副标题），中间背景写临时文件后自动删除，`output/` 中只保留最终合成图。
- **分步调用**：若先运行 **banner-background-from-image** 再运行本 Skill 的 `compose_banner.py`，`output/` 中会有两张图（中间背景 + 最终图）；若只需最终图，可手动删除中间文件，或改用上面的 `make_banner_from_image.py`。

## Resources

- **Full layout and typography rules（含共享规范）**: [references/spec.md](references/spec.md) — 含安全区等**共享规范**，后续与 banner 相关的 Skill（如裁切、扩图）应引用并遵守。
- **Canvas size presets (~20 sizes)**: [references/presets.md](references/presets.md)
- **Composition script**: `scripts/compose_banner.py` — run with `--help` for arguments (background path, main title, subtitle, output path, optional preset or width/height). **主标题**：当设置 `GEMINI_API_KEY` 时由 Gemini 智能换行（通用规则，不拆词）；可用 `--no-ai-linebreak` 关闭。**副标题**：不设换行规则，单行显示。
- **一键出图（仅保留最终图）**: `scripts/make_banner_from_image.py` — 输入原图 + 主标题 + 副标题，内部先做背景（可 `--remove-text`）再合成，**中间背景写临时文件后删除**，故 `output/` 中只生成一张最终图。参数与上类似，含 `--main-title`、`--subtitle`、`--remove-text`、`--preset` 等。
- **智能换行**: `scripts/gemini_linebreak.py` — 仅主标题：调用 Gemini 返回换行位置（通用规则）；副标题无换行规则。
- **字体安装说明**: [references/install_font.md](references/install_font.md)（Windows / macOS）。
- **字体检测**: `scripts/install_font.py` — 检测微软雅黑是否已安装，未安装时输出安装指引。

## Dependencies

- Python 3
- Pillow (PIL). Install: `pip install Pillow`
- **字体**: 微软雅黑（唯一合规，无备选）。主标题用 Bold (`msyhbd.ttf`)，副标题用 Regular (`msyh.ttf`)。未安装时合成脚本会报错并退出；安装说明见 [references/install_font.md](references/install_font.md)（支持 Windows 与 macOS）。可先运行 `scripts/install_font.py` 检测是否已安装。
- **主标题 AI 换行（可选）**: 设置 `GEMINI_API_KEY` 时主标题启用智能换行；未设置时主标题固定 8 字/行。副标题无换行规则，单行显示。
