import fs from "fs";
import path from "path";
import { execFile } from "child_process";

const pluginDir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const opencodeDir = path.resolve(pluginDir, "..");
const projectRoot = path.resolve(opencodeDir, "..");
const inputDir = path.resolve(projectRoot, "input");
const outputDir = path.resolve(projectRoot, "output");
const latestOutputFile = path.join(inputDir, "latest_output.txt");

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

function pluginLog(msg) {
  try {
    const logFile = path.join(inputDir, ".plugin_log.txt");
    fs.appendFileSync(logFile, `[${new Date().toISOString()}] [file-watcher] ${msg}\n`);
  } catch (e) {}
}

function isImageFile(filePath) {
  return IMAGE_EXTS.has(path.extname(filePath).toLowerCase());
}

function toRelPath(absPath) {
  try {
    return path.relative(projectRoot, absPath);
  } catch (e) {
    return absPath;
  }
}

/** 递归扫描目录，返回所有图片文件的 { path, mtime } */
function scanImages(dir) {
  const results = new Map();
  if (!fs.existsSync(dir)) return results;
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        for (const [k, v] of scanImages(full)) results.set(k, v);
      } else if (entry.isFile() && isImageFile(entry.name)) {
        try {
          const stat = fs.statSync(full);
          results.set(full, stat.mtimeMs);
        } catch (e) {}
      }
    }
  } catch (e) {}
  return results;
}

function showSystemToast(title, message) {
  // Windows 系统通知，写临时 ps1 文件再执行，避免引号嵌套问题
  const safeTitle = title.replace(/'/g, "''");
  const safeMsg = message.replace(/'/g, "''");
  const ps = [
    "Add-Type -AssemblyName System.Windows.Forms",
    "$notify = New-Object System.Windows.Forms.NotifyIcon",
    "$notify.Icon = [System.Drawing.SystemIcons]::Information",
    "$notify.Visible = $true",
    `$notify.ShowBalloonTip(4000, '${safeTitle}', '${safeMsg}', [System.Windows.Forms.ToolTipIcon]::Info)`,
    "Start-Sleep -Milliseconds 4500",
    "$notify.Dispose()",
  ].join("\r\n");

  const tmpFile = path.join(inputDir, "_toast_tmp.ps1");
  try {
    fs.writeFileSync(tmpFile, ps, "utf8");
    execFile("powershell", ["-NoProfile", "-NonInteractive", "-File", tmpFile], { windowsHide: true }, (err) => {
      if (err) pluginLog(`systemToast error: ${err.message}`);
      try { fs.unlinkSync(tmpFile); } catch (e) {}
    });
  } catch (e) {
    pluginLog(`showSystemToast write error: ${e.message}`);
  }
}

function writeLatestOutput(filePath) {
  try {
    if (!fs.existsSync(inputDir)) fs.mkdirSync(inputDir, { recursive: true });
    fs.writeFileSync(latestOutputFile, filePath, "utf8");
  } catch (e) {
    pluginLog(`writeLatestOutput error: ${e.message}`);
  }
}

export const FileWatcherPlugin = async ({ client }) => {
  pluginLog("=== FileWatcherPlugin initialized ===");

  // 初始快照
  let snapshot = new Map([...scanImages(outputDir), ...scanImages(inputDir)]);
  pluginLog(`initial snapshot: ${snapshot.size} images`);

  async function checkNewFiles() {
    const current = new Map([...scanImages(outputDir), ...scanImages(inputDir)]);
    const newFiles = [];

    for (const [filePath, mtime] of current) {
      const prev = snapshot.get(filePath);
      if (prev === undefined || mtime > prev) {
        newFiles.push(filePath);
      }
    }

    snapshot = current;

    for (const filePath of newFiles) {
      const relPath = toRelPath(filePath);
      const isOutput = filePath.startsWith(outputDir);
      const label = isOutput ? "新图片" : "上传图片";

      pluginLog(`${label}: ${relPath}`);

      if (isOutput) {
        writeLatestOutput(filePath);
      }

      // 系统通知（兼容 IDE 插件模式）— 已禁用
      // showSystemToast("OpenCode", `${label}：${relPath}`);

      // 同时尝试 TUI toast（纯终端模式下生效）
      try {
        pluginLog(`calling showToast: client.tui=${typeof client?.tui}, showToast=${typeof client?.tui?.showToast}`);
        await client.tui.showToast({
          body: { message: `${label}：${relPath}`, variant: "success" },
        });
        pluginLog(`showToast OK`);
      } catch (e) {
        pluginLog(`showToast error: ${e.message}`);
      }
    }

    return newFiles.length;
  }

  return {
    /** Bash 工具执行完后扫描新文件 */
    "tool.execute.after": async (input) => {
      try {
        const toolName = input?.tool || input?.name || "";
        pluginLog(`tool.execute.after fired: tool=${toolName}`);
        if (toolName !== "bash") return;
        const found = await checkNewFiles();
        pluginLog(`checkNewFiles result: ${found} new files`);
      } catch (e) {
        pluginLog(`tool.execute.after error: ${e.message}`);
      }
    },

    /** session 空闲时也扫一次（兜底） */
    "session.idle": async () => {
      try {
        await checkNewFiles();
      } catch (e) {
        pluginLog(`session.idle error: ${e.message}`);
      }
    },
  };
};
