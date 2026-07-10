# 方案 A 完整流程（run_full_with_custom_prompt）

## Prompt 来源规则

| 情况 | 行为 |
|------|------|
| **用户上传了 prompt**（提供了 `--description` 或 `--description-file`） | **Qwen、prompt_library、banner-composer 在 prompt 上不做任何事**：不调用 Qwen，不读 prompt_library，直接将用户提供的 prompt（加前后缀后）传给即梦生图。 |
| **用户未上传 prompt**（只提供主标题 + 副标题） | 根据主副标题，用 prompt-engine（完整管线）/ prompt-optimizer-template（确定性模板）/ 本地 Ollama + prompt_library 的 few-shot 生成成图用 prompt，再传给即梦生图。 |

- **banner-composer**（Step 2）只负责用已生成的 `output/bg.png` 做多尺寸合成，不参与任何 prompt 逻辑。
- **prompt_library** 仅在上述「未上传 prompt、用主副标题生成」时被使用。

---

## 参考图 ( -i / --ref ) 与图生图 (i2i)

传入 `-i <图片路径>` 或 `--ref <图片路径>` 时，Step 1 走**图生图 (i2i)**，不再走文生图。

| 模型 | 是否支持 i2i | 说明 |
|------|----------------|------|
| **jimeng** | ✅ | 即梦火山 API `jimeng_volc_api.py --i2i` |
| **gemini** | ✅ | Gemini generateContent 多模态输入（参考图 + 文本）→ 出图 |
| **nano-banana** | ✅ | CLI `-r`/`--ref` 传入参考图 |
| **t8star** | ⚠️ 尝试 | 调用 `/v1/images/edits`；若贞贞未开放该接口则报错，提示改用 -M jimeng / -M gemini 或 nano-banana |

未传 `-i` 时，所有模型均为文生图 (t2i)。

---

## 一、不带参考图（纯文生图）

```
你输入：描述 + 主标题 + 副标题 + 分组（如 -g 商店日常）+ -M jimeng

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1：generate_from_description.py → 产出一张无字背景 output/bg.png    │
└─────────────────────────────────────────────────────────────────────────┘
  │
  │  1.1 描述 → 成图用 prompt（PROMPT_PREFIX + description + PROMPT_SUFFIX）
  │  1.2 文生图 (t2i)：即梦 jimeng_volc_api.py --t2i，输出尺寸 -W 3024 / -H 1296
  │  1.3 裁切到目标尺寸：crop_to_target.py（画面中心对齐安全区）→ output/bg.png
  │
  ↓
  output/bg.png

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2：run_all_presets.py 以 output/bg.png 为输入                      │
└─────────────────────────────────────────────────────────────────────────┘
  prepare_background 三路（default / wide / legend_rec_2590）→ compose 多尺寸
  ↓
  output/<分组_主标题_时间戳>/ 下各尺寸 banner
```

---

## 二、带参考图（即梦图生图 i2i）

```
你输入：描述 + 主标题 + 副标题 + 分组 + -M jimeng + --ref input/ref.png

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1：generate_from_description.py → 产出一张无字背景 output/bg.png   │
└─────────────────────────────────────────────────────────────────────────┘
  │
  │  1.1 描述 → 成图用 prompt（同上）
  │
  │  1.2 图生图 (i2i)（因传了 --ref 且 --model jimeng）
  │      · 即梦：jimeng_volc_api.py --i2i -p <prompt> -i <参考图路径> -o <临时文件> -W 3024 -H 1296
  │      · 请求体：binary_data_base64=[参考图 base64] + prompt + scale=0.5, seed=-1
  │      · 即梦按「参考图 + 描述」做图生图，返回一张图，输出尺寸由 -W 3024 / -H 1296 指定
  │      · 这里直接产出一张无字的背景图，命名为 bg，后续根据 bg 进行
  │
  │  1.3 裁切到目标尺寸：crop_to_target.py → output/bg.png
  │
  ↓
  output/bg.png（由「参考图 + 描述」生成的无字背景）

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2：与「不带参考图」完全相同                                         │
└─────────────────────────────────────────────────────────────────────────┘
  run_all_presets.py 以 output/bg.png 为输入 → prepare_background 三路 → compose 多尺寸
  ↓
  output/<分组_主标题_时间戳>/ 下各尺寸 banner
```

---

## 三、对比

| 项目     | 不带参考图   | 带参考图（--ref + -M jimeng）     |
|----------|--------------|-----------------------------------|
| Step 1.2 | 即梦 t2i     | 即梦 i2i（参考图 + 描述）         |
| 输出尺寸 | -W 3024 -H 1296 | -W 3024 -H 1296（同）         |
| Step 1 产出 | output/bg.png | output/bg.png（无字背景，命名为 bg） |
| Step 2   | 相同         | 相同                             |
