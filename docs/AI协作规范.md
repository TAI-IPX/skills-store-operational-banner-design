# Banner 生成：AI 协作规范

本文档定义了使用 AI 助手（Claude Code / Cursor）进行 Banner 生成时的规范和最佳实践。

---

## 一、Prompt 生成规范

### 1.1 必读文档

生成或优化文生图描述时，**必须**参考以下文档：

- **用户偏好**：`.claude/skills/banner-background-from-description/prompt_library/user_preferences.md`
  - 常用风格词、描述结构、禁忌事项
- **Prompt 库**：`.claude/skills/banner-background-from-description/prompt_library/`
  - 预设模板（1.json ~ 9.json）
  - 索引文件：`index.md`
- **参考图库**：`.claude/skills/banner-background-from-description/ref_image_library/`
  - 参考图片：`images/`
  - 元数据：`refs.json`
  - 索引：`index.md`

### 1.2 运营插画要求

写运营/活动类插画描述时，要求：

**首选风格：Q 版 3D 卡通**
- 圆润充气造型，Q 版大头比例人物
- 充气软胶/黏土质感，无写实纹理无毛孔细节
- 柔和环形布光，边缘微弱补光轮廓
- 糖果色系高饱和：暖橙/深蓝/明黄/奶油白
- 辅助元素同样充气圆润材质（书本、灯泡、地球仪等）
- 微笑表情，校服风格几何化

**画面特征：**
- ✅ 有张力、有趣、能吸引人
- ✅ 色彩：高饱和、有对比和光效
- ✅ 构图：有动势、透视或趣味化主体（跃起、握拳、奔跑）
- ✅ 留白：一侧留白便于后期压字
- ✅ 格式：横版、画面无标题文字

**默认构图**：叙事留白式（构图 #5），主体居中偏右，左侧大面积留白

**禁忌：**
- ❌ 避免呆板对称
- ❌ 不要字面化翻译文案
- ❌ 不要 C4D 写实渲染、照片级画质

### 1.3 语义优先原则

**核心理念**：根据文案的**具体语义**来构思画面，不要扣字面。

**错误示例：**
- 「电量满格」→ ❌ 不要画电池
- 「充能」→ ❌ 不要画充电图标
- 「开学回血」→ ❌ 不要画血袋

**正确做法：**
1. 理解文案的情绪、氛围、概念
2. 用色彩、构图、元素组合表达那种感受
3. 例如「充能」→ 表达活力、饱满、春日感

### 1.4 文字处理规则

**标题文字（禁止）：**
- ❌ 画面中不出现作为标题/标语的大字
- ❌ 不出现活动名、主副标题、Slogan
- 原因：便于后期压字

**物体文字（允许）：**
- ✅ 物体自带的、作为细节的文字可以出现
- ✅ 例如：票面信息、书本内页、包装标签、二维码等

**描述用词：**
- ✅ 使用「画面无标题文字」
- ❌ 不要笼统说「无文字」

---

## 二、Prompt 库使用指南

### 2.1 库结构

```
.claude/skills/banner-background-from-description/prompt_library/
├── index.md              # 索引（ID、标题、标签）
├── user_preferences.md   # 用户偏好（必读）
├── 1.json ~ 9.json       # 预设 prompt 模板
└── scripts/
    ├── generate_prompt_library_index.py  # 生成索引
    └── upload_prompt_to_library.py       # 上传新 prompt
```

### 2.2 预设模板列表

| ID | 主题/风格 | 关键标签 | 适用场景 |
|----|----------|---------|---------|
| 3 | 运动篮球 | 3D, C4D, 橙蓝渐变 | 体育活动 |
| 4 | 花城深圳 | 五一, 地标, 火车票, 鱼眼 | 旅游节日 |
| 5 | 春日书店 | 喜马拉雅, 中心构图, 小岛 | 阅读活动 |
| 6 | 竹筒建筑 | Kim Jung Gi, 极细钢笔, 中式 | 传统文化 |
| 7 | 油画质感 | 光斑, bokeh, 蓝色, 梦幻 | 文艺风格 |
| 8 | 春日充能 | 3D, 卡通, 横版, 无文字 | 春季活动 |
| 9 | 开放平台 | 科技感, 蓝色渐变, 留白 | 技术产品 |

### 2.3 使用方式

**按 ID 引用：**
```
用户：用第 8 条生成
AI：读取 prompt_library/8.json（春日充能）
```

**按标签查找：**
```
用户：按春日那种风格
AI：查找 tags 包含"春日"的 prompt（5, 8）
```

**按主题引用：**
```
用户：用开放平台的风格
AI：读取 prompt_library/9.json
```

---

## 三、参考图库使用指南

### 3.1 库结构

```
.claude/skills/banner-background-from-description/ref_image_library/
├── images/          # 参考图片文件
├── refs.json        # 图片元数据
├── index.md         # 图片索引
└── scripts/
    ├── list_ref_images.py      # 查询参考图
    └── upload_ref_image.py     # 上传新参考图
```

### 3.2 查询参考图

```bash
# 按标签查询
python .claude/skills/banner-background-from-description/scripts/list_ref_images.py --tags 春日,3D

# 查看所有参考图
python .claude/skills/banner-background-from-description/scripts/list_ref_images.py
```

### 3.3 使用参考图生成

```bash
# 生成时指定参考图
python .claude/skills/banner-background-from-description/scripts/generate_from_description.py \
  -i ref_image_library/images/xxx.jpg \
  --prompt "你的描述"
```

---

## 四、优质描述结构

### 4.1 标准结构（4 步）

