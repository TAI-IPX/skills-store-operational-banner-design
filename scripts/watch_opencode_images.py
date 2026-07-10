#!/usr/bin/env python3
"""
事件驱动监控 OpenCode 数据库，新图片自动保存到 input/ 目录。
使用 watchdog 监听数据库文件变化，变化时批量保存所有新增图片。

用法:
    python scripts/watch_opencode_images.py
    按 Ctrl+C 停止。
"""

import base64
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("[error] 需要安装 watchdog: pip install watchdog")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
DB_PATH = Path(os.environ.get("USERPROFILE", "")) / ".local" / "share" / "opencode" / "opencode.db"
STATE_FILE = INPUT_DIR / ".last_image_hash.txt"
LOG_FILE = INPUT_DIR / ".watch_log.txt"
MAX_KEEP = 20
MAX_SAVE_PER_TRIGGER = 10  # 每次最多保存 10 张
TIME_LIMIT_MINUTES = 5     # 只读取最近 5 分钟的图片


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.write_text(LOG_FILE.read_text() + line + "\n")
    except Exception:
        pass


def get_history():
    """读取历史记录，返回 (hash列表, 记录列表)"""
    index_file = INPUT_DIR / "uploads_index.json"
    if not index_file.exists():
        return [], []
    try:
        data = json.loads(index_file.read_text("utf-8"))
        hashes = [item.get("hash", "") for item in data if item.get("hash")]
        return hashes, data
    except Exception:
        return [], []


def save_history(records):
    """保存历史记录，保持最多 MAX_KEEP 条"""
    index_file = INPUT_DIR / "uploads_index.json"
    records = records[:MAX_KEEP]
    index_file.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def extract_all_images():
    """从数据库提取最近图片，返回列表 [(fmt, img_bytes, hash), ...]"""
    if not DB_PATH.is_file():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=1)
        # 只读取最近的 20 条图片记录
        rows = conn.execute(
            "SELECT message_id, data FROM part WHERE data LIKE '%\"type\":\"file\"%' AND data LIKE '%image/%' ORDER BY time_created DESC LIMIT 20"
        ).fetchall()
        conn.close()
    except Exception:
        return []

    results = []
    for message_id, data_str in rows:
        try:
            d = json.loads(data_str)
            if d.get("type") != "file":
                continue
            mime = d.get("mime", "")
            if not mime.startswith("image/"):
                continue
            url = d.get("url", "")
            fmt = mime.split("/")[1] if "/" in mime else "png"
            img_bytes = None

            if url.startswith("data:"):
                m = re.match(r"data:image/([a-z]+);base64,(.+)", url, re.DOTALL)
                if m:
                    fmt = m.group(1)
                    img_bytes = base64.b64decode(m.group(2) + "==")
            elif url:
                img_bytes = base64.b64decode(url + "==")

            if img_bytes:
                img_hash = hash(img_bytes[:256])
                results.append((fmt, img_bytes, img_hash))
        except Exception:
            pass
    return results


def save_images_batch(images):
    """批量保存图片，返回保存数量"""
    if not images:
        return 0

    saved_count = 0
    history_hashes, history_records = get_history()

    # 倒序保存（最早的上传在前），同时去重（批次内和历史都检查）
    batch_hashes = set()  # 批次内去重
    for fmt, img_bytes, img_hash in reversed(images):
        if saved_count >= MAX_SAVE_PER_TRIGGER:
            break
        img_hash_str = str(img_hash)
        if img_hash_str in history_hashes or img_hash_str in batch_hashes:
            continue
        batch_hashes.add(img_hash_str)

        ext = "jpg" if fmt == "jpeg" else fmt
        fname = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{saved_count}.{ext}"
        out_path = INPUT_DIR / fname
        with open(out_path, "wb") as f:
            f.write(img_bytes)

        record = {
            "path": str(out_path),
            "savedAt": datetime.now().isoformat(),
            "hash": img_hash_str
        }
        history_records.insert(0, record)
        saved_count += 1

        # 同时更新 upload_current.png（最新上传的那张）
        current_path = INPUT_DIR / "upload_current.png"
        import shutil
        shutil.copy(out_path, current_path)

    if saved_count > 0:
        save_history(history_records)

    return saved_count


class DBChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_mtime = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith("opencode.db"):
            return
        self.process_change()

    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith("opencode.db"):
            return
        self.process_change()

    def process_change(self):
        try:
            all_images = extract_all_images()
            if not all_images:
                return

            history_hashes, _ = get_history()
            new_images = [(fmt, img_bytes, img_hash) for fmt, img_bytes, img_hash in all_images
                          if str(img_hash) not in history_hashes]

            if new_images:
                saved_count = save_images_batch(new_images)
                log(f"新增 {saved_count} 张图片已保存")
        except Exception as e:
            log(f"处理错误: {e}")


def main():
    print(f"[watch] 监控 OpenCode 图片（事件驱动，批量保存）")
    print(f"[watch] 按 Ctrl+C 停止")
    print(f"[watch] 输入目录: {INPUT_DIR}")
    print(f"[watch] 最多保留: {MAX_KEEP} 张")

    LOG_FILE.write_text("")

    if not DB_PATH.exists():
        log(f"[error] 数据库不存在: {DB_PATH}")
        sys.exit(1)

    handler = DBChangeHandler()
    observer = Observer()
    observer.schedule(handler, str(DB_PATH.parent), recursive=False)
    observer.start()

    log("已启动监控...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("已停止")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()