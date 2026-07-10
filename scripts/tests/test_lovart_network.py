import sys, os, socket, ssl, urllib.request

print("=== 网络连通性测试 ===")

# 1. DNS 解析
try:
    ip = socket.gethostbyname("lgw.lovart.ai")
    print(f"DNS OK: lgw.lovart.ai -> {ip}")
except Exception as e:
    print(f"DNS 失败: {e}")

# 2. TCP 连接
try:
    s = socket.create_connection(("lgw.lovart.ai", 443), timeout=5)
    s.close()
    print("TCP 443 OK")
except Exception as e:
    print(f"TCP 443 失败: {e}")

# 3. HTTPS GET
try:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        "https://lgw.lovart.ai",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
        print(f"HTTPS OK: status={r.status}")
except Exception as e:
    print(f"HTTPS 失败: {type(e).__name__}: {e}")
