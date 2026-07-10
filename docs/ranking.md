# Icon 扒取经验教训

> 项目：联想拯救者 PC 游戏榜单 icon 批量下载
> 日期：2025-07-03
> 结果：50/50 全部正方形 icon，0 错误匹配

---

## 1. 数据源选择：移动端 ≠ PC 端

| 尝试 | 结果 | 原因 |
|------|------|------|
| `3g.lenovomm.com` 搜索 | ❌ | 手机应用商店，搜 PC 游戏名返回「艾尔兴」「抖音」等不相关 APP |
| `lestore.lenovo.com` 搜索 | ⚠️ | PC 商店但搜索结果排序差，盲目取第一条大概率错 |
| `lestore.lenovo.com` 分类列表 | ✅ | 直接拉取全部 207 款 PC 游戏做本地索引，精准可控 |
| Steam CDN + appid 映射 | ✅ | 兜底方案，覆盖 lestore 缺失的游戏 |

**教训：同一域名下的列表 API 比搜索 API 可靠得多。** 搜索受排序算法影响，列表是原始数据不会跑偏。

---

## 2. API 加密不是拦路虎

遇到 `RequestDecryptException` 时第一反应可能是放弃，但实际上：

- JS 源码里硬编码了 `Key = IV = "65023EC4BA7420BB"`
- 算法：`AES-128-CBC + PKCS7`
- 复现只需要 5 行 Python

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

KEY = b"65023EC4BA7420BB"
def encrypt(body):
    raw = json.dumps(body).encode()
    cipher = AES.new(KEY, AES.MODE_CBC, iv=KEY)
    return base64.b64encode(cipher.encrypt(pad(raw, 16))).decode()
```

**教训：前端的加密对逆向来说几乎没有门槛，搜索 JS 里的 `encrypt`/`AES`/`crypto` 关键词即可。**

---

## 3. 匹配逻辑迭代

| 版本 | 逻辑 | 典型错误 |
|------|------|---------|
| v1 取第一条 | `docs[0]` | 搜「只狼」返回「QQ」，搜「杀戮尖塔」返回「抖音」 |
| v2 关键词子串 | `if kw in name` | 「城市：天际线」→「海绵城市计算辅助软件」 |
| v3 全部关键词命中 | `all(kw in name for kw in kws)` | ✅ 无跨游戏匹配错误 |

**教训：匹配必须要求全部关键词命中，宁可少几个也不能张冠李戴。**

实现细节：
- 去掉停用词（PC、模拟器、国际服、官方版等）
- 用全角半角通用的分割方式提取关键词
- `all()` 而非 `any()` 做判断

---

## 4. Steam 图片裁剪方向

游戏竖版封面的**视觉重心在上半部分**（标题 + 角色图案）：

```
┌──────────────┐    ┌──────────────┐
│ 🎮 游戏标题  │    │ 🎮 游戏标题  │  ← 顶部裁剪保留了
│ 🐵 角色图案  │    │ 🐵 角色图案  │
│              │    └──────────────┘
│   场景背景   │ ← 居中裁剪切掉了标题和角色
│              │
└──────────────┘
```

| 方式 | 代码 | 效果 |
|------|------|------|
| ❌ 居中裁剪 | `img.crop((0, (h-w)//2, w, (h-w)//2+w))` | 切掉黑神话悟空的标题 |
| ✅ 顶部裁剪 | `img.crop((0, 0, w, w))` | 保留完整标题和角色 |

**教训：裁剪前先搞清楚内容的视觉重心在哪。**

---

## 5. 验证机制不可或缺

如果没有 `verify.html`，以下错误无法发现：
- 城市：天际线 → 海绵城市计算辅助软件
- 黑神话悟空头部被裁切
- 杀戮尖塔 → QQ

```html
<!-- verify.html 结构 -->
每行 = [序号] [64x64 icon缩略图] [游戏中文名]
红色背景行 = 需人工检查
```

**教训：批量下载后必须生成可视化的逐行验证页面，肉眼确认。**

---

## 6. 最终三级来源架构

```
优先级 1: lestore 分类列表 API
  └─ POST /api/webstorecontents/class/class_apps_list (AES 加密)
  └─ 全量拉取 207 款 → 本地 JSON 缓存 → 毫秒级匹配
  └─ 匹配逻辑: all(kw in name for kw in keywords)

        ↓ 未命中

优先级 2: lestore 搜索 API
  └─ POST /api/webstorecontents/search/contents (AES 加密)
  └─ 同样的全关键词命中逻辑

        ↓ 未命中

优先级 3: Steam CDN
  └─ 预置 appid 映射表（手动精准维护 40+ 款）
  └─ library_600x900.jpg → 顶部裁剪方形
```

最终结果：**50/50 全部正方形，0 错误匹配。**
