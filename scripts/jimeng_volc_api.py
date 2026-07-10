#!/usr/bin/env python3
"""
即梦 4.0 火山引擎直连 API：文生图（jimeng_t2i_v40）与图生图。
使用 Signature V4 签名，凭证从环境变量或项目根 .env 读取：VOLC_ACCESS_KEY_ID、VOLC_SECRET_ACCESS_KEY。
参考：火山引擎 visual.volcengineapi.com CVProcess 接口。
"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

# 从项目根 .env 加载凭证（若存在）
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            if _k in ("VOLC_ACCESS_KEY_ID", "VOLC_SECRET_ACCESS_KEY") and _v.strip():
                if _k not in os.environ:
                    os.environ[_k] = _v.strip().strip('"\'')

try:
    import requests
except ImportError:
    print("请安装 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

METHOD = "POST"
HOST = "visual.volcengineapi.com"
REGION = "cn-north-1"
ENDPOINT = "https://visual.volcengineapi.com"
SERVICE = "cv"

# 即梦 4.0 模型名
REQ_KEY_T2I = "jimeng_t2i_v40"
REQ_KEY_I2I = "seededit_v3.0"  # 图生图：即梦 SeedEdit 3.0 指令编辑（智能绘图图生图）
REQ_KEY_I2I_SMART_REF = "jimeng_i2i_v30"  # 图生图：即梦 3.0 智能参考（与 Web 端「智能参考」一致，异步 task_id + 轮询）


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = sign(key.encode("utf-8"), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    k_signing = sign(k_service, "request")
    return k_signing


def format_query(parameters: dict) -> str:
    return "&".join(k + "=" + parameters[k] for k in sorted(parameters))


def sign_v4_request(
    access_key: str,
    secret_key: str,
    service: str,
    req_query: str,
    req_body: str,
) -> tuple[str, dict]:
    if not access_key or not secret_key:
        raise ValueError("需要设置环境变量 VOLC_ACCESS_KEY_ID 和 VOLC_SECRET_ACCESS_KEY")
    t = datetime.datetime.now(datetime.timezone.utc)
    current_date = t.strftime("%Y%m%dT%H%M%SZ")
    datestamp = t.strftime("%Y%m%d")
    canonical_uri = "/"
    canonical_querystring = req_query
    signed_headers = "content-type;host;x-content-sha256;x-date"
    payload_hash = hashlib.sha256(req_body.encode("utf-8")).hexdigest()
    content_type = "application/json"
    canonical_headers = (
        "content-type:" + content_type + "\n"
        "host:" + HOST + "\n"
        "x-content-sha256:" + payload_hash + "\n"
        "x-date:" + current_date + "\n"
    )
    canonical_request = (
        METHOD + "\n"
        + canonical_uri + "\n"
        + canonical_querystring + "\n"
        + canonical_headers + "\n"
        + signed_headers + "\n"
        + payload_hash
    )
    algorithm = "HMAC-SHA256"
    credential_scope = datestamp + "/" + REGION + "/" + service + "/" + "request"
    string_to_sign = (
        algorithm + "\n"
        + current_date + "\n"
        + credential_scope + "\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )
    signing_key = get_signature_key(secret_key, datestamp, REGION, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization_header = (
        algorithm + " " + "Credential=" + access_key + "/" + credential_scope + ", "
        "SignedHeaders=" + signed_headers + ", " + "Signature=" + signature
    )
    headers = {
        "X-Date": current_date,
        "Authorization": authorization_header,
        "X-Content-Sha256": payload_hash,
        "Content-Type": content_type,
    }
    request_url = ENDPOINT + "?" + canonical_querystring
    return request_url, headers


def _call_cv_process(body_params: dict) -> requests.Response:
    access_key = os.environ.get("VOLC_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("VOLC_SECRET_ACCESS_KEY", "").strip()
    if not access_key or not secret_key:
        raise ValueError("请设置环境变量 VOLC_ACCESS_KEY_ID 和 VOLC_SECRET_ACCESS_KEY")
    query_params = {"Action": "CVProcess", "Version": "2022-08-31"}
    formatted_query = format_query(query_params)
    req_body = json.dumps(body_params, ensure_ascii=False)
    request_url, headers = sign_v4_request(
        access_key, secret_key, SERVICE, formatted_query, req_body
    )
    r = requests.post(request_url, headers=headers, data=req_body.encode("utf-8"), timeout=120)
    return r


def t2i(prompt: str, output_path: str, width: int = 1024, height: int = 1024) -> bool:
    """
    文生图：即梦 4.0 jimeng_t2i_v40。
    prompt: 文本描述。output_path: 保存路径。width/height: 输出尺寸（以火山文档支持为准）。
    """
    # 火山即梦 body 格式以官方文档为准，此处为常见形式
    body_params = {
        "req_key": REQ_KEY_T2I,
        "prompt": prompt,
        "width": width,
        "height": height,
    }
    r = _call_cv_process(body_params)
    resp_str = r.text.replace("\\u0026", "&")
    if r.status_code != 200:
        print(f"[即梦 t2i] HTTP {r.status_code}: {resp_str[:500]}", file=sys.stderr)
        return False
    data = json.loads(resp_str)
    # 解析响应：可能是 data.image_base64 / data.image_url / task_id 需轮询
    return _save_response_image(data, output_path, "t2i")


def _poll_i2i_task(
    task_id: str,
    output_path: str,
    req_key: str = REQ_KEY_I2I_SMART_REF,
    max_wait_sec: int = 120,
    interval_sec: float = 2.0,
) -> bool:
    """
    轮询即梦异步图生图任务结果。查询接口请求体：req_key, task_id（必选）, req_json（可选）。
    同一 CVProcess 网关，Body 传 req_key + task_id，直到 data 中出现 binary_data_base64 / image_url 或超时。
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max_wait_sec
    while time.monotonic() < deadline:
        body_params = {"req_key": req_key, "task_id": task_id}
        r = _call_cv_process(body_params)
        resp_str = r.text.replace("\\u0026", "&")
        if r.status_code != 200:
            time.sleep(interval_sec)
            continue
        try:
            data = json.loads(resp_str)
        except Exception:
            time.sleep(interval_sec)
            continue
        # 优先从 data 里取图
        if "data" in data and isinstance(data["data"], dict):
            d = data["data"]
            b64_list = d.get("binary_data_base64")
            if isinstance(b64_list, list) and len(b64_list) > 0:
                raw = base64.standard_b64decode(b64_list[0])
                out.write_bytes(raw)
                print(f"[即梦 i2i 智能参考] 轮询完成，已保存: {out.resolve()}")
                return True
            if d.get("image_base64"):
                raw = base64.standard_b64decode(d["image_base64"])
                out.write_bytes(raw)
                print(f"[即梦 i2i 智能参考] 轮询完成，已保存: {out.resolve()}")
                return True
            if d.get("image_url"):
                try:
                    rr = requests.get(d["image_url"], timeout=60)
                    if rr.status_code == 200:
                        out.write_bytes(rr.content)
                        print(f"[即梦 i2i 智能参考] 轮询完成，已保存: {out.resolve()}")
                        return True
                except Exception as e:
                    print(f"[即梦 i2i 智能参考] 拉取 url 失败: {e}", file=sys.stderr)
        # 若接口返回未就绪状态码/字段，可在此判断后 break
        time.sleep(interval_sec)
    print(f"[即梦 i2i 智能参考] 轮询超时（{max_wait_sec}s），未获取到图片", file=sys.stderr)
    return False


