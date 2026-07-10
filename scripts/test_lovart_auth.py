#!/usr/bin/env python3
"""测试 lovart AK/SK 是否有效：先测 chat（不上传），再测 upload_file。"""
import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 加载 .env
env_file = Path(__file__).resolve().parent.parent / ".env"
for line in env_file.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"\'')
        if k in ("LOVART_ACCESS_KEY","LOVART_SECRET_KEY","LOVART_BASE_URL") and v:
            os.environ[k] = v

from agent_skill import AgentSkill, AgentSkillError

ak = os.environ.get("LOVART_ACCESS_KEY","")
sk = os.environ.get("LOVART_SECRET_KEY","")
base = os.environ.get("LOVART_BASE_URL","https://lgw.lovart.ai")
print(f"AK: {ak[:12]}...  SK: {sk[:12]}...  BASE: {base}")

client = AgentSkill(base_url=base, access_key=ak, secret_key=sk, timeout=30)

# 1. 测试 list_projects（轻量接口）
print("\n[test] list_projects ...")
try:
    r = client._request("GET", "/v1/openapi/project/list", params={"page": 1, "page_size": 1})
    print(f"  OK: {r}")
except AgentSkillError as e:
    print(f"  FAIL ({e.code}): {e.message}")

# 2. 测试 upload_file（用一个小图）
print("\n[test] upload_file ...")
test_img = Path("input/pirate_ship_ref.png")
if test_img.is_file():
    try:
        url = client.upload_file(str(test_img))
        print(f"  OK: {url[:80]}")
    except AgentSkillError as e:
        print(f"  FAIL ({e.code}): {e.message}")
else:
    print("  SKIP: test image not found")
