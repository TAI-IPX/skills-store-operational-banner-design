# skills-store-operational-banner-design（商店运营 Banner 设计）— 横幅（Banner）+ 活动长图（竖版海报）生成系统

Claude / Cursor 技能项目：横幅制作与技能模板。

## 技能列表

| 技能 | 说明 |
|------|------|
| **banner-composer** | 从背景图 + 主标题 + 副标题合成横幅图（固定版式、微软雅黑、渐变遮罩） |
| **banner-background-from-image** | 用用户提供的图片制备横幅背景（裁剪/扩图、安全区、可选去字） |
| **banner-background-from-description** | 根据文案描述用 Gemini 生成横幅背景图 |
| **prompt-engine** | 主副标题→高质量中文文生图 Prompt（16 风格 + 11 构图 + 6 步推导 + 质检评分 ≥43） |
| **skill-creator** | 创建与维护新技能的指南与脚本 |
| **template** | 技能占位模板，便于基于此扩展新技能 |

三个 banner 技能需一起使用：`banner-background-from-*` 产出背景，交给 `banner-composer` 合成最终横幅。

## 快速开始

### 环境要求

- Python 3.8+

### 安装依赖

```bash
pip install -r pyproject.toml
# 或
pip install Pillow requests python-dotenv google-generativeai anthropic opencv-python numpy
```

### 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 GEMINI_API_KEY 等密钥
```

### 使用

```bash
# 完整流程：处理图片 + 叠字
python scripts/run_banner.py -i input/your_image.png -m "主标题" -s "副标题"

# 仅叠字（跳过图片处理）
python scripts/run_banner_compose_only.py -i output/step1_prepared_background.png -m "主标题" -s "副标题"

# 自定义描述生成背景
python scripts/run_full_with_custom_prompt.py

# 仅主副标题，自动生成描述（prompt-engine 完整管线）
python scripts/run_full_with_custom_prompt.py -m "主标题" -s "副标题" --prompt-engine

# 商店移动端日常（独立管线）
python scripts/run_full_with_custom_prompt.py -g 商店移动端日常 -m "主标题" -s "副标题" --description "描述..." --micugpt2 --packy7s

# 活动长图（-g 活动长图，KV + 自动取色 + AI 背景 + 三区排版）
python scripts/run_full_with_custom_prompt.py -g 活动长图 -m "主标题" -s "副标题" \\
  --xingchengpt --event-date "1.1-1.15" --prize-dir input/prizes \\
  --rules "规则一|规则二|规则三" --font-title fonts/title.otf

# 活动长图仅合成（跳过Step1，复用已有KV）
python scripts/run_changtu.py --kv input/kv.jpg --font-title fonts/title.otf \\
  -m "主标题" -s "副标题" --xingchengpt -o output/活动长图.jpg

# 邮件长图全流程（-g 邮件长图，KV + EVENT01~04 四区排版 + Vision 风格分析 + API 装饰背景）
python scripts/run_full_with_custom_prompt.py -g 邮件长图 -m "主标题" -s "副标题" \\
  --kv input/kv.png --font-title fonts/title.otf \\
  --event-date "2026/7/6-2026/10/10" \\
  --prize-dir input/prizes --prize-order "礼盒2|礼盒1|礼盒4|礼盒3" \\
  --method-dir input/screenshots \\
  --method-desc "在联想应用商店...|在LegionZone..." \\
  --history-dir input/history --history-order "礼品1|礼品4|礼品3|礼品2" \\
  --intro-text "《王者荣耀世界》是由腾讯天美工作室研发的..." \\
  --xingchengpt

# 邮件长图仅合成（跳过Step1，复用已有KV）
python scripts/run_email_poster.py --kv input/kv.png --font-title fonts/title.otf \\
  -m "主标题" -s "副标题" --event-date "2026/7/6-2026/10/10" \\
  --prize-dir input/prizes --method-dir input/screenshots \\
  --history-dir input/history --intro-text "游戏介绍..." --xingchengpt

# 查看帮助
python scripts/run_banner.py --help
```

在 Cursor 中使用时，Agent 会自动读取 `AGENTS.md` 中的技能表；或通过 `openskills read <skill-name>` 加载对应技能。

## 图片输入

在 OpenCode 对话框粘贴图片后，image-saver 插件自动保存到 `input/uploads/`：
- `current.png` — 最新图片固定路径
- `<时间戳>.png` — 历史存档
- `uploads_index.json` — 上传记录索引

遇到图片无法提取时，直接读取 `input/uploads_index.json` 获取最新路径，或使用 `input/uploads/current.png`。

## 项目结构

```
.
├── .env                     # API 密钥（勿提交）
├── .env.example             # 密钥模板
├── AGENTS.md                # Cursor/Agent 说明
├── pyproject.toml           # 依赖配置
├── .opencode/
│   └── image-saver.config.json  # OpenCode 图片保存插件配置
├── .claude/skills/          # 技能脚本（含 prompt-engine/）
│   └── prompt-engine/       # 文生图 Prompt 生成系统
├── scripts/                 # 工具脚本（含主入口 run_banner.py、run_mobile_presets.py）
│   ├── changtu/             # 活动长图合成管线
│   │   ├── poster.py        # 主合成器（1080px 竖版、KV/福利/规则三区）
│   │   ├── color_extract.py # KV 自动取色（11 token，k-means 聚类）
│   │   ├── micu_image_gen.py # AI 背景延续生成（gpt-image-2）
│   │   ├── fonts.py         # 4 角色本地字体管理
│   │   └── env_setup.py     # .env 加载
│   ├── email_poster/        # 邮件长图合成管线
│   │   └── poster.py        # 主合成器（1920px 竖版、KV+EVENT01~04四区、Vision风格分析+API装饰背景）
│   └── run_changtu.py       # 活动长图入口
│   └── run_email_poster.py  # 邮件长图入口
├── docs/                    # 文档
├── input/                   # 输入图片（含 uploads/ 子目录和 uploads_index.json）
└── output/                  # 输出结果
```

## 文档

- [流程与规则](docs/流程与规则.md) - 主流程、安全区、Step1/Step2 规则
- [AI 协作规范](docs/AI协作规范.md) - Prompt 库、参考图、运营插画习惯
- [文生图路径说明](docs/文生图路径说明.md)
- [对话框内完成全流程说明](docs/对话框内完成全流程说明.md)