1. **风格/类型**：如超现实、意识流、平面插画、3D 卡通、科技感等
2. **色彩与氛围**：高饱和、粉绿主色、渐变、柔和光影等
3. **主体与场景、构图**：纵深、前后景、中心构图、留白等
4. **格式说明**：高清、横版、画面无标题文字等

### 4.2 运营插画结构（5 步）

1. **运营插画风格 + 横版**：点明「运营插画风格，横版，有张力、有趣、吸睛」
2. **语义重点**：用一两句写主副标题的语义重点（不字面翻译）
3. **风格与色彩**：3D 卡通或扁平+轻 3D，色彩高饱和，主色与渐变
4. **主体与构图**：按主副标题提炼视觉线索，有层次和主次，一侧留白
5. **整体观感**：一句总结 + 「画面无标题文字，横版」

### 4.3 常用风格词

**风格：**
- 3D、卡通、中心构图、粉彩、治愈、小红书风格、科技感、现代简洁

**主题：**
- 春日、书店、开放平台、Kim Jung Gi、极细钢笔、竹筒/中式、留白

**色彩/氛围：**
- 蓝色渐变、粉绿、鹅黄、薄荷绿、柔和光影、光斑

---

## 五、描述与成图的关系

### 5.1 核心原则

库中的描述用于传达**整体语义**（主题、风格、氛围、大致构图与元素）。

**目标：**
- ✅ 语义一致
- ✅ 观感对味

**不追求：**
- ❌ 与文案逐字逐句完全一致
- ❌ 每个词都对应一个视觉元素

### 5.2 评判标准

成图质量以「语义一致、观感对味」为准，不追求与文案逐字一致。

---

## 六、禁忌事项

### 6.1 内容禁忌

- ❌ 避免与品牌无关的强商业元素
- ❌ 不要字面化翻译文案
- ❌ 不要画标题/标语/活动名的大字

### 6.2 风格禁忌

- ❌ 避免呆板对称
- ❌ 避免过于复杂或杂乱
- ❌ 避免暗淡无生气

---

## 七、工作流程示例

### 7.1 用户提供主副标题

```
用户：主标题"电量满格" 副标题"尽情享受"

AI 工作流程：
1. 读取 user_preferences.md
2. 理解语义：活力、饱满、尽兴
3. 避免字面化：不画电池
4. 构思画面：春日感、充能感、活力元素
5. 生成描述：运营插画风格，横版...
```

### 7.2 用户指定预设

```
用户：用第 8 条生成

AI 工作流程：
1. 读取 prompt_library/8.json
2. 获取 prompt 内容
3. 直接使用或微调
4. 调用生成脚本
```

### 7.3 用户指定风格

```
用户：按春日那种风格

AI 工作流程：
1. 查找 tags 包含"春日"的 prompt
2. 找到 5.json（春日书店）和 8.json（春日充能）
3. 根据上下文选择合适的
4. 或询问用户选择哪个
```

---

## 八、维护指南

### 8.1 添加新 Prompt

```bash
# 1. 创建 JSON 文件
cat > prompt_library/10.json << 'EOF'
{
  "id": "10",
  "prompt": "你的描述...",
  "source": "用户上传",
  "main_title": "主标题",
  "subtitle": "副标题",
  "tags": ["标签1", "标签2"],
  "notes": "备注",
  "created_at": "2026-04-01T00:00:00"
}
EOF

# 2. 更新索引
python .claude/skills/banner-background-from-description/scripts/generate_prompt_library_index.py
```

### 8.2 添加参考图

```bash
python .claude/skills/banner-background-from-description/scripts/upload_ref_image.py \
  --image path/to/image.jpg \
  --tags "春日,3D,卡通" \
  --description "描述"
```

### 8.3 修改用户偏好

直接编辑 `user_preferences.md`，AI 会自动读取最新内容。

---

## 九、代码修改规范

改代码时：
- ✅ **只改任务相关文件**
- ✅ 风格与现有脚本保持一致
- ✅ 遵循项目的代码规范
- ❌ 不要过度重构
- ❌ 不要改变现有接口

---

## 十、快速参考

### 10.1 关键文件路径

```
.claude/skills/banner-background-from-description/
├── prompt_library/
│   ├── user_preferences.md    # 必读：用户偏好
│   ├── index.md               # Prompt 索引
│   └── 1.json ~ 9.json        # 预设模板
└── ref_image_library/
    ├── images/                # 参考图片
    ├── refs.json              # 图片元数据
    └── index.md               # 图片索引
```

### 10.2 常用命令

```bash
# 查询参考图
python .claude/skills/banner-background-from-description/scripts/list_ref_images.py --tags 春日

# 生成背景（使用预设）
python .claude/skills/banner-background-from-description/scripts/generate_from_description.py \
  --prompt-library-id 8

# 生成背景（自定义描述）
python .claude/skills/banner-background-from-description/scripts/generate_from_description.py \
  --prompt "你的描述"

# 生成背景（使用参考图）
python .claude/skills/banner-background-from-description/scripts/generate_from_description.py \
  -i ref_image_library/images/xxx.jpg \
  --prompt "你的描述"
```

---

## 附录：Prompt 库 JSON 格式

```json
{
  "id": "8",
  "prompt": "春日充能主题横版背景，清新明亮...",
  "source": "用户上传",
  "main_title": "主标题（可选）",
  "subtitle": "副标题（可选）",
  "tags": ["春日", "充能", "3D", "卡通"],
  "notes": "备注信息",
  "created_at": "2026-03-16T00:00:00"
}
```

**必填字段：**
- `id`：唯一标识符
- `prompt`：完整的文生图描述
- `source`：来源（如"用户上传"）
- `tags`：标签数组
- `created_at`：创建时间（ISO 8601 格式）

**可选字段：**
- `main_title`：主标题
- `subtitle`：副标题
- `notes`：备注信息
