---
name: banner-spec
description: Single source of truth for banner canvas presets, safe zones, legend zones, layout, output filenames, and component specs (e.g., bubble). All banner skills and generate_bubble.py derive spec data from here.
license: Same as repo.
---

# Banner Spec（规范管理）

本 Skill 是 **banner 规范的唯一数据源**：预设名与尺寸、安全区、图例区、布局配置、规范分组（-g）与输出文件名均在此定义。文生图（banner-background-from-description）、图生图（banner-background-from-image）、合成（banner-composer）及根目录 `run_all_presets.py` 应从此处读取规范，不再各自维护一份。

## When to use

- 需要查询或修改「画布预设、安全区、图例区、布局、规范分组」时，只改本 Skill 内 [scripts/spec.py](scripts/spec.py) 与 [references/](references/)。
- 其他 Skill 或脚本通过 import 或调用本 Skill 的 `spec.py` 获取 PRESETS、get_safe_zone、get_legend_zone、get_layout、GENRE_PRESETS、OUTPUT_FILENAME_BY_PRESET 等。
- 生成气泡：`scripts/generate_bubble.py` 从 `references/bubble_dev.md` 读取规范。

## 提供的接口（scripts/spec.py）

| 名称 | 说明 |
|------|------|
| `PRESETS` | 预设名 → (宽, 高) |
| `LAYOUT_BY_CANVAS` | (宽, 高) → 布局 dict（主/副标题、渐变、legend_zone 等） |
| `SAFE_ZONE_BY_CANVAS` | (宽, 高) → 安全区 (x_min, x_max, y_min, y_max) |
| `SAFE_ZONE_BY_PRESET` | preset → 安全区覆盖（与同尺寸画布默认并存，裁切时传 `preset` 生效） |
| `LAYOUT_BY_PRESET` | preset → 布局覆盖（与同画布 `LAYOUT_BY_CANVAS` 合并，如同尺寸多规格） |
| `LEGEND_ZONE_BY_CANVAS` | (宽, 高) → 图例区 (x_min, x_max, y_min, y_max) |
| `DIALOG_ZONE_BY_CANVAS` | (宽, 高) → 对话框区域 (x_min, x_max, y_min, y_max) |
| `TEXT_ART_ZONE_BY_CANVAS` | (宽, 高) → 文字艺术字区域 (x_min, x_max, y_min, y_max) |
| `EXCLUSION_ZONES_BY_CANVAS` | (宽, 高) → 排除区列表 [(x_min, x_max, y_min, y_max), …] |
| `GENRE_PRESETS` | 规范分组名 → 该组要跑的 preset 列表（-g 用） |
| `OUTPUT_FILENAME_BY_PRESET` | 预设名 → 约定输出文件名（如 首页 1976x464.png） |
| `get_safe_zone(width, height, preset=None)` | 返回安全区或 None；`preset` 在 `SAFE_ZONE_BY_PRESET` 中有定义时优先 |
| `get_safe_zone_center(width, height, preset=None)` | 返回安全区中心 (x, y) 或 None |
| `get_legend_zone(width, height)` | 返回图例区或 None |
| `get_dialog_zone(width, height)` | 返回对话框区域或 None |
| `get_text_art_zone(width, height)` | 返回文字艺术字区域或 None |
| `get_exclusion_zones(width, height)` | 返回排除区列表 []（画面主要内容需避开的区域） |
| `get_layout(width, height, preset=None)` | 返回该画布布局 dict（可选 preset 合并 `LAYOUT_BY_PRESET`） |

## 依赖本 Skill 的模块

- **banner-composer**：PRESETS、LAYOUT_BY_CANVAS（或 get_layout）
- **banner-background-from-image**：PRESETS、SAFE_ZONE_BY_CANVAS、LEGEND_ZONE_BY_CANVAS、get_safe_zone、get_legend_zone 等
- **banner-background-from-description**：PRESETS（文生图选尺寸与裁切）
- **run_all_presets.py**：GENRE_PRESETS、PRESETS、OUTPUT_FILENAME_BY_PRESET
- **generate_bubble.py**：references/bubble_dev.md（气泡生成）

## 文档

- [references/spec.md](references/spec.md) — 安全区、图例区、主/副标题、渐变、输出等完整规范说明
- [references/presets.md](references/presets.md) — 预设名与尺寸表
- [references/bubble_dev.md](references/bubble_dev.md) — 气泡提示框组件规范（4 种类型、Icon 处理流程）
- [references/joint_logo.md](references/joint_logo.md) — 联合 Logo 合成规范（两图 + X 按钮分隔符，高度 50px）

## 使用方式（其他脚本中）

将本 Skill 的 `scripts` 目录加入 `sys.path` 后：

```python
from spec import PRESETS, get_safe_zone, get_legend_zone, get_layout, GENRE_PRESETS, OUTPUT_FILENAME_BY_PRESET
```

或通过仓库内相对路径加载（见各消费方实现）。
