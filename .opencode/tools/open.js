import { tool } from "@opencode-ai/plugin";
import fs from "fs";
import path from "path";
import { execFile } from "child_process";

const projectRoot = process.cwd();
const latestOutputFile = path.join(projectRoot, "input", "latest_output.txt");

function readLatestOutput() {
  try {
    if (fs.existsSync(latestOutputFile)) {
      const p = fs.readFileSync(latestOutputFile, "utf8").trim();
      if (p && fs.existsSync(p)) return p;
    }
  } catch (e) {}
  return null;
}

function openFile(filePath) {
  return new Promise((resolve, reject) => {
    // Windows: cmd /c start "" "<path>"
    execFile("cmd", ["/c", "start", "", filePath], { windowsHide: true }, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}

export default tool({
  description: "用系统默认程序打开图片文件。不传路径时自动打开最新生成的图片。",
  args: {
    path: tool.schema
      .string()
      .optional()
      .describe("图片文件路径（绝对路径或相对于项目根目录的相对路径）。不填则打开最新生成的图片。"),
  },
  async execute(args, context) {
    const worktree = context?.worktree || projectRoot;

    let targetPath = args.path || null;

    // 解析路径
    if (targetPath) {
      if (!path.isAbsolute(targetPath)) {
        targetPath = path.resolve(worktree, targetPath);
      }
    } else {
      // 读取最新输出图片
      targetPath = readLatestOutput();
      if (!targetPath) {
        // 尝试读取最新上传图片
        const uploadPath = path.join(worktree, "input", "upload_path.txt");
        try {
          if (fs.existsSync(uploadPath)) {
            const p = fs.readFileSync(uploadPath, "utf8").trim();
            if (p && fs.existsSync(p)) targetPath = p;
          }
        } catch (e) {}
      }
    }

    if (!targetPath) {
      return "没有找到可打开的图片。请先生成图片，或指定图片路径，例如：open_image output/xxx/banner.png";
    }

    if (!fs.existsSync(targetPath)) {
      return `文件不存在：${targetPath}`;
    }

    try {
      await openFile(targetPath);
      const relPath = path.relative(worktree, targetPath);
      return `已打开：${relPath}`;
    } catch (e) {
      return `打开失败：${e.message}\n路径：${targetPath}`;
    }
  },
});
