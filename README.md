# skills-store-operational-banner-design（商店运营 Banner 设计）— 横幅（Banner）生成系统

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

