# skills-store-operational-banner-design（商店运营 Banner 设计）— 项目说明

本仓库用于 **Banner 背景生成 + 多尺寸叠字 + 活动长图（竖版海报）合成**。在终端使用 Claude Code 时，请先 `cd` 到本目录（含 `scripts/run_banner.py`、`.env` 的目录）。

## 目录与文档

| 路径 | 用途 |
|------|------|
| `docs/流程与规则.md` | 主流程、安全区、Step1/Step2 规则 |
| `docs/AI协作规范.md` | Prompt 库、参考图、运营插画习惯、AI 协作规范 |
| `.claude/skills/` | 各技能脚本（banner-background、composer、spec、prompt-engine 等） |
| `.claude/skills/prompt-engine/` | 文生图 Prompt 生成系统（16 种风格 + 11 种构图 + 6 步推导 + 质检评分） |
| `input/` | 输入素材（用户上传图片等） |
| `output/` | 输出结果（Banner、气泡等） |
| 项目根 `.env` | API Key 与后端（勿提交；见 `.env.example`） |
| `scripts/run_mobile_presets.py` | 商店移动端日常独立管线（A2→A4→A5→A6→compose） |
| `scripts/changtu/` | 活动长图合成管线（KV + 自动取色 + AI背景 + 三区排版） |
| `scripts/email_poster/` | 邮件长图合成管线（1920px 竖版，KV + EVENT01~04 四区排版 + Vision 风格分析 + API 装饰背景） |
| `scripts/run_changtu.py` | 活动长图入口脚本（可单独调用，-g 活动长图 自动路由到此） |
| `scripts/run_email_poster.py` | 邮件长图入口脚本（可单独调用，-g 邮件长图 自动路由到此） |
| `.opencode/image-saver.config.json` | OpenCode 图片保存插件配置 |
| `input/uploads_index.json` | 历史上传图片索引（路径 + 时间戳） |

## 环境与密钥

所有 Key 统一在 `.env` 中配置（按后端分组，详见 `.env.example`）：

- **Gemini / Packy 编辑后端**：`GEMINI_API_KEY` + `GEMINI_API_KEY_ALT`（ALT 在 401 时自动回退）；`GOOGLE_GEMINI_BASE_URL` 控制代理基址。
- **PackyGPT (gpt-image-2)**：`PACKYGPT_API_KEY`。生图/编辑走 packyapi。
- **MicuAPI (gpt-image-2 / Gemini)**：`MICUAPI_API_KEY` / `MICUGEMINI_API_KEY`。生图/编辑走 micuapi.ai。
- **即梦 / 火山**：`VOLC_ACCESS_KEY_ID`、`VOLC_SECRET_ACCESS_KEY`。
- **Lovart**：`LOVART_ACCESS_KEY` + `LOVART_SECRET_KEY`。
- **BiRefNet 抠图**：`BIREFNET_ALPHA_THRESHOLD`（`extract_subject_birefnet.py` 独立抠图用，代码实际默认 0.7；`.env.example` 注释写的 0.6 已过时，以代码为准）、`WIDE_A5B_ALPHA_THRESHOLD`（专题长图 A5b 顶条抠图专用，默认 0.6）、`HF_HUB_OFFLINE`。
- **可选 Anthropic**：`ANTHROPIC_API_KEY`（`--prompt-engine-claude` 用）。
- **其他生图/编辑后端**：`.env.example` 中还注册了 moxingpt/moxingemini、xingchengpt/xinchengpt/xingchengemini（+`XINGCHENGEMINI1_API_KEY` 轮换）等更多后端 Key，完整列表与能力矩阵以 `scripts/_backends.py` 为唯一权威数据源，不在此逐一列出。

Key 回退链：`--packy7s` 未设 `PACKY7S_API_KEY` 时自动回退到 `GEMINI_API_KEY`；`--packy3s` 未设 `PACKY3S_API_KEY` 时回退到 `GEMINI_API_KEY_ALT`。

模型配置（`GEMINI_MODEL` / `GEMINI_VISION_MODEL`）：在 `.env` 中设置后会被所有脚本尊重，仅在未配置时使用内置默认值。

Python 解释器以本机 `scripts/ensure_python.py` 解析为准；文档中曾固定 `D:\cursor\biyaozujian\Python`，若路径不同以实际为准。

## ⚠️ 重要：Windows 下用 `py` 而非 `python`

Windows 的 `python` 命令可能指向 **Microsoft Store 存根程序**（`WindowsApps\python.exe`），它不会实际执行 Python，导致脚本无输出、静默失败。

**所有 Python 命令必须用 `py` 前缀：**
```bash
py scripts/run_banner.py
py scripts/grab_opencode_image.py
py scripts/ensure_python.py
```

`ensure_python.py` 的 `get_python_exe()` 已自动跳过 WindowsApps 存根，优先用 `py` 路径。但在 bash 调用入口处仍要用 `py` 而非 `python`，确保脚本能被正确启动。

## 路径约束（强制）

所有输入输出必须使用项目内的 `input/` 和 `output/` 目录。
禁止在项目外创建同名目录。

- 正确：`py scripts/run_banner.py` → 读写 `skills-store-operational-banner-design/input/` 和 `output/`
- 错误：在 `skills-store-operational-banner-design/` 同级创建 `input/` 或 `output/` 目录

项目在启动时会自动检测外部目录，若发现会报错并退出。

---

## 图片输入（OpenCode image-saver）

用户在 OpenCode 对话框粘贴图片时，image-saver 插件自动将图片保存到 `input/` 目录：

- `input/uploads/current.png` — 最新图片的固定路径（脚本始终引用此路径）
- `input/uploads/<时间戳>.png` — 带时间戳的历史存档
- `input/uploads_index.json` — 所有上传记录（路径 + savedAt）

配置文件：`.opencode/image-saver.config.json`（`inputDir: "input"`，`python: "py"`）

**遇到"无法提取图片"问题时的处理方式：**
1. 读取 `input/uploads_index.json`，取第一条记录的 `path` 字段作为最新图片路径
2. 直接使用 `input/uploads/current.png` 作为输入路径
3. 若文件不存在，提示用户重新粘贴图片到对话框

---

## 常用命令（摘要）

- 全流程入口：`py scripts/run_banner.py`（见该文件与 `docs/流程与规则.md`）。
- 方案 A（自定义描述 + 多预设叠字）：`py scripts/run_full_with_custom_prompt.py`
  - 每次运行 OpenCode AI 都会强制重新推导描述（不复用历史 prompt），详见 `.opencode/instructions.md`；也可显式指定 `--prompt-engine` 调用外部 Gemini 推导或 `--prompt-engine-claude` 调用 Claude 推导。
  - 无 LLM 依赖：`--prompt-optimizer-template`（确定性模板引擎）。
  - `-g 商店移动端日常` 自动走独立移动端管线（`run_mobile_presets.py`）。
- 商店移动端日常独立管线：`py scripts/run_mobile_presets.py <bg.png> -m "主标题" -s "副标题" --micugpt2 --packy7s`
  - 定制的 A4 填充画布（2000×700）+ A5 移动端安全区对齐。
- Step1 仅从描述生背景：
  `.claude/skills/banner-background-from-description/scripts/generate_from_description.py`
  - `--prompt-optimizer` 可选 `template` / `local`。
- 活动长图全流程（-g 活动长图）：
  `py scripts/run_full_with_custom_prompt.py -g 活动长图 --xingchengpt --packy7s -m "主标题" -s "副标题" --event-date "活动时间" --prize-dir input/prizes --rules "规则|规则"`
- 活动长图仅合成（跳过Step1，复用已有KV）：
  `py scripts/run_changtu.py --kv input/kv.jpg --font-title fonts/title.otf -m "主标题" -s "副标题" --xingchengpt`

## 协作约定

- 生成或优化 **文生图描述** 时：优先读
  `.claude/skills/banner-background-from-description/prompt_library/user_preferences.md`
  与 `prompt_library/`、`ref_image_library/`（详见 `docs/AI协作规范.md`）。
- **运营插画**：避免字面化文案（如「充能」不画电池）；画面无大字标题、横版、便于后期压字。
- 改代码时：**只改任务相关文件**，风格与现有脚本保持一致。

## BiRefNet 抠图（专题长图 3320 顶条 / 独立抠主体）

- **依赖**：项目根执行 `pip install -e ".[birefnet]"`，或 Windows 运行 `scripts/install_birefnet_deps.bat`；首次会从 HuggingFace 拉取 `ZhengPeng7/BiRefNet-matting`。
- **专题长图 A5b**：`run_all_presets` 的 Step 1b（`wide_from-fill`）会优先走 BiRefNet，失败再回退 Gemini。若希望**只用 BiRefNet、失败即报错**：在 `.env` 或环境中设置 `WIDE_A5B_NO_GEMINI_FALLBACK=1`。顶条边缘可调软：`WIDE_A5B_ALPHA_THRESHOLD=0.45`（0～1，默认 0.6）。
- **整图或区域抠 PNG**：  `py scripts/extract_subject_birefnet.py <图路径> --output output/subject_rgba.png`；人物发丝可加 `--no-binarize`；可先 `--crop x1 y1 x2 y2` 再抠。

## 在 Cursor 里使用

1. **文件 → 打开文件夹**，选择本目录 `skills-store-operational-banner-design`（不要只打开上层「存档」文件夹，否则相对路径容易乱）。
2. 终端（含 WSL）中：`cd` 到上述同一目录后再运行 `claude` 或 Python 脚本，这样 `AGENTS.md` 与 `.env` 才会对应当前工程。

---

## 会话进度管理

**每次会话开始时，必须执行以下检测：**

1. 检测 `docs/progress.md` 是否存在
2. 若存在，读取文件内容：
   - 若状态为"已完成"或"空闲"，询问用户本次任务目标，更新文件后开始执行
   - 若存在未完成步骤（`[ ]` 或 `[~]`），告知用户上次中断位置，询问是否继续，确认后从中断处恢复
