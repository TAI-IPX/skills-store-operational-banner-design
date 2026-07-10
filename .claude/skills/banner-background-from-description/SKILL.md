---
name: banner-background-from-description
description: Generate a banner background image from a short description or marketing copy (e.g. "我们喜爱的独立游戏", "发现远足秘径"). Default image backend is nano-banana-2 (BANNER_IMAGE_BACKEND=nano-banana); optional gemini for direct API. Then crops to target W×H with shared safe zone. Use when the user wants a banner background created from text only—not from an existing image. Output is suitable for banner-composer. For existing images use banner-background-from-image.
license: Complete terms in LICENSE.txt
---

# Banner Background From Description

Generate a banner-ready background image from **one short description** (运营文案/营销句). No source image—text to image, then crop to target size with shared safe zone.

## When to use

- User gives a **sentence or phrase** and wants a banner background generated from it.
- No existing image; the background is to be **created** from the description.
- Output must match banner-composer canvas (presets or W×H) and shared safe zone.

## When NOT to use

- User provides an **existing image** to use as background → use **banner-background-from-image** instead.

## Shared spec (must follow)

This skill follows the **shared specification** from banner-spec:

- **Safe zone**: Cropping keeps core content within **x = 752～1457, y = 0～464** (see [banner-spec/references/spec.md](../banner-spec/references/spec.md)).
- **Output**: Default dir `./output/`; format PNG or JPG; dimensions = target W×H (same as banner-composer).

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Description | Yes | One short phrase or sentence (e.g. 我们喜爱的独立游戏, 发现远足秘径). |
| Target W×H | No | Preset name or explicit width×height; default same as banner-composer (1976×464). |
| Output path | No | Default `./output/`; filename or full path. |

## Workflow

1. **Description → image prompt**: Turn the user description into an image-generation prompt (no text in image, wide/banner-friendly, subject in lower half for safe zone).
2. **Text-to-image**: 默认使用 nano-banana-2（需安装 Bun 并配置 `~/.nano-banana/.env` 或 `GEMINI_API_KEY`）。可通过环境变量 `BANNER_IMAGE_BACKEND=gemini` 改为直接调用 Gemini API。
3. **Crop to target**: Run the same crop logic as banner-background-from-image (crop to W×H, safe-zone aware). No expand—generated image is always cropped to exact size.
4. **Output**: Save to the chosen path; format compatible with banner-composer.

## Resources

- **模型指定（--model）**: [references/model_aliases.md](references/model_aliases.md) — 支持 `gemini` / `t8-gemini` / `t8-jimeng` 三种指令，便于指定调用。
- **Spec summary**: [references/spec.md](references/spec.md)
- **Shared spec (safe zone, canvas)**: [banner-spec/references/spec.md](../banner-spec/references/spec.md)
- **Presets**: [banner-composer/references/presets.md](../banner-composer/references/presets.md)
- **Scripts**:
  - `scripts/generate_from_description.py` — Entry: description + optional preset/W×H/output、**--model gemini|t8-gemini|t8-jimeng** → text-to-image → crop → save. Run with `--help`. 未指定 `--model` 时由环境变量 `BANNER_IMAGE_BACKEND` 决定；见 [references/model_aliases.md](references/model_aliases.md)。
  - `scripts/requirements.txt` — Pillow (for crop step if invoked in-process); optional.

## Dependencies

- Python 3.
- **GEMINI_API_KEY** (required for image generation). Same as banner-background-from-image: [references/gemini_edit.md](../banner-background-from-image/references/gemini_edit.md).
- Crop step reuses **banner-background-from-image** scripts: `crop_to_target.py` (same repo path). Pillow is required by that script.

## Integration with other banner skills

- **banner-composer**: Use this skill's output as the background image path.
- **banner-background-from-image**: Use when the user has an existing image; use this skill when the user has only a description. Both output the same W×H and format for banner-composer.
