# 气泡提示框组件规范文档

> 脚本：`scripts/generate_bubble.py`
> 最后更新：2026-05-07

本规范为气泡提示框组件的**唯一数据源**，支持 4 种气泡类型。

---

## 目录

1. [类型规格](#1-类型规格)
   - [商店弹泡新规](#11-商店弹泡新规)
   - [商店弹泡旧规](#12-商店弹泡旧规)
   - [浏览器弹泡旧规](#13-浏览器弹泡旧规)
   - [浏览器弹泡新规](#14-浏览器弹泡新规)
2. [代码规范](#2-代码规范)
3. [Icon 处理流程](#3-icon-处理流程)
4. [变更记录](#4-变更记录)
5. [经验教训](#5-经验教训)

---

## 1. 类型规格

### 1.1 商店弹泡新规

| 属性 | 值 |
|------|-----|
| 尺寸 | 149×48px（最小），宽度随文字自适应 |
| 形状 | 圆角矩形 + 底部尾巴 |
| 填充 | 主题渐变（left → white），渐变终止 x=114px |
| 边框 | 1px `#D5D5D5`，alpha=255 全程固定 |
| 关闭按钮 | 8×8px × 图标，距右边框 8px，垂直居中 |
| 文字 | Microsoft YaHei Bold 13px，左对齐 x=43，垂直居中 |
| Icon | 38×38px，位置 x=4 y=0，独立导出 |
| 导出方式 | 默认分开导出 icon + bg |
| 命名前缀 | `新规-` |

### 1.2 商店弹泡旧规

| 属性 | 值 |
|------|-----|
| 关闭按钮 | 无（不绘制，右侧空间保留） |
| 其他规格 | 同商店弹泡新规 |
| 命名前缀 | `旧规-` |

### 1.3 浏览器弹泡旧规

| 属性 | 值 |
|------|-----|
| 尺寸 | 227×42px（固定，不随文字扩展） |
| 形状 | 圆角矩形（r=6）+ 左侧向左箭头 |
| 填充 | 主题渐变（同商店弹泡） |
| 边框 | 1px `#D5D5D5`，alpha=255 全程固定 |
| drop-shadow | dx=0, dy=2, stdDeviation=0.5, opacity=0.1，GaussianBlur 柔边 |
| 关闭按钮 | 20×20px 圆角方块 + × 线条，`#D5D5D5 30%`，对齐气泡顶部右上角 |
| 文字 | Microsoft YaHei Bold 16px，左对齐 x=54，垂直居中，超出截断 |
| Icon | 41×37px，位置 x=9 y=0，合并进 bg 一起导出 |
| 命名前缀 | `浏览器弹泡旧规-` |

### 1.4 浏览器弹泡新规

| 属性 | 值 |
|------|-----|
| 尺寸 | 149×48px（与商店新规相同） |
| 形状 | 与商店新规相同（底部尾巴） |
| 其他规格 | 同商店新规 |
| 导出方式 | 默认合并导出（icon 合并进 bg） |
| 命名前缀 | `浏览器弹泡新规-` |

---

## 2. 代码规范

### 2.1 运行方式

```bash
# 位置参数格式
py scripts/generate_bubble.py "文案" 类型 主题色

# 示例
py scripts/generate_bubble.py "今天星期五了" 商店弹泡新规 蓝色
py scripts/generate_bubble.py "明天五一放假了" 商店弹泡旧规 粉色
py scripts/generate_bubble.py "快速开机tips！" 浏览器弹泡旧规 蓝色
py scripts/generate_bubble.py "新功能上线" 浏览器弹泡新规 绿色

# 合并导出（覆盖默认分开导出）
py scripts/generate_bubble.py "文案" 商店弹泡新规 蓝色 --no-split

# 指定 icon 路径和裁剪区域
py scripts/generate_bubble.py "文案" 商店弹泡新规 蓝色 --icon-path output/my_icon.png --icon-crop 0 0 512 512
```

### 2.2 可配置参数（脚本顶部常量）

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `SVG_W` | 149.0 | 最小总宽，实际宽度随文字自适应 |
| `SVG_H` | 48.0 | 总高（含顶部 7px icon 溢出空白） |
| `OFFSET_Y` | 7.0 | 主体上移偏移量 |
| `BODY_X1` | 148.5 | 主体右边界 |
| `BODY_Y1` | 38.5 | 主体底边（尾巴起点） |
| `GRAD_LEFT` | (104,164,255) | 背景渐变左色（默认蓝色） |
| `GRAD_RIGHT` | (255,255,255) | 背景渐变右色 |
| `GRAD_END_X` | 114.0 | 背景渐变终止 x |
| `TEXT_COLOR` | 随主题变化 | 文字颜色 |
| `TEXT_SIZE` | 13 | 文字字号（px） |
| `CLOSE_COLOR` | (180,170,175) | 关闭按钮颜色 |
| `ICON_PATH` | `output/icon_rgba.png` | icon 默认路径 |
| `ICON_CROP` | (262,111,778,922) | icon 裁剪区域（原图坐标） |
| `SCALES` | [1, 1.5, 2, 3] | 输出倍率列表 |

### 2.3 主题色与文字颜色

| 主题 | 背景渐变左色 | 文字颜色 |
|------|-------------|---------|
| 粉色 | #FEA6A6 (254,166,166) | #82144D (130,20,77) |
| 黄色 | #FFE57D (255,229,125) | #7C3720 (124,55,32) |
| 绿色 | #4AD093 (74,208,147) | #386E42 (56,110,66) |
| 蓝色 | #68A4FF (104,164,255) | #26315F (38,49,95) |
| 紫色 | #CA94FF (202,148,255) | #69057E (105,5,126) |

### 2.4 倍率对应尺寸

| 倍率 | 命名 | 商店/浏览器新规 | 浏览器旧规 |
|------|------|---------------|-----------|
| 1x | @100 | 187×48 | 227×42 |
| 1.5x | @150 | 281×72 | 341×63 |
| 2x | @200 | 374×96 | 454×84 |
| 3x | @300 | 561×144 | 681×126 |

### 2.5 核心实现说明

| 模块 | 说明 |
|------|------|
| `cbez()` | 三次贝塞尔采样（SVG C 命令） |
| `qbez()` | 二次贝塞尔采样（备用） |
| `make_icon_image()` | 独立 icon 处理函数 |
| 超采样 SS=4 | 4 倍尺寸绘制，LANCZOS 缩小 |
| 渐变填充 | numpy 向量化逐列插值 |
| 边框 | 1px 外描边，alpha=255 全程固定 |

---

## 3. Icon 处理流程

### 3.1 正确处理流程

| 步骤 | 操作 | 命令 |
|------|------|------|
| 1 | 上传图片到对话框 | 用户粘贴到对话框，图片自动保存到 `input/uploads/current.png` |
| 2 | rembg 抠图 | `py -c "from rembg import remove; from PIL import Image; remove(Image.open('input/xxx.jpg')).save('output/icon_rgba.png')"` |
| 3 | 获取裁剪区域 | 运行 Python 代码分析 `output/icon_rgba.png` 的非透明区域坐标 |
| 4 | 更新 ICON_CROP | 在 `generate_bubble.py` 中更新 `ICON_CROP = (x1, y1, x2, y2)` |
| 5 | 生成气泡 | `py scripts/generate_bubble.py "文案" 类型 主题色` |

### 3.2 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| Icon 不正确 | 使用了旧的裁剪坐标 | 每换一次 icon 需重新抠图并更新 ICON_CROP |

---

## 4. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-04-17 | 初版，二次贝塞尔近似尾巴圆角 |
| 2026-04-17 | 改用三次贝塞尔，完全还原 SVG 路径 |
| 2026-04-17 | 渐变色改为 `#68A4FF → #FFFFFF` |
| 2026-04-17 | 每次输出到时间戳目录，不覆盖历史 |
| 2026-04-17 | 框体宽度改为 149px，尾巴坐标不变 |
| 2026-04-17 | 背景渐变终止点改为 x=114 |
| 2026-04-17 | 文字左对齐，起始 x=43px |
| 2026-04-17 | 关闭按钮改为 8×8px × 图标 |
| 2026-04-17 | 补充5套主题色、双变体输出、Icon 规范 |
| 2026-04-30 | 商店弹泡新规：命名规则、Icon 处理流程 |
| 2026-05-06 | 修正旧规背景宽度：与新规相同（187px @100），仅不绘制 × |
| 2026-05-06 | 删除固定最小宽度，改为动态计算；边框改为 1px |
| 2026-05-06 | 改用 rembg 抠图，更新 ICON_CROP 坐标 |
| 2026-05-06 | 提取 `make_icon_image()` 独立函数 |
| 2026-05-06 | 新增 `--icon-path`、`--icon-crop`、`--color-left`、`--text-color` 参数 |
| 2026-05-06 | 渐变填充改为 numpy 向量化 |
| 2026-05-06 | 浏览器弹泡旧规：重写为圆角矩形+左侧箭头，固定 227×42px |
| 2026-05-06 | 浏览器弹泡旧规：关闭按钮 20×20px 圆角方块+× |
| 2026-05-06 | 浏览器弹泡旧规：文字 Microsoft YaHei 加粗 16px，超出截断 |
| 2026-05-07 | 浏览器弹泡旧规：箭头垂直居中（OFFSET_Y=4.0） |
| 2026-05-07 | 浏览器弹泡旧规：描边改为 #D5D5D5，全程固定无渐变 |
| 2026-05-07 | 浏览器弹泡旧规：文字左对齐 x=54，垂直居中于画布 |
| 2026-05-07 | 浏览器弹泡旧规：关闭按钮对齐气泡顶部右上角 |
| 2026-05-07 | 浏览器弹泡旧规：icon 41×37px，合并进 bg 导出 |
| 2026-05-07 | 新增浏览器弹泡新规：形状同商店新规，默认合并导出 |

---

## 5. 经验教训

### 5.1 箭头坐标 TOP/BOT 命名陷阱

SVG 路径中箭头的上下切点，命名为 `ARROW_Y_TOP` / `ARROW_Y_BOT` 容易产生歧义：

- **视觉上**：y=12 在上（TOP），y=22 在下（BOT）
- **路径顺序**：路径从 y=22（下切点）出发 → 尖端 → y=12（上切点）

**正确做法**：以 SVG 路径注释说明路径顺序，变量名加注释标明"先到/后到"。

### 5.2 `anchor="mm"` 不可靠

Pillow 的 `anchor="mm"` 在某些字体/版本下行为不一致。

**正确做法**：用 `font.getbbox(text)` 获取实际边界框，手动计算：

```python
tb = font.getbbox(text)
tw, th = tb[2] - tb[0], tb[3] - tb[1]
tx = center_x - tw // 2 - tb[0]
ty = center_y - th // 2 - tb[1]
draw.text((tx, ty), text, font=font, fill=color)
```

### 5.3 超采样画布坐标系混淆

代码中存在两套坐标系：
- **超采样画布**：`px()/py()` 用于尺寸 `W×H = cw*SS × ch*SS`
- **最终画布**：`sx()/sy()` 用于尺寸 `cw×ch`

边框绘制在超采样画布，直接 `alpha_composite` 即可。**不能对 `border_layer` 调用 `.resize()`**。

### 5.4 浏览器弹泡 icon 合并导出

浏览器弹泡的 icon 应合并进 bg 一起输出，不单独导出 icon 文件：

```python
img = make_bubble(..., with_icon=use_browser, ...)
if not use_browser:
    icon_canvas = make_icon_image(...)
    icon_canvas.save(...)
```

### 5.5 位置参数与旧参数兼容

argparse 同时支持位置参数和可选参数时，需要注意：

```python
parser.add_argument("text", nargs="?", default=None)
parser.add_argument("--text", dest="text_option", default=None)

final_text = args.text if args.text else args.text_option if args.text_option else None
```

### 5.6 气泡类型命名与用户术语对应

开发过程中类型名称可能变化（如"浏览器新规"→"浏览器弹泡新规"），需要：代码 choices 与用户认知保持一致，文件命名前缀、解析逻辑、默认值三者统一，文档及时同步更新。

### 5.7 阴影柔边实现

drop-shadow 需要柔边时，使用 `PIL.ImageFilter.GaussianBlur`：

```python
shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2))
matrix = (1, 0, offset_x, 0, 1, offset_y)
shadow_offset = shadow_layer.transform((cw, ch), Image.AFFINE, matrix, Image.BILINEAR)
img = Image.alpha_composite(shadow_offset, img)
```

### 5.8 关闭按钮圆角绘制顺序

绘制多圆角矩形时，按路径顺序依次绘制：左上角 → 右上圆角 → 右边 → 右下圆角 → 底边 → 左下圆角 → 左边 → 左上圆角 → 回起点。

### 5.9 特定气泡类型的特殊处理

某些气泡类型有特殊行为（如浏览器新规默认合并导出），需要：

```python
# 解析气泡类型时
if args.bubble_type == "浏览器弹泡新规":
    use_split = False

# 解析导出方式时（强制覆盖）
if args.bubble_type == "浏览器弹泡新规":
    use_split = False
else:
    use_split = not args.no_split
```

### 5.10 文字垂直居中计算

相对于整个画布高度（ch）而非主体高度：

```python
tb = font.getbbox(text)
th = tb[3] - tb[1]
ty = (ch - th) // 2 - tb[1]  # tb[1] 是 baseline 偏移
```

### 5.11 关闭按钮对齐方式差异

- **商店弹泡**：垂直居中于画布
- **浏览器弹泡旧规**：对齐气泡顶部右上角（不是垂直居中）

### 5.12 关闭按钮颜色差异

- **商店弹泡**：`#505050 30%`（alpha=77）
- **浏览器弹泡旧规**：`#D5D5D5 30%`

### 5.13 边框透明度固定

统一使用 `#D5D5D5`，alpha=255 全程固定（无渐变）。

### 5.14 numpy 向量化渐变

比 `draw.line` 循环快约 10x：

```python
import numpy as np
cols = np.arange(w).reshape(1, -1)
t = np.clip(cols / grad_end_x, 0, 1).reshape(-1, 1)
gradient = (left_color * (1 - t) + right_color * t).astype(np.uint8)
```

### 5.15 ICON_CROP 是原图坐标

`ICON_CROP = (x1, y1, x2, y2)` 裁剪的是原始素材图片坐标，不是目标画布坐标。每换一次 icon 需重新分析非透明区域并更新。

### 5.16 argparse choice 大小写敏感

用户输入需精确匹配（如"粉色"不是"Pink"）。

### 5.17 文字宽度用 font.getlength()

准确计算而非估计：

```python
text_width = font.getlength(text)
```

### 5.18 PIL alpha 范围是 0-255

不是 CSS 的 0-1：

```python
alpha_30_percent = int(255 * 0.3)  # = 77
```

### 5.19 RGBA 转 JPEG 需先转换

PIL 保存 JPEG 不支持 alpha 通道：

```python
img_rgb = img.convert("RGB")
img_rgb.save("output.jpg", "JPEG")
```

### 5.20 内存优化

超采样 4 倍尺寸会占用大量内存，大批量生成时注意及时释放中间变量。

### 5.21 贝塞尔精度

每段采样 20 步足够平滑，再高提升不明显。

### 5.22 超采样+LANCZOS

SS=4 先以 4 倍尺寸绘制，LANCZOS 算法缩小到目标尺寸，抗锯齿效果最好。

### 5.23 输出目录时间戳

每次生成默认输出到 `output/bubble_YYYYMMDD_HHMMSS/`，不覆盖历史，便于追溯。

### 5.24 图片提取流程

图片通过 OpenCode image-saver 插件自动保存到 `input/uploads/current.png`。所有入口脚本在未指定图片路径时自动调用 `_paths.auto_extract_latest()` 提取最新上传图片。

**正确使用流程**：
1. 粘贴图片到对话框
2. 直接运行脚本（脚本自动读取 `input/uploads/current.png`）
3. 确认输出尺寸与原图一致