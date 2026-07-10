---
name: banner-background-from-image
description: Prepare a single banner background image from a user-provided image to meet target width×height. Decides between crop, outpainting (expand with image model to fill missing areas and handle occlusion), or both—based on achieving the best visual result for the target size. Respects shared safe zone (x=770～1457, y=0～464); can remove irrelevant text from the image. Use when the user provides an existing image to use as a banner background; output is intended for banner-composer. Does not generate images from text—use banner-background-from-description for that.
license: Complete terms in LICENSE.txt
---

# Banner Background From Image

Turn a user-provided image into a banner-ready background: target width×height, best visual result (crop and/or expand), safe zone respected, optional text removal.

## When to use

- User provides an existing image and wants it as a banner background.
- Need to fit target dimensions (from banner presets or shared spec) with best possible composition.
- May need to expand missing regions (via image model) or remove irrelevant text; decision is driven by **best visual outcome for the target size**, not just pixel coverage.

## Shared spec (must follow)

This skill follows the **shared specification** from banner-composer. When cropping or expanding:

- **Safe zone**: Keep core/subject content within **x = 752～1457, y = 0～464** (see [banner-spec/references/spec.md](../banner-spec/references/spec.md)). Output dimensions must match the target W×H used by banner-composer.
- **Output**: Default dir `./output/`; format PNG or JPG as needed for downstream.

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| Source image | Yes | Path to the user-provided image. |
| Target width × height | Yes | From preset or explicit W, H (same as banner-composer canvas). |
| Output path | No | Default `./output/`; filename or path. |

## Workflow (high level)

1. **Optional text removal**: If the image contains irrelevant text (watermarks, captions), remove it first or after resize (see [references/workflow.md](references/workflow.md)).
2. **Decide crop vs expand**: For the given target W×H, choose the strategy that yields the **best visual result** (composition, subject in safe zone, natural look). Options: crop only, expand only, or crop + expand. Expansion uses an image model to fill missing regions and handle occlusion.
3. **Execute**: Crop and/or expand; ensure subject/core stays in safe zone; output W×H image to the chosen path.

Full decision flow and safe-zone usage: [references/workflow.md](references/workflow.md).

## Resources

- **Decision flow (crop vs expand, safe zone, text removal)**: [references/workflow.md](references/workflow.md)
- **Shared spec (safe zone, canvas)**: [banner-spec/references/spec.md](../banner-spec/references/spec.md)
- **Target presets**: [banner-composer/references/presets.md](../banner-composer/references/presets.md)
- **Scripts** (for multi-user consistency):
  - `scripts/crop_to_target.py` — Crop (and scale) source to W×H; safe-zone aware; optional `--subject-y` (0..1). Run with `--help` for args.
  - `scripts/prepare_background.py` — Entry point: crop and/or expand (Gemini), optional remove-text. **Auto subject**: when `GEMINI_API_KEY` is set and `--subject-y` is not given, uses Gemini Vision to detect main subject position for better crop (use `--no-auto-subject` to force center crop).
  - `scripts/gemini_image_edit.py` — 图像编辑（outpaint/去字）。**默认固定使用 Gemini 3.1 API**（`gemini-3.1-flash-image-preview`）；`BANNER_IMAGE_BACKEND=nano-banana` 可改用 nano-banana CLI。Used by prepare_background when key is set; can be run standalone with `--mode outpaint` or `--mode remove-text`.
  - `scripts/gemini_subject_detect.py` — Gemini Vision: returns main subject vertical center as 0–1 ratio for crop; used by prepare_background when auto subject is on.
  - `scripts/requirements.txt` — Pillow. Install: `pip install -r scripts/requirements.txt`.

## Dependencies

- Python 3, Pillow (`pip install -r scripts/requirements.txt`).
- **扩图 / 去文字**：默认**固定使用 Gemini 3.1 API**（`gemini-3.1-flash-image-preview`），需 `GEMINI_API_KEY`。环境变量 `BANNER_IMAGE_BACKEND=nano-banana` 可改用 nano-banana CLI。见 [references/gemini_edit.md](references/gemini_edit.md)。未设置 key 时仅执行裁切。