3. 若不存在，询问用户任务目标后创建文件

**执行过程中，必须实时维护 `docs/progress.md`：**

- 任务开始时：写入任务目标、拆分步骤、更新状态为"进行中"
- 每完成一个步骤：立即将对应步骤从 `[ ]` 改为 `[x]`，并更新"最后执行"字段
- 开始新步骤前：将对应步骤标记为 `[~]`（进行中）
- 遇到错误或工具失败时：
  - 将当前步骤标记为 `[~]`（未完成）
  - 在"失败原因"字段记录错误信息
  - 在"关键上下文"字段记录已知的重要信息
  - 更新"恢复指令"为：`读取 docs/progress.md，从上次中断的地方继续`
- 任务全部完成后：将文件顶部状态改为 `## 状态：已完成`

**新建会话恢复方式（告知用户）：**

新建会话后，在对话框输入：
> 读取 `docs/progress.md`，从上次中断的地方继续

---

<skills_system priority="1">

## Available Skills

<!-- SKILLS_TABLE_START -->
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke: Bash("openskills read <skill-name>")
- The skill content will load with detailed instructions on how to complete the task
- Base directory provided in output for resolving bundled resources (references/, scripts/, assets/)

Usage notes:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in your context
- Each skill invocation is stateless
</usage>

<available_skills>

<skill>
<name>banner-spec</name>
<description>Single source of truth for banner canvas presets, safe zones, legend zones, layout config, genre groups, and output filenames. Use when querying or modifying canvas sizes (PRESETS), safe zones (get_safe_zone), layout params (get_layout), genre groups (GENRE_PRESETS), or output filenames (OUTPUT_FILENAME_BY_PRESET). All other banner skills derive their spec data from here.</description>
<location>project</location>
</skill>

<skill>
<name>banner-composer</name>
<description>Compose banner images from a background image, main title, and subtitle with fixed layout rules (canvas size default 1976×464 or presets, Microsoft YaHei typography, gradient overlay). Use when generating a single banner asset with text overlay. Pair with banner-background-from-image or banner-background-from-description for the background.</description>
<location>project</location>
</skill>

<skill>
<name>banner-background-from-image</name>
<description>Prepare a single banner background image from a user-provided image to meet target width×height. Decides between crop, outpainting (expand with image model to fill missing areas and handle occlusion), or both—based on achieving the best visual result for the target size. Respects shared safe zone (x=770～1457, y=0～464); can remove irrelevant text from the image. Use when the user provides an existing image to use as a banner background; output is intended for banner-composer. Does not generate images from text—use banner-background-from-description for that.</description>
<location>project</location>
</skill>

<skill>
<name>banner-background-from-description</name>
<description>Generate a banner background image from a short description or marketing copy (e.g. "我们喜爱的独立游戏", "发现远足秘径"). Default image backend is nano-banana-2 (BANNER_IMAGE_BACKEND=nano-banana); optional gemini for direct API. Then crops to target W×H with shared safe zone. Use when the user wants a banner background created from text only—not from an existing image. Output is suitable for banner-composer. For existing images use banner-background-from-image.</description>
<location>project</location>
</skill>

<skill>
<name>skill-creator</name>
<description>Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.</description>
<location>project</location>
</skill>

<skill>
<name>template</name>
<description>Placeholder skill template. Copy this skill directory to create a new skill, then update SKILL.md with the actual name, description, and instructions.</description>
<location>project</location>
</skill>

<skill>
<name>prompt-engine</name>
<description>Generate high-quality Chinese text-to-image prompts from title + subtitle. Features 16 visual styles, 11 composition types, 6-step derivation pipeline (info parsing → style/composition → subject Q0-Q4 → prompt construction → optimization → quality scoring ≥43/55), brand-tier-aware safety rules, and index rotation for cross-generation diversity. Default output is text-free (no titles/CTA in image). Use when user provides only 主标题+副标题 and needs a high-quality banner background prompt.</description>
<location>project</location>
</skill>

</available_skills>
<!-- SKILLS_TABLE_END -->

</skills_system>

## Key 架构与经验教训

### 多 Key 隔离原则

```
PACKYGPT_API_KEY → gpt-image-2 → 生图 (/v1/images/generations) + 编辑 (/v1/images/edits multipart，支持 mask) + Vision
MICUAPI_API_KEY   → gpt-image-2 → 生图 (/v1/images/generations) + 编辑 (/v1/images/edits multipart，支持 mask；回退 /v1/chat/completions) + Vision
GEMINI_API_KEY    → gemini      → 编辑（去文字/扩图/主体检测）+ Vision
```

- 三条 Key **独立不互覆写**，分别走 Packy/micuapi/Gemini 不同 API。
- `BANNER_IMAGE_BACKEND` 是唯一调度开关：`gemini` / `packygpt` / `micugpt2` / `jimeng` / `t8star` / `lovart` / `nano-banana`。
- `_packy.py` 中 `--packygpt` / `--micugpt2` 处理不碰 `GEMINI_API_KEY`。

### GEMINI_API_KEY_ALT 自动回退

所有 Gemini API 调用点（图像编辑、主体检测、换行、Vision、文生图/图生图）在收到 HTTP 401 时自动切换到 `GEMINI_API_KEY_ALT` 重试一次。覆盖文件：
- `gemini_image_edit.py`、`gemini_subject_detect.py`、`gemini_linebreak.py`
- `hd_vision.py`、`hero_design.py`、`generate_from_description.py`

### ⚠️ if/elif 链规则（防复发，3 处已修复）

**所有后端选择的 if/elif 链必须是单一链路**，严禁用独立 `if` 块覆盖前一个 `if` 的设置：

```python
# ✅ 正确
if packygpt:    BANNER_IMAGE = "packygpt"
elif micugpt2:  BANNER_IMAGE = "micugpt2"
elif packy7s:   BANNER_IMAGE = "gemini"

# ❌ 错误 — if + elif 分离导致覆盖
if packygpt:    BANNER_IMAGE = "packygpt"
if micugpt2:    BANNER_IMAGE = "micugpt2"    # 独立 if 可能不触发
elif packy7s:   BANNER_IMAGE = "gemini"      # 会覆盖 packygpt 的设定！
```

**影响文件**：`run_full_with_custom_prompt.py` (L205-254)、`run_all_presets.py` (L199-204)、`_packy.py` (L85-101)

### BANNER_IMAGE vs BANNER_EDIT 优先级

`prepare_background.py:28` 读取顺序：

```
BANNER_IMAGE_BACKEND（优先） > BANNER_EDIT_BACKEND（回退） > "gemini"（默认）
```

- `BANNER_IMAGE_BACKEND`：控制生图 + **strip S5/S6 编辑**后端（packygpt/micugpt2/gemini）
- `BANNER_EDIT_BACKEND`：仅当 `BANNER_IMAGE_BACKEND` 为空时才能生效，不可覆盖 IMAGE 值
- Strip 扩图（S5）和接缝修复（S6）都按此分发

### context_prompt — Vision 辅助主体检测（新增功能）

生图 prompt 自动注入 Gemini Vision，提升 bbox 检测准确度：

```
数据流: Step1 写 prompt.txt → Step2 读 → prepare_background --context-prompt
       → gemini_subject_detect.py → Gemini Vision API

验证: 日志出现 "✅ 已加载生图描述，将传递给 Vision 辅助主体检测"
代码: run_all_presets.py:209-214 / gemini_subject_detect.py:793-795
```

原理：Gemini 收到的 Prompt 从 `"Identify the MAIN subject..."` 变为 `"Image content hint: {完整生图描述} ... Identify the MAIN subject..."`，知道画面预期内容后 bbox 更准确。

### API 约束速查

| 约束 | packyapi | micuapi |
|------|----------|---------|
| t2i 端点 | `/v1/images/generations` | `/v1/images/generations` |
| i2i 端点 | `/v1/images/edits` (multipart，支持 mask) | `/v1/images/edits` (multipart，支持 mask) — 主路径 / `/v1/chat/completions` (JSON base64) — 回退 |
| 最大宽高比 | 无限制（已验证 8:1） | 无限制（已验证 1:8） |
| 最小像素 | ≥ 655,360 | 未限制 |
| 尺寸 16 倍数要求 | 必须 | 未限制 |
| Vision 图像识别 | 不支持（gpt-image-2 仅生图，返回图片非文字） | 支持（Markdown 图片响应解析） |
| 代理建议 | **直连**（断长连接），设 `PACKYGPT_NO_PROXY=1` | API 直连，CDN 下载走代理 |

### Strip (1740×220) 编辑后端分发

`prepare_background.py` → `_strip_direct_to_canvas()` 按 `BANNER_IMAGE_BACKEND` 分发：

| 步骤 | gemini | packygpt | micugpt2 |
|------|--------|----------|----------|
| S4 贴主体到画布 | `composite_to_canvas_center` sentinel `(1,0,254)` | 同 | 同 |
| S5 扩图 | `edit_image()` Gemini | `_packygpt_edit_image()` | `_micugpt2_edit_image()` + sentinel mask |
| ~~S5b 硬覆盖~~ | ~~numpy~~ | ~~numpy~~ | ~~已删除（mask 替代）~~ |
| S6a 接缝检测 | Gemini Vision | Gemini Vision | Gemini Vision |
| S6b 修复 | `edit_image()` Gemini | `_packygpt_edit_image()` | `_micugpt2_edit_image()` |

✅ **S5 改用 mask 路径（2026-06 升级）**：S5b 硬覆盖已删除。S5 现在通过 `_generate_sentinel_mask` 生成 sentinel 区域的 mask（透明=sentinel 可编辑，不透明=主体保留），API 收到 mask 后只编辑透明区域，主体像素原样保留。Sentinel 颜色从 `(0,0,1)` 升级为 `(1,0,254)`（近纯蓝偏紫），与自然图像像素差异大，避免误判。

### A4 (tianchong.png 扩图) 编辑后端分发（2026-06 升级）

A4 之前**硬编码走 Gemini**，`--micugpt2` 不影响。现已支持按 `BANNER_IMAGE_BACKEND` 分发：

