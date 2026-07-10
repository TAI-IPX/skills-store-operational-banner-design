#!/usr/bin/env python3
"""
后端能力矩阵 — 单一数据源。

所有后端的类型、优先级、能力差异在此处声明，不散落在多个 if/elif 链中。
新增后端只需加一行，下游分发代码统一从此处读取。

设计原则：
  1. 功能固定，Key 可换
  2. 生图后端 (gpt-image-2) 优先级 > 编辑后端 (Gemini)
  3. 编辑后端统一走 mask 机制保护原始主体
"""

import os

# priority 越大越先命中
# edit: 该后端是否支持图编（去字/扩图/填充）
# mask: 该后端是否支持 mask 遮罩编辑（透明=可编辑，不透=保留）
BACKENDS: dict = {
    # ── gpt-image-2 生图类（优先，排在前面）──
    "packygpt": {
        "type": "gpt-image-2",
        "priority": 10,
        "edit": True,
        "mask": False,
        "api_key": "PACKYGPT_API_KEY",
        "base_url_key": None,
        "model": "gpt-image-2",
        "t2i_endpoint": "/v1/images/generations",
        "edit_endpoint": "/v1/images/edits",
    },
    "xingchengpt": {
        "type": "gpt-image-2",
        "priority": 9,
        "edit": True,
        "mask": False,
        "api_key": "XINGCHENGGPT_API_KEY",
        "base_url_key": "XINGCHENGGPT_BASE_URL",
        "model": "gpt-image-2",
        "t2i_endpoint": "/v1/images/generations",
        "edit_endpoint": "/v1/chat/completions",
    },
    "micugpt2": {
        "type": "gpt-image-2",
        "priority": 8,
        "edit": True,
        "mask": True,
        "api_key": "MICUAPI_API_KEY",
        "base_url_key": None,
        "model": "gpt-image-2",
        "t2i_endpoint": "/v1/images/generations",
        "edit_endpoint": "/v1/images/edits",
    },
    "moxingpt": {
        "type": "gpt-image-2",
        "priority": 7,
        "edit": True,
        "mask": False,
        "api_key": "MOXINGPT_API_KEY",
        "base_url_key": "MOXINGPT_BASE_URL",
        "model": "gpt-image-2",
        "t2i_endpoint": "/v1/chat/completions",
        "edit_endpoint": "/v1/chat/completions",
    },
    # ── Gemini 编辑类（回退，排在后面）──
    "micugemini": {
        "type": "gemini",
        "priority": 6,
        "edit": True,
        "mask": True,
        "api_key": "MICUGEMINI_API_KEY",
        "base_url_key": None,
        "model": "gemini-3-pro-image-preview",
        "t2i_endpoint": None,
        "edit_endpoint": "/v1/chat/completions",
    },
    "xingchengemini": {
        "type": "gemini",
        "priority": 5,
        "edit": True,
        "mask": True,
        "api_key": "XINGCHENGEMINI_API_KEY",
        "base_url_key": "XINGCHENGEMINI_BASE_URL",
        "model": "gemini-3.1-flash-image-preview",
        "t2i_endpoint": None,
        "edit_endpoint": "/v1/chat/completions",
    },
    "moxingemini": {
        "type": "gemini",
        "priority": 5,
        "edit": True,
        "mask": True,
        "api_key": "MOXINGEMINI_API_KEY",
        "base_url_key": "MOXINGEMINI_BASE_URL",
        "model": os.environ.get("MOXINGEMINI_MODEL", "[次]gemini-3.1-flash-image-preview"),
        "t2i_endpoint": None,
        "edit_endpoint": "/v1/chat/completions",
    },
    "packy7s": {
        "type": "gemini",
        "priority": 4,
        "edit": True,
        "mask": False,
        "api_key": "PACKY7S_API_KEY",
        "base_url_key": None,
        "model": "gemini-3.1-flash-image-preview",
        "t2i_endpoint": None,
        "edit_endpoint": ":generateContent",
    },
    "packy3s": {
        "type": "gemini",
        "priority": 3,
        "edit": True,
        "mask": False,
        "api_key": "PACKY3S_API_KEY",
        "base_url_key": None,
        "model": "gemini-3.1-flash-image-preview",
        "t2i_endpoint": None,
        "edit_endpoint": ":generateContent",
    },
    "packy": {
        "type": "gemini",
        "priority": 2,
        "edit": True,
        "mask": False,
        "api_key": "PACKY_API_KEY",
        "base_url_key": None,
        "model": "gemini-3.1-flash-image-preview",
        "t2i_endpoint": None,
        "edit_endpoint": ":generateContent",
    },
    # ── 其他 ──
    "nano-banana": {
        "type": "other",
        "priority": 1,
        "edit": False,
        "mask": False,
    },
}


def get_available_backends() -> list[str]:
    """返回所有已注册的后端名称"""
    return list(BACKENDS.keys())


def get_backend(name: str) -> dict | None:
    """根据名称获取后端配置"""
    return BACKENDS.get(name)


def get_sorted_backends(filter_type: str | None = None) -> list[tuple[str, dict]]:
    """返回按 priority 降序排列的后端列表，可选过滤类型"""
    items = BACKENDS.items()
    if filter_type:
        items = [(n, c) for n, c in items if c.get("type") == filter_type]
    return sorted(items, key=lambda x: -x[1]["priority"])


def get_active_backend(args) -> str | None:
    """
    从 argparse.Namespace 中确定当前活跃的 BANNER_IMAGE_BACKEND。
    按 priority 顺序检测，返回第一个 args 中为 True 的后端名称。
    """
    for name, _ in get_sorted_backends():
        flag = name.replace("-", "_")  # packygpt → packygpt
        if getattr(args, flag, False):
            return name
    return None


def active_backend_has(name: str, capability: str) -> bool:
    """检查活跃后端是否具有某项能力"""
    import os
    backend = BACKENDS.get(name)
    if not backend:
        return False
    return bool(backend.get(capability, False))


# ══ 固定配置（不随 Key 变化）══

# sentinel 颜色：composite_to_canvas_center 使用的填充色
SENTINEL_COLOR = (1, 0, 254)

# tianchong 画布尺寸（FILL_CANVAS）
TIANCHONG_W, TIANCHONG_H = 2048, 512

# 不走 S4-S5-S6 的预设（纯 cover-crop）
DIRECT_TO_CANVAS_PRESETS = {"default"}

# Mask 使用的特殊 token（micugemini / xingchengemini 需要）


def _generate_sentinel_mask(image_path: str) -> str:
    """
    从 sentinel 画布生成 RGBA mask：
      transparent (alpha=0) = sentinel (1,0,254) 区域 → API 可编辑
      opaque (alpha=255)   = 原始主体区域           → API 应保留
    返回 mask 临时文件路径。
    """
    from PIL import Image
    import numpy as np
    import tempfile
    import os as _os

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    sentinel = (arr[:, :, 0] == 1) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 254)

    mask = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    mask[:, :, 3] = 255
    mask[sentinel, 3] = 0

    fd, mask_path = tempfile.mkstemp(suffix=".png")
    _os.close(fd)
    Image.fromarray(mask, "RGBA").save(mask_path, "PNG")
    return mask_path


# XINGCHENGEMINI_MASK_TOKEN = "sct=ZolZrUT0e1IDTQOj"  ← key 私有不写死
