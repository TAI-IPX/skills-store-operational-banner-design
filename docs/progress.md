# 任务进度追踪

> 此文件由 AI 自动维护。新建会话时读取此文件可恢复上次进度。

## 状态：已完成

## 任务目标

专题长图 3320×500 顶部白条抠不出主体（柜子/桌子）修复：
- 现象：主体真实顶边落在 y≈41-44，卡在 y=0-40 白条外，白条纯白无主体探入
- 根因：`_wide_auto_top_poke` 与 A5b 抠图都依赖 BiRefNet，但 BiRefNet 在全景超宽图上漏判上半主体（把顶行判成 y=220+），导致探顶用垃圾值上移 + A5b strip 带 alpha 近空 → 白条被重铺纯白
- 方案：新增背景差异法（不依赖 BiRefNet），驱动探顶顶行 + A5b strip alpha 兜底

---

## 步骤状态

- [x] prepare_background.py 新增 `_detect_content_top_row()` + `_content_strip_rgba()`（背景差异法，两侧边列估背景色）
- [x] `_wide_auto_top_poke` 顶行检测改为：背景差异法优先，None 时回退 BiRefNet
- [x] A5b `_composite_wide_top_strip_birefnet`：BiRefNet strip 带不透明列过少（<max(20,2%宽)）时用 `_content_strip_rgba` 兜底重建
- [x] prepare_background_micugpt2.py 孪生同步（新增 `_detect_content_top_row` + `_content_strip_rgba` + 改造 `_wide_auto_top_poke` + A5b 兜底）
- [x] 两文件语法校验通过
- [x] 复用 bg.png 离线重跑验证：探顶 top_row=0（背景差异）+ A5b 背景差异兜底触发 + 白条露出主体（680 非白列，集中 x=1400-2400 柜子区）
- [x] 用修复逻辑重跑用户 run_dir 的 wide 背景 + compose 叠字，产出 `专题长图 3320x460_FIXED_20260709_185011.png`
- [x] 清理临时验证产物
- [x] docs/progress.md 更新

---

## 验证摘要

| 检测项 | 结果 |
|--------|------|
| 背景差异法检测主体真实顶行 | ✅ y=41（BiRefNet 误报 y=220-227）|
| `_wide_auto_top_poke` 用背景差异顶行 | ✅ 日志「wide 自动探顶（背景差异）：主体顶行 y=0」|
| A5b BiRefNet strip alpha 近空检测 | ✅ 不透明列 0 → 触发背景差异兜底 |
| A5b 背景差异兜底重建 strip | ✅ 日志「改用背景差异兜底」|
| 白条露出主体（柜子探入） | ✅ 680 非白列，集中 x=1400-2400 |
| 白条两侧保持纯白 | ✅ x<1400、x>2400 白 |
| 产出尺寸 | ✅ 3320×500 |

## 代码/配置改动文件清单

| 文件 | 改动 |
|------|------|
| `.claude/skills/banner-background-from-image/scripts/prepare_background.py` | 新增 `_detect_content_top_row()` + `_content_strip_rgba()`；`_wide_auto_top_poke` 背景差异优先；A5b strip alpha 近空时背景差异兜底 |
| `scripts/prepare_background_micugpt2.py` | 孪生同步上述三处 |
| `docs/progress.md` | 本文件 |

## 环境变量

- `WIDE_TOP_POKE_BG_DIST`（默认 45）：背景差异法判前景的最大通道差阈值（越大越严，只取与背景差异更大的主体像素）
- `WIDE_AUTO_TOP_POKE`（默认 1）、`WIDE_TOP_POKE_TARGET`（默认 12）、`WIDE_TOP_EXTEND_PX`（手动优先，设非空非0禁用自动探顶）— 沿用

## 关键结论

- **BiRefNet 在全景超宽专题长图上不可靠**：容易把上半主体（柜子/桌子顶部）漏判成背景，顶行报到 y=200+。凡是"主体在暗底/纯色底上、需要检测顶边或抠出顶部"的场景，背景差异法（两侧边列估背景色 + 通道差阈值）比 BiRefNet 稳健，已作为探顶主检测 + A5b 兜底。
- 探顶顶行检测与 A5b strip alpha 现在都有"背景差异法"这条不依赖模型的兜底路径。

## 最后执行

- 2026-07-09（背景差异法修复白条探入，端到端验证 + run_dir 重出图成功）

## 恢复指令

读取 docs/progress.md，从上次中断的地方继续