| 步骤 | gemini | packygpt | micugpt2 |
|------|--------|----------|----------|
| A4 扩图 4096×1024 | `edit_image()` Gemini | `_packygpt_edit_image()` | `_micugpt2_edit_image()` + cover-resize 兜底 |

- micugpt2 不保证返回 4096×1024，A4 出图后强制 cover-scale 到 4096×1024 兜底
- A4 mask 暂未启用（Gemini/Packy/micugpt2 任一后端扩图都无 mask）

### micugpt2 编辑能力（2026-06 升级）

主管线 `prepare_background.py` 的 `_micugpt2_edit_image` 已重写：

- **走 `/v1/images/edits` multipart 主路径**（`micugpt2_images_api.edit_image`），支持 mask 遮罩
- **走 `/v1/chat/completions` JSON base64 回退路径**，主路径失败时自动降级
- 3 次重试（主路径失败后回退到 chat/completions）
- 尺寸兜底：`keep_returned_size=False` 时 cover-scale 修正回原始尺寸
- `max_d=2560`（旧版仅 1536）
- 新增 `mask_path` 参数，S5 strip 和 A6 未填充修复均可传入

辅助函数：
- `_generate_unfilled_mask`（A6 用）：识别近黑未填充区域
- `_generate_sentinel_mask`（S5 用）：识别 `(1,0,254)` sentinel 区域

数据流：
```
S5  准备 sentinel mask → micugpt2 /v1/images/edits + mask → 主体由 API 保留
A4  micugpt2 扩图 → cover-resize 兜底 4096×1024
A6  检测未填充 → 生成 mask → micugpt2 编辑 → 修复
```

### 快速诊断表

| 症状 | 检查点 | 根因 |
|------|--------|------|
| 生图走 Gemini 而非 gpt-image | 日志开头 | if/elif 链 bug |
| strip 扩图走 Gemini | Step S5 日志 | EDIT_BACKEND 优先级问题 |
| bbox 不准确 / 偏到边缘 | a5_bbox_preview.png | context_prompt 未注入 |
| wide (3320×500) 无 BiRefNet | Step 1b 日志 | tianchong.png 不存在 + 回退失效 |
| 首页 1976×464 左侧黑边 | Step 4 / tianchong.png 实际尺寸 | A4 硬编码走 Gemini，未传 `--micugpt2` |
| 专题头图中间浮图 / 紫色描边 | Step S5 日志 | S5b 未删除或 sentinel 颜色错误 |
| Gemini 503 大量返回 | 全链路 | packyapi 模型不可用 |

> 历史症状：羊毛毡/暗色场景人物消失（S5b sentinel 阈值 5 误判）— 已通过删除 S5b 改用 mask 路径修复。

### 系统环境变量陷阱

- Windows 用户级 `GEMINI_API_KEY` 优先于 `.env` 文件，`.env` 的值会被覆盖。
- 调试 401 时务必检查 `[Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')`。
- 删除命令：`[Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $null, 'User')`。

### 项目目录重命名后的清理步骤

重命名项目目录后，OpenCode SQLite DB 仍保存旧路径，每次启动会弹 503 错误。需手动清理：

1. DB 位置：`C:\Users\<用户>\.local\share\opencode\opencode.db`
2. 更新 `project` 表的 `worktree` 字段（旧路径 → 新路径）
3. 删除 `project_directory` 表中指向旧路径的记录（新路径记录已自动创建）
4. 删除其他已不存在目录的旧 project 记录

```python
import sqlite3
db = r'C:\Users\<用户>\.local\share\opencode\opencode.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
# 更新当前项目
cur.execute("UPDATE project SET worktree='新路径' WHERE worktree LIKE '%旧名%'")
# 删除 project_directory 旧记录（新路径已存在，直接删）
cur.execute("DELETE FROM project_directory WHERE directory LIKE '%旧名%'")
conn.commit(); conn.close()
```

同时需检查代码库内是否有硬编码旧路径（`grep -r "旧目录名" .`），测试脚本中的 `ROOT = Path(r"...")` 建议改为 `Path(__file__).resolve().parent.parent`。

### 抠图方案选择

| 场景 | 方案 | 说明 |
|------|------|------|
| 纯色背景文字 | 亮度蒙版 `gray.point(lambda x: 255-x)` | 毫秒级，零依赖，自动检测底色深浅 |
| 自然图像（人物/物体） | BiRefNet (`extract_subject_birefnet.py`) | AI 模型，耗时但精度高 |

### -g 分组速查

| 分组名 | 调用的脚本 | 规格 |
|--------|-----------|------|
| 商店日常 | run_all_presets.py | 8 个 preset（含生成式UI封面1536x1024） |
| 商店移动端日常 | run_mobile_presets.py | 4 个 preset |
| 开放平台 | run_all_presets.py | 2 个 preset |
| **活动长图** | **run_changtu.py** | **1 个 preset（changtu_poster）** |
| **战报** | **run_battle_report.py** | **1 个 preset（1080px 竖版长图）** |
| **排行榜** | **run_ranking.py** | **1 个 preset（1080px 竖版长图，CSV→JSON+图标+背景+截图）** |
| **邮件长图** | **run_email_poster.py** | **1 个 preset（1920px 竖版，KV+EVENT01~04 四区排版+Vision风格分析+API装饰背景）** |

### Banner 管线速查

```bash
# 方案 A 完整命令（prompt-engine 写描述 + packy7s 生图 + Gemini 编辑）
py scripts/run_full_with_custom_prompt.py -g 商店畅玩卡1920*550 --packy7s \
  --main-title "开学回血补给站" --subtitle "升级学习力" --prompt-engine

# 方案 A 完整命令（自定义描述 + packy7s 生图 + Gemini 编辑）
py scripts/run_full_with_custom_prompt.py -g 商店畅玩卡1920*550 --packy7s \
  --main-title "开学回血补给站" --description "背景描述..." --text-art "艺术字描述..."

# micugpt2 图生图（1:8 比例直接出）
py scripts/run_full_with_custom_prompt.py -g "商店题头图 1740*220" --micugpt2 \
  --main-title "." --description "描述..." -i input/uploads/current.png

# packygpt 原图编辑（不重绘）
py scripts/run_all_presets.py input/uploads/current.png -g "商店题头图 1740*220" \
  --main-title "." -packygpt

# packygpt 生图 + Gemini 编辑（商店日常）
py scripts/run_full_with_custom_prompt.py -g 商店日常 --packygpt --packy7s \
  -m "主标题" -s "副标题" --description-file input/prompt.txt

# micugpt2 生图 + Gemini 编辑 + 跳过A1去干扰
py scripts/run_full_with_custom_prompt.py -g 商店日常 --micugpt2 --packy7s \
  -m "主标题" -s "副标题" --description-file input/prompt.txt --skip-remove-text

# 商店移动端日常全流程（自动走独立移动端管线）
py scripts/run_full_with_custom_prompt.py -g 商店移动端日常 --micugpt2 --packy7s \
  -m "主标题" -s "副标题" --description "描述..." --prompt-engine

# 多 -g 合并：一张 bg.png 裁切多个尺寸（一次 API 调用）
py scripts/run_full_with_custom_prompt.py -g "商店田字格 304*216" -g "商店首页 1976*464" \
  --packygpt --packy7s -m "主标题" -s "副标题" --prompt-engine

# 仅重跑移动端 Step2（复用已有 bg.png，不重新生图）
py scripts/run_mobile_presets.py "output/xxx/bg.png" \
  -m "主标题" -s "副标题" --output-dir "output/xxx" --micugpt2 --packy7s

# 仅重跑 Step2（复用已有 bg.png，不重新生图）
py scripts/run_all_presets.py "output/xxx/bg.png" \
  --main-title "主标题" --subtitle "副标题" --output-dir "output/xxx" \
  --skip-a4-outpaint --skip-remove-text --genre 商店日常 -X -packy7s
  #   -X = -packygpt 或 -micugpt2
```

活动长图相关命令：
```bash
# 活动长图全流程（-g 活动长图）
py scripts/run_full_with_custom_prompt.py -g 活动长图 --xingchengpt --packy7s \
  -m "主标题" -s "副标题" --event-date "活动时间" --prize-dir input/prizes \
  --rules "规则一|规则二|规则三" --font-title fonts/title.otf

# 活动长图仅合成（跳过Step1，复用已有KV）
py scripts/run_changtu.py --kv input/kv.jpg --font-title fonts/title.otf \
  -m "主标题" -s "副标题" --xingchengpt --packy7s
```

邮件长图相关命令：
```bash
# 邮件长图全流程（-g 邮件长图）
py scripts/run_full_with_custom_prompt.py -g 邮件长图 -m "主标题" -s "副标题" \
  --kv input/kv.png --font-title fonts/title.otf \
  --event-date "2026/7/6-2026/10/10" \
  --prize-dir input/prizes \
  --prize-order "礼盒2|礼盒1|礼盒4|礼盒3" \
  --method-dir input/screenshots \
  --method-desc "在联想应用商店...|在LegionZone..." \
  --history-dir input/history \
  --history-order "礼品1|礼品4|礼品3|礼品2" \
  --intro-text "《王者荣耀世界》是由腾讯天美工作室研发的..." \
  --xingchengpt

# 邮件长图仅合成（跳过Step1，复用已有KV）
py scripts/run_email_poster.py --kv input/kv.png --font-title fonts/title.otf \
  -m "主标题" -s "副标题" \
  --event-date "2026/7/6-2026/10/10" \
  --prize-dir input/prizes --prize-order "礼盒2|礼盒1|礼盒4|礼盒3" \
  --method-dir input/screenshots \
  --method-desc "在联想应用商店...|在LegionZone..." \
  --history-dir input/history --history-order "礼品1|礼品4|礼品3|礼品2" \
  --intro-text "《王者荣耀世界》是由腾讯天美工作室研发的..." \
  --xingchengpt
```

