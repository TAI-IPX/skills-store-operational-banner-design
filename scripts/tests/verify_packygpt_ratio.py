#!/usr/bin/env python3
"""验证 PackyGPT gpt-image-2 的实际比例限制。

测试多种比例（2:1 到 8:1），找出 API 实际接受的边界。
使用最小像素合法值 + 递增比例进行探测。
"""
import json, os, sys, math
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


def round_up_16(n):
    return ((n + 15) // 16) * 16


def test_ratio(size_w, size_h, label):
    """测试指定尺寸是否被 API 接受。"""
    import urllib.request, urllib.error

    body = json.dumps({
        "model": "gpt-image-2",
        "prompt": "A single white pixel",
        "size": f"{size_w}x{size_h}",
        "quality": "high",
        "n": 1,
        "response_format": "url",
    }).encode("utf-8")

    url = f"{BASE_URL}/v1/images/generations"
    req = urllib.request.Request(url, data=body, method="POST", headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            if resp.get("data"):
                result = "PASS"
                detail = "成功返回图片"
            elif resp.get("error"):
                result = "REJECT"
                detail = resp["error"].get("message", str(resp["error"]))[:150]
            else:
                result = "UNKNOWN"
                detail = str(resp)[:100]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        try:
            err = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            err = body
        result = "REJECT"
        detail = f"HTTP {e.code}: {err[:150]}"
    except Exception as e:
        result = "ERROR"
        detail = str(e)[:150]

    h_ratio = max(size_w, size_h) / min(size_w, size_h)
    print(f"  {result:8s} | {size_w:>6d}x{size_h:<6d} | {h_ratio:.1f}:1     | {label} | {detail}")
    return result == "PASS"


def find_min_pixel_target(w, h):
    """确保尺寸满足 ≥ 655360 像素且 16 倍数。"""
    px = w * h
    min_px = 655360
    if px < min_px:
        scale = math.sqrt(min_px / px)
        return round_up_16(int(w * scale)), round_up_16(int(h * scale))
    return round_up_16(w), round_up_16(h)


if __name__ == "__main__":
    print("PackyGPT gpt-image-2 比例限制探测")
    print("=" * 75)
    print(f"{'结果':8s} | {'尺寸':15s} | {'比例':8s} | {'说明':15s} | 详情")
    print("-" * 75)

    tests = [
        (1024, 512, "2:1 基准"),
        (1536, 512, "3:1 边界"),
        (2048, 512, "4:1 超限"),
        (2560, 512, "5:1 超限"),
        (3072, 512, "6:1 超限"),
        (4096, 512, "8:1 极端"),
        (1536, 640, "2.4:1 常用"),
        (1792, 1024, "1.75:1 接近正方形"),
    ]

    results = []
    for w, h, label in tests:
        tw, th = find_min_pixel_target(w, h)
        ok = test_ratio(tw, th, label)
        results.append((w, h, tw, th, label, ok))

    print("\n" + "=" * 75)
    print("汇总:")
    print("-" * 75)
    pass_ratios = []
    fail_ratios = []
    for ow, oh, tw, th, label, ok in results:
        ratio = max(tw, th) / min(tw, th)
        status = "PASS" if ok else "FAIL"
        print(f"  {status:5s} | {label:25s} | 原始 {ow}x{oh} | 实际 {tw}x{th} | 比例 {ratio:.1f}:1")
        if ok:
            pass_ratios.append(ratio)
        else:
            fail_ratios.append(ratio)

    if pass_ratios:
        print(f"\n最大通过比例: {max(pass_ratios):.1f}:1")
    if fail_ratios:
        print(f"最小失败比例: {min(fail_ratios):.1f}:1  (如果存在)")
    if not fail_ratios:
        print("所有测试比例均通过，无上限限制！")
