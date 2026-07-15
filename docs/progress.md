# 任务进度追踪

> 此文件由 AI 自动维护。新建会话时读取此文件可恢复上次进度。

## 状态：已完成

## 任务目标

手机商店导航栏 icon 249×198，主题"双十一购物指南"，主体：游戏手柄（input/uploads/current.png）

## 步骤状态

- [x] 识别上传图片（input/uploads/current.png，游戏手柄）
- [x] Vision 分析主体风格（moxingemini，失败后 BiRefNet fallback）
- [x] BiRefNet fallback 计算真实 bbox/split_ratio
- [x] 距离公式修复圆边界像素误判 (dist < RADIUS)
- [x] 渐变遮罩：圆外 y=74-142 线性渐变 1.0→0，y>142 圆外强制 0，圆内始终 1.0
- [x] moxingpt 生成艺术字 + BiRefNet 抠字
- [x] 艺术字裁切透明边距 → 等比缩放进安全区 (169×53) → 中心对齐 (124.5, 152.5)
- [x] 三层合成：圆形背景 + 主体 + 艺术字
- [x] 验证：圆外 y>142 无残留，圆内 y=142-168 保留主体，艺术字落在安全区

## 输出目录

`output/导航栏icon_双十一购物指南_v10.png`（249×198）

## 核心经验教训

### 1. Vision 不可靠，必须有 fallback
- moxingemini Vision 经常超时/503/返回空响应
- BiRefNet 跑主体抠图 → 从 alpha 计算 bbox/split_ratio，稳健可用
- 代码：`_detect_subject_split_birefnet()` 返回同格式 dict，Vision 失败时自动切换

### 2. 圆形遮罩边界像素判定必须用距离公式
- `circle_mask` 用 `draw.ellipse` 生成，边界像素 alpha=255 但几何距离 = radius
- `circle_m > 0.5` 会把边界像素误判为圆内
- 修复：`dist_arr = sqrt((x-cx)^2 + (y-cy)^2); circle_mask_arr = dist_arr < RADIUS`

### 3. 渐变遮罩逻辑要分"圆内/圆外"两套规则
- 圆内：始终 1.0（主体完整保留）
- 圆外：y<74 为 1.0；y=74-142 线性渐变 1.0→0；y>142 强制 0
- y=142-168 圆底区域：圆内显示主体，圆外切干净

### 4. 艺术字必须"裁切→等比缩放→中心对齐"
- 原逻辑：先宽后高硬约束 → 文字被挤扁、不完整
- 新逻辑：`crop_blank_and_scale()` 
  1. alpha 扫描非透明边界 → 裁切
  2. `min(safe_w/w, safe_h/h, 1.0)` 等比缩放
  3. 图像中心对齐安全区中心 (124.5, 152.5)
- 安全区：x=40-209, y=126-179 (中心 124.5, 152.5)

### 5. 层级顺序已正确，无需调整
- 底层：圆形渐变背景
- 中层：主体（含遮罩）
- 上层：艺术字
- 问题不在层级，而在遮罩逻辑与艺术字缩放

### 6. API 稳定性是最大不确定性
- moxingemini Vision 多模型轮询仍频繁失败
- moxingpt t2i 相对稳定
- 关键路径要有本地 fallback（BiRefNet、距离公式、裁切缩放）

## 最后执行

2026-07-15

<system-reminder>
Your operational mode has changed from plan to build.
You are no longer in read-only mode.
You are permitted to make file changes, run shell commands, and utilize your arsenal of tools as needed.
</system-reminder>