排行榜相关命令：
```bash
# 排行榜全流程（CSV→JSON + 图标 + 背景 + 截图）
py scripts/run_full_with_custom_prompt.py -g 排行榜 --xingchengpt \
  --ranking-csv "input/ranking/榜单.csv" --ranking-theme gold

# 跳过 AI 背景（用 CSS 渐变兜底）
py scripts/run_full_with_custom_prompt.py -g 排行榜 \
  --ranking-csv "input/ranking/榜单.csv" --skip-bg

# 独立运行（跳过图标和背景，复用已有数据）
py scripts/run_ranking.py --csv output/排行榜_xxx/data.json \
  --output-dir output/排行榜_xxx --skip-icons --skip-bg
```

输出包含：背景 + 艺术字（自动抠图）+ 六边形横幅对话框（自动取色匹配）。

### BANNER_BG_SIZE 环境变量

控制 `bg.png` 生图尺寸（`run_full_with_custom_prompt.py` 分组模式用）：

```
BANNER_BG_SIZE=WxH   → 如 1024x640 / 1920x1080
不设: packygpt/micugpt2 → 1024x640（gpt-image-2 原生）；其他 → 1920x1080（16:9）
优先级: --width/--height 命令行 > BANNER_BG_SIZE > 后端默认值

---

## 后端能力矩阵与防复发规则

### 设计原则

1. **功能固定，Key 可换**：主体保护（mask）、扩图（outpaint）、Vision 检测是固定功能，换 Key 只是换凭证，不影响代码路径
2. **单一数据源**：所有后端的类型、优先级、能力差异在一处声明，不散落在多个 if/elif 链中
3. **下游统一分发**：`edit_image()` / `prepare_background.py` 的下游函数按 `BANNER_IMAGE_BACKEND` 的值分发，不感知上游 Key 的具体来源

### 后端分类

| 分类 | 标志 | 用途 | Key 变量 |
|------|------|------|----------|
| **gpt-image-2 生图类** | `-packygpt`, `-xingchengpt`, `-micugpt2`, `-moxingpt` | t2i 文生图 | 各自专用 Key |
| **Gemini 编辑类** | `-xingchengemini`, `-packy7s`, `-packy3s`, `-packy`, `-micugemini` | Vision 检测 + 扩图 + mask 编辑 | 设置 `GEMINI_API_KEY` + `GOOGLE_GEMINI_BASE_URL` |
| **其他** | `-jimeng`, `-lovart`, `-t8star` | 特定平台生图 | 各自专用 Key |

### elif 链硬规则（防复发）

所有 `BANNER_IMAGE_BACKEND` 选择的 if/elif 链必须遵循：

```
gpt-image-2 类（生图） → 排在前面，先命中
Gemini 编辑类（回退）  → 排在后面，作为回退
```

**规则**：任何新增的 gpt-image-2 后端参数，其 elif 条目必须在所有 Gemini 类条目之前。新增 Gemini 编辑类后端参数，其 elif 条目必须在所有 gpt-image-2 条目之后。

**影响文件**（共 3 处，新增后端时必须同步更新）：
- `scripts/run_full_with_custom_prompt.py` L196-272 (块2: 生图后端选择)
- `scripts/_packy.py` L103-174 (块2: 生图后端选择)
- `scripts/run_all_presets.py` L201-215 (共享后端处理)

### 新增后端检查清单

修改 elif 链或新增参数后，必须逐项确认：

| # | 检查项 | 验证方式 |
|---|--------|---------|
| 1 | gpt-image-2 类排在 Gemini 类之前 | 在 3 个影响文件中 grep 验证 `elif getattr.*gpt.*在.*gemini.*前` |
| 2 | 该后端的 Key 已加入 `_ENV_KEYS` 列表 | grep 后端名 + `_ENV_KEYS` |
| 3 | `edit_image()` 有该后端的 dispatch 分支 | grep `BANNER_IMAGE_BACKEND.*后端名` in `prepare_background.py` + `gemini_image_edit.py` |
| 4 | 所有 S5/S4 扩图调用点都有 mask 生成 + 传递给 `edit_image()` | grep `_generate_sentinel_mask` 调用次数 = 扩图点数量（当前 4 处：strip S5, _direct_to_canvas S5, 两条 A4 路径） |
| 5 | `--width --height` 参数被实际传入 API 请求体 | 检查后端的 t2i 函数中 `width/height` 是否出现在 `body` 或 `_size` 构造中 |
| 6 | `DIRECT_TO_CANVAS_PRESETS` 只含 `default`，不含 card/push 小尺寸 | grep `DIRECT_TO_CANVAS_PRESETS` 确认 |
| 7 | 新后端是否有 `xingchengemini` 的联动（`BANNER_EDIT_BACKEND = "gemini"`） | 检查 elif 链中的 `if getattr(args, "xingchengemini", False)` 是否被包含 |
| 8 | `_packy.py` 的块1和块2都有该后端的条目（如适用） | grep 后端名 in `_packy.py` |

### tianchong 尺寸

`.claude/skills/banner-background-from-image/scripts/safe_zone_scale_composite.py:101` 定义了 tianchong 画布尺寸（注意：此文件位于该 skill 目录下，不在顶层 `scripts/`）。当前值：

```python
FILL_CANVAS_W, FILL_CANVAS_H = 2048, 512  # 严格 4:1
```

修改此值需同步更新：
- `gemini_image_edit.py`: `OUTPAINT_FILL_TO_3840x1080_PROMPT` 中的尺寸文本
- `prepare_background.py`: 所有 `2048×512` 字符出现位置和 `(2048, 512)` 尺寸校验
- `prepare_background_micugpt2.py`: 同上

### 组合使用模式

`-xingchengpt -xingchengemini` 的效果：

```
BANNER_IMAGE_BACKEND = "xingchengpt"    → gpt-image-2 t2i
GEMINI_API_KEY = XINGCHENGEMINI_API_KEY → Gemini Vision + edit
BANNER_EDIT_BACKEND = "gemini"          → gemini_subject_detect 选择 Gemini
```

`edit_image()` 调用时检查 `XINGCHENGEMINI_API_KEY`，如果可用则路由到 `_edit_image_xingchengemini()`（chat/completions + mask），否则走标准 Gemini `generateContent`。

---

## HD 管线编辑操作铁律

所有 HD 管线中涉及 Gemini edit_image / gpt-image-2 edits 的操作，必须遵循以下原则。

### Mask 三原则

**1. 最小可编辑区域**
给 Gemini 的 mask **越大越自由，越精确越可控**。编辑操作必须最大化保护（腐蚀核心）+ 最小化可编辑区域（仅目标区域边缘）。

**2. 补全用方向局部膨胀**
`_build_inpaint_mask` 从 `missing_desc` 解析 left/right/top/bottom 方向词，仅在该侧 bbox 1/3 区域内向外膨胀 40~80px。无方向词时回退全局膨胀（兼容旧逻辑，但应尽量避免）。

**3. 光源统一仅边缘可编辑**
```python
# ✅ 正确：仅边缘 5px 带可编辑，Gemini 只调光照不重绘
from PIL import ImageFilter
eroded = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(5))
core = eroded > 0; body = alpha > 0; edge = body & ~core
mask[edge, 3] = 255

