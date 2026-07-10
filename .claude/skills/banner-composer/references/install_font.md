# 微软雅黑安装说明（Windows / macOS）

本 Skill 仅支持微软雅黑，无备选字体。使用前请确保系统已安装以下字体文件：

- **主标题**: 微软雅黑 Bold — `msyhbd.ttf`
- **副标题**: 微软雅黑 Regular — `msyh.ttf`

---

## Windows

多数 Windows 系统已预装微软雅黑，路径一般为：

- `C:\Windows\Fonts\msyh.ttf`
- `C:\Windows\Fonts\msyhbd.ttf`

若未找到：

1. 从已安装微软雅黑的电脑复制上述两个文件，或从公司/项目提供的合规渠道获取。
2. 双击 `.ttf` 文件，在打开窗口中点击「安装」即可。

也可在 PowerShell 中运行本 Skill 提供的检测脚本确认是否已安装：

```powershell
python scripts/install_font.py
```

---

## macOS

macOS 默认不包含微软雅黑，需手动安装：

1. **获取字体文件**  
   从已安装的 Windows 电脑复制 `msyh.ttf` 与 `msyhbd.ttf`（路径见上），或从公司/项目提供的合规渠道获取。请勿从不明来源下载，以符合版权与安全要求。

2. **安装方式（任选其一）**  
   - **当前用户**: 将两个 `.ttf` 文件复制到 `~/Library/Fonts/`。  
   - **本机所有用户**: 将两个 `.ttf` 文件复制到 `/Library/Fonts/`（需管理员权限）。

3. **验证**  
   在终端运行：

   ```bash
   python3 scripts/install_font.py
   ```

   若输出“微软雅黑已就绪”，即可使用 `compose_banner.py`。

---

## 检测脚本

在 Skill 的 `scripts` 目录下运行：

```bash
python scripts/install_font.py
```

或（若已在该目录）：

```bash
python install_font.py
```

脚本会检测当前系统是否可用的微软雅黑（Regular / Bold），并给出已就绪或安装指引。不包含自动下载或分发字体文件。
