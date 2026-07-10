import fs from "fs";
import path from "path";
import { execFile } from "child_process";

const pluginDir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const opencodeDir = path.resolve(pluginDir, "..");
const projectRoot = path.resolve(opencodeDir, "..");

const configPath = path.join(opencodeDir, "image-saver.config.json");
let config = { inputDir: "input", python: "py", postScript: null };
try {
  if (fs.existsSync(configPath)) {
    Object.assign(config, JSON.parse(fs.readFileSync(configPath, "utf8")));
  }
} catch (e) {}

const inputDir = path.resolve(projectRoot, config.inputDir);
if (!fs.existsSync(inputDir)) {
  fs.mkdirSync(inputDir, { recursive: true });
}

function pluginLog(msg) {
  try {
    const logFile = path.join(inputDir, ".plugin_log.txt");
    fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${msg}\n`);
  } catch(e) {}
}

pluginLog(`=== Plugin initialized! ===`);
pluginLog(`pluginDir: ${pluginDir}`);
pluginLog(`opencodeDir: ${opencodeDir}`);
pluginLog(`projectRoot: ${projectRoot}`);
pluginLog(`inputDir: ${inputDir}`);

const seenIds = new Set();

function saveImagePart(part, messageId) {
  if (!part || typeof part !== "object") return null;

  try {
    const debugInfo = {
      type: part.type,
      keys: Object.keys(part),
      sourceType: part.source?.type,
      sourceMediaType: part.source?.mediaType || part.source?.media_type,
      hasSourceData: !!part.source?.data,
      sourceDataLen: part.source?.data?.length,
      hasSourceUrl: !!part.source?.url,
      sourceUrlPrefix: part.source?.url?.slice(0, 30),
      mimeType: part.mimeType || part.mime_type || part.mediaType,
    };
    pluginLog(`part debug: ${JSON.stringify(debugInfo)}`);
  } catch (e) {}

  const isBase64Image =
    part.type === "image" &&
    part.source?.type === "base64" &&
    String(part.source?.mediaType || part.source?.media_type || "").startsWith("image");

  const isDataUrlImage =
    (part.type === "image" || part.type === "image_url") &&
    (
      String(part.source?.url || "").startsWith("data:image") ||
      String(part.url || "").startsWith("data:image") ||
      String(part.image_url?.url || "").startsWith("data:image")
    );

  const isFilePart =
    part.type === "file" &&
    String(part.mime || part.mediaType || part.mimeType || part.mime_type || "").startsWith("image");

  if (!isBase64Image && !isDataUrlImage && !isFilePart) return null;

  pluginLog(`matched! isBase64=${isBase64Image} isDataUrl=${isDataUrlImage} isFile=${isFilePart}`);

  const partId = part.id || part.source?.id || null;
  if (partId && seenIds.has(partId)) {
    pluginLog(`skipping duplicate part.id=${partId}`);
    return null;
  }
  if (partId) {
    seenIds.add(partId);
  }

  let data;
  let mediaType = part.mime || part.source?.mediaType || part.source?.media_type || part.mediaType || part.mimeType || part.mime_type || "image/png";

  try {
    if (isBase64Image) {
      data = Buffer.from(part.source.data, "base64");
    } else if (String(part.source?.url || "").startsWith("data:")) {
      const raw = part.source.url;
      data = Buffer.from(raw.split(",")[1], "base64");
      mediaType = raw.split(";")[0].split(":")[1] || mediaType;
    } else if (String(part.url || "").startsWith("data:")) {
      const raw = part.url;
      data = Buffer.from(raw.split(",")[1], "base64");
      mediaType = raw.split(";")[0].split(":")[1] || mediaType;
    } else if (String(part.image_url?.url || "").startsWith("data:")) {
      const raw = part.image_url.url;
      data = Buffer.from(raw.split(",")[1], "base64");
      mediaType = raw.split(";")[0].split(":")[1] || mediaType;
    } else if (isFilePart && part.data) {
      data = Buffer.from(part.data, "base64");
    } else if (isFilePart && part.base64) {
      data = Buffer.from(part.base64, "base64");
    } else if (isFilePart && part.url && !part.url.startsWith("data:")) {
      const filePath = part.url.startsWith("file://") ? new URL(part.url).pathname.replace(/^\/([A-Za-z]:)/, "$1") : part.url;
      if (fs.existsSync(filePath)) {
        data = fs.readFileSync(filePath);
      } else {
        pluginLog(`file path not found: ${filePath}`);
        return null;
      }
    } else {
      return null;
    }
  } catch (e) {
    console.error(`[image-saver] decode error: ${e.message}`);
    return null;
  }

  const extMap = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/png": ".png",
  };
  const ext = extMap[mediaType] || ".png";
  const ts = Date.now();
  const filename = part.filename || part.name || `upload_${ts}${ext}`;
  const dest = path.join(inputDir, filename.endsWith(ext) ? filename : filename + ext);

  try {
    fs.writeFileSync(dest, data);
    fs.writeFileSync(path.join(inputDir, "upload_path.txt"), dest);
    console.error(`[image-saver] saved → ${dest}`);

    const uploadsDir = path.join(inputDir, "uploads");
    if (!fs.existsSync(uploadsDir)) fs.mkdirSync(uploadsDir, { recursive: true });
    const currentPath = path.join(uploadsDir, "current.png");
    fs.copyFileSync(dest, currentPath);
    const now = new Date();
    const tsStr = now.toISOString().replace(/[-:T]/g, "").slice(0, 15);
    fs.copyFileSync(dest, path.join(uploadsDir, `${tsStr}.png`));
    console.error(`[image-saver] also wrote → ${currentPath}`);

    const indexFile = path.join(inputDir, "uploads_index.json");
    let index = [];
    try {
      if (fs.existsSync(indexFile)) {
        index = JSON.parse(fs.readFileSync(indexFile, "utf8"));
      }
    } catch (e) {}
    index = index.filter((e) => e.path !== dest);
    index.unshift({ path: dest, savedAt: new Date().toISOString() });
    index = index.slice(0, 50);
    fs.writeFileSync(indexFile, JSON.stringify(index, null, 2));

    if (config.postScript) {
      const scriptPath = path.join(projectRoot, config.postScript);
      console.error(`[image-saver] running postScript: ${config.python} ${scriptPath} ${dest}`);
      execFile(config.python, [scriptPath, dest], { cwd: projectRoot }, (err, stdout, stderr) => {
        if (err) console.error(`[image-saver] postScript error: ${err.message}`);
        if (stdout) console.error(`[image-saver] postScript stdout: ${stdout}`);
        if (stderr) console.error(`[image-saver] postScript stderr: ${stderr}`);
      });
    }

    return dest;
  } catch (e) {
    console.error(`[image-saver] failed to save ${filename}: ${e.message}`);
    return null;
  }
}

function readLatestUploadPath() {
  const pointerFile = path.join(inputDir, "upload_path.txt");
  try {
    if (fs.existsSync(pointerFile)) {
      const p = fs.readFileSync(pointerFile, "utf8").trim();
      if (p && fs.existsSync(p)) return p;
    }
  } catch (e) {}
  return null;
}

export const ImageSaverPlugin = async () => {
  return {
    /** Intercept messages with all parts (including file type images) */
    "experimental.chat.messages.transform": async (input, output) => {
      const messages = output.messages || [];
      for (const msg of messages) {
        const msgId = msg.info?.id || null;
        const parts = msg.parts || [];

        // 1. 先保存所有图片 part
        for (const part of parts) {
          const saved = saveImagePart(part, msgId);
          if (saved) {
            pluginLog(`image saved via messages.transform: ${saved}`);
          }
        }

        // 2. 过滤掉 image_url / image 类型的 part，防止 DeepSeek 等不支持的模型报错
        const filtered = parts.filter((part) => {
          const t = part?.type;
          if (t === "image_url" || t === "image") {
            pluginLog(`filtered out image part type=${t}`);
            return false;
          }
          return true;
        });

        if (filtered.length !== parts.length) {
          msg.parts = filtered;
          pluginLog(`removed ${parts.length - filtered.length} image part(s) from message`);
        }
      }
    },

    /** Shell environment injection */
    "shell.env": async (input, output) => {
      const latest = readLatestUploadPath();
      if (latest) {
        output.env.LATEST_UPLOAD = latest;
        console.error(`[image-saver] injected LATEST_UPLOAD: ${latest}`);
      }
    },

    /** Session compaction context */
    "experimental.session.compacting": async (input, output) => {
      const latest = readLatestUploadPath();
      const indexFile = path.join(inputDir, "uploads_index.json");
      let index = [];
      try {
        if (fs.existsSync(indexFile)) {
          index = JSON.parse(fs.readFileSync(indexFile, "utf8"));
        }
      } catch (e) {}

      if (!latest && index.length === 0) return;

      const lines = ["## 已上传图片（image-saver 插件自动记录）"];
      if (latest) {
        lines.push(`- 最新上传：\`${latest}\``);
      }
      if (index.length > 1) {
        lines.push("- 历史上传（最近 5 张）：");
        index.slice(0, 5).forEach((e) => {
          lines.push(`  - \`${e.path}\`（${e.savedAt}）`);
        });
      }
      lines.push("- 脚本可通过环境变量 `LATEST_UPLOAD` 或读取 `input/upload_path.txt` 获取最新图片路径。");

      output.context = output.context || [];
      output.context.push(lines.join("\n"));
    },
  };
};