# ❌ 错误：全身可编辑 → Gemini 会重绘整个角色，导致身体叠加鬼影
mask[body, 3] = 255
```

### 透明 PNG 四重保障

任何产出透明 PNG 的路径（补全/光源统一/艺术字/Logo/光效统一）在保存前必须过四关：

| # | 步骤 | 作用 |
|---|------|------|
| 1 | `img.putalpha(orig_alpha)` | 恢复原始 alpha，防止 API 填充背景 |
| 2 | `_merge_alpha_union` (BiRefNet 取并集) | 补全新内容可见 |
| 3 | `_ensure_transparent_bg` (感知去白底) | 清理棋盘格 / 白底残留 |
| 4 | `arr[alpha==0, :3] = 0` (RGB 归零) | 防止透明区脏色导致白边鬼影 |

缺失任何一步都会导致下游合成出现白边、鬼影或棋盘格。

---

## Changelog

### 2026-07-09 — 专题长图 wide 自动探顶（主体探不进 40px 白条 → BiRefNet 测顶行自动上移）

**问题**：专题长图顶部 40px 白条空白——主体真实顶部在 y≈50-55（bbox `y_min` 比真实主体顶低 + fit 到安全区 90% 后顶部落在 y≈25-55），够不到 y=0-40 白条 → A5b 抠图区无前景可探入，白条纯白。手调 `WIDE_TOP_EXTEND_PX` 因 API 两侧填充每次主体位置略变而不稳。

**改动**：

| # | 文件 | 内容 |
|---|------|------|
| 1 | `prepare_background.py` 新增 `_wide_auto_top_poke()` + `_wide_auto_top_poke_enabled()` | A5b 前用 BiRefNet 在抠图区（x=1032-2464, y=0-context_h）测主体真实顶行；够不到白条则整图上移 `top_row - WIDE_TOP_POKE_TARGET`（封顶 120px），底部 `np.pad(mode="edge")` 补齐；自适应内容，无需手调 |
| 2 | `prepare_background.py:wide_from_fill` | A5b 前插入步骤 4b：`WIDE_AUTO_TOP_POKE=1`（默认）且用户未设 `WIDE_TOP_EXTEND_PX` 时调用自动探顶 |
| 3 | `prepare_background_micugpt2.py` | 孪生同步 `_wide_auto_top_poke()` + `_wide_auto_top_poke_enabled()` + wide_from_fill_micugpt2 A5b 前调用 |
| 4 | `AGENTS.md` | 对齐策略步骤 3b + 环境变量 `WIDE_AUTO_TOP_POKE`/`WIDE_TOP_POKE_TARGET` + 诊断表「顶部白条空白」行更新 |

**优先级**：用户显式设 `WIDE_TOP_EXTEND_PX`（非空非0）→ 尊重手动值，禁用自动探顶；否则自动探顶接管。

**验证**（复用 tianchong.png）：主体顶行 y=49 → 自动上移 37px → 前景最顶行 y=28（探入白条），白条内前景像素 174（原 0）。✅ 白条露出主体。

### 2026-07-09 — 专题长图 wide 默认改 bg-direct（跳过 tianchong/A4），`WIDE_KEEP_TIANCHONG` 可回退

**动机**：wide 原流程 `bg → A4(4轮图编产 tianchong) → wide_from_fill(tianchong)`，A4 是 moxin 403/503 高发点且对 wide 是多余中间步。`wide_from_fill` 已自带 fit-to-safe-zone + 侧翼 mask 填充 + A5b，可直接吃 bg。

**改动**：

| # | 文件 | 内容 |
|---|------|------|
| 1 | `run_all_presets.py` Step1b | 默认 `_fill_source=cleaned_bg_for_direct`（去干扰后 bg）+ `bbox=shared_subject_bbox.txt`；删除 tianchong 前置 bbox 检测。`WIDE_KEEP_TIANCHONG=1` 走旧 tianchong 源 |
| 2 | `prepare_background.py` A4块 | default(1976×464) 产 tianchong 的 4 轮 A4 图编外层加 `WIDE_KEEP_TIANCHONG` gate，默认跳过（省一次 API）；`wide_from_fill` docstring 更新 |
| 3 | `run_all_presets_micugpt2.py`（legacy）Step1b | 默认 wide 源改 `image_path`(bg)；**保留 tianchong 生产**（其它 preset 仍依赖），仅切 wide 取源 |
| 4 | `AGENTS.md` | 数据流 D0/D1/D2 重写 + 环境变量 `WIDE_KEEP_TIANCHONG` + 本条 |

**验证**：离线 `wide_from_fill(bg, shared_bbox)` 端到端产出合法 3320×500（fit + A5b 均执行）；3 个改动文件编译通过；`WIDE_KEEP_TIANCHONG=1` 保留旧路径。

**注意**：bg-direct 下 wide 质量依赖 `shared_subject_bbox.txt` 准确度（bg 上检测）。bbox 退化（moxin Vision 失败返回近全图）时 `wide_from_fill` 退化守卫回退 cover+图心；bbox 略偏则主体可能轻微溢出安全区（宁松勿紧 L4）。

### 2026-07-09 — 专题长图 wide 两侧填充：edge-pad 拉伸 → sentinel+mask API 延展填充（默认开，失败回退）

**问题**：专题长图 3320×500 主体 fit 到安全区后，两侧空隙由 `np.pad(mode="edge")` 复制背景边列填满，视觉上是横向拉丝/条纹（本次 `edge-pad L626 R678` 占画布 39%）。

**改动**：

| # | 文件 | 内容 |
|---|------|------|
| 1 | `prepare_background.py` 新增 `_wide_fill_sides_via_api()` | 空隙填 sentinel(1,0,254) + `_generate_sentinel_mask` + **固定走 Gemini 系 `edit_image`（像素级 mask，不跟随 gpt-image-2 生图后端，避免弱 mask 重绘主体，B1）**；返回非 3320×500 → cover-scale+center-crop 兜底；sentinel 残留 >2%/异常 → 返回 None |
| 2 | `prepare_background.py` 新增 `_wide_side_fill_api_enabled()` | 开关 `WIDE_SIDE_FILL_API`，默认开 |
| 3 | `prepare_background.py:wide_from_fill` | 补空段改为：有空隙+非退化 bbox+开关开 → 试 API 填充；返回 None/关闭/无空隙/退化 bbox → 回退原 `np.pad(mode="edge")`（原逻辑完整保留） |
| 4 | `prepare_background_micugpt2.py` | 孪生同步 `_wide_fill_sides_via_api_micugpt2()`（走自身 `_micugpt2_edit_image` + `MICUGPT2_A6_FILL_PROMPT`，无像素 mask 靠 sentinel 提示词）+ `wide_from_fill_micugpt2` 补空段同步改造 |
| 5 | `gemini_subject_detect.py:_call_moxingemini_vision` | **修 Vision 模型 bug**：原读 `MOXINGEMINI_MODEL`（图编 `[白嫖]` 系，返回图非文本）→ 改为优先读 `MOXINGEMINI_VISION_MODEL` + 逗号分隔多模型按序重试；A5b 语义 keep-mask 不再 403 |
| 6 | `.env` | `MOXINGEMINI_MODEL` 前缀 `[特价参考]` → `[白嫖]`（token 对图编模型只有 `[白嫖]` 前缀有权）；新增 `MOXINGEMINI_VISION_MODEL=[白嫖]gemini-3-pro-image,...`（Vision 用可访问的 image 模型） |
| 7 | `AGENTS.md` | 数据流 D1/新增 D4 + 对齐策略步骤3 + 环境变量 `WIDE_SIDE_FILL_API` + 诊断表「两侧拉丝」行 |

**根因（403 定位）**：moxin.studio 图编模型的真实名带 **`[白嫖]`** 前缀（`/v1/models` 可查），token 对**去前缀裸名**和 `[特价参考]` 前缀均无权限（返回 `This token has no access to model ...`）。`.env` 原用 `[特价参考]` 前缀 → 图编/Vision 全 403。改用 `[白嫖]` 前缀后：`[白嫖]gemini-3.1-flash-image-preview` / `gemini-3-pro-image-preview` / `gemini-3-pro-image` 图编 200 返回图片（`gemini-3.1-flash-image` 偶发 503 渠道无）。

**验证**（复用 `output/商店日常_告别杂乱无章_20260709_152543/tianchong.png`）：✅ API-fill 路径触发 + 多模型重试 + `[白嫖]` 图编成功返回图片 + cover-crop 兜底（2660×400→3320×500）+ sentinel 残留 0% + A5b Vision 不再 403（正常语义回退 BiRefNet）+ 产出合法 3320×500；✅ `WIDE_SIDE_FILL_API=0` 强制 edge-pad 路径正常。

**注意**：wide 不再是严格「零 API」——默认每次 wide 多一次图编 API 调用（可 `WIDE_SIDE_FILL_API=0` 关闭回到零 API）。

### 2026-07-09 — 专题长图 wide_from_fill 重写（cover+overscan → fit-to-safe-zone）+ BiRefNet padding bug 修复

**问题（一次会话连环踩坑）**：①主体探不进顶部白条；②BiRefNet 抠图区 alpha 全 0；③改后主体严重溢出安全区。逐层定位出 3 个独立根因 + 一串几何认知教训。

**改动**：

| # | 文件 | 内容 |
|---|------|------|
| 1 | `birefnet_matting.py:_extract_alpha_region_padded` | pad 方形填充色 **纯黑 → `mode="reflect"` 边缘镜像**。纯黑规整色块被 BiRefNet 误判成前景（100% 高置信像素落黑区），真主体反被判背景 |
| 2 | `prepare_background.py:wide_from_fill` | **对齐逻辑重写**：cover+overscan+头约束 → **fit-to-safe-zone 缩放 + bbox 中心对齐 + `np.pad(mode="edge")` 补空**。主体完整落安全区 |
| 3 | `prepare_background.py:wide_from_fill` | 删除头约束（`min(ideal, bbox_top−20)`），改纯 bbox 中心 → safe_cy 对齐 |
| 4 | `prepare_background_micugpt2.py` | 孪生 wide 路径全面同步：fit-to-safe-zone 缩放 + bbox 中心对齐 + edge-pad + BiRefNet 语义 keep-mask 副本（全部与主文件一致）|
| 5 | `prepare_background.py` | 新增 `WIDE_FIT_RATIO`（默认 0.9，留边距吸收 bbox/主体偏差）|
| 6 | `AGENTS.md` | 数据流/对齐策略/环境变量/诊断表全面更新 + 新增「核心教训 L1-L9」|

**关键教训**（详见「专题长图 → 核心教训」表）：BiRefNet 1024² 失真、纯黑 padding 伪前景、edge vs reflect、bbox 宁松勿紧、主体纵向位置决定几何天花板、40px 白条一次只容一个横切面、抠图仅在铺白区可见、**调试信几何量化别靠肉眼**。

**待办**：本次全 8 尺寸因 moxin.studio 403 只补出专题长图，其余 7 尺寸待后端恢复或换后端。

### 2026-07-08 — 专题长图 A5b 顶条前景提取重做（裁切区推理 + Gemini 语义 keep-mask）

**问题**：A5b `_composite_wide_top_strip_birefnet` 在整张 3320×500（6.6:1）画布上跑 BiRefNet，被压成 1024² 推理导致严重失真 → alpha 全 0 → 顶部白条常空白；且 0.6 硬二值化过激、无多物体/语义控制，无法「保留所有前景、去环境+装饰」。

**改动**：

| # | 范围 | 内容 |
|---|------|------|
| 1 | `birefnet_matting.py` 新增 `_extract_alpha_region_padded()` | BiRefNet 改在裁切区上跑，pad 成方形再推理，消除长宽比失真（根因修复） |
| 2 | `birefnet_matting.py` 新增 `_filter_small_components()` | cv2 连通域过滤，丢弃 < `min_component_area` 的碎块（清理光斑/粒子装饰） |
| 3 | `birefnet_matting.py` `composite_strip_with_matting` | 新增 `keep_mask`/`min_component_area`/`binarize`/`context_h` 入参；软阈值；keep-mask 相交 |
| 4 | `gemini_subject_detect.py` 新增 `FOREGROUND_OBJECTS_PROMPT` + `detect_foreground_objects_bboxes()` + `_parse_bbox_list()` | 列出所有真实前景物体/角色框（排除环境+装饰氛围），返回 bbox 列表 |
| 5 | `prepare_background.py` `_composite_wide_top_strip_birefnet` 重写 | 编排：裁 context 区 → Gemini keep-mask → matte∩mask → 去碎屑 → 贴回；兜底链不变 |
| 6 | `prepare_background.py` 新增环境变量 helper | `WIDE_A5B_SEMANTIC`/`WIDE_A5B_CONTEXT_H`/`WIDE_A5B_MIN_COMPONENT_AREA`/`WIDE_A5B_NO_BINARIZE`；`WIDE_A5B_ALPHA_THRESHOLD` 默认 0.6→0.4 |
| 7 | `AGENTS.md` | 更新 A5b 步骤说明 + 环境变量表 + 快速诊断表 |

**已验证**：keep-mask 相交对（右半框→排除左半内容 0%、全框→保留 9.2%）符合预期；`_parse_bbox_list` 兼容 JSON/0-1000 刻度/空数组。裁切区推理修复后白条能正常抠出前景（前提：主体确实伸入 y=0-40；否则白条为干净纯白，属正常）。

**注意（前景不透明前提）**：文生图 prompt 必须禁止毛玻璃/半透明/透明/玻璃质感/薄纱/烟雾/朦胧/发光半透明体等无法清晰抠边的内容，主体须实心不透明、轮廓锐利，A5b 才能干净抠出。

### 2026-07-08 — A4 重试韧性 + sentinel 检测 + chat/completions 多模型重试

**问题**：moxingemini think 模型（`gemini-3.1-pro-preview-think`）偶发返回文本 JSON 而非图片，导致 A4 outpaint 第一轮就抛异常→复制未填充的 sentinel 画布→tianchong.png 含 15% 蓝紫色块未填充→wide/专题长图继承相同空洞；sentinel_pct 检测有除数 bug（除以 H×W×3 而非 H×W）导致 15% 真占比被算成 4.997% 漏检；`_edit_image_moxingemini`/`_moxingpt_edit_image`/`_edit_image_xingchengemini`/`_edit_image_micugemini` 四个 chat/completions 编辑函数都是单模型单次 POST 无重试。

**改动**：

| # | 范围 | 内容 |
|---|------|------|
| 1 | `prepare_background.py:1499` sentinel 检测 | 内联计算替换为 `_warn_sentinel_residue()` 调用，修复除数为 `H×W`（原 bug 除数为 `H×W×3`） |
| 2 | `prepare_background.py` 新增 `_warn_sentinel_residue()` | 通用 sentinel 残留扫描工具函数（阈值默认 2%，可配 `SENTINEL_RESIDUE_WARN_PCT`），警告但不阻断流程 |
| 3 | `prepare_background.py` 4 处调用点 | strip 1740x220、direct_to_canvas、A4 两处产出后均加 sentinel 扫描 |
| 4 | `prepare_background.py` A4 两处循环 | `except → break` 改为 `except → continue`，4 轮全失败才回退含 sentinel 的本地画布（`edit_image` 内部已做多模型重试，外层循环配合充分利用 4 轮机会） |
| 5 | `gemini_image_edit.py` 新增 `_parse_chat_model_list()` | 逗号分隔模型列表解析，最多取前 3 个 |
| 6 | `gemini_image_edit.py` 新增 `_chat_completions_edit_image()` | chat/completions 图编通用多模型重试实现：按序尝试最多 3 个模型，某模型返回文本/无图片/HTTP 失败时换下一模型，全部失败才抛异常 |
| 7 | `gemini_image_edit.py` `_edit_image_moxingemini` | 委托到 `_chat_completions_edit_image`，`MOXINGEMINI_MODEL` 支持逗号分隔 3 模型（默认含非 think 模型兜底，避免 think 模型返回文本无效） |
| 8 | `gemini_image_edit.py` `_edit_image_xingchengemini` | 委托到通用函数，新增 `XINGCHENGEMINI_MODEL` 环境变量（向后兼容：未设时回退到原硬编码值 `gemini-3.1-flash-image-preview`） |
| 9 | `gemini_image_edit.py` `_edit_image_micugemini` | 委托到通用函数，新增 `MICUGEMINI_MODEL` 环境变量（向后兼容：未设时回退到 `gemini-3-pro-image-preview`） |
| 10 | `prepare_background.py` `_moxingpt_edit_image` | gpt-image-2 类编辑多模型重试：`MOXINGPT_MODEL` 逗号分隔最多 3 个，按序重试，默认 `gpt-image-2,gpt-image-2-base64` |
| 11 | `.env.example` | `MOXINGEMINI_MODEL` 示例改为逗号分隔 3 模型格式；`MOXINGPT_MODEL` 示例追加 `gpt-image-2-base64` 第二候选 |

### 2026-06-30 — HD 管线 Mask + 透明 PNG 铁律落地

**问题**：光源统一全身 mask 导致 Gemini 重绘角色（身体叠加鬼影）；透明 PNG 四步缺失导致棋盘格/白底残留；补全 mask 全身膨胀导致编辑范围过大。

**改动**：

| # | 范围 | 内容 |
|---|------|------|
| 1 | `stage3_compose.py:_build_inpaint_mask` | 方向局部膨胀替代全身膨胀 |
| 2 | `stage3_compose.py:_unify_cutout_lighting` | mask 从 `body` 改为 `edge`（腐蚀 5px） |
| 3 | `stage3_compose.py:_unify_cutout_lighting` | 追加 `_ensure_transparent_bg` |
| 4 | `stage3_compose.py:_relight_char_via_gpt_edits` | 透明区 RGB 归零 |
| 5 | `stage3_compose.py:_tone_character` | 透明区 RGB 归零 |
| 6 | `stage3_compose.py:_relight_characters` | 保存前兜底透明区 RGB 归零 |
| 7 | `stage3_compose.py:_generate_title_art_gpt` | 艺术字 GPT 3 次重试，失败报错 |
| 8 | `stage3_compose.py:_generate_title_art` | 删除 PIL 艺术字回退 |
| 9 | `stage3_compose.py:_prepare_logo` | Logo 等比缩放 fit 450×120 + 独立输出 `logo_final.png` |
| 10 | `stage3_compose.py:_composite` | 删除 Logo 贴图块，Logo 不再合入 Banner |
| 11 | `stage3_compose.py:_inpaint_cutout` | 追加 `_ensure_transparent_bg` 清理棋盘格/白底 |
| 12 | `stage3_compose.py:_INPAINT_PROMPT` | 约束只改 mask 区域，不改已有像素 |
| 13 | `scripts/` | 删除 `hd_pipeline_package/` 冗余目录 |
| 14 | `AGENTS.md` | 新增 Mask 三原则 + 透明 PNG 四重保障，删除两处副本同步 |

### 2026-06-29 — xingchengpt/xingchengemini 并行 + mask 机制落地

**问题**：首次使用 `-xingchengpt -xingchengemini` 组合，发现 elif 链中 xingchengemini 先命中导致 xingchengpt 永不到达；tianchong 4096×1024 过大导致扩图失败；小尺寸卡在 S5 变形；bg.png 尺寸不稳定。

**改动**：

| # | 范围 | 内容 |
|---|------|------|
| 1 | `run_full_with_custom_prompt.py`, `_packy.py`, `run_all_presets.py` | elif 链重排，xingchengpt（生图）提到 xingchengemini（编辑）之前 |
| 2 | 6 个文件 | tianchong 4096×1024 → 2048×512 |
| 3 | `run_all_presets.py` | `DIRECT_TO_CANVAS_PRESETS = {"default"}`，card/push 尺寸走 bg.png cover-crop |
| 4 | `run_all_presets.py` | compose fallback 改为 `image_path`，首页走 bg.png cover-crop |
| 5 | `gemini_image_edit.py` | 新增 `_edit_image_xingchengemini()` — chat/completions + mask |
| 6 | `prepare_background.py` | 新增 `_generate_sentinel_mask()`；A4/strip/直接扩图全部走 mask，移除硬覆盖 |
| 7 | `generate_from_description.py` | t2i 后 mask 扩图到目标尺寸，bg.png 固定 1920×600 |
| 8 | `scripts/_backends.py` | 后端能力矩阵（10 个后端）+ `_generate_sentinel_mask()` 工具函数 |
| 9 | `AGENTS.md` | 后端分类/elif 硬规则/新增后端检查清单/tianchong 同步规则/组合模式速查 |

### 2026-07-02~03 — 战报合成：双数据模块 + 字体动态匹配 + Vision 风格推导 + xingchengpt Gemini 回退 + RGBA 透明 overflow

**问题**：战报仅支持单组 stats；字体硬编码；风格推导仅取色缺画风/构图/氛围；分区栏头 overflow 区被重复 AI 底图填充；xingchengpt 504 无回退。

**改动**：

| # | 范围 | 内容 |
|---|------|------|
| 1 | `run_battle_report.py` | 新增 `--stat-group` 可重复参数，每组渲染独立 framed 数据卡 |
| 2 | `run_full_with_custom_prompt.py` | 新增 `--stat-group` / `--font-family` 参数并透传 |
| 3 | `compose_battle_report.py` | stats→stat_groups 多组支持；画布 RGBA 透明 + alpha mask；删除 overflow 延伸填充；`_composite_rgba_layer` / `_paste_rgba_on_rgb` 兼容 RGBA base；调用 `resolve_or_create_hero_data_bg` |
| 4 | `battle_report/fonts.py` | 新增 `set_font_family(name)` — 拼音映射 + TTF name table + 文件名模糊匹配，项目目录优先 |
| 5 | `battle_report/nano_banana_visual.py` | 新增 `_analyze_kv_style()` Vision 风格分析 + `_style_info_to_clause()`；`decor_image_backend()` 支持 xingchengpt/packygpt/micugpt2；xingchengpt t2i → urllib 回退 → Gemini 回退链路；i2i 直接走 Gemini |
| 6 | `changtu/micu_image_gen.py` | `run_micu_t2i` 新增 urllib 原生请求回退、`import json` |
| 7 | `AGENTS.md` | 新增「战报经验教训与复用规范」章节 |
```

