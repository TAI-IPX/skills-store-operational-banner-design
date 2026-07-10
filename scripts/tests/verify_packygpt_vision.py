#!/usr/bin/env python3
"""验证 PackyGPT /v1/chat/completions 是否支持 Vision 多模态图像识别。

测试：发送一张 1x1 白色 PNG（base64 内联）+ 文本，看 API 是否返回文本分析。
"""
import json, os, sys, base64, struct, zlib
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
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def make_1x1_white_png_b64():
    """生成 1x1 白色 PNG 并返回 base64 字符串。"""
    w, h = 1, 1
    raw = b"\x00" + struct.pack("BBBB", 255, 255, 255, 255)  # 白色 RGBA
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def test_vision_chat():
    """通过 /v1/chat/completions 测试 Vision 能力。"""
    import urllib.request, urllib.error

    b64 = make_1x1_white_png_b64()
    body = {
        "model": "gpt-image-2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe the color and content of this image in one word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
                ],
            }
        ],
        "max_tokens": 50,
    }

    url = f"{BASE_URL}/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=HEADERS)

    print("[测试] PackyGPT Vision: /v1/chat/completions 多模态 ...")
    print(f"  请求体 model={body['model']}, 图片 1x1 white PNG")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            print(f"  HTTP {r.status}")
            if resp.get("choices"):
                content = resp["choices"][0].get("message", {}).get("content", "")
                print(f"  回复: {content[:100]}")
                print("  => [PASS] PackyGPT 支持 Vision（chat/completions 多模态）")
                return True
            elif resp.get("error"):
                err = resp.get("error")
                err_msg = err.get("message", str(err))
                print(f"  错误: {err_msg[:200]}")
                if "vision" in err_msg.lower() or "image_url" in err_msg.lower() or "modal" in err_msg.lower():
                    print("  => [INFO] Vision 不支持")
                elif "model" in err_msg.lower():
                    print("  => [INFO] gpt-image-2 不支持 chat/completions，尝试 gpt-4o 兼容模型...")
                else:
                    print("  => [FAIL]")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"  HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"  => [ERROR] {e}")
        return False


def test_chat_fallback():
    """回退测试：不传图片的纯文本 chat。"""
    import urllib.request, urllib.error

    body = {
        "model": "gpt-image-2",
        "messages": [
            {"role": "user", "content": "Reply with the single word: OK"}
        ],
        "max_tokens": 10,
    }

    url = f"{BASE_URL}/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=HEADERS)

    print("\n[基线] /v1/chat/completions 纯文本（确认端点可达）...")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            print(f"  HTTP {r.status}")
            if resp.get("choices"):
                content = resp["choices"][0].get("message", {}).get("content", "")
                print(f"  回复: {content[:50]}")
                print("  => [PASS] /v1/chat/completions 纯文本正常")
                return True
            elif resp.get("error"):
                print(f"  错误: {resp['error'].get('message', str(resp['error']))[:200]}")
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        print(f"  HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"  => [ERROR] {e}")
        return False


if __name__ == "__main__":
    test_chat_fallback()
    test_vision_chat()
