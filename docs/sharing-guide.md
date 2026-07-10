# Banner 自动化生成系统 — 项目分享手册

> 本文档面向两类读者：
> - **运营/设计同学**：请阅读第一、二部分，了解如何快速上手使用
> - **开发同学**：请阅读完整文档，了解项目架构与详细文件清单

---

## 目录

- [第一部分：快速上手](#第一部分快速上手)
  - [一、项目简介](#一项目简介)
  - [二、环境准备](#二环境准备)
  - [三、快速命令速查（按场景）](#三快速命令速查按场景)
  - [四、图片输入方式](#四图片输入方式)
  - [五、输出目录说明](#五输出目录说明)
- [第二部分：项目结构与参考](#第二部分项目结构与参考)
  - [六、项目架构](#六项目架构)
  - [七、目录结构总览](#七目录结构总览)
  - [八、scripts/ 文件清单](#八scripts-文件清单)
  - [九、.claude/skills/ 技能模块](#九claudeskills-技能模块)
  - [十、docs/ 文档索引](#十docs-文档索引)
  - [十一、后端调度说明](#十一后端调度说明)
  - [十二、常见问题与已知陷阱](#十二常见问题与已知陷阱)

---

# 第一部分：快速上手

---

## 一、项目简介

本项目是一个**多后端 Banner 自动化生成系统**。你可以提供一张图片或一段文字描述，系统会自动处理背景图，叠加上主标题和副标题，输出符合各平台尺寸规范的 Banner 图。

核心能力：

| 能力 | 说明 |
|------|------|
| 图片 → Banner | 上传一张图，自动去干扰、检测主体、扩图填充、对齐安全区，输出多尺寸 Banner |
| 描述 → Banner | 给主副标题，AI 自动生成背景图 + 叠字合成 |
| 批量多尺寸 | 一次命令生成 30+ 种预设尺寸（首页、专题、移动端等） |
| 多种 AI 后端 | 支持 7 种图像生成/编辑后端（Gemini、gpt-image-2、即梦、Lovart 等） |
| 商店移动端日常 | 定制管线专门处理移动端 Banner（984×442、650×275、720×220） |
| HD 生产线 | 多张人物图 → 智能抠图 → 排版 → 高清 Banner（3840×1200） |

---

## 二、环境准备

### 2.1 安装 Python 依赖

```bash
# 进入项目目录
cd skills-store-operational-banner-design

# 安装核心依赖
pip install -e .

# 如需 BiRefNet 抠图功能（CPU 版）
pip install -e ".[birefnet]"
# 或运行
py scripts/install_birefnet_deps.bat
```

核心依赖：Pillow、requests、python-dotenv、google-generativeai、anthropic、opencv-python、numpy

### 2.2 配置 API Key

复制 `.env.example` 为 `.env`，填入对应的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，至少需要配置一个图像后端。推荐的最小配置：

```ini
# Gemini（主体检测、图像编辑、视觉理解）— 最常用
GEMINI_API_KEY=你的 Google API Key

# 或 Packy 代理（国内可直接访问）
# GOOGLE_GEMINI_BASE_URL=https://www.packyapi.com
# PACKY_API_KEY=sk-你的 Packy 令牌
```

其他可选后端（按需配置）：

| 后端 | 需要配置的 Key | 用途 |
|------|---------------|------|
| PackyGPT | `PACKYGPT_API_KEY` | gpt-image-2 文生图 |
| MicuAPI | `MICUAPI_API_KEY` | gpt-image-2，支持 1:8 极端比例 |
| Packy7s | `PACKY7S_API_KEY` | 并行 Packy 后端 |
| 即梦 | `VOLC_ACCESS_KEY_ID` + `VOLC_SECRET_ACCESS_KEY` | 即梦 4.0 文生图 |
| t8star | `T8STAR_API_KEY` | 即梦/t8star 文生图 |
| Lovart | `LOVART_ACCESS_KEY` + `LOVART_SECRET_KEY` | Lovart AI 文生图/图编 |

### 2.3 重要：Windows 下用 `py` 而非 `python`

Windows 的 `python` 命令可能指向 Microsoft Store 存根（不实际执行 Python），**所有命令必须用 `py`**：

```bash
py scripts/run_banner.py     # ✅ 正确
python scripts/run_banner.py # ❌ 可能失败
```

---

## 三、快速命令速查（按场景）

### 场景 A：我有一张图，想生成多尺寸 Banner

```bash
py scripts/run_all_presets.py input/uploads/current.png \
  -m "你的主标题" -s "你的副标题" -g 商店日常
```

参数说明：
- 第一个参数是图片路径（可用 `input/uploads/current.png` 或 `@` 读取 upload_path.txt）
- `-m` / `-s`：主标题 / 副标题
- `-g`：分组名，控制输出哪些预设尺寸。常用分组：

| 分组 | 包含的预设 |
|------|-----------|
| `商店日常` | default(1976×464)、wide(3320×500)、strip(1740×220)、card-500、card-304 |
| `商店移动端日常` | shop_mobile_banner_984、shop_mobile_card_650、shop_mobile_strip_720 |
| `商店畅玩卡1920*550` | shop_play_card_1920、shop_play_card_mobile |
| `lz` | legend 系列全部预设 |

### 场景 B：我只有主副标题，让 AI 生成背景图再叠字（方案 A 全流程）

```bash
py scripts/run_full_with_custom_prompt.py -g 商店日常 \
  -m "你的主标题" -s "你的副标题" --description "你的背景描述"
```

参数说明：
- `--description`：背景描述文字（必填）
- 也可用 `--description-file input/prompt.txt` 从文件读取描述
- 或用 `--prompt-engine` 让 AI 自动从主副标题推导描述

指定后端（默认 Gemini）：

```bash
# 用 MicuAPI 生图 + Gemini 编辑
py scripts/run_full_with_custom_prompt.py -g 商店日常 --micugpt2 --packy7s \
  -m "你的主标题" -s "你的副标题" --description "你的背景描述"

# 用 PackyGPT 生图 + Gemini 编辑
py scripts/run_full_with_custom_prompt.py -g 商店日常 --packygpt --packy7s \
  -m "你的主标题" -s "你的副标题" --description "你的背景描述"
```

### 场景 C：商店移动端日常 Banner

```bash
# 提供已有背景图（仅叠字）
py scripts/run_mobile_presets.py "output/xxx/bg.png" \
  -m "你的主标题" -s "你的副标题" --micugpt2 --packy7s

# 从描述生成背景 + 叠字（全流程）
py scripts/run_full_with_custom_prompt.py -g 商店移动端日常 --micugpt2 --packy7s \
  -m "你的主标题" -s "你的副标题" --description "你的背景描述"
```

### 场景 D：商店移动端田字格 355×350 Banner

```bash
py scripts/run_shop_mobile_tianzige.py -i input/uploads/current.png \
  -m "你的主标题" -c 蓝色
```

颜色选项：`蓝色` / `绿色` / `黄色` / `紫色`

### 场景 E：商店专题长图 3320×460

```bash
py scripts/run_wide_only.py input/uploads/current.png \
  -m "你的主标题" -s "你的副标题"
```

### 场景 F：从已有 A4 填充图快速输出所有预设（跳过 A1-A4）

```bash
py scripts/run_from_a4.py output/xxx/tianchong.png \
  -m "你的主标题" -s "你的副标题" -g 商店日常
```

### 场景 G：仅叠字（已有背景图，不重新生图）

```bash
py scripts/run_all_presets.py output/xxx/bg.png \
  -m "你的主标题" -s "你的副标题" --output-dir output/xxx \
  --skip-a4-outpaint --skip-remove-text -g 商店日常 -X -packy7s
```

`-X` 替换为后端标识：`-packygpt` 或 `-micugpt2`

### 场景 H：HD 生产线（多张人物图 → 高清 Banner）

```bash
py scripts/run_hd.py -g "legend_top_banner_3840" \
  -p "背景描述" --packy7s --images "input/p1.png" "input/p2.png" "input/p3.png"
```

---

## 四、图片输入方式

项目支持以下方式传入图片：

| 方式 | 用法 | 说明 |
|------|------|------|
| **对话框粘贴** | 直接粘贴图片到 Cursor/OpenCode 对话框 | 自动保存到 `input/uploads/current.png`，脚本不带 `-i` 时自动提取 |
| **指定文件路径** | `-i input/你的图片.png` | 最推荐的方式，明确指定 |
| **`@` 快捷读取** | 第一个参数写 `@` | 自动读取 `input/upload_path.txt` 中的路径 |
| **复制到 uploads** | `py scripts/set_upload_image.py 图片路径 --copy` | 复制到 `input/uploads/current.png` |

---

## 五、输出目录说明

每次运行会在 `output/` 下创建以 `分组_主标题_时间戳` 命名的子目录，包含：

```
output/
├── <分组_主标题_时间戳>/
│   ├── bg.png                      # Step1 生成的背景图
│   ├── tianchong.png               # A4 填充图（4096×1024）
│   ├── step1_<预设名>.png           # 各预设的 Step1 背景（裁切后）
│   ├── zhuti.png                    # 主体 bbox 标注图
│   ├── a5_bbox_preview.png         # 主体 bbox 检测预览
│   ├── <预设名>.png                 # 最终合成 Banner（如「首页 1976x464.png」）
│   ├── dialog_raw.png              # 六边形对话框
│   ├── text_art_rgba.png           # 艺术字透明 PNG
│   └── prompt_engine_trace.md      # Prompt 推导日志（如有）
└── ...
```

---

# 第二部分：项目结构与参考

---

## 六、项目架构

项目采用三层架构：

```
┌─────────────────────────────────────────────────────────┐
│                    规范层（banner-spec）                   │
│          spec.py：所有画布尺寸、安全区、布局参数            │
│                     唯一数据源                             │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    生成层（两条路径）                      │
│                                                          │
│  ┌─── 图片输入路径 ──────────────────────────────────┐   │
│  │  run_all_presets.py                                │   │
│  │    → prepare_background.py                         │   │
│  │      A1 去干扰 → A2 主体检测 → A3 标注             │   │
│  │      → A4 扩图填充 → A5 安全区对齐裁切              │   │
│  └────────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─── 描述输入路径 ──────────────────────────────────┐   │
│  │  run_full_with_custom_prompt.py                    │   │
│  │    → generate_from_description.py                  │   │
│  │      文生图 → crop 到目标画布                       │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    合成层（banner-composer）              │
│          compose_banner.py                               │
│    背景图 → 渐变蒙层 → 主标题 → 副标题 → 最终 Banner    │
└─────────────────────────────────────────────────────────┘
```

### 后端调度架构

```
                    BANNER_IMAGE_BACKEND 环境变量
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
      Gemini API        gpt-image-2          即梦/Lovart
    (生图+编辑+Vision)   (packygpt/micugpt2)  (jimeng/t8star/lovart)
```

三条 Key 独立隔离，互不覆写：
- `PACKYGPT_API_KEY` / `MICUAPI_API_KEY` → gpt-image-2 文生图/图生图
- `GEMINI_API_KEY` → 主体检测、扩图编辑、Vision 视觉理解

---

## 七、目录结构总览

```
skills-store-operational-banner-design/
│
├── scripts/                  # 所有 Python 脚本
│   ├── hd/                   # HD 生产线子包（Step0-5）
│   ├── tests/                # 测试与调试脚本
│   ├── launchers/            # 快捷启动器
│   └── assets/               # 静态资源（logo 占位图）
│
├── .claude/skills/           # AI 技能模块（7 个）
│   ├── banner-spec/          # 规范数据源
│   ├── banner-composer/      # 叠字合成
│   ├── banner-background-from-image/  # 图片→背景
│   ├── banner-background-from-description/  # 描述→背景
│   ├── prompt-engine/        # Prompt 生成引擎
│   ├── lovart-skill/         # Lovart AI 官方技能
│   └── skill-creator/        # 技能创建指南
│
├── docs/                     # 文档目录
│   ├── 流程与规则.md
│   ├── AI协作规范.md
│   ├── 新增后端指南.md
│   ├── 图片处理说明.md
│   ├── 说明.txt
│   └── progress.md           # 会话进度追踪
│
├── input/                    # 输入素材
│   └── uploads/              # 对话框粘贴图片存档
│       ├── current.png       # 最新图片（固定路径）
│       └── <时间戳>.png       # 历史存档
│
├── output/                   # 输出结果（按任务分子目录）
│
├── .env                      # API Key（勿提交）
├── .env.example              # 环境变量模板
├── pyproject.toml            # Python 依赖配置
├── AGENTS.md                 # 项目总说明
└── README.md                 # 项目简介
```

---

## 八、scripts/ 文件清单

### 8.1 主入口脚本

| 文件 | 功能 | 关键参数 | 调用链 |
|------|------|----------|--------|
| `run_banner.py` | 最简入口：单图 → 单张 Banner | `-i 图片` `-m 主标题` `-s 副标题` `--preset 预设` | → `prepare_background` → `compose_banner` |
| `run_all_presets.py` | 多尺寸批量合成（Step2 核心） | `image` `-m` `-s` `-g 分组` `--skip-a4-outpaint` `--skip-remove-text` `--packygpt/--micugpt2` | → `prepare_background` → `compose_banner` + `generate_dialog_banner` |
| `run_full_with_custom_prompt.py` | 方案 A 全流程（描述→生图→叠字） | `--description/--description-file` `-m` `-s` `-g` `--prompt-engine` `--packygpt/--micugpt2/--packy7s` | → `generate_from_description`（Step1）→ `run_all_presets`（Step2） |
| `run_mobile_presets.py` | 商店移动端日常管线（A2→A4→A5→A6→compose） | `bg.png` `-m` `-s` `--micugpt2` `--packy7s` | import `prepare_background` + `compose_banner` |
| `run_from_a4.py` | 从 tianchong.png 直接出所有预设（跳过 A1-A4） | `image` `-m` `-s` `-g` `--packy/--packy7s/--packygpt` | → `prepare_background` → `compose_banner` |
| `run_wide_only.py` | 仅生成商店专题长图 3320×460 | `image` `-m` `-s` `--skip-remove-text` `--packy7s/--packygpt` | → `prepare_background` → `compose_banner` |
| `run_banner_compose_only.py` | 仅叠字合成（不跑 prepare_background） | `-i 背景图` `-m` `-s` `-o` | → `compose_banner` |
| `run_hd.py` | HD 生产线主入口（多人物→3840×1200） | `-p prompt` `-g` `--packy7s` `--images` | import `hd/` 各步骤模块 |
| `run_hd_line.py` | HD 产线高级入口（智能拼版/layout-preset） | `--images` `--prompt` `-g` `--hd-style` `--layout-preset` `--no-i2i` | import + subprocess 多种 |
| `run_lz_top_banner_with_title_art.py` | LZ 顶部 Banner + 艺术字一键流程 | `-i 背景图` `-t 艺术字PNG` `-m` `--title-art-desc` `--background-only` | → `run_all_presets` + `compose_title_art_preview` |
| `run_shop_mobile_tianzige.py` | 商店移动端田字格 355×350 Banner | `-i 输入` `-m 主标题` `-c 颜色` | → `generate_from_description` → `compose_banner` |

### 8.2 基础工具模块（被其他脚本 import）

| 文件 | 功能 | 被谁调用 | 备注 |
|------|------|----------|------|
| `_env.py` | 统一 .env 加载（`load_env`/`get_env_key`），带缓存 | 所有主入口 | 无本地依赖 |
| `_packy.py` | 多后端 Key 调度，设置 `BANNER_IMAGE_BACKEND` | 所有主入口 | 依赖 `_env` |
| `_paths.py` | 路径定义（ROOT/INPUT_DIR/OUTPUT_DIR）、路径验证、`auto_extract_latest` | 所有主入口 | 依赖 `lib/opencode_image_input` |
| `ensure_python.py` | 检测可用 Python 解释器（跳过 Windows Store 存根） | 所有用 subprocess 的脚本 | 无本地依赖 |
| `agent_skill.py` | Lovart Agent OpenAPI 零依赖客户端（HMAC-SHA256 签名） | `lovart_helper` | 无本地依赖 |
| `lovart_helper.py` | Lovart AI 后端封装（t2i/i2i/outpaint/inpaint/upscale） | `lovart_edit` `lovart_vision` | 依赖 `agent_skill` |
| `lovart_vision.py` | Lovart Vision 封装，替代 Gemini Vision 做主体检测 | `gemini_subject_detect` | 依赖 `lovart_helper` |
| `jimeng_volc_api.py` | 即梦 4.0 火山引擎直连 API（Signature V4 签名） | `generate_calendar_icon` `generate_course_icon` `generate_assets` | 无本地依赖 |

### 8.3 图像处理工具

| 文件 | 功能 | 关键参数 |
|------|------|----------|
| `extract_subject_birefnet.py` | BiRefNet 抠图，输出透明底 PNG | `input` `--crop x1 y1 x2 y2` `--output` `--alpha-threshold` `--no-binarize` |
| `compose_title_art_preview.py` | 透明艺术字 PNG 按 spec 合成到背景图 | `--background` `--title-art` `--output` `--preset` `--rect` `--fit-scale` |
| `generate_bubble.py` | 生成气泡提示框 PNG（1x/1.5x/2x/3x），5 种主题 | `--text` `--theme` `--no-close` `--icon-path` `--color-left` `--text-color` |
| `generate_bubble_icon.py` | 生成气泡装饰图标并合成气泡预览 | `--icon` `--text` `--theme` `--output-dir` |
| `generate_bubble_icon_lovart.py` | 用 Lovart 文生图生成气泡图标 | `--prompt` `--output` |
| `generate_dialog_banner.py` | 绘制六边形横幅底托（颜色自动推导描边/阴影） | `--color <hex>` 或 `--bg --region x1 y1 x2 y2` `--output` `--scale` |
| `combine_joint_logo.py` | 联合 logo 合成（logo1 — X 按钮 — logo2） | `--logo1` `--logo2` `--output` `--height` |
| `fallback_title_art_pil.py` | API 不可用时用系统字体生成简易艺术字 PNG | `--main` `--footer` `--output` `--preset` |
| `set_upload_image.py` | 将图片路径写入 `input/upload_path.txt` | `background` `[logo]` `--copy` |
| `watch_opencode_images.py` | 监控 OpenCode DB，新图片自动保存（需 watchdog） | 无参数 |
| `compose_wide_from_step1.py` | 从 step1_wide.png 合成专题长图 | `--dir` 子目录名 |
| `lovart_edit.py` | Lovart 图像编辑 CLI（outpaint/remove-text/upscale/i2i） | `mode input output [--prompt]` |
| `sort_hd_images_vision.py` | 用 Gemini Vision 对 3-5 张 HD 素材排序 | 位置参数（图片路径） |

### 8.3.1 联合 Logo 合成规范

`combine_joint_logo.py` 将两个 logo 通过 X 按钮分隔符合成为一张透明底 PNG：

```
┌────────┐  20px  ┌──┐  20px  ┌──────────┐
│ logo1  │ ────── │X │ ────── │  logo2   │
│(可替换) │        │  │        │(固定logo) │
└────────┘        └──┘        └──────────┘
                         整体高度 = 50px
```

| 参数 | 值 | 说明 |
|------|-----|------|
| 整体高度 | 50px | 两图等比缩放到的目标高度 |
| 间距 | 20px | 图与X按钮之间的间距 |
| X 按钮 | 22×22px `#FFFFFF` 线宽2px | 无背景，高度内居中 |
| logo1 默认 | `assets/logo1.png` | 前面可替换 logo |
| logo2 默认 | `assets/logo2.png` | 后面固定 logo（LEGION ZONE 风格） |
| 输出 | `output/joint_logo.png` | 透明底 PNG |

```bash
py scripts/combine_joint_logo.py                                      # 默认
py scripts/combine_joint_logo.py --logo1 a.png --logo2 b.png           # 自定义
py scripts/combine_joint_logo.py -1 a.png -2 b.png -o out.png -h 60   # 全自定义
```

详细规范见：`.claude/skills/banner-spec/references/joint_logo.md`

### 8.4 调试/一次性脚本

| 文件 | 功能 | 备注 |
|------|------|------|
| `generate_store_popup.py` | 生成商店弹泡新规/旧规 | 封装 `generate_bubble` |
| `generate_assets.py` | 批量生成日历图标+商店弹泡 | 依赖即梦 API |
| `generate_calendar_icon.py` | 生成日历图标 | 即梦 API |
| `generate_course_icon.py` | 生成课程图标 | 即梦 API |
| `compute_icon_crop.py` | 计算 icon 非透明区域 bbox（含 numpy） | — |
| `compute_icon_crop_no_numpy.py` | 同上，无 numpy 版本 | — |
| `convert_logo_svg.py` | SVG → 透明底 PNG | 需 cairosvg |
| `create_placeholder_logos.py` | 创建占位 logo 图片 | — |
| `test_lovart_auth.py` | 测试 Lovart AK/SK 鉴权 | — |

### 8.5 hd/ 子目录（HD 生产线步骤模块）

| 文件 | 步骤 | 功能 |
|------|------|------|
| `hd/__init__.py` | — | 包标识（空文件） |
| `hd/classify_images.py` | Step 0 | Gemini Vision 分类图片（CHARACTER/LOGO/TITLE_ART）并按质量排序 |
| `hd/step1_extract.py` | Step 1 | Gemini bbox 检测 → 裁切 → BiRefNet 抠图，输出 RGBA PNG |
| `hd/step2_layout.py` | Step 2 | Gemini 智能排版（主体高度比例 95%/90%/88%，安全区对齐） |
| `hd/step3_check_integrity.py` | Step 3a | Gemini Vision 检测主体完整性 + inpaint 补齐 + 统一光源色调 |
| `hd/step3_generate.py` | Step 3b | 以 layout_ref.png 为参考图，Gemini i2i 生成 3840×1200 背景 |
| `hd/step4_background.py` | Step 4a | prompt 生成 4128×1024 背景 + Vision 风格检查 + 裁切到 3840×1200 |
| `hd/step4_clean.py` | Step 4b | Gemini inpaint 去背景文字/水印 + 人物边缘精修 |
| `hd/step5_composite.py` | Step 5 | 背景+3主体合成 + Gemini Vision 割裂检测（不合格重试最多2次） |

### 8.6 tests/ 子目录

| 文件 | 功能 |
|------|------|
| `draw_safe_zone.py` | 在 banner 图上用红框标出安全区 |
| `test_compose_two_specs.py` | 测试两种 spec 的 compose 输出 |
| `test_edge_black.py` | 测试边缘黑色处理 |
| `test_gemini_3_pro_image_preview.py` | 测试 Packy 上 gemini-3-pro-image-preview 接口 |
| `test_lovart_connection.py` | 测试 Lovart API 连接 |
| `test_lovart_network.py` | 测试 Lovart 网络连通性 |
| `test_packy_model.py` | 测试 Packy 上各模型可用性 |
| `test_with_image.py` | 带图片的 API 集成测试 |

### 8.7 launchers/ 子目录（快捷启动器）

| 文件 | 说明 |
|------|------|
| `_run_packy.py` | 快捷调用 run_all_presets（packy 后端） |
| `_run_packy3s.py` | 快捷调用 run_all_presets（packy3s 后端） |
| `_run_packy7s.py` | 快捷调用 run_all_presets（packy7s 后端） |
| `_run_temp.py` | 临时快捷启动器（默认 Gemini 后端） |
| `run_lz_popup.bat` | 快捷运行 LZ 弹窗生成 |
| `run_popup.bat` | 快捷运行弹泡生成 |
| `run_show_latest.bat` | 快捷显示最新输出 |
| `run_watch.bat` | 快捷启动 watch_opencode_images |

### 8.8 其他批处理/PowerShell

| 文件 | 功能 |
|------|------|
| `install_birefnet_deps.bat` | Windows 安装 BiRefNet 依赖（CPU 版 PyTorch） |
| `run_banner.ps1` | Banner 生成 PowerShell 入口 |
| `run_banner_compose_only.ps1` | 仅合成 Banner 的 PowerShell 入口 |
| `run_from_a4_shortcut.ps1` | run_from_a4 的 PowerShell 快捷方式 |
| `install_shortcut.ps1` | 安装桌面快捷方式 |

---

## 九、.claude/skills/ 技能模块

### 9.1 banner-spec（规范唯一数据源）

| 文件/目录 | 说明 |
|-----------|------|
| `scripts/spec.py` | 核心：30+ 预设尺寸（PRESETS）、安全区（SAFE_ZONE_BY_CANVAS）、规范分组（GENRE_PRESETS）、输出文件名（OUTPUT_FILENAME_BY_PRESET）、布局参数（get_layout） |
| `references/spec.md` | 规范说明文档 |
| `references/presets.md` | 预设列表文档 |
| `references/bubble_dev.md` | 气泡开发规范 |

### 9.2 banner-background-from-image（图片→背景处理）

| 文件 | 功能 |
|------|------|
| `scripts/prepare_background.py` | **核心**：A1去干扰 → A2主体检测 → A3标注 → A4扩图填充 → A5/A5b/A6 安全区对齐裁切。支持 gemini/packygpt/micugpt2 后端 |
| `scripts/crop_to_target.py` | 按安全区裁切图片到目标尺寸（主体对齐安全区中心） |
| `scripts/gemini_subject_detect.py` | Gemini Vision 主体检测（bbox/xy/y 三种模式），含 context_prompt 注入 |
| `scripts/gemini_image_edit.py` | 图像编辑（outpaint/inpaint），支持 gemini/t8star/packygpt/micugpt2/nano-banana |
| `scripts/safe_zone_scale_composite.py` | 主体 bbox 缩放到安全区 85%，中心对齐 |
| `scripts/birefnet_matting.py` | BiRefNet 抠图（ZhengPeng7/BiRefNet-matting） |
| `scripts/birefnet_extract_region.py` | BiRefNet 区域抠图 |
| `scripts/draw_subject_box.py` | 在图片上绘制主体 bbox 预览框 |

### 9.3 banner-background-from-description（文字→背景生成）

| 文件 | 功能 |
|------|------|
| `scripts/generate_from_description.py` | **核心**：从描述文字生成 Banner 背景图。支持 nano-banana/gemini/t8star/packygpt/micugpt2/jimeng/lovart 等后端，含 prompt 优化器 |
| `scripts/prompt_library.py` | Prompt 库管理（读/写/few-shot 示例），JSON 文件存储 |
| `scripts/ref_image_library.py` | 参考图库管理 |
| `prompt_library/` | Prompt 模板库目录 |
| `ref_image_library/` | 参考图库目录（参考图 + 元数据 JSON） |

### 9.4 banner-composer（叠字合成）

| 文件 | 功能 |
|------|------|
| `scripts/compose_banner.py` | **核心**：背景图 + 渐变蒙层 + 主标题 + 副标题 → 最终 Banner。微软雅黑字体，AI 智能换行 |
| `scripts/gemini_linebreak.py` | Gemini AI 智能换行（8字/行回退） |
| `scripts/make_banner_from_image.py` | 一键出图包装（子进程调用 compose_banner） |

### 9.5 prompt-engine（Prompt 生成引擎）

| 文件 | 功能 |
|------|------|
| `PROMPT_SYSTEM .md` | 核心 System Prompt：16 种视觉风格 + 11 种构图类型 + 6 步推导管道 |
| `scripts/prompt_engine_optimizer.py` | Prompt 引擎实现 |

### 9.6 lovart-skill（Lovart AI 官方技能）

多语言技能包（中/英/日/繁），包含 Agent OpenAPI 调用指南。

---

## 十、docs/ 文档索引

| 文件 | 内容 | 适合阅读者 |
|------|------|-----------|
| `流程与规则.md` | 主流程（Step1 A1-A5 详细流程）、安全区规则、Step2 合成规则、已知问题与规避 | 所有人 |
| `AI协作规范.md` | Prompt 生成规范、运营插画要求、语义优先原则、AI 协作最佳实践 | 运营/设计 |
| `新增后端指南.md` | 向项目添加新 AI 图像后端的四步操作指南 | 开发者 |
| `图片处理说明.md` | OpenCode 图片输入流程说明（deepseek 模型限制及自动提取流程） | 所有人 |
| `sharing-guide.md` | **本文档** | 所有人 |
| `progress.md` | 会话进度追踪（AI 自动维护，用于跨会话恢复） | AI |
| `说明.txt` | 最简使用说明（3 种使用方式） | 所有人 |

---

## 十一、后端调度说明

### 11.1 BANNER_IMAGE_BACKEND 环境变量

控制生图和编辑的后端。优先级：命令行 flag > 环境变量 > 默认值（`gemini`）。

| 值 | 对应 Key | 模型 | 特点 |
|------|----------|------|------|
| `gemini` | `GEMINI_API_KEY` | Gemini 系列 | 默认，支持生图+编辑+Vision |
| `packygpt` | `PACKYGPT_API_KEY` | gpt-image-2（通过 Packy） | 生图+编辑+mask，无比例限制 |
| `micugpt2` | `MICUAPI_API_KEY` | gpt-image-2（通过 MicuAPI） | 生图+编辑+Vision，支持 1:8 极端比例 |
| `moxingpt` | `MOXINGPT_API_KEY` | gpt-image-2（通过 Moxin） | 生图+编辑，NewAPI channel |
| `xingchengpt` | `XINGCHENGGPT_API_KEY` | gpt-image-2（通过 newapi.pro） | 生图+编辑，OpenAI 兼容接口 |
| `jimeng` | `VOLC_ACCESS_KEY_ID` | 即梦 4.0 / SeedEdit 3.0 | 生图+图生图 |
| `t8star` | `T8STAR_API_KEY` | 即梦（通过 t8star） | 生图 |
| `lovart` | `LOVART_ACCESS_KEY` | Lovart 多模型 | 生图+编辑+Vision |
| `nano-banana` | 无需 Key | nano-banana-2 | 本地生图，需安装 Bun |

### 11.2 命令行 flag 与 Key 对应

| flag | 设置 | 生图后端 | 编辑/检测后端 |
|------|------|---------|-------------|
| `--packygpt` | `PACKYGPT_API_KEY` → OPENAI API Key | gpt-image-2 (packygpt) | Gemini |
| `--micugpt2` | `MICUAPI_API_KEY` → OPENAI API Key | gpt-image-2 (micugpt2) | Gemini |
| `--moxingpt` | `MOXINGPT_API_KEY` → OPENAI API Key | gpt-image-2 (moxingpt) | Gemini |
| `--xingchengpt` | `XINGCHENGGPT_API_KEY` → OPENAI API Key | gpt-image-2 (xingchengpt) | Gemini |
| `--packy7s` | `PACKY7S_API_KEY` → `GEMINI_API_KEY` | Gemini (packy7s 代理) | Gemini (packy7s) |
| `--packy` | `PACKY_API_KEY` → `GEMINI_API_KEY` | Gemini (packy 代理) | Gemini (packy) |
| `--packy3s` | `PACKY3S_API_KEY` → `GEMINI_API_KEY` | Gemini (packy3s 代理) | Gemini (packy3s) |

### 11.3 后端选用建议

| 场景 | 推荐后端 | 原因 |
|------|---------|------|
| 高质量背景生成 | `--packy7s` | Gemini 模型画质好 |
| 1:8 极端比例直出 | `--micugpt2` | gpt-image-2 无比例限制 |
| 纯生图（无需编辑） | `--packygpt` | gpt-image-2 速度快 |
| 国内直连 | `--packy7s` 或 `--packygpt` | 无需翻墙 |

---

## 十二、常见问题与已知陷阱

### 12.1 多 Key 隔离原则

三条 Key 独立不互覆写：

```
PACKYGPT_API_KEY  → gpt-image-2 生图/编辑
MICUAPI_API_KEY   → gpt-image-2 生图/编辑 + Vision
GEMINI_API_KEY    → Gemini 编辑（去文字/扩图/主体检测）+ Vision
```

**不要混淆不同后端的 Key。**

### 12.2 if/elif 链规则（防复发）

所有后端选择的 if/elif 链必须是单一链路，严禁用独立 if 块覆盖前一个 if 的设置：

```python
# ✅ 正确
if packygpt:    BANNER_IMAGE = "packygpt"
elif micugpt2:  BANNER_IMAGE = "micugpt2"
elif packy7s:   BANNER_IMAGE = "gemini"

# ❌ 错误 — if + elif 分离导致覆盖
if packygpt:    BANNER_IMAGE = "packygpt"
if micugpt2:    BANNER_IMAGE = "micugpt2"     # 独立 if 可能不触发
elif packy7s:   BANNER_IMAGE = "gemini"       # 会覆盖 packygpt 的设定！
```

### 12.3 Windows 系统环境变量陷阱

- Windows 用户级 `GEMINI_API_KEY` 优先于 `.env` 文件，`.env` 的值会被覆盖。
- 调试 401 时检查：`[Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')`
- 删除用户级变量：`[Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $null, 'User')`

### 12.4 入口命令须用 `py` 而非 `python`

Windows 的 `python` 命令可能指向 Microsoft Store 存根程序（`WindowsApps\python.exe`），不会实际执行 Python。**所有命令必须用 `py`**。

### 12.5 图片自动提取可能拿错旧图

脚本不传 `-i` 时，自动从 OpenCode DB 提取最新图片，可能提取到旧图片。
**规避**：明确用 `-i` 指定路径。

### 12.6 API 约束速查

| 约束 | packyapi | micuapi |
|------|----------|---------|
| t2i 端点 | `/v1/images/generations` | `/v1/images/generations` |
| i2i 端点 | `/v1/images/edits` (multipart，支持 mask) | `/v1/chat/completions` (JSON base64) |
| 最大宽高比 | 无限制（已验证 8:1） | 无限制（已验证 1:8） |
| 最小像素 | ≥ 655,360 | 未限制 |
| 尺寸 16 倍数要求 | 必须 | 未限制 |

### 12.7 抠图方案选择

| 场景 | 方案 | 说明 |
|------|------|------|
| 纯色背景文字 | 亮度蒙版（`gray.point(lambda x: 255-x)`） | 毫秒级，零依赖，自动检测底色 |
| 自然图像（人物/物体） | BiRefNet（`extract_subject_birefnet.py`） | AI 模型，耗时但精度高 |

### 12.8 快速诊断表

| 症状 | 检查点 | 根因 |
|------|--------|------|
| 生图走 Gemini 而非 gpt-image | 日志开头 `[packygpt]`/`[micugpt2]` | if/elif 链 bug |
| strip 扩图走 Gemini | Step S5 日志 | EDIT_BACKEND 优先级问题 |
| bbox 不准确 / 偏到边缘 | a5_bbox_preview.png | context_prompt 未注入 |
| wide 无 BiRefNet 抠图 | Step 1b 日志 | tianchong.png 不存在 + 回退失效 |
| 羊毛毡/暗色场景人物消失 | S5b sentinel 阈值 | 阈值 5 误判（暗色物料 delta 仅 2-4） |
| Gemini 503 大量返回 | 全链路 | packyapi 模型不可用 |
| 黑边出现在最终 Banner | A4 扩图日志 | Gemini 返回尺寸小于目标 |
| 弹泡透明像素变黑色 | `_paste_dialog` 日志 | `convert("RGB")` 丢弃 alpha |
| 艺术字被抠掉 | 亮度蒙版日志 | 黑白方向判断错误（已自动修复） |

---

> 如有其他问题，请查阅 `docs/` 目录下对应文档，或联系项目维护者。