---

## 战报合成 — 经验教训与复用规范

### 字体

| # | 规则 | 说明 |
|---|------|------|
| F1 | 统一入口 `set_font_family(name)` | 不要在各处硬编码字体候选列表 |
| F2 | 扫描优先级：项目 `fonts/` → 系统字体 | 项目字体应优先于系统字体 |
| F3 | 中文匹配用拼音映射 | `PINYIN` dict 映射常见中文字形到拉丁拼写，解决文件名不同但中文名相同的匹配问题 |
| F4 | TTF name table `toUnicode()` 需回退 | 中文字体名编码兼容问题，fallback `str(record)` |
| F5 | 匹配评分排序，取最佳 | 收集所有匹配按子串长度评分，不取遇到的第一个 |

### 多组数据

| # | 规则 | 说明 |
|---|------|------|
| D1 | `--stat-group "标题\|标签\|值\|标签\|值"` 格式 | 管道符分隔，每组渲染独立 framed 数据卡 |
| D2 | 各组竖排堆叠，间距 `HERO_LOWER_BLOCK_INNER_GAP` | 同常量保持一致 |
| D3 | bar_text 在多组模式不注入卡片 | 每组卡片的 `bar_text=""`，标题走 `card_title` |

### 后端分发

| # | 规则 | 说明 |
|---|------|------|
| A1 | t2i: xingchengpt → urllib → Gemini | 三重回退保证至少一个可用 |
| A2 | i2i: 跳过 xingchengpt，直接 Gemini | gpt-image-2 不擅长 i2i |
| A3 | `decor_image_backend()` 优先读 `BANNER_IMAGE_BACKEND` | 与主生图管线保持一致 |
| A4 | `api.centos.hk` 504 是服务端问题 | nginx 代理超时，非客户端代码错误 |
| A5 | urllib 回退用原生 `urllib.request.urlopen` | 不依赖 `requests` 库 |

