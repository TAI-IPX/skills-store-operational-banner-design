# 战报字体（本地指定）

战报合成**禁止使用系统默认回退字体**；必须从本目录加载 `.ttf` / `.otf` / `.ttc`。

## 放置方式

将设计稿同款字体文件放入本目录，文件名与 `docs/战报规范.md` 中「字体映射表」一致。

推荐命名（可按实际字体改名，但须同步更新规范表）：

| 用途 | 建议文件名 | 字重 |
|------|------------|------|
| 主标题 / 栏目标题 | `display-bold.otf` | Bold / Heavy |
| 副标题 / 强调句 | `display-medium.otf` | Medium |
| 正文 / 评论 / 说明 | `body-regular.otf` | Regular |
| 数据数字（曝光、下载等） | `data-bold.otf` | Bold（可与 display-bold 相同） |

## 环境变量（可选，供后续脚本读取）

```bash
BATTLE_REPORT_FONT_DISPLAY_BOLD=scripts/assets/fonts/battle-report/display-bold.otf
BATTLE_REPORT_FONT_DISPLAY_MEDIUM=scripts/assets/fonts/battle-report/display-medium.otf
BATTLE_REPORT_FONT_BODY=scripts/assets/fonts/battle-report/body-regular.otf
BATTLE_REPORT_FONT_DATA=scripts/assets/fonts/battle-report/data-bold.otf
```

路径可为相对项目根或绝对路径。

## 检测

字体就位后，可在项目根执行（待实现）：

```bash
python3 scripts/check_battle_report_fonts.py
```

```bash
python3 scripts/check_battle_report_fonts.py
```

战报合成（`run_battle_report.py`）启动时会打印 `[战报/字体]` 日志；**全部**头图/数据/栏头/评论叠字经 `load_font()` 加载，不使用系统默认字体。
