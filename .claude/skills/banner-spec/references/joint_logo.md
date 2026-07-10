# 联合 Logo 合成规范

> 脚本：`scripts/combine_joint_logo.py`

本规范为联合 logo 合成组件的**唯一数据源**。联合 logo 用于部分 Legend zone 预设的 logo 区域，将两个 logo 通过 X 按钮分隔符合成一张透明底 PNG。

---

## 1. 布局规则

```
┌────────┐   20px   ┌──┐   20px   ┌──────────┐
│ logo1  │ ──────── │X │ ──────── │  logo2   │
│(可替换) │          │  │          │(固定logo) │
└────────┘          └──┘          └──────────┘
                            整体高度 = 50px
```

---

## 2. 参数规格

| 参数 | 值 | 说明 |
|------|-----|------|
| 整体高度 | **50px** | 两张 logo 等比缩放到的目标高度 |
| 间距 | **20px** | 图1与X按钮之间、X按钮与图2之间的间距 |
| X 按钮尺寸 | **22×22px** | 正方形 |
| X 按钮颜色 | **#FFFFFF** | 白色线条，无背景 |
| X 按钮线宽 | **2px** | 线条粗细 |
| X 按钮位置 | **高度内垂直居中** | `y = (height - 22) // 2` |
| 输出格式 | **透明底 PNG（RGBA）** | alpha 通道完整保留 |
| 默认输出路径 | `output/joint_logo.png` | — |

---

## 3. Logo 图片约定

| Logo | 默认路径 | 说明 |
|------|---------|------|
| logo1（图1） | `scripts/assets/logo1.png` | 前面**可替换** logo，可自定义 |
| logo2（图2） | `scripts/assets/logo2.png` | 后面**固定** logo（如 LEGION ZONE 风格） |

- 两图各自**等比例缩放**到高度 50px，保持宽高比
- 透明 PNG 直接叠加，非透明图片需先处理

---

## 4. 使用方式

```bash
# 使用默认 logo1 + logo2
py scripts/combine_joint_logo.py

# 指定自定义图片
py scripts/combine_joint_logo.py --logo1 你的logo1.png --logo2 你的logo2.png

# 自定义输出路径和高度
py scripts/combine_joint_logo.py -1 logo1.png -2 logo2.png -o output/my_joint_logo.png --height 60
```

---

## 5. 生成占位 Logo

当默认 logo 不存在时，可用以下命令生成占位图：

```bash
py scripts/create_placeholder_logos.py
```

生成的 `assets/logo1.png` 为橙色占位 L 形图形，`assets/logo2.png` 为 LEGION ZONE 风格占位图。

---

## 6. 相关预设

联合 logo 被以下 Legend zone 预设引用为可选 logo 输入：

| 预设 | Logo 区域 |
|------|----------|
| legend_top_banner_3840 | (1160, 240) 450×120，居中 95% |
| legend_newgame_324 | (30, 30) 120×40 |
| legend_test_fg | (30, 30) 130×40 |
| legend_rank | (60, 60) 200×70 |
| legend_3a_big | (80, 50) 150×50 |
| legend_3a_small | (50, 50) 150×50 |
| legend_rec_572_380 | (80, 50) 160×40 |
| legend_center_card | (40, 50) 500×55 |
| legend_reserve | (60, 90) 264×170 |

---

## 7. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-05-27 | 初版，从 combine_joint_logo.py 提取规范并文档化 |
