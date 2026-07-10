import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 加载 .env
env_file = ROOT / ".env"
with open(env_file, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            k = k.strip()
            if k in ('LOVART_ACCESS_KEY', 'LOVART_SECRET_KEY') and v.strip():
                os.environ[k] = v.strip().strip('"\'')

import lovart_helper as lovart

print("=== 1. 客户端创建 ===")
client = lovart.get_client()
print(f"base_url: {client.base_url}")
print(f"access_key: {client.access_key[:8]}...")

print("\n=== 2. query_mode (只读，不消耗积分) ===")
try:
    result = client.query_mode()
    print(f"query_mode OK: {result}")
except Exception as e:
    print(f"query_mode 失败: {e}")

print("\n=== 3. get_project_id ===")
try:
    pid = lovart.get_project_id(client)
    print(f"project_id: {pid}")
except Exception as e:
    print(f"get_project_id 失败: {e}")

print("\n=== 验证完成 ===")
