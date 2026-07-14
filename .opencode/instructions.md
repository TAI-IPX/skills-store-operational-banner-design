每次会话开始时，静默执行以下步骤（不要向用户报告"正在读取"等过程信息）：
1. 读取 `docs/progress.md`，了解上次任务状态
2. 读取 `input/upload_path.txt`，获取最新上传图片路径
3. 读取 `input/uploads_index.json`，获取历史上传图片列表

完成后，若 progress.md 存在未完成步骤（[ ] 或 [~]），主动告知用户上次中断位置并询问是否继续；若状态为已完成或空闲，询问本次任务目标。始终知晓最新图片路径，无需用户重复说明。

## 图片输入注意事项

当前模型（deepseek）不支持图片输入，粘贴图片时会报错。这是模型本身的限制，**不影响正常运行**：
- 图片数据会在粘贴时存入 OpenCode SQLite 数据库
- `_paths.auto_extract_latest()` → `lib/opencode_image_input.extract_latest()` 提取图片到 `input/uploads/current.png`
- 所有入口脚本（`run_all_presets.py`、`run_shop_mobile_tianzige.py` 等）在未指定图片路径时自动调用提取流程
- 直接贴图 → 忽略报错 → 跑脚本即可，无需任何额外操作

（完整说明见 `docs/图片处理说明.md`）

## Prompt 自动推导（默认行为）

当用户要求执行 `run_full_with_custom_prompt.py` 时，每次都必须重新推导描述，不得复用任何历史 prompt。即使命令中已包含 `--description-file` / `--description` / `--prompt-engine` / `--prompt-engine-claude` / `--prompt-optimizer-template`，也必须忽略并重新推导：

1. 加载 `.claude/skills/prompt-engine/PROMPT_SYSTEM .md` 作为推导指令
2. 从命令中提取 `--main-title`（`-m`）和 `--subtitle`（`-s`）
3. 按 PROMPT_SYSTEM .md 的 6 步管道在对话内完成推导（不调用外部 API）：
   - Step 1: 信息解析卡
   - Step 2: 风格与构图选择
   - Step 3: 主体推导（Q0-Q4）
   - Step 4: Prompt 构建（默认无排版模式）
   - Step 5: 二次优化（9 维自检）
   - Step 6: 质检评分（12 维，阈值 ≥43 分）
4. 提取 `【最终 Prompt】` 或 `【修正版 Prompt】` 段作为描述文本
5. 将描述写入临时文件（路径：`input/tmp_description_<timestamp>.txt`）
6. 将完整推导日志暂存为 `input/tmp_trace_<timestamp>.md`
7. 移除命令中已有的 `--description-file` / `--description` 参数（若存在），在命令末尾追加 `--description-file <临时描述文件路径>`
8. 执行命令
9. 命令执行完成后：
   a. 从 `output/` 下找到本次创建的 `run_dir`（匹配主标题和时间戳）
   b. 将暂存的推导日志复制到 `run_dir/prompt_engine_trace.md`
   c. 删除两个临时文件
10. 全程不向用户输出推导过程，保持静默（推导日志已保存到 trace.md，用户可自行查看）

**重要**：此推导使用当前 AI 模型（DeepSeek）在对话内完成，不调用任何外部 API。只有最后执行命令时才会由脚本调用生图 API。默认后端为 moxingpt（生图）+ moxingemini（编辑），无需在命令中显式指定 `--moxingpt --moxingemini`。

## 战报合成交互规范（-g 战报）

当用户要求执行 `run_full_with_custom_prompt.py -g 战报` 时，AI 需要构建素材目录结构：

1. **提取 KV 图**：从 `input/uploads/` 中识别最大尺寸的图片作为 KV 头图
2. **多分区截图分类**：
   - 列出所有剩余图片
   - 在对话框中询问用户每张图片归属哪个分区（**核心资源矩阵** / **联动活动火热开启** / **玩家真实好评**）
   - 若用户未指定分区或仅有少量图片，全部归入"战报截图"统一分区
3. **构建临时素材目录**（路径：`<run_dir>/_report_materials/`）：
   ```
   _report_materials/
     KV.jpg              ← KV 图（复制）
     核心资源矩阵/       ← 分区 B（按用户分类创建）
       01.png ...
     联动活动火热开启/   ← 分区 C（按用户分类创建）
     玩家真实好评/       ← 分区 D（按用户分类创建）
   ```
4. **传递参数**：在命令中追加 `--report-dir <临时素材目录路径>`
5. **无 KV 回退**：若 `input/uploads/` 中没有任何图片，走正常的 Step 1 文生图流程生成 bg.png 作为 KV 代替
6. **KV 早退**：若通过 `--kv` / `--report-dir`（目录内含 KV.jpg）/ `--ref` 提供了 KV 图，脚本自动跳过描述推导 + Step 1，直接进入战报合成；此时 AI 不需要执行 Prompt 自动推导流程
