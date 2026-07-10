# Banner Background From Description — 规范摘要

本 Skill 遵守 **banner-composer 的共享规范**，仅做摘要；完整安全区与画布约定见 [banner-composer/references/spec.md](../../banner-composer/references/spec.md)。

## 共享规范

- **安全区**：纵向 y = 931～1457。裁切时，核心画面/主体须落在此范围内（中心裁切或按比例）。
- **目标尺寸**：与 banner-composer 画布一致（预设或显式 W×H），见 [banner-composer/references/presets.md](../../banner-composer/references/presets.md)。

## 输出

- **目录**：默认 `./output/`。
- **格式**：PNG 或 JPG，与 banner-composer 兼容。

## 与 banner-background-from-image 的差异

- 本 Skill：**无输入图**，由一句描述经文生图 → 再裁切到 W×H。
- banner-background-from-image：**有输入图**，裁切/扩图/去文字。两者输出规格一致，均可作为 banner-composer 的背景图。