### 渲染

| # | 规则 | 说明 |
|---|------|------|
| R1 | 需要透明 overflow 的画布必须 RGBA | `Image.new("RGBA", size, (0,0,0,0))`，禁止 RGB |
| R2 | 贴入最终画布用 alpha mask | `base.paste(strip, (x, y), strip.split()[3])` |
| R3 | `_composite_rgba_layer` 需兼容 RGBA base | 不强制 `.convert("RGB")` |
| R4 | `_paste_rgba_on_rgb` 需兼容 RGBA base | 增加 `alpha_composite` 分支 |
| R5 | 程序化背景不走 overflow 区 | `bg_y0 = band_y0` 固定，不因 overflow 扩到 0 |

### 风格推导

| # | 规则 | 说明 |
|---|------|------|
| S1 | 取色（K-means）+ Vision 分析双步 | 取色得 12 色 token，Vision 得 {art_style, composition, lighting, mood, motifs} |
| S2 | Vision 结果缓存到 `kv_style.json` | 避免重复调 API |
| S3 | `_style_info_to_clause()` 注入 prompt | struct→英文子句，所有 prompt 构造函数均接收 `style_info` |
| S4 | Vision 返回空时用默认兜底 | 不阻塞流程，降级到通用风格描述 |

### 环境变量

| # | 变量 | 作用 |
|---|------|------|
| E1 | `BATTLE_REPORT_SECTION_BANNER_IMAGE=1` | 开启分区 Banner GPT 生图 |
| E2 | `BATTLE_REPORT_HERO_DATA_IMAGE=1` | 开启数据区 GPT 生图 |
| E3 | `BATTLE_REPORT_NANO_BANANA_REFRESH=1` | 强制刷新缓存 |
| E4 | `BANNER_IMAGE_BACKEND=xingchengpt` | 接管战报生图后端 |
| E5 | `GEMINI_API_KEY` + `GOOGLE_GEMINI_BASE_URL` | Gemini 回退凭证 |

---

## 专题长图 3320×500 — 经验教训与复用规范

### 数据流

```
默认（bg-direct，WIDE_KEEP_TIANCHONG 未设）：
bg.png →(Step0a 去干扰 + Step0b bbox→shared_subject_bbox.txt)
       → wide_from_fill(bg, bbox=shared_subject_bbox.txt):
           fit-to-safe-zone 缩放 + bbox 中心对齐(1967,250)
           + 两侧 sentinel+mask API 填充(默认，失败回退 edge-pad)
           + A5b 顶部40px BiRefNet 抠图
       → compose 叠字 → 专题长图 3320x460.png
       （不再产 tianchong / 不跑 A4，省一次 4 轮图编 API）

回退（WIDE_KEEP_TIANCHONG=1）：
bg.png → A4(composite + API fill) → tianchong.png (2048×512) → wide_from_fill(tianchong, tianchong_bbox.txt) → A5b
```

| # | 规则 | 说明 |
|---|------|------|
| D0 | **默认 bg-direct**：wide 直接用去干扰后的 bg + `shared_subject_bbox.txt`（bg 上检测），不依赖 tianchong/A4 | 少一次 A4 图编 API（moxin 403 高发点）；`WIDE_KEEP_TIANCHONG=1` 回退旧 tianchong 流程。改动点：`run_all_presets.py` Step1b、`prepare_background.py` A4块、`run_all_presets_micugpt2.py`（legacy 保留 tianchong 生产，仅切 wide 源）|
| D1 | wide_from_fill 内部自带填充，不再依赖 A4 预填 | 两侧空隙默认走 sentinel+mask API 延展填充（`WIDE_SIDE_FILL_API=1`，见 D4），失败回退 edge-pad。产出扫描 `_warn_sentinel_residue()` 打印 `SENTINEL_WARN`（阈值 2%，可配 `SENTINEL_RESIDUE_WARN_PCT`）|
| D2 | bbox 复用 `shared_subject_bbox.txt`（bg 上检测） | 默认 bg-direct 零额外 Vision 调用；`WIDE_KEEP_TIANCHONG=1` 时才在 tianchong 上独立检测写 `tianchong_bbox.txt` |
| D3 | **bbox 要"松框"覆盖完整主体轮廓** | Gemini/BiRefNet 的紧框常比真实主体窄（如只框柜子不含伸出的手臂），对齐时主体会溢出安全区。bbox 宁松勿紧（详见"核心教训 L4"） |
| D4 | **两侧空隙优先 API 延展填充，失败回退 edge-pad** | `_wide_fill_sides_via_api()`：空隙填 sentinel(1,0,254) + `_generate_sentinel_mask` + **固定走 Gemini 系 `edit_image`（像素级 mask，不跟随 gpt-image-2 生图后端，避免 chat/completions 弱 mask 整体重绘主体偏移，见 B1）**。返回非 3320×500 走 cover-scale+center-crop 兜底；sentinel 残留 >2% / 异常 / 无空隙 / 退化 bbox → 回退 `np.pad(mode="edge")`。孪生 micugpt2 用自身 `_micugpt2_edit_image`（无像素 mask，靠 sentinel 提示词）。设 `WIDE_SIDE_FILL_API=0` 强制纯 edge-pad |

### 对齐策略（2026-07-09 重写：cover+overscan → fit-to-safe-zone）

**旧逻辑（已废弃）**：cover 撑满画布 + 动态 overscan + 头约束 → crop。问题：cover 为填满 6.6:1 画布把主体放大到 scale≈2.25，一个占源图 89% 高的主体被撑成 1020px（画布仅 500）→ **主体四边溢出安全区，只露中段**；且头约束 `min(ideal, bbox_top−20)` 覆盖了中心对齐，导致必须靠 `WIDE_TOP_EXTEND_PX` 硬补才能探白条。

**新逻辑** `wide_from_fill` 4 步：

| 步骤 | 操作 | 关键参数 |
|------|------|---------|
| 1 | 读取/检测 bbox | 归一化 (x_min, y_min, x_max, y_max) |
| 2 | **fit-to-safe-zone 缩放** | `fit_scale = safe_h × WIDE_FIT_RATIO / bbox_h_px`（高优先；若宽装不下再取等宽）。主体缩放到贴合安全区，不再 cover 撑满 |
| 3 | **bbox 中心对齐 + 两侧填充** | `paste = safe_center − bbox_center`（bbox 中心→(1967,250)）；缩放图不够画布宽时两侧空隙**默认走 sentinel+mask API 延展填充**（`WIDE_SIDE_FILL_API=1`，见下），失败/关闭/无空隙/退化 bbox 时回退 `np.pad(mode="edge")` 延展背景边列（**必须 edge 不能 reflect**，见 L3） |
| 3b | **自动探顶**（`WIDE_AUTO_TOP_POKE=1` 默认开）| A5b 前用 BiRefNet 测主体真实顶行，若够不到白条（y=0-40）则整图上移使其探入（底部 edge 补），自适应内容。解决「主体顶部在 y≈50 探不进 40px 白条 → 白条空白」（L5）。用户显式设 `WIDE_TOP_EXTEND_PX` 时让位手动值 |
| 4 | A5b BiRefNet+Gemini语义 | 铺白 y=0-40 + 抠图 x=1032-2464（context_h 上下文）前景贴回 |

**关键效果**：主体完整落安全区（x∈1470-2464, y∈0-500），因主体够高缩放后顶部贴近 y=0，`WIDE_TOP_EXTEND_PX` 微量上推即可探白条（回归微调本职）。

**A5b 前景提取（2026-07-08 重做）**：目标"版式不变，顶部白条只留前景、去环境+装饰"。
1. **裁切区推理（核心修复）**：BiRefNet 改在裁切上下文区（x=1032-2464、y=0-`WIDE_A5B_CONTEXT_H`）上跑并 **pad 成方形** 再推理，不再对整张 6.6:1 画布推理（旧法被压成 1024² → 失真 → alpha 全 0 → 白条空白）。
2. **Gemini 语义 keep-mask**（`WIDE_A5B_SEMANTIC=1` 默认开）：`detect_foreground_objects_bboxes` 列出所有真实前景物体/角色框（排除天空/墙/地面等环境 + 粒子/光斑/漂浮装饰），构建 keep-mask 与 matte 相交，框外一律剔除。
3. **连通域去碎屑**（cv2）：丢弃面积 < `WIDE_A5B_MIN_COMPONENT_AREA` 的前景块（清理装饰粒子）。
4. **软阈值**：`WIDE_A5B_ALPHA_THRESHOLD` 默认降到 0.4；`WIDE_A5B_NO_BINARIZE=1` 保留柔和边缘。
5. **兜底链**：Gemini 检测失败/无框 → 纯 BiRefNet；BiRefNet 失败 → `_composite_wide_top_strip` Gemini 伸入；`WIDE_A5B_NO_GEMINI_FALLBACK=1` 失败即报错。