def i2i(
    prompt: str,
    image_path: str,
    output_path: str,
    width: int = 1024,
    height: int = 1024,
    *,
    use_smart_ref: bool = False,
) -> bool:
    """
    图生图：use_smart_ref=False 为即梦 SeedEdit 3.0 指令编辑；
    use_smart_ref=True 为即梦 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致，可能返回 task_id 需轮询。
    """
    path = Path(image_path)
    if not path.is_file():
        print(f"[即梦 i2i] 输入图片不存在: {image_path}", file=sys.stderr)
        return False
    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    req_key = REQ_KEY_I2I_SMART_REF if use_smart_ref else REQ_KEY_I2I
    body_params = {
        "req_key": req_key,
        "prompt": prompt,
        "binary_data_base64": [b64],
        "width": width,
        "height": height,
    }
    if not use_smart_ref:
        body_params["scale"] = 0.5
        body_params["seed"] = -1
    r = _call_cv_process(body_params)
    resp_str = r.text.replace("\\u0026", "&")
    if r.status_code != 200:
        print(f"[即梦 i2i] HTTP {r.status_code}: {resp_str[:500]}", file=sys.stderr)
        return False
    try:
        data = json.loads(resp_str)
    except Exception as e:
        print(f"[即梦 i2i] 响应解析失败: {e}", file=sys.stderr)
        return False
    # 智能参考：可能返回 task_id，需轮询
    task_id = None
    if "data" in data and isinstance(data["data"], dict):
        task_id = data["data"].get("task_id")
    if not task_id:
        task_id = data.get("task_id")
    if use_smart_ref and task_id:
        return _poll_i2i_task(task_id, output_path, req_key=req_key)
    return _save_response_image(data, output_path, "i2i")


