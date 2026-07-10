# 文生图模型指定（--model）

用户或 Agent 可通过 `--model`（或 `-M`）指定文生图使用的模型，无需改环境变量。

## 指令一览

| 指令（--model） | 含义 | 说明 |
|----------------|------|------|
| **gemini** | 直连 Google Gemini API | `BANNER_IMAGE_BACKEND=gemini`，需 `GEMINI_API_KEY`。模型默认 `gemini-3.1-flash-image-preview`，可用 `GEMINI_MODEL` 覆盖。 |
| **t8-gemini** | t8star（贞贞的AI工坊）上的 Gemini | `BANNER_IMAGE_BACKEND=t8star`，需 `T8STAR_API_KEY`。默认模型 `gemini-3.1-flash-image-preview`；可用环境变量 `T8STAR_IMAGE_MODEL` 覆盖。 |
| **t8-jimeng** | t8star 上的即梦 | 同上。贞贞 API 可用模型名为 `jimeng-4.5`、`jimeng-4.1`、`jimeng-4.0`（见 [贞贞的AI工坊](https://ai.t8star.cn/api-set) 错误提示）。若返回 500「倍率或价格未配置」，需在贞贞后台为账号开通即梦模型或联系管理员。 |
| **jimeng** / **即梦** | 火山引擎即梦 4.0 直连 | 调用项目 `scripts/jimeng_volc_api.py`，需在 `.env` 或环境变量中配置 `VOLC_ACCESS_KEY_ID`、`VOLC_SECRET_ACCESS_KEY`。 |

## 用法示例

```bash
# 用 Gemini 直连
python generate_from_description.py --model gemini "春日荷塘" output/bg.png

# 用 t8star 的 Gemini
python generate_from_description.py --model t8-gemini "春日荷塘" output/bg.png

# 用 t8star 的即梦（即梦模型 id 以 t8star 文档为准，可设 T8STAR_IMAGE_MODEL 覆盖）
python generate_from_description.py --model t8-jimeng "春日荷塘" output/bg.png

# 用火山即梦 4.0 直连（jimeng 或 即梦 均可）
python generate_from_description.py --model jimeng "春日荷塘" output/bg.png
python generate_from_description.py -M 即梦 "春日荷塘" output/bg.png

# 主副标题 → prompt-engine / prompt-optimizer（写描述）→ 文生图（需 GEMINI_API_KEY）
python generate_from_description.py --model jimeng --preset fill_canvas -m "开学回血补给站" -s "升级学习力 轻松新学期" output/bg.png
```

## prompt-optimizer（主副标题 → 文生图描述）

使用 `--main-title`（`-m`）与 `--subtitle`（`-s`）时，不传 description，改为由 **prompt-optimizer** / **prompt-engine** 调用 LLM 根据主副标题语义生成文生图描述，再交给即梦/Gemini 等文生图。需配置 **GEMINI_API_KEY**（或 **ANTHROPIC_API_KEY**）。

## 参考图（图生图 i2i）

使用 `--reference-image`（`-i`）传入**参考图的文件路径**且 `--model jimeng` 时，走即梦**图生图(i2i)**：以参考图 + 提示词生成新图再裁切。不传 `-i` 或 model 非 jimeng 时为纯**文生图(t2i)**。

- **`-i` 后面必须跟参考图的路径**（相对或绝对均可），例如将参考图存为 `input/ref.png` 后：
  ```bash
  python generate_from_description.py --model jimeng -i input/ref.png -m "主标题" -s "副标题" output.png
  ```
  或使用描述 + 参考图：
  ```bash
  python generate_from_description.py --model jimeng -i input/ref.png "一段风格描述" output.png
  ```

## 与环境变量的关系

- **未传 `--model`**：行为与之前一致，由环境变量 `BANNER_IMAGE_BACKEND`、`T8STAR_IMAGE_MODEL` 等决定。
- **传了 `--model`**：优先按上表选用后端与模型；若为 t8star 且已设置 `T8STAR_IMAGE_MODEL`，则用环境变量中的模型名覆盖别名默认值。

## t8star 模型名

贞贞的AI工坊 / 接口文档中「文生图」接口的 `model` 参数取值。即梦当前可用 id：`jimeng-4.5`、`jimeng-4.1`、`jimeng-4.0`（未指定 `--model t8-jimeng` 时可用 `T8STAR_IMAGE_MODEL` 覆盖）。若接口返回「倍率或价格未配置」，需在 [贞贞的AI工坊](https://ai.t8star.cn/api-set) 为令牌/账号开通对应即梦模型。

---

## 即梦（t8 jimeng）接入：文生图 + 图生图

即梦支持**文生图**与**图生图**（扩图/去字等），统一使用 t8star 兼容接口，需配置 **T8STAR_API_KEY**。

### 1. 配置 Key（勿提交到版本库）

在项目根目录的 `.env` 中增加一行（若已有其他 key，可追加）：

```env
T8STAR_API_KEY=你的即梦API密钥
```

或临时设置环境变量（PowerShell）：

```powershell
$env:T8STAR_API_KEY="你的即梦API密钥"
```

**注意**：`.env` 已在 `.gitignore` 中，请勿将真实 key 提交到仓库。

### 2. 文生图（描述 → 背景图）

```bash
python .claude/skills/banner-background-from-description/scripts/generate_from_description.py --model t8-jimeng "你的描述" output/bg.png
```

脚本会自动从项目根 `.env` 读取 `T8STAR_API_KEY`（若存在）。

### 3. 图生图（扩图 / 去字等）

使用 `run_banner.py` 或 `run_all_presets.py` 时，在 `.env` 中同时设置：

```env
BANNER_IMAGE_BACKEND=t8star
T8STAR_IMAGE_MODEL=jimeng
T8STAR_API_KEY=你的即梦API密钥
```

则 prepare_background 的扩图、去字会走即梦。若即梦在图编接口的 model id 与文生图不同，以接口文档为准修改 `T8STAR_IMAGE_MODEL`。

### 4. 简易文生图（gpt-best 文档格式）

若你的网关实现的是 [gpt-best 文生图](https://gpt-best.apifox.cn/api-229045941)（请求仅 `prompt`、`n`、`size`，响应 `data[].url`，无 `model` 参数），可启用简易模式，**在走“按 model 列表请求”之前**先尝试该格式：

```env
T8STAR_SIMPLE_T2I=1
T8STAR_BASE_URL=https://你的文生图网关地址
T8STAR_API_KEY=你的key
```

可选：`T8STAR_SIMPLE_T2I_SIZE=1024x1024`（或 `256x256`、`512x512`）。启用后，t8star 会先发 `{ "prompt": "...", "n": 1, "size": "1024x1024" }` 并解析 `data[0].url` 拉图；失败再按模型列表请求。