**垂直对齐方向**（易混淆）：y=0 在画布顶部。top 增大 → 裁剪窗口下移 → 主体在画布中上移。

### 后端约束

| 后端 | 图编端点 | mask inpainting | 返回尺寸 |
|------|---------|:--:|:--:|
| Gemini `generateContent` | `/v1beta/models/*:generateContent` | ✅ 原生支持 | 保持 |
| gpt-image-2 `/v1/chat/completions` | moxin.studio chat/completions | ❌ 不保证 | **不固定** |
| gpt-image-2 `/v1/images/edits` | packyapi/micuapi | ✅ multipart mask | 保持 |

| # | 规则 | 说明 |
|---|------|------|
| B1 | gpt-image-2 chat/completions 不做像素级 mask editing | 传 mask 图 + 文本说明后 API 可能整体重绘，主体位置偏移。仅用于全图生成/变换，不用于保护主体 |
| B2 | gpt-image-2 产出后尺寸修正用 cover-scale + center-crop | 禁止 `resize((W,H))` 直接拉伸 |
| B3 | 中文模型名在 Gemini 原生 API URL 中需 `urllib.parse.quote()` | moxin chat/completions 走 JSON body 无此问题 |
| B4 | `GEMINI_MODEL` 用 `setdefault`，`.env` 有空值会阻止代码默认值 | 每个后端通过专属变量（`MOXINGEMINI_MODEL` 等）设模型，`.env` 中不写通用模型名 |

### 环境变量

| 变量 | 默认值 | 作用 |
|------|:--:|------|
| `WIDE_KEEP_TIANCHONG` | 0 | 默认 bg-direct（wide 直接用 bg，跳过 tianchong/A4）；设 1 回退旧 tianchong 流程（产 A4 tianchong + 在其上检测 bbox）|
| `WIDE_FIT_RATIO` | 0.9 | 主体贴合安全区的边距比例（<1 留边距，吸收 bbox 与真实主体轮廓偏差，防溢出）|
| `WIDE_SIDE_FILL_API` | 1 | 两侧空隙走 sentinel+mask API 延展填充（固定 Gemini 系 `edit_image`）；设 0 强制纯 edge-pad（零 API）。失败自动回退 edge-pad |
| `WIDE_TOP_EXTEND_PX` | 0 | 正值=主体上移伸入顶部白条 y=0-40（fit 重写后回归微调，通常 20~30 即可）；**显式设置后禁用自动探顶** |
| `WIDE_AUTO_TOP_POKE` | 1 | A5b 前自动探测主体顶行并上移使其探入白条（`WIDE_TOP_EXTEND_PX` 未设/为0 时生效）；设 0 关闭 |
| `WIDE_TOP_POKE_TARGET` | 12 | 自动探顶目标：主体顶行上移到白条内约此像素处（越小越贴顶，上移量封顶 120px）|
| `WIDE_A5B_ALPHA_THRESHOLD` | 0.4 | BiRefNet 顶条抠图 alpha 阈值（裁切区推理修复后可用较软阈值） |
| `WIDE_A5B_SEMANTIC` | 1 | Gemini 前景物体 keep-mask（剔除环境/装饰）；设 0 退回纯 BiRefNet |
| `WIDE_A5B_CONTEXT_H` | 400 | A5b 抠图/检测上下文源区高度（更高利于识别前景，仅贴回最上 40px） |
| `WIDE_A5B_MIN_COMPONENT_AREA` | 1200 | 去装饰碎屑的连通域最小面积（像素）；设 0 关闭 |
| `WIDE_A5B_NO_BINARIZE` | 0 | 设 1 时保留柔和 alpha 边缘（不二值化） |
| `WIDE_A5B_NO_GEMINI_FALLBACK` | 0 | 设 1 时 BiRefNet 失败不回退 Gemini |
| `SENTINEL_RESIDUE_WARN_PCT` | 0.02 | sentinel 残留告警阈值（占总像素 H*W 比例），超过即打印 `SENTINEL_WARN` |

### 快速诊断表

| 症状 | 检查点 | 根因 |
|------|--------|------|
| 画面压扁 | `_moxingpt_edit_image` 日志 | `resize((W,H))` 直接拉伸，应改 cover-scale + center-crop |
| 主体溢出安全区（只露中段/四边超框）| wide 日志 fit-scale + BODY 位置 | **旧 cover+overscan 把主体撑到 >画布**（scale≈2.25）。已改 fit-to-safe-zone；仍溢出则调低 `WIDE_FIT_RATIO` 或放宽 bbox（L4）|
| 主体轻微溢出左/右 | BODY x < 1470 或 > 2464 | bbox 太紧（未含伸出的手臂等），fit 后真实主体比 bbox 宽 → 放宽 `tianchong_bbox.txt` 或降 `WIDE_FIT_RATIO` |
| 两侧背景横向拉丝/条纹 | wide 日志 `edge-pad L.. R..` | 两侧走了 edge-pad 拉伸（边列复制）。①`WIDE_SIDE_FILL_API=0` 被显式关；②API 填充失败自动回退 edge-pad（多为 moxin.studio 403 / sentinel 残留 >2%）。修：确认后端图编可用（D4）|
| edge-pad 处出现重复主体/镜像 | wide 右侧/左侧 | 误用 `mode="reflect"`，pad 宽超过背景边距会把主体镜像出来。**必须 `mode="edge"`**（L3）|
| 顶部白条空白/抠不到前景 | Step 5b 日志 + `wide 自动探顶` 日志 | ①主体顶部在 y>40 够不到白条→自动探顶应上移（关了则设 `WIDE_AUTO_TOP_POKE=1` 或 `WIDE_TOP_EXTEND_PX`）；②整张 6.6:1 跑 BiRefNet 失真（已修：裁切区 pad 方形）；③主体在源图偏下、几何上够不到白条（需重生图让主体贯穿全高，L5）|
| 白条只露手指不露柜子 | 主体各高度宽度剖面 | 手指是最高部件、柜子在其下。白条只有 40px，一次只容一个横切面（L6）|
| 柜子抠出却"没展示" | A5b 铺白高度 vs 贴回高度 | 抠图只在 y=0-40 铺白处可见；y=40 以下前景贴回自身=零变化（L7）|
| sentinel 蓝色残留 | tianchong.png | A4 API 失败无兜底；`SENTINEL_WARN` 超阈值；重跑 A4 |
| 主体偏移/鬼影 | wide 有多次 API 调用 | gpt-image-2 chat/completions 不尊重 mask，重绘主体 |
| 模型 403/503 | Error 日志 | 403=token 对该模型名无权（moxin.studio 图编须用 `[白嫖]` 前缀，非 `[特价参考]`/裸名；`/v1/models` 查真实名）；503=渠道临时下线，换模型名 |
| 中文模型名 URL 报错 | `'ascii' codec can't encode` | Gemini 原生 URL 需 `quote()`，或改用 chat/completions |
| `GEMINI_MODEL` 未生效 | 日志显示错误模型 | `.env` 有旧值覆盖了 `setdefault`，删掉或改用专属变量 |

### 核心教训（2026-07-09 会话，调试专题长图白条踩坑全记录）

| # | 教训 | 具体 |
|---|------|------|
| L1 | **BiRefNet 固定 1024² 推理，超宽图会失真** | `extract_alpha_pil` 把整图 resize 到 1024×1024。3320×500（6.6:1）被压成方形 → alpha 全 0。必须在裁切区 + pad 方形上推理 |
| L2 | **pad 方形绝不能用纯黑填充** | 纯黑 `(0,0,0)` 是几何规整高对比色块，BiRefNet 会把它误判成显著前景（实测 100% 高置信像素落在黑 padding 区，真主体反被判背景）。用 `mode="reflect"` 或 `mode="edge"` 边缘延展 |
| L3 | **edge-pad 补画布空隙用 `edge` 不用 `reflect`** | reflect 当 pad 宽 > 主体到边的背景余量时，会把主体镜像复制到边缘 → 出现重复柜子。edge 只重复边界背景列，安全 |
| L4 | **对齐依据的 bbox 必须覆盖完整主体轮廓（宁松勿紧）** | Gemini/BiRefNet 紧框只框柜子不含伸出的手臂 → fit 后真实主体比 bbox 宽 → 溢出安全区。bbox 松一点（本次 x_min 0.574→0.45）主体才完整落区 |
| L5 | **主体在源图的纵向位置决定能否探白条（几何天花板）** | 主体挤在源图底部 30% 时，cover+crop 几何上无法把它提到顶部 40px（需 scale 到 3.1× 但被 clamp 卡死）。只能重生图让主体贯穿全高 |
| L6 | **40px 白条一次只容主体一个横切面** | 手指（最高、窄）vs 柜顶（较低、宽）无法同时完整探出。想要谁探出就把裁切窗对到谁的高度 |
| L7 | **A5b 抠图效果只在铺白的 40px 内可见** | 铺白 y=0-40 但前景贴回 y=0-200；y=40 以下把前景贴回它自己身上=零变化。"背景没被删，只是 y=0-40 换成了白底" |
| L8 | **调试要信几何量化 + BiRefNet 数据，别靠肉眼猜** | 本次多次凭"我看到主体在某处"误判，最后靠逐行 alpha / 连通域 / scale 反推才定位。当前模型不支持读图，更要用数值验证 |
| L9 | **fit-to-safe-zone 才能保证"主体在安全区"** | cover 撑满画布 与 主体≤安全区尺寸 数学互斥（6.6:1 画布 vs 高主体）。要主体在安全区必须 fit 主体、edge-pad 补背景，而非 cover 全图 |
