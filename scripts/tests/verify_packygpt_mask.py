#!/usr/bin/env python3
"""验证 PackyGPT /v1/images/edits 是否支持 mask 遮罩参数。

原理：发送一张带透明区域的图片 + mask，看 API 是否接受 mask 字段并正确处理。
使用 4x4 最小 PNG 避免浪费配额。
"""
import json, os, sys, base64, struct, zlib, io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from _env import load_env

load_env(("PACKYGPT_API_KEY",))
api_key = os.environ.get("PACKYGPT_API_KEY", "").strip()
if not api_key.startswith("sk-"):
    print("FAIL: PACKYGPT_API_KEY 未设置或不以 sk- 开头", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://www.packyapi.com"
HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def make_4x4_rgba_png(color=(255, 0, 0, 255)):
    """生成 4x4 RGBA PNG 字节（纯色不透明）。"""
    w, h = 4, 4
    raw = b""
    for y in range(h):
        raw += b"\x00"  # filter byte
        for x in range(w):
            raw += struct.pack("BBBB", *color)

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def make_4x4_rgba_png_full_mask(transparent_color=(0, 0, 0, 0)):
    """生成全透明 mask PNG。"""
    w, h = 4, 4
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += struct.pack("BBBB", *transparent_color)

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_mask():
    """测试 /v1/images/edits 是否支持 mask 参数。"""
    import urllib.request, urllib.error

    image_png = make_4x4_rgba_png(color=(255, 0, 0, 255))
    mask_png = make_4x4_rgba_png_full_mask()

    boundary = "----TestBoundary"
    body = b""
    for name, filename, data, mime in [
        ("image", "test.png", image_png, "image/png"),
        ("mask", "mask.png", mask_png, "image/png"),
    ]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += f"Content-Type: {mime}\r\n\r\n".encode()
        body += data + b"\r\n"

    for name, value in [
        ("model", "gpt-image-2"),
        ("prompt", "Keep the image exactly as-is. Make no changes."),
        ("size", "4x4"),
        ("quality", "high"),
        ("n", "1"),
        ("response_format", "b64_json"),
    ]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    url = f"{BASE_URL}/v1/images/edits"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", HEADERS["User-Agent"])

    print("[测试 1] 带 mask 参数调用 /v1/images/edits ...")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            print(f"  HTTP {r.status}")
            print(f"  响应: {json.dumps(resp, ensure_ascii=False)[:300]}")
            if resp.get("data"):
                print("  => [PASS] PackyGPT 支持 mask 参数")
                return True
            elif resp.get("error"):
                err_msg = str(resp.get("error"))
                print(f"  错误: {err_msg[:200]}")
                if "mask" in err_msg.lower() or "unsupported" in err_msg.lower():
                    print("  => [INFO] API 明确拒绝 mask，不支持 mask 遮罩")
                else:
                    print("  => [FAIL] 其他错误")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"  HTTP {e.code}")
        print(f"  响应: {body}")
        if e.code == 400 and "mask" in body.lower():
            print("  => [INFO] HTTP 400 提到 mask，可能不支持")
        else:
            print(f"  => [FAIL]")
        return False
    except Exception as e:
        print(f"  => [ERROR] {e}")
        return False


def test_without_mask():
    """对比：不带 mask 的调用是否能正常工作。"""
    import urllib.request, urllib.error

    image_png = make_4x4_rgba_png(color=(0, 0, 255, 255))

    boundary = "----TestBoundary2"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="image"; filename="test.png"\r\n'.encode()
    body += f"Content-Type: image/png\r\n\r\n".encode()
    body += image_png + b"\r\n"

    for name, value in [
        ("model", "gpt-image-2"),
        ("prompt", "Keep the image exactly as-is. Make no changes."),
        ("size", "4x4"),
        ("quality", "high"),
        ("n", "1"),
        ("response_format", "b64_json"),
    ]:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    url = f"{BASE_URL}/v1/images/edits"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", HEADERS["User-Agent"])

    print("\n[测试 2] 不带 mask 的基线对比调用 /v1/images/edits ...")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            print(f"  HTTP {r.status}")
            if resp.get("data"):
                print(f"  响应: {json.dumps(resp, ensure_ascii=False)[:300]}")
                print("  => [PASS] 不带 mask 的 edits 正常工作")
                return True
            elif resp.get("error"):
                err_msg = str(resp.get("error"))
                print(f"  错误: {err_msg[:200]}")
                if "size" in err_msg.lower() or "minimum" in err_msg.lower():
                    print("  => [INFO] 4x4 尺寸不满足最低要求（不影响 mask 结论）")
                    return True
                print("  => [FAIL]")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"  HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"  => [ERROR] {e}")
        return False


if __name__ == "__main__":
    test_without_mask()
    test_mask()
    print("\n结论：以上两个测试完成。对比两次结果即可判断 mask 支持情况。")
