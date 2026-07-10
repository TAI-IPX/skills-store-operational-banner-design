# Banner Background From Image — 规范摘要

本 Skill 遵守 **banner-composer 的共享规范**，仅做摘要；完整安全区与画布约定见 [banner-composer/references/spec.md](../../banner-composer/references/spec.md)。

## 共享规范

- **安全区**：人为规定的固定区域（x=770～1457，y=0～464，画布 1976×464），仅识别并执行，不参与计算。裁切或扩图时，核心画面/主体须落在此范围内。
- **目标尺寸**：与 banner-composer 画布一致（预设或显式 W×H），见 [banner-composer/references/presets.md](../../banner-composer/references/presets.md)。

## 输出

- **目录**：默认 `./output/`。
- **格式**：PNG 或 JPG，与下游（banner-composer）兼容即可。

## 决策原则

裁切 vs 扩图由**目标宽高下的最佳画面效果**决定，详见 [workflow.md](workflow.md)。