def _save_response_image(data: dict, output_path: str, mode: str) -> bool:
    """从响应中取出图片（base64 或 url）并写入 output_path。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if "data" in data and isinstance(data["data"], dict):
        d = data["data"]
        # 火山即梦返回 data.binary_data_base64 数组
        b64_list = d.get("binary_data_base64")
        if isinstance(b64_list, list) and len(b64_list) > 0:
            raw = base64.standard_b64decode(b64_list[0])
            out.write_bytes(raw)
            print(f"[即梦 {mode}] 已保存: {out.resolve()}")
            return True
        if d.get("image_base64"):
            raw = base64.standard_b64decode(d["image_base64"])
            out.write_bytes(raw)
            print(f"[即梦 {mode}] 已保存: {out.resolve()}")
            return True
        if d.get("image_url"):
            try:
                r = requests.get(d["image_url"], timeout=60)
                if r.status_code == 200:
                    out.write_bytes(r.content)
                    print(f"[即梦 {mode}] 已保存: {out.resolve()}")
                    return True
            except Exception as e:
                print(f"[即梦 {mode}] 拉取 url 失败: {e}", file=sys.stderr)
    # 异步 task_id 则需轮询（此处仅打印，可后续扩展）
    if data.get("task_id"):
        print(f"[即梦 {mode}] 返回 task_id（异步），需轮询结果。原始响应: {json.dumps(data, ensure_ascii=False)[:400]}", file=sys.stderr)
    else:
        print(f"[即梦 {mode}] 未解析到图片，响应: {json.dumps(data, ensure_ascii=False)[:500]}", file=sys.stderr)
    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="即梦 4.0 火山引擎 API：文生图 / 图生图")
    parser.add_argument("--t2i", action="store_true", help="文生图")
    parser.add_argument("--i2i", action="store_true", help="图生图（需 --image 输入图）")
    parser.add_argument("--prompt", "-p", required=True, help="提示词")
    parser.add_argument("--output", "-o", required=True, help="输出图片路径")
    parser.add_argument("--image", "-i", default="", help="图生图时的输入图片路径")
    parser.add_argument("--width", "-W", type=int, default=1024)
    parser.add_argument("--height", "-H", type=int, default=1024)
    parser.add_argument("--smart-ref", action="store_true", dest="smart_ref", help="图生图使用即梦 3.0 智能参考（jimeng_i2i_v30），与 Web 端「智能参考」一致")
    args = parser.parse_args()

    if args.t2i:
        ok = t2i(args.prompt, args.output, width=args.width, height=args.height)
    elif args.i2i:
        if not args.image:
            print("图生图需指定 --image 输入图片路径", file=sys.stderr)
            sys.exit(1)
        ok = i2i(args.prompt, args.image, args.output, width=args.width, height=args.height, use_smart_ref=getattr(args, "smart_ref", False))
    else:
        print("请指定 --t2i 或 --i2i", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if ok else 1)
