# 图像编辑（扩图 / 去文字）配置

本 Skill 的扩图（outpaint）与去文字（inpainting）**默认固定使用 Gemini 3.1 API**（模型 `gemini-3.1-flash-image-preview`），需 **GEMINI_API_KEY**。

- **默认**：`BANNER_IMAGE_BACKEND=gemini`（未设置时即默认）— 仅走 Gemini 3.1 API 做图编。
- **改用 nano-banana**：设置 `BANNER_IMAGE_BACKEND=nano-banana` 则优先调用 nano-banana CLI，失败时回退 API。nano-banana 可从 `~/.nano-banana/.env` 读取 key；可设置 `NANO_BANANA_EXE` 指向可执行文件。
- **改用贞贞的AI工坊（t8star）**：设置 `BANNER_IMAGE_BACKEND=t8star` 则使用 [贞贞的AI工坊](https://ai.t8star.cn/api-set) 的 OpenAI 兼容图编接口（与 Gemini 同级，失败不回退）。需设置 `T8STAR_API_KEY`（在网站获取令牌）；可选 `T8STAR_BASE_URL`（默认 `https://ai.t8star.cn`）、`T8STAR_IMAGE_MODEL`（默认 `gpt-image-1.5`）。

## 设置 API Key

1. 在 [Google AI Studio](https://aistudio.google.com/apikey) 获取 API Key。
2. 设置环境变量（任选一种方式）：

**当前终端有效：**

- Windows (PowerShell): `$env:GEMINI_API_KEY = "你的key"`
- Windows (CMD): `set GEMINI_API_KEY=你的key`
- macOS / Linux: `export GEMINI_API_KEY="你的key"`

**长期生效：**

- Windows: 系统设置 → 环境变量 → 新建用户变量 `GEMINI_API_KEY`。
- macOS / Linux: 在 `~/.zshrc` 或 `~/.bashrc` 中加入一行：  
  `export GEMINI_API_KEY="你的key"`  
  然后执行 `source ~/.zshrc`（或 `source ~/.bashrc`）。

**示例（测试用）：**  
`export GEMINI_API_KEY="AIzaSyBhcUI"`  
（请替换为你自己的正式 key；正式环境请勿使用他人或示例 key。）

## 如何更改 Key

- **临时**：在当前终端重新执行一次 `export GEMINI_API_KEY="新key"`。
- **长期**：编辑上面「长期生效」里用的文件，把 `GEMINI_API_KEY` 的值改成新 key，保存后新开终端或重新 source 配置。

## 可选：使用不同模型

默认模型为 `gemini-3.1-flash-image-preview`（固定使用 Gemini 3.1 处理图片）。若需覆盖，可设置环境变量：

- `GEMINI_MODEL=gemini-3.1-flash-image-preview`（默认）  
- 或改为 API 支持的其他图像编辑模型 ID。

## 填充/扩图规则（延展而非重复）

- **Step 5 / Step 7 填黑**：空白区域（RGB(0,0,1) 或近黑）须用**延展画面**方式填满——即从现有场景边缘自然延续背景（天空、云、水、光效、氛围），使整图看起来是一张连续的宽幅图。
- **禁止重复/平铺**：不得复制、平铺或重复主体/人物或主场景到左右上下；空白处只允许延伸背景环境，不能出现第二个主体。

## 使用贞贞的AI工坊（t8star）时

1. 在 [贞贞的AI工坊](https://ai.t8star.cn/api-set) 注册并获取 API 令牌。
2. 设置环境变量：
   - `BANNER_IMAGE_BACKEND=t8star`
   - `T8STAR_API_KEY=你的令牌`（必填）
   - 可选：`T8STAR_BASE_URL=https://ai.t8star.cn`、`T8STAR_IMAGE_MODEL=gpt-image-1.5`
  - **502/503 重试**：遇服务端 502/503 时自动重试。可选 `T8STAR_MAX_RETRIES=3`（默认 3 次）、`T8STAR_RETRY_DELAY=10`（默认间隔 10 秒）。
3. 运行流程与 Gemini 相同（如 `prepare_background.py` 的扩图/去字/填充步骤会改为调用 t8star 的 `/v1/images/edits`）。

**示例（PowerShell）：**  
`$env:BANNER_IMAGE_BACKEND="t8star"; $env:T8STAR_API_KEY="你的令牌"`

**注意**：请勿将令牌提交到仓库或写在代码中，仅通过环境变量配置。

### t8star 返回图片 URL 时出现 403 的原因

若接口返回的是图片 **URL** 而非 **base64**，本脚本会再请求该 URL 下载图片。此时可能出现 **HTTP 403 Forbidden**，常见原因：

1. **鉴权方式不匹配**：图片实际存放在第三方存储（如 CDN/对象存储），该域名不认可 API 的 Bearer 令牌，或需要其它鉴权（如签名、Cookie）。
2. **来源/Referer 限制**：存储服务只允许浏览器或特定来源访问，拒绝脚本直接 GET。
3. **临时链接**：URL 有时效或一次性使用，稍后请求即失效。

**当前处理**：请求图编接口时已传 `response_format=b64_json`，尽量让 t8star 直接返回 base64，避免再请求 URL，从而规避 403。若接口仍只返回 URL，脚本会先带 `Authorization: Bearer <T8STAR_API_KEY>` 请求一次，若 403 再不带鉴权重试一次；若仍 403 则报错。可联系贞贞的AI工坊确认是否支持 `response_format=b64_json` 或提供可脚本拉取的图片链接方式。

## 未设置 Key 时的行为

- **扩图**：若未设置 `GEMINI_API_KEY`，`prepare_background.py --try-expand` 会跳过扩图，仅做裁切并提示。
- **去干扰（去文字/logo 等）**：使用 `--remove-text` 时，会调用 Gemini 去除图中的文字、水印、logo、色块、模糊层、按钮、UI 等干扰信息并自然补全背景。若未设置 key，不执行该步，直接使用原图继续裁切/扩图。
