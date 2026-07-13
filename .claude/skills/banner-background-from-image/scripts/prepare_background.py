#!/usr/bin/env python3
"""
Prepare a banner background from a user-provided image to target W×H.
Decision: crop only, expand only, or crop+expand — based on best visual result for target size
(see references/workflow.md). Expand/remove-text use gemini_image_edit (Gemini or t8star per
BANNER_IMAGE_BACKEND; requires GEMINI_API_KEY or T8STAR_API_KEY).
Output suitable for banner-composer. Shared safe zone respected in crop.
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 保证同目录模块可被导入（无论从何处以何方式调用本脚本）
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
# 保证项目根 scripts/ 可被导入（_backends 等）
_root_scripts = Path(_script_dir).parent.parent.parent.parent / "scripts"
if str(_root_scripts) not in sys.path:
    sys.path.insert(0, str(_root_scripts))

# Same presets and output convention as crop_to_target
from crop_to_target import PRESETS, get_safe_zone, get_safe_zone_center, crop_to_target

DEFAULT_OUTPUT_DIR = "output"

# 图编后端：gemini / nano-banana / t8star。扩图/去字由 gemini_image_edit 根据此选择；此处仅判断是否有对应 API key
_raw_edit = os.environ.get("BANNER_IMAGE_BACKEND", "gemini") or os.environ.get("BANNER_EDIT_BACKEND", "")
BANNER_IMAGE_BACKEND = _raw_edit.strip().lower()


def _has_image_edit_key() -> bool:
    """True 表示可执行扩图/去字：gemini 需 GEMINI_API_KEY，t8star 需 T8STAR_API_KEY，packygpt 需 PACKYGPT_API_KEY，micugpt2 需 MICUAPI_API_KEY，moxingpt 需 MOXINGPT_API_KEY，xingchengpt 需 XINGCHENGGPT_API_KEY，xinchengpt 需 XINCHENGPT_API_KEY。"""
    if BANNER_IMAGE_BACKEND == "t8star":
        return bool(os.environ.get("T8STAR_API_KEY"))
    if BANNER_IMAGE_BACKEND == "packygpt":
        key = os.environ.get("PACKYGPT_API_KEY", "").strip()
        return key.startswith("sk-")
    if BANNER_IMAGE_BACKEND == "moxingpt":
        key = os.environ.get("MOXINGPT_API_KEY", "").strip()
        return key.startswith("sk-")
    if BANNER_IMAGE_BACKEND == "xingchengpt":
        key = os.environ.get("XINGCHENGGPT_API_KEY", "").strip()
        return key.startswith("sk-")
    if BANNER_IMAGE_BACKEND == "xinchengpt":
        key = os.environ.get("XINCHENGPT_API_KEY", "").strip()
        return key.startswith("sk-")
    if BANNER_IMAGE_BACKEND == "micugpt2":
        key = os.environ.get("MICUAPI_API_KEY", "").strip()
        return key.startswith("sk-")
    return bool(os.environ.get("GEMINI_API_KEY"))


def _wide_a5b_alpha_threshold() -> float:
    """3320×500 A5b BiRefNet 条带 alpha 阈值，默认 0.5（更保守的二值化，减少边缘杂色）；可用 WIDE_A5B_ALPHA_THRESHOLD 覆盖。"""
    raw = os.environ.get("WIDE_A5B_ALPHA_THRESHOLD", "").strip()
    if not raw:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.5


def _wide_a5b_no_gemini_fallback() -> bool:
    """为 1/true/yes 时 BiRefNet 失败直接抛错，不回退 Gemini 顶部条带。"""
    v = os.environ.get("WIDE_A5B_NO_GEMINI_FALLBACK", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _needs_expand(w0: int, h0: int, W: int, H: int) -> bool:
    """True if source is smaller than target on either dimension (simplified heuristic)."""
    return w0 < W or h0 < H


def _expand_with_gemini(
    image_path: str,
    width: int,
    height: int,
    output_path: str,
    *,
    subject_center_y_ratio: float | None = None,
    subject_center_x_ratio: float | None = None,
    align_image_center_to_safe_zone: bool = True,
    preset: str | None = None,
) -> Path | None:
    """
    Outpaint with Gemini, then crop to W×H. Returns output path or None on failure.
    When align_image_center_to_safe_zone: crop so expanded image center = safe zone center.
    """
    if not _has_image_edit_key():
        print(
            "API key not set; skipping expand. Set GEMINI_API_KEY, or BANNER_IMAGE_BACKEND=t8star and T8STAR_API_KEY.",
            file=sys.stderr,
        )
        return None
    try:
        from gemini_image_edit import edit_image, OUTPAINT_PROMPT
    except ImportError:
        print("gemini_image_edit not found; skipping expand.", file=sys.stderr)
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        expanded_path = f.name
    try:
        edit_image(image_path, expanded_path, OUTPAINT_PROMPT)
        return crop_to_target(
            expanded_path,
            output_path,
            width,
            height,
            subject_center_y_ratio=None if align_image_center_to_safe_zone else subject_center_y_ratio,
            subject_center_x_ratio=None if align_image_center_to_safe_zone else subject_center_x_ratio,
            align_image_center_to_safe_zone=align_image_center_to_safe_zone,
            preset=preset,
        )
    except Exception as e:
        print(f"Expand failed: {e}", file=sys.stderr)
        return None
    finally:
        if os.path.isfile(expanded_path):
            try:
                os.unlink(expanded_path)
            except OSError:
                pass


def _remove_text_with_gemini(image_path: str) -> Path | None:
    """Run remove-text (Gemini/t8star/packygpt per BANNER_IMAGE_BACKEND); return path to cleaned image or None."""
    if not _has_image_edit_key():
        return None
    if BANNER_IMAGE_BACKEND == "packygpt":
        from gemini_image_edit import INPAINT_REMOVE_TEXT_PROMPT
        _soften = (
            "\n\nCRITICAL: The output must match the input pixel-for-pixel everywhere except where text/labels were removed. "
            "Do NOT alter colors, brightness, composition, subjects, background, or any visual element. "
            "ONLY remove overlaid text and inpaint the tiny region where text was. "
            "The result must look identical to the original except with text gone."
        )
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _packygpt_edit_image(image_path, out, INPAINT_REMOVE_TEXT_PROMPT + _soften)
            return Path(out)
        except Exception as e:
            print(f"  packygpt 去干扰失败: {e}", file=sys.stderr)
            if os.path.isfile(out):
                try:
                    os.unlink(out)
                except OSError:
                    pass
            return None
    if BANNER_IMAGE_BACKEND == "moxingpt":
        from gemini_image_edit import INPAINT_REMOVE_TEXT_PROMPT
        _soften = (
            "\n\nCRITICAL: The output must match the input pixel-for-pixel everywhere except where text/labels were removed. "
            "Do NOT alter colors, brightness, composition, subjects, background, or any visual element. "
            "ONLY remove overlaid text and inpaint the tiny region where text was. "
            "The result must look identical to the original except with text gone."
        )
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _moxingpt_edit_image(image_path, out, INPAINT_REMOVE_TEXT_PROMPT + _soften)
            return Path(out)
        except Exception as e:
            print(f"  moxingpt 去干扰失败: {e}", file=sys.stderr)
            if os.path.isfile(out):
                try:
                    os.unlink(out)
                except OSError:
                    pass
            return None
    if BANNER_IMAGE_BACKEND == "xingchengpt":
        from gemini_image_edit import INPAINT_REMOVE_TEXT_PROMPT
        _soften = (
            "\n\nCRITICAL: The output must match the input pixel-for-pixel everywhere except where text/labels were removed. "
            "Do NOT alter colors, brightness, composition, subjects, background, or any visual element. "
            "ONLY remove overlaid text and inpaint the tiny region where text was. "
            "The result must look identical to the original except with text gone."
        )
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _xingchengpt_edit_image(image_path, out, INPAINT_REMOVE_TEXT_PROMPT + _soften)
            return Path(out)
        except Exception as e:
            print(f"  xingchengpt 去干扰失败: {e}", file=sys.stderr)
            if os.path.isfile(out):
                try:
                    os.unlink(out)
                except OSError:
                    pass
            return None
    if BANNER_IMAGE_BACKEND == "xinchengpt":
        from gemini_image_edit import INPAINT_REMOVE_TEXT_PROMPT
        _soften = (
            "\n\nCRITICAL: The output must match the input pixel-for-pixel everywhere except where text/labels were removed. "
            "Do NOT alter colors, brightness, composition, subjects, background, or any visual element. "
            "ONLY remove overlaid text and inpaint the tiny region where text was. "
            "The result must look identical to the original except with text gone."
        )
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            _xinchengpt_edit_image(image_path, out, INPAINT_REMOVE_TEXT_PROMPT + _soften)
            return Path(out)
        except Exception as e:
            print(f"  xinchengpt 去干扰失败: {e}", file=sys.stderr)
            if os.path.isfile(out):
                try:
                    os.unlink(out)
                except OSError:
                    pass
            return None
    try:
        from gemini_image_edit import edit_image, INPAINT_REMOVE_TEXT_PROMPT
    except ImportError:
        return None
    fd, out = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        edit_image(image_path, out, INPAINT_REMOVE_TEXT_PROMPT)
        return Path(out)
    except Exception:
        if os.path.isfile(out):
            try:
                os.unlink(out)
            except OSError:
                pass
        return None


def _packygpt_size_val(orig_w: int, orig_h: int, needs_upscale: bool, nw: int, nh: int) -> str:
    """Return packygpt size string. Use explicit size when ratio ≤3:1, auto otherwise."""
    w = nw if needs_upscale else orig_w
    h = nh if needs_upscale else orig_h
    ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 1
    if ratio <= 3:
        return f"{w}x{h}"
    return "auto"


def _packygpt_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
) -> None:
    """
    PackyGPT 图编：通过 packyapi.com /v1/images/edits 编辑图片。
    若原图总像素 < 655,360，自动 upscale 后发请求，产物 downscale 回原尺寸。
    需 PACKYGPT_API_KEY，触发条件：BANNER_IMAGE_BACKEND=packygpt。
    """
    import json as _json
    import requests as _requests

    api_key = os.environ.get("PACKYGPT_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("PACKYGPT_API_KEY 未设置")

    base_url = os.environ.get("OPENAI_BASE_URL", "https://www.packyapi.com").rstrip("/")
    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    from PIL import Image as _PILImage
    from io import BytesIO as _BytesIO

    im = _PILImage.open(ref_path).convert("RGB")
    orig_w, orig_h = im.size
    total_px = orig_w * orig_h

    MIN_PX = 655360
    needs_upscale = total_px < MIN_PX
    if needs_upscale:
        scale = (MIN_PX / total_px) ** 0.5
        nw = max(16, ((int(orig_w * scale) + 15) // 16) * 16)
        nh = max(16, ((int(orig_h * scale) + 15) // 16) * 16)
        im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        print(f"[packygpt edit] 原图 {orig_w}×{orig_h} ({total_px} px) 不满足最低 {MIN_PX} px，放大至 {nw}×{nh}", flush=True)

    ref_bytes = _BytesIO()
    im.save(ref_bytes, format="PNG")
    ref_bytes = ref_bytes.getvalue()

    _proxies = None
    _no_proxy = os.environ.get("PACKYGPT_NO_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
        if _proxies:
            print("[packygpt edit] 检测到代理，如超时请设 PACKYGPT_NO_PROXY=1", flush=True)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    files = {"image": (ref_path.name, ref_bytes, "image/png")}
    data = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "size": _packygpt_size_val(orig_w, orig_h, needs_upscale, nw if needs_upscale else 0, nh if needs_upscale else 0),
        "quality": "high",
        "output_format": "png",
        "response_format": "url",
        "input_fidelity": "high",
    }

    url = f"{base_url}/v1/images/edits"
    print(f"[packygpt edit] {orig_w}×{orig_h} -> 编辑中...", flush=True)
    resp = _requests.post(url, data=data, files=files, headers=headers, timeout=600, proxies=_proxies)
    resp.raise_for_status()
    result = resp.json()
    img_url = result.get("data", [{}])[0].get("url", "")
    if not img_url:
        raise RuntimeError(f"packygpt edits 无图片 URL: {_json.dumps(result, ensure_ascii=False)[:300]}")

    dl = _requests.get(img_url, timeout=300, proxies=_proxies)
    dl.raise_for_status()

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if needs_upscale and not keep_returned_size:
        import tempfile as _tmp
        fd, tmp = _tmp.mkstemp(suffix=".png")
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(dl.content)
            out_im = _PILImage.open(tmp).convert("RGB")
            out_im = out_im.resize((orig_w, orig_h), _PILImage.Resampling.LANCZOS)
            out_im.save(str(out_path), "PNG")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    else:
        with open(str(out_path), "wb") as f:
            f.write(dl.content)

    out_sz = _PILImage.open(str(out_path)).size
    print(f"[packygpt edit] 已保存: {out_path} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _moxingpt_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
    mask_path: str | None = None,
) -> None:
    """
    MoxinGPT 图编：通过 moxin.studio /v1/chat/completions 编辑图片，多模型按序重试（MOXINGPT_MODEL 逗号分隔，最多3个）。
    需 MOXINGPT_API_KEY，触发条件：BANNER_IMAGE_BACKEND=moxingpt。
    mask_path: RGBA PNG，透明=可编辑区域，不透明=需保护的主体区域。

    注意：moxin.studio 的 gpt-image-2 只支持 t2i 生图（/v1/images/generations），
    其 /v1/chat/completions 图编端点已不可用（403/404）。当配置了 MOXINGEMINI_API_KEY 时，
    编辑操作委托给 moxingemini（Gemini 系，走 chat/completions 图编，可用）。
    这与 edit_image() 的路由（moxingpt+MOXINGEMINI→_edit_image_moxingemini）保持一致。
    """
    import json as _json
    import requests as _requests
    import base64 as _b64
    import re as _re

    # moxingpt 图编端点不可用 → 有 moxingemini key 时委托给它（AGENTS.md 标准组合 --moxingpt --moxingemini）
    if os.environ.get("MOXINGEMINI_API_KEY", "").strip().startswith("sk-"):
        print("[moxingpt edit] moxin.studio 图编端点不可用，委托 moxingemini（Gemini 系）编辑", flush=True)
        from gemini_image_edit import _edit_image_moxingemini
        _edit_image_moxingemini(
            image_path, output_path, prompt,
            keep_returned_size=keep_returned_size, mask_path=mask_path,
        )
        return

    api_key = os.environ.get("MOXINGPT_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("MOXINGPT_API_KEY 未设置")

    base_url = os.environ.get("MOXINGPT_BASE_URL", "https://www.moxin.studio").rstrip("/")
    _quality = os.environ.get("MOXINGPT_QUALITY", "auto").strip() or "auto"
    _size = os.environ.get("MOXINGPT_SIZE", "auto").strip() or "auto"
    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    img_b64 = _b64.standard_b64encode(ref_path.read_bytes()).decode("ascii")

    _proxies = None
    _no_proxy = os.environ.get("MOXINGPT_NO_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
        if _proxies:
            print("[moxingpt edit] 检测到代理，如超时请设 MOXINGPT_NO_PROXY=1", flush=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # 多模型重试：MOXINGPT_MODEL 支持逗号分隔，最多3个候选
    _raw_models = os.environ.get("MOXINGPT_MODEL", "[次]gpt-image-2,gpt-image-2-c").strip()
    model_list = [m.strip() for m in _raw_models.split(",") if m.strip()][:3]
    if not model_list:
        model_list = ["gpt-image-2"]

    orig_w, orig_h = None, None
    try:
        from PIL import Image as _PILImage
        im = _PILImage.open(ref_path)
        orig_w, orig_h = im.size
    except Exception:
        pass

    url = f"{base_url}/v1/chat/completions"
    img_url, b64_out = "", ""
    last_err: Exception | None = None
    for mi, model in enumerate(model_list, 1):
        parts: list = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
        ]
        if mask_path and os.path.isfile(mask_path):
            mask_bytes = Path(mask_path).read_bytes()
            mask_b64 = _b64.standard_b64encode(mask_bytes).decode("ascii")
            parts.append({"type": "text", "text": "The transparent areas in the mask image above indicate regions that need to be filled/outpainted. The opaque white areas must remain completely unchanged. Only edit the transparent regions."})
            parts.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + mask_b64}})
        body = {
            "model": model,
            "messages": [{"role": "user", "content": parts}],
            "size": _size,
            "quality": _quality,
        }
        try:
            print(f"[moxingpt edit] {orig_w or '?'}×{orig_h or '?'} (model={model}, {mi}/{len(model_list)}) -> 编辑中...", flush=True)
            resp = _requests.post(url, json=body, headers=headers, timeout=600, proxies=_proxies)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            last_err = e
            print(f"[moxingpt edit] model={model} 请求失败 ({mi}/{len(model_list)}): {e}", flush=True)
            continue
        img_url, b64_out = "", ""
        for c in data.get("choices", []):
            ct = c.get("message", {}).get("content", "")
            if isinstance(ct, list):
                for p in ct:
                    if isinstance(p, dict) and p.get("type") in ("image_url", "image"):
                        img_url = p.get("image_url", {}).get("url", "") or p.get("image", {}).get("data", "") or p.get("data", "")
                        if img_url and not img_url.startswith("data:"):
                            break
                        elif img_url:
                            b64_out = img_url.split(",", 1)[-1] if "," in img_url else img_url
                            img_url = ""
                            break
            elif isinstance(ct, str):
                m = _re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", ct)
                if m:
                    img_url = m.group(1)
                elif ct.startswith("data:image"):
                    b64_out = ct.split(",", 1)[-1]
                elif ct.strip().startswith(("https://", "http://")):
                    img_url = ct.strip().split()[0]
        if img_url or b64_out:
            break
        # 响应 200 但不含图片数据
        dall_e_data = data.get("data", [{}])
        if dall_e_data:
            img_url = dall_e_data[0].get("url", "")
            b64_out = dall_e_data[0].get("b64_json", "")
            if img_url or b64_out:
                break
        last_err = RuntimeError(f"moxingpt edit no image (model={model}). resp: " + _json.dumps(data, ensure_ascii=False)[:500])
        print(f"[moxingpt edit] model={model} 未返回图片 ({mi}/{len(model_list)})，换下一模型...", flush=True)

    if not img_url and not b64_out:
        raise last_err if last_err is not None else RuntimeError("moxingpt edit failed: no image after all models")

    out_path_p = Path(output_path)
    out_path_p.parent.mkdir(parents=True, exist_ok=True)

    if img_url:
        dl = _requests.get(img_url, timeout=300, proxies=_proxies)
        dl.raise_for_status()
        out_path_p.write_bytes(dl.content)
    else:
        out_path_p.write_bytes(_b64.b64decode(b64_out))

    if not keep_returned_size and orig_w and orig_h:
        try:
            from PIL import Image as _PILImage
            ed = _PILImage.open(out_path_p)
            if ed.size != (orig_w, orig_h):
                # cover-scale + center-crop 保持长宽比
                scale = max(orig_w / ed.size[0], orig_h / ed.size[1])
                nw = max(1, round(ed.size[0] * scale))
                nh = max(1, round(ed.size[1] * scale))
                ed = ed.resize((nw, nh), _PILImage.Resampling.LANCZOS)
                left = (nw - orig_w) // 2
                top = (nh - orig_h) // 2
                ed = ed.crop((left, top, left + orig_w, top + orig_h))
                ed.save(out_path_p, "PNG")
                print(f"[moxingpt edit] cover-scale 回 {orig_w}×{orig_h}", flush=True)
        except Exception:
            pass

    try:
        from PIL import Image as _PILImage
        out_sz = _PILImage.open(str(out_path_p)).size
    except Exception:
        out_sz = (0, 0)
    print(f"[moxingpt edit] 已保存: {out_path_p} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _xingchengpt_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
) -> None:
    """
    XingchenGPT 图编：通过 newapi.pro /v1/chat/completions 编辑图片。
    需 XINGCHENGGPT_API_KEY，触发条件：BANNER_IMAGE_BACKEND=xingchengpt。
    """
    import json as _json
    import requests as _requests
    import base64 as _b64
    import re as _re

    api_key = os.environ.get("XINGCHENGGPT_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("XINGCHENGGPT_API_KEY 未设置")

    base_url = os.environ.get("XINGCHENGGPT_BASE_URL", "https://api.newapi.pro").rstrip("/")
    model = os.environ.get("XINGCHENGGPT_MODEL", "gpt-image-2").strip()
    _quality = os.environ.get("XINGCHENGGPT_QUALITY", "auto").strip() or "auto"
    _size = os.environ.get("XINGCHENGGPT_SIZE", "auto").strip() or "auto"
    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    img_b64 = _b64.standard_b64encode(ref_path.read_bytes()).decode("ascii")
    parts: list = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
    ]

    # 默认直连（不探测系统代理），避免本机代理软件掐断长连接请求。
    # 需要走代理时显式设置 XINGCHENGGPT_USE_PROXY=1。
    _proxies = None
    _no_proxy = os.environ.get("XINGCHENGGPT_NO_PROXY", "").strip()
    _use_proxy = os.environ.get("XINGCHENGGPT_USE_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes") and _use_proxy.lower() in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
        if _proxies:
            print("[xingchengpt edit] 检测到代理，如超时请设 XINGCHENGGPT_NO_PROXY=1", flush=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": parts}],
        "size": _size,
        "quality": _quality,
    }

    url = f"{base_url}/v1/chat/completions"
    orig_w, orig_h = None, None
    try:
        from PIL import Image as _PILImage
        im = _PILImage.open(ref_path)
        orig_w, orig_h = im.size
    except Exception:
        pass
    print(f"[xingchengpt edit] {orig_w or '?'}×{orig_h or '?'} -> 编辑中...", flush=True)
    resp = _requests.post(url, json=body, headers=headers, timeout=600, proxies=_proxies)
    resp.raise_for_status()
    data = resp.json()

    img_url, b64_out = "", ""
    for c in data.get("choices", []):
        ct = c.get("message", {}).get("content", "")
        if isinstance(ct, list):
            for p in ct:
                if isinstance(p, dict) and p.get("type") in ("image_url", "image"):
                    img_url = p.get("image_url", {}).get("url", "") or p.get("image", {}).get("data", "") or p.get("data", "")
                    if img_url and not img_url.startswith("data:"):
                        break
                    elif img_url:
                        b64_out = img_url.split(",", 1)[-1] if "," in img_url else img_url
                        img_url = ""
                        break
        elif isinstance(ct, str):
            m = _re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", ct)
            if m:
                img_url = m.group(1)
            elif _re.search(r"!\[.*?\]\((data:image/[^)]+)\)", ct):
                b64_out = _re.search(r"!\[.*?\]\((data:image/[^)]+)\)", ct).group(1).split(",", 1)[-1]
            elif ct.startswith("data:image"):
                b64_out = ct.split(",", 1)[-1]
            elif ct.strip().startswith(("https://", "http://")):
                img_url = ct.strip().split()[0]

    if not img_url and not b64_out:
        dall_e_data = data.get("data", [{}])
        if dall_e_data:
            img_url = dall_e_data[0].get("url", "")
            b64_out = dall_e_data[0].get("b64_json", "")

    if not img_url and not b64_out:
        raise RuntimeError(f"xingchengpt edit no image. resp: " + _json.dumps(data, ensure_ascii=False)[:500])

    out_path_p = Path(output_path)
    out_path_p.parent.mkdir(parents=True, exist_ok=True)

    if img_url:
        dl = _requests.get(img_url, timeout=300, proxies=_proxies)
        dl.raise_for_status()
        out_path_p.write_bytes(dl.content)
    else:
        out_path_p.write_bytes(_b64.b64decode(b64_out))

    if not keep_returned_size and orig_w and orig_h:
        try:
            from PIL import Image as _PILImage
            ed = _PILImage.open(out_path_p)
            if ed.size != (orig_w, orig_h):
                ed = ed.resize((orig_w, orig_h), _PILImage.Resampling.LANCZOS)
                ed.save(out_path_p, "PNG")
                print(f"[xingchengpt edit] 已缩放回 {orig_w}×{orig_h}", flush=True)
        except Exception:
            pass

    try:
        from PIL import Image as _PILImage
        out_sz = _PILImage.open(str(out_path_p)).size
    except Exception:
        out_sz = (0, 0)
    print(f"[xingchengpt edit] 已保存: {out_path_p} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _xinchengpt_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
) -> None:
    """
    XinchenGPT 图编：通过 api.centos.hk /v1/chat/completions 编辑图片。
    需 XINCHENGPT_API_KEY，触发条件：BANNER_IMAGE_BACKEND=xinchengpt。
    """
    import json as _json
    import requests as _requests
    import base64 as _b64
    import re as _re

    api_key = os.environ.get("XINCHENGPT_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("XINCHENGPT_API_KEY 未设置")

    base_url = os.environ.get("XINCHENGPT_BASE_URL", "https://api.centos.hk").rstrip("/")
    model = os.environ.get("XINCHENGPT_MODEL", "gpt-image-2").strip()
    _quality = os.environ.get("XINCHENGPT_QUALITY", "auto").strip() or "auto"
    _size = os.environ.get("XINCHENGPT_SIZE", "auto").strip() or "auto"
    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    img_b64 = _b64.standard_b64encode(ref_path.read_bytes()).decode("ascii")
    parts: list = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
    ]

    # 默认直连（不探测系统代理），避免本机代理软件掐断长连接请求。
    # 需要走代理时显式设置 XINCHENGPT_USE_PROXY=1。
    _proxies = None
    _no_proxy = os.environ.get("XINCHENGPT_NO_PROXY", "").strip()
    _use_proxy = os.environ.get("XINCHENGPT_USE_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes") and _use_proxy.lower() in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
        if _proxies:
            print("[xinchengpt edit] 检测到代理，如超时请设 XINCHENGPT_NO_PROXY=1", flush=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": parts}],
        "size": _size,
        "quality": _quality,
    }

    url = f"{base_url}/v1/chat/completions"
    orig_w, orig_h = None, None
    try:
        from PIL import Image as _PILImage
        im = _PILImage.open(ref_path)
        orig_w, orig_h = im.size
    except Exception:
        pass
    print(f"[xinchengpt edit] {orig_w or '?'}×{orig_h or '?'} -> 编辑中...", flush=True)
    resp = _requests.post(url, json=body, headers=headers, timeout=600, proxies=_proxies)
    resp.raise_for_status()
    data = resp.json()

    img_url, b64_out = "", ""
    for c in data.get("choices", []):
        ct = c.get("message", {}).get("content", "")
        if isinstance(ct, list):
            for p in ct:
                if isinstance(p, dict) and p.get("type") in ("image_url", "image"):
                    img_url = p.get("image_url", {}).get("url", "") or p.get("image", {}).get("data", "") or p.get("data", "")
                    if img_url and not img_url.startswith("data:"):
                        break
                    elif img_url:
                        b64_out = img_url.split(",", 1)[-1] if "," in img_url else img_url
                        img_url = ""
                        break
        elif isinstance(ct, str):
            m = _re.search(r"!\[.*?\]\((https?://[^\s)]+)\)", ct)
            if m:
                img_url = m.group(1)
            elif _re.search(r"!\[.*?\]\((data:image/[^)]+)\)", ct):
                b64_out = _re.search(r"!\[.*?\]\((data:image/[^)]+)\)", ct).group(1).split(",", 1)[-1]
            elif ct.startswith("data:image"):
                b64_out = ct.split(",", 1)[-1]
            elif ct.strip().startswith(("https://", "http://")):
                img_url = ct.strip().split()[0]

    if not img_url and not b64_out:
        dall_e_data = data.get("data", [{}])
        if dall_e_data:
            img_url = dall_e_data[0].get("url", "")
            b64_out = dall_e_data[0].get("b64_json", "")

    if not img_url and not b64_out:
        raise RuntimeError(f"xinchengpt edit no image. resp: " + _json.dumps(data, ensure_ascii=False)[:500])

    out_path_p = Path(output_path)
    out_path_p.parent.mkdir(parents=True, exist_ok=True)

    if img_url:
        dl = _requests.get(img_url, timeout=300, proxies=_proxies)
        dl.raise_for_status()
        out_path_p.write_bytes(dl.content)
    else:
        out_path_p.write_bytes(_b64.b64decode(b64_out))

    if not keep_returned_size and orig_w and orig_h:
        try:
            from PIL import Image as _PILImage
            ed = _PILImage.open(out_path_p)
            if ed.size != (orig_w, orig_h):
                ed = ed.resize((orig_w, orig_h), _PILImage.Resampling.LANCZOS)
                ed.save(out_path_p, "PNG")
                print(f"[xinchengpt edit] 已缩放回 {orig_w}×{orig_h}", flush=True)
        except Exception:
            pass

    try:
        from PIL import Image as _PILImage
        out_sz = _PILImage.open(str(out_path_p)).size
    except Exception:
        out_sz = (0, 0)
    print(f"[xinchengpt edit] 已保存: {out_path_p} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _micugpt2_edit_image(
    image_path: str,
    output_path: str,
    prompt: str,
    *,
    keep_returned_size: bool = False,
) -> None:
    """
    MicuGPT2 图编：通过 micuapi.ai /v1/chat/completions 编辑图片。
    多模态输入（text + base64 image），支持 1:8 等极端比例无需 upscale。
    需 MICUAPI_API_KEY。
    """
    import json as _json
    import requests as _requests
    import base64 as _base64
    import re as _re

    api_key = os.environ.get("MICUAPI_API_KEY", "").strip()
    if not api_key.startswith("sk-"):
        raise RuntimeError("MICUAPI_API_KEY 未设置")

    ref_path = Path(image_path)
    if not ref_path.is_file():
        raise FileNotFoundError(f"图片不存在: {ref_path}")

    from PIL import Image as _PILImage
    from io import BytesIO as _BytesIO

    ref_bytes = ref_path.read_bytes()
    im = _PILImage.open(_BytesIO(ref_bytes))
    im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
    w, h = im.size
    max_d = 1536
    if max(w, h) > max_d:
        scale = max_d / float(max(w, h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        im = im.resize((nw, nh), _PILImage.Resampling.LANCZOS)
        buf = _BytesIO()
        im.save(buf, format="PNG")
        ref_bytes = buf.getvalue()
        print(f"[micugpt2 edit] 参考图已缩放至 {nw}×{nh} (原 {w}×{h})", flush=True)
    ref_b64 = _base64.standard_b64encode(ref_bytes).decode("ascii")

    # 代理检测（API 直连更快，CDN 下载需要代理）
    _proxies = None
    _no_proxy = os.environ.get("MICUGPT2_NO_PROXY", "").strip()
    if _no_proxy.lower() not in ("1", "true", "yes"):
        _sys_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if not _sys_proxy:
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                if winreg.QueryValueEx(key, "ProxyEnable")[0]:
                    _sys_proxy = winreg.QueryValueEx(key, "ProxyServer")[0]
                    if _sys_proxy and not _sys_proxy.startswith("http"):
                        _sys_proxy = "http://" + _sys_proxy
                winreg.CloseKey(key)
            except Exception:
                pass
        if _sys_proxy:
            _proxies = {"https": _sys_proxy, "http": _sys_proxy}
        if _proxies:
            print("[micugpt2 edit] 检测到代理（API 直连不发代理，CDN 下载走代理）", flush=True)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    body = _json.dumps({
        "model": "gpt-image-2",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref_b64}"}},
            ]
        }],
    }).encode("utf-8")

    url = "https://www.micuapi.ai/v1/chat/completions"
    print(f"[micugpt2 edit] {w}×{h} -> 编辑中...", flush=True)
    resp = _requests.post(url, data=body, headers=headers, timeout=600, proxies=None)
    resp.raise_for_status()
    data = resp.json()

    img_url = ""
    for choice in data.get("choices", []):
        ct = choice.get("message", {}).get("content", "")
        if isinstance(ct, str):
            m = _re.search(r'!\[.*?\]\((https?://[^\s)]+)\)', ct)
            if m:
                img_url = m.group(1)
                break
    if not img_url:
        raise RuntimeError(f"micugpt2 edits 无图片 URL: {_json.dumps(data, ensure_ascii=False)[:300]}")

    dl = _requests.get(img_url, timeout=300, proxies=_proxies)
    dl.raise_for_status()

    out_path_obj = Path(output_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_path_obj), "wb") as f:
        f.write(dl.content)

    out_sz = _PILImage.open(str(out_path_obj)).size
    print(f"[micugpt2 edit] 已保存: {out_path_obj} ({out_sz[0]}×{out_sz[1]})", flush=True)


def _detect_subject_y(image_path: str) -> float | None:
    """Auto-detect subject vertical center via Gemini Vision; None on failure (use center crop)."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from gemini_subject_detect import detect_subject_y_ratio
        return detect_subject_y_ratio(image_path)
    except Exception:
        return None


def _detect_subject_xy(image_path: str) -> tuple[float | None, float | None]:
    """Auto-detect subject (x, y) center via Gemini Vision; (None, None) on failure."""
    if not os.environ.get("GEMINI_API_KEY"):
        return (None, None)
    try:
        from gemini_subject_detect import detect_subject_xy_ratio
        return detect_subject_xy_ratio(image_path)
    except Exception:
        return (None, None)


def _remove_edge_black(
    image_path: str,
    edge_width: int = 2,
    threshold: int = 40,
    *,
    use_inner_boundary: bool = True,
    content_ratio: float = 0.3,
) -> None:
    """
    去除四边黑/近黑条：若 use_inner_boundary 为 True，先向内扫描找到第一条「有内容」的列/行
    （该列/行中非黑像素占比 >= content_ratio），再用该边界列/行的颜色填充整段黑边；
    否则用 edge_width 内「相邻 1 像素」覆盖（原逻辑）。原地覆盖保存。
    """
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    pix = img.load()

    def col_nonblack_ratio(x: int) -> float:
        if x < 0 or x >= w:
            return 0.0
        n = sum(1 for y in range(h) if max(pix[x, y]) >= threshold)
        return n / h if h else 0.0

    def row_nonblack_ratio(y: int) -> float:
        if y < 0 or y >= h:
            return 0.0
        n = sum(1 for x in range(w) if max(pix[x, y]) >= threshold)
        return n / w if w else 0.0

    if use_inner_boundary:
        # 左：找到第一条「有内容」的列，用该列颜色填满左侧
        boundary_left = w
        for x in range(w):
            if col_nonblack_ratio(x) >= content_ratio:
                boundary_left = x
                break
        if boundary_left > 0 and boundary_left < w:
            for x in range(boundary_left):
                for y in range(h):
                    if max(pix[x, y]) < threshold:
                        pix[x, y] = pix[boundary_left, y]

        # 右：找到最右一条「有内容」的列
        boundary_right = -1
        for x in reversed(range(w)):
            if col_nonblack_ratio(x) >= content_ratio:
                boundary_right = x
                break
        if boundary_right >= 0 and boundary_right < w - 1:
            for x in range(boundary_right + 1, w):
                for y in range(h):
                    if max(pix[x, y]) < threshold:
                        pix[x, y] = pix[boundary_right, y]

        # 上：找到第一条「有内容」的行
        boundary_top = h
        for y in range(h):
            if row_nonblack_ratio(y) >= content_ratio:
                boundary_top = y
                break
        if boundary_top > 0 and boundary_top < h:
            for y in range(boundary_top):
                for x in range(w):
                    if max(pix[x, y]) < threshold:
                        pix[x, y] = pix[x, boundary_top]

        # 下：找到最下一条「有内容」的行
        boundary_bottom = -1
        for y in reversed(range(h)):
            if row_nonblack_ratio(y) >= content_ratio:
                boundary_bottom = y
                break
        if boundary_bottom >= 0 and boundary_bottom < h - 1:
            for y in range(boundary_bottom + 1, h):
                for x in range(w):
                    if max(pix[x, y]) < threshold:
                        pix[x, y] = pix[x, boundary_bottom]
    else:
        # 原逻辑：edge_width 内用相邻 1 像素覆盖
        for x in range(edge_width):
            for y in range(h):
                if max(pix[x, y]) < threshold:
                    pix[x, y] = pix[min(x + 1, w - 1), y]
        for x in reversed(range(w - edge_width, w)):
            for y in range(h):
                if max(pix[x, y]) < threshold:
                    pix[x, y] = pix[max(x - 1, 0), y]
        for y in range(edge_width):
            for x in range(w):
                if max(pix[x, y]) < threshold:
                    pix[x, y] = pix[x, min(y + 1, h - 1)]
        for y in reversed(range(h - edge_width, h)):
            for x in range(w):
                if max(pix[x, y]) < threshold:
                    pix[x, y] = pix[x, max(y - 1, 0)]

    img.save(image_path, "PNG")


def _draw_bbox_and_save(image_path: str, bbox: tuple[float, float, float, float], out_path: Path) -> None:
    """在图片上画 bbox 红框并保存。bbox 为 0–1 比例 (x_min, y_min, x_max, y_max)。"""
    from PIL import Image, ImageDraw
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    x_min, y_min, x_max, y_max = bbox
    left = max(0, min(int(x_min * w), w - 2))
    top = max(0, min(int(y_min * h), h - 2))
    right = max(left + 2, min(int(x_max * w), w))
    bottom = max(top + 2, min(int(y_max * h), h))
    draw = ImageDraw.Draw(img)
    draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))


def _crop_step5_to_canvas(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    preset: str | None = None,
    subject_bbox_norm: tuple[float, float, float, float] | None = None,
    context_prompt: str | None = None,
) -> None:
    """
    A5：根据 A4 输出（tianchong）使用 Gemini Vision（与 A2 相同逻辑：SUBJECT_PROMPT_BBOX）识别主体 bbox；
    若检测失败则报错结束流程，不做回退。
    然后读取规范安全区 → 主体 bbox 等比缩放到安全区 90%，中心对齐后裁切。始终保存到 output_path。
    subject_bbox_norm: 外部传入的共用 bbox (x_min, y_min, x_max, y_max)（0~1），不为 None 时跳过 Vision 检测。
    context_prompt: 可选，原始生图描述，帮助 Vision 更准确识别主体。
    """
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    if (W, H) == (width, height):
        shutil.copy2(image_path, output_path)
        print(f"Step 5 裁切: 尺寸已为 {width}×{height}，复制 → {output_path}", flush=True)
        return

    # 1) 识别主体 bbox：外部传入时直接使用，否则调用 Gemini Vision
    from PIL import ImageDraw
    if subject_bbox_norm is not None:
        bbox = subject_bbox_norm
        print(f"Step 5 裁切: 使用共用 bbox {bbox}", flush=True)
    else:
        from gemini_subject_detect import detect_subject_bbox
        bbox = detect_subject_bbox(image_path, context_prompt=context_prompt)
        if bbox is None:
            raise RuntimeError("A5 主体 bbox 检测失败，无法继续")

    # 2) 读取规范安全区（preset 可覆盖同画布默认，如 legend_top_banner_3840）
    safe = get_safe_zone(width, height, preset)
    if safe is None:
        safe_cx, safe_cy = width / 2.0, height / 2.0
        safe_w, safe_h = float(width), float(height)
        x_min_s, x_max_s, y_min_s, y_max_s = 0, width, 0, height
    else:
        x_min_s, x_max_s, y_min_s, y_max_s = safe
        safe_cx = (x_min_s + x_max_s) / 2.0
        safe_cy = (y_min_s + y_max_s) / 2.0
        safe_w = x_max_s - x_min_s
        safe_h = y_max_s - y_min_s

    x_min, y_min, x_max, y_max = bbox
    # 不再对 bbox 做宽高交换：规范要求模型返回 x_min,y_min,x_max,y_max，主体应完整落在框内
    bw = (x_max - x_min) * W
    bh = (y_max - y_min) * H
    if bw < 1 or bh < 1:
        bw, bh = 1.0, 1.0
    cx = (x_min + x_max) / 2 * W
    cy = (y_min + y_max) / 2 * H

    # 3) 红框中心对齐安全区中心，红框内缩放到安全区 90%；bbox 严格落在安全区内，允许裁切缩放图超出画布部分，空白由 Step 6 填充（方案 A）
    SAFE_ZONE_SCALE = 0.90
    target_bw = safe_w * SAFE_ZONE_SCALE
    target_bh = safe_h * SAFE_ZONE_SCALE
    scale = min(target_bw / bw, target_bh / bh)
    w1 = max(1, int(round(W * scale)))
    h1 = max(1, int(round(H * scale)))
    img_scaled = img.resize((w1, h1), Image.Resampling.LANCZOS)
    cx_scaled = cx * scale
    cy_scaled = cy * scale
    x0 = safe_cx - cx_scaled
    y0 = safe_cy - cy_scaled
    # 位置限制：缩放后 bbox 必须完整落在安全区内（不裁 bbox）；允许缩放图超出画布，超出部分裁掉
    left_s = x_min * w1
    right_s = x_max * w1
    top_s = y_min * h1
    bottom_s = y_max * h1
    x0 = max(x_min_s - left_s, min(x_max_s - right_s, x0))
    y0 = max(y_min_s - top_s, min(y_max_s - bottom_s, y0))

    # A5 裁切前：在 tianchong 上画红框（主体 bbox）与蓝框（目标安全区在 tianchong 上的对应区域）并保存
    img_vis = img.copy()
    draw = ImageDraw.Draw(img_vis)
    left = max(0, min(int(x_min * W), W - 2))
    top = max(0, min(int(y_min * H), H - 2))
    right = max(left + 2, min(int(x_max * W), W))
    bottom = max(top + 2, min(int(y_max * H), H))
    draw.rectangle([left, top, right, bottom], outline=(255, 0, 0), width=4)
    if safe is not None and scale > 0:
        (x_min_s, x_max_s, y_min_s, y_max_s) = safe
        left_s = int((x_min_s - safe_cx) / scale + cx)
        top_s = int((y_min_s - safe_cy) / scale + cy)
        right_s = int((x_max_s - safe_cx) / scale + cx)
        bottom_s = int((y_max_s - safe_cy) / scale + cy)
        draw.rectangle([max(0, left_s), max(0, top_s), min(W, right_s), min(H, bottom_s)], outline=(0, 0, 255), width=3)
    out_preview = Path(output_path).parent / "a5_bbox_preview.png"
    out_preview.parent.mkdir(parents=True, exist_ok=True)
    img_vis.save(str(out_preview), "PNG")
    print(f"Step 5 裁切前主体识别区域（红框=主体，蓝框=安全区）→ {out_preview}", flush=True)

    # 将缩放图与画布重叠部分贴到画布（bbox 已在安全区内，超出画布部分裁掉），留白由 Step 6 填充
    # 虚拟摆放：缩放图左上角在画布 (x0,y0)，使主体中心落在安全区中心。画布可见 [0,W)×[0,H)。
    # 画布 (dx,dy) 对应源 (dx-x0, dy-y0)。x0<0 时需从源图向右偏移取样：src_left=-x0（不可用 -dest_left，否则 x0<0 时恒为 0 变成「左上角裁切」）。
    rx0 = round(x0)
    ry0 = round(y0)
    dest_left = max(0, rx0)
    dest_top = max(0, ry0)
    src_left = max(0, -rx0)
    src_top = max(0, -ry0)
    avail_w = width - dest_left
    avail_h = height - dest_top
    src_right = min(w1, src_left + avail_w)
    src_bottom = min(h1, src_top + avail_h)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    if src_right > src_left and src_bottom > src_top:
        patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
        canvas.paste(patch, (dest_left, dest_top))
    canvas.save(output_path, "PNG")
    print(
        f"Step 5 裁切: 主体 bbox 缩放至安全区 90%，bbox 严格落安全区内，中心 ({cx_scaled:.0f},{cy_scaled:.0f}) 对齐安全区 ({safe_cx:.0f},{safe_cy:.0f})，空白由 Step 6 填充",
        flush=True,
    )
    print(f"Step 5 产出: {W}×{H} → 缩放 {w1}×{h1} → 贴图 {width}×{height} → {output_path}", flush=True)


# 商店专题长图 3320×460：画布 3320×500，顶部 y=0-40 纯白 #FFFFFF；
# BiRefNet 抠图区域为 x=1032-2464、y=0-200（与 WIDE_STRIP_BIREFNET_* 一致）。

def _safe_print(msg: str) -> None:
    """Windows GBK 控制台安全 print：emoji / 非 ASCII 字符遇到编码不支持时自动替换为 '?'，
    确保 except 块内的 print 不会因 UnicodeEncodeError 再次抛出异常，吞掉正常的返回值。"""
    try:
        print(msg, flush=True)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            print(msg.encode("gbk", errors="replace").decode("gbk"), flush=True)
        except Exception:
            pass  # 完全静默，绝不再抛出

WIDE_CANVAS_SIZE = (3320, 500)
WIDE_TOP_STRIP_H = 40
# 顶部条带内容区域（Gemini 回退）：x=1470-2464；BiRefNet 单独用 WIDE_STRIP_BIREFNET_*
WIDE_TOP_STRIP_X_MIN = 1470
WIDE_TOP_STRIP_X_MAX = 2464
WIDE_STRIP_BIREFNET_X_MIN = 1032
WIDE_STRIP_BIREFNET_X_MAX = 2464
WIDE_STRIP_BIREFNET_Y_MIN = 0
WIDE_STRIP_BIREFNET_Y_MAX = 200

# 商店专题头图（规范命名「专题头图 1740x220」）：专属 A6b 画质流程
SHOP_TOPIC_HEADER_SIZE = (1740, 220)
# A6b：一检一修后可二检二修（每轮修复后复检，最多修复本次数）
A6B_MAX_REPAIR_ROUNDS = 2

from _backends import _generate_sentinel_mask

# sentinel 残留告警阈值（占总像素 H*W 的比例）；超过即打印警告（不阻断流程）
SENTINEL_RESIDUE_WARN_PCT = float(os.environ.get("SENTINEL_RESIDUE_WARN_PCT", "0.02"))


def _warn_sentinel_residue(image_path: str, label: str, max_pct: float | None = None) -> float:
    """扫描图片中 sentinel 色 (1,0,254) 残留占比（分母为像素数 H*W）。

    超过阈值时打印明确警告但不阻断流程（由人工判断是否重跑）。
    返回实际占比（0~1）；读取/计算失败返回 0.0。
    """
    if max_pct is None:
        max_pct = SENTINEL_RESIDUE_WARN_PCT
    try:
        import numpy as np
        from PIL import Image as _Img
        arr = np.array(_Img.open(image_path).convert("RGB"))
        mask = (arr[:, :, 0] == 1) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 254)
        pct = float(mask.sum()) / float(arr.shape[0] * arr.shape[1])
        if pct > max_pct:
            print(
                f"  SENTINEL_WARN [{label}] {pct*100:.1f}% sentinel residue (threshold {max_pct*100:.0f}%), fill may have failed, check manually",
                flush=True,
            )
        return pct
    except Exception:
        return 0.0


def _strip_direct_to_canvas(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
) -> None:
    """Strip (1740×220) fast path: composite subject directly to target canvas,
    then Gemini fills blank areas in one shot. Eliminates A4→A5 3-segment stitching."""
    from PIL import Image
    from safe_zone_scale_composite import composite_to_canvas_center
    from gemini_image_edit import edit_image, STRIP_DIRECT_FILL_PROMPT, A6B_SHOP_HEADER_EXTEND_PROMPT
    from gemini_subject_detect import image_a6b_shop_header_need_repair
    import tempfile
    import os

    safe = get_safe_zone(width, height)
    if safe is None:
        raise ValueError(f"No safe zone for {width}×{height}")
    safe_x0, safe_x1, safe_y0, safe_y1 = safe
    safe_cx = (safe_x0 + safe_x1) / 2
    safe_cy = (safe_y0 + safe_y1) / 2

    # S4: Place subject on target canvas with sentinel color (0,0,1)
    print("Step S4 / strip: 主体直贴到 1740×220 画布 (绕过 A4 2048×512)...", flush=True)

    fd, temp_canvas = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        composite_to_canvas_center(
            image_path, temp_canvas,
            canvas_w=width, canvas_h=height,
            subject_bbox=bbox,
            subject_ratio=0.8,
            center_x_ratio=safe_cx / width,
            center_y_ratio=safe_cy / height,
        )

        # S5: Fill the target canvas with mask protection
        print("Step S5 / strip: 生成 sentinel mask 并延展填充 1740×220 画布...", flush=True)
        mask_path = _generate_sentinel_mask(temp_canvas)
        try:
            if BANNER_IMAGE_BACKEND == "packygpt":
                _packygpt_edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "micugpt2":
                _micugpt2_edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT)
            elif BANNER_IMAGE_BACKEND == "moxingpt":
                _moxingpt_edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xingchengpt":
                edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT, keep_returned_size=True, mask_path=mask_path)
            elif BANNER_IMAGE_BACKEND == "xinchengpt":
                _xinchengpt_edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT, keep_returned_size=True)
            else:
                edit_image(temp_canvas, output_path, STRIP_DIRECT_FILL_PROMPT, keep_returned_size=True, mask_path=mask_path)
        finally:
            if os.path.isfile(mask_path):
                try:
                    os.unlink(mask_path)
                except OSError:
                    pass
    except Exception as e:
        print(f"  strip 填充失败: {e}", file=sys.stderr)
        import shutil
        try:
            shutil.copy2(temp_canvas, output_path)
        except Exception:
            pass
        raise
    finally:
        if os.path.isfile(temp_canvas):
            try:
                os.unlink(temp_canvas)
            except OSError:
                pass

    # S6: Quality check + one repair round if needed
    print("Step S6 / strip: 画质检测（接缝/割裂）...", flush=True)
    need_repair = image_a6b_shop_header_need_repair(output_path)
    if need_repair:
        print("  S6: 检测到接缝，进行一次修复...", flush=True)
        try:
            if BANNER_IMAGE_BACKEND == "packygpt":
                _packygpt_edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                    keep_returned_size=True,
                )
            elif BANNER_IMAGE_BACKEND == "micugpt2":
                _micugpt2_edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                )
            elif BANNER_IMAGE_BACKEND == "moxingpt":
                _moxingpt_edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                    keep_returned_size=True,
                )
            elif BANNER_IMAGE_BACKEND == "xingchengpt":
                _xingchengpt_edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                    keep_returned_size=True,
                )
            elif BANNER_IMAGE_BACKEND == "xinchengpt":
                _xinchengpt_edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                    keep_returned_size=True,
                )
            else:
                edit_image(
                    output_path, output_path,
                    A6B_SHOP_HEADER_EXTEND_PROMPT,
                    keep_returned_size=True,
                )
            need_final = image_a6b_shop_header_need_repair(output_path)
            if need_final is False:
                print("  S6: 修复后复检通过。", flush=True)
            elif need_final is True:
                print("  S6: 修复后复检仍不通过（建议人工检查）。", flush=True)
            else:
                print("  S6: 复检未返回明确结果。", flush=True)
        except Exception as e:
            print(f"  S6 修复失败（保留当前产出）: {e}", file=sys.stderr)
    elif need_repair is False:
        print("  S6: 通过。", flush=True)
    else:
        print("  S6: 检测未返回明确结果。", flush=True)
    _warn_sentinel_residue(output_path, "strip 1740x220")


def _direct_to_canvas(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    bbox: tuple[float, float, float, float],
    width_fit: bool = False,
) -> None:
    """通用直达画布路径：主体直接贴到目标画布 → API 填补空白 → 检测修补。
    绕过 A4 2048×512，适用于非专属流程的标准预设。
    width_fit=True 时按宽匹配安全区缩放，超出画布的顶/底自动裁切。"""
    from PIL import Image
    from safe_zone_scale_composite import composite_to_canvas_center
    from gemini_image_edit import edit_image, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, A6B_SHOP_HEADER_EXTEND_PROMPT
    from gemini_subject_detect import image_has_unfilled_blanks
    import tempfile
    import os

    safe = get_safe_zone(width, height)
    if safe is None:
        raise ValueError(f"No safe zone for {width}×{height}")
    safe_x0, safe_x1, safe_y0, safe_y1 = safe
    safe_cx = (safe_x0 + safe_x1) / 2
    safe_cy = (safe_y0 + safe_y1) / 2

    if width_fit:
        safe_w = safe_x1 - safe_x0
        s_ratio = safe_w / width
        fit_mode = True
        print(f"Step S4 / 直达画布: 按宽匹配安全区 主体直贴到 {width}×{height} (subject_ratio={s_ratio:.3f}, width_fit)...", flush=True)
    else:
        s_ratio = 0.85
        fit_mode = False
        print(f"Step S4 / 直达画布: 主体直贴到 {width}×{height} (subject_ratio={s_ratio})...", flush=True)

    fd, temp_canvas = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        composite_to_canvas_center(
            image_path, temp_canvas,
            canvas_w=width, canvas_h=height,
            subject_bbox=bbox,
            subject_ratio=s_ratio,
            center_x_ratio=safe_cx / width,
            center_y_ratio=safe_cy / height,
            fit_width_only=fit_mode,
        )

        # S5: Fill the target canvas with mask protection
        print(f"Step S5 / 生成 sentinel mask 并延展填充 {width}×{height}...", flush=True)
        mask_path = _generate_sentinel_mask(temp_canvas)
        try:
            if BANNER_IMAGE_BACKEND == "packygpt":
                _packygpt_edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "micugpt2":
                _micugpt2_edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT)
            elif BANNER_IMAGE_BACKEND == "moxingpt":
                _moxingpt_edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xingchengpt":
                edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True, mask_path=mask_path)
            elif BANNER_IMAGE_BACKEND == "xinchengpt":
                _xinchengpt_edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            else:
                edit_image(temp_canvas, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True, mask_path=mask_path)
        finally:
            if os.path.isfile(mask_path):
                try:
                    os.unlink(mask_path)
                except OSError:
                    pass

        # Post-check: verify output dimensions
        try:
            post = Image.open(output_path)
            if post.size != (width, height):
                print(f"  S5: 返回 {post.size[0]}×{post.size[1]}，缩放至 {width}×{height}...", flush=True)
                post = post.resize((width, height), Image.Resampling.LANCZOS)
                post.save(output_path, "PNG")
            post.close()
        except Exception:
            pass

    except Exception as e:
        print(f"  直达画布填充失败: {e}", file=sys.stderr)
        import shutil
        try:
            shutil.copy2(temp_canvas, output_path)
        except Exception:
            pass
        raise
    finally:
        if os.path.isfile(temp_canvas):
            try:
                os.unlink(temp_canvas)
            except OSError:
                pass

    # S6: Quality check + one repair round
    print("Step S6 / 画质检测（未填充区域）...", flush=True)
    has_unfilled = image_has_unfilled_blanks(output_path)
    if has_unfilled is None:
        from gemini_image_edit import image_has_black_bars_full_image, image_has_black_bars
        has_unfilled = image_has_black_bars_full_image(output_path) or image_has_black_bars(output_path)
    if has_unfilled:
        print("  S6: 检测到未填充区域，进行一次修复...", flush=True)
        try:
            if BANNER_IMAGE_BACKEND == "packygpt":
                _packygpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "micugpt2":
                _micugpt2_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT)
            elif BANNER_IMAGE_BACKEND == "moxingpt":
                _moxingpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xingchengpt":
                edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xinchengpt":
                _xinchengpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            else:
                edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            print("  S6: 修复完成。", flush=True)
        except Exception as e:
            print(f"  S6 修复失败（保留当前产出）: {e}", file=sys.stderr)
    elif has_unfilled is False:
        print("  S6: 通过。", flush=True)
    else:
        print("  S6: 检测未返回明确结果。", flush=True)
    _warn_sentinel_residue(output_path, f"direct_to_canvas {width}x{height}")


def _wide_side_fill_api_enabled() -> bool:
    """wide 两侧空隙是否走 sentinel+mask API 延展填充（默认开）；设 WIDE_SIDE_FILL_API=0 回退纯 edge-pad。"""
    v = os.environ.get("WIDE_SIDE_FILL_API", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _wide_auto_top_poke_enabled() -> bool:
    """A5b 前是否自动探测主体顶部并上移使其探入白条（默认开）；设 WIDE_AUTO_TOP_POKE=0 关闭。
    仅当用户未显式设置 WIDE_TOP_EXTEND_PX（手动模式优先）时生效。"""
    if os.environ.get("WIDE_TOP_EXTEND_PX", "").strip() not in ("", "0"):
        return False  # 用户手动指定了 extend，尊重手动值
    v = os.environ.get("WIDE_AUTO_TOP_POKE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _detect_content_top_row(canvas_rgb, x0: int, x1: int, scan_h: int) -> int | None:
    """
    背景差异法检测主体真实顶行（不依赖 BiRefNet）。
    专题长图主体（柜子/人物/物件）在暗底/纯色底上呈明显亮度或色彩差异，
    从两侧极窄边列估计背景色，再找抠图区内首个与背景差异显著的行。

    对 BiRefNet 在全景超宽图上漏判上半主体（把顶行判成 y=200+）是稳健兜底/替代。

    canvas_rgb：整张画布 PIL.Image（RGB）
    x0, x1：抠图区横向范围
    scan_h：向下扫描的高度（像素）
    返回：主体真实顶行 y（相对画布顶部），检测失败返回 None
    """
    import numpy as np
    try:
        w, h = canvas_rgb.size
        x0 = max(0, min(x0, w - 1))
        x1 = max(x0 + 1, min(x1, w))
        scan_h = max(1, min(scan_h, h))
        reg = np.asarray(canvas_rgb.convert("RGB"), dtype=np.int16)[:scan_h, x0:x1]
        rw = reg.shape[1]
        # 从两侧极窄边列（各 4%，至少 8px）估计背景色中位数
        edge = max(8, int(rw * 0.04))
        side = np.concatenate(
            [reg[:, :edge].reshape(-1, 3), reg[:, -edge:].reshape(-1, 3)], axis=0
        )
        bg = np.median(side, axis=0)
        # 与背景色的最大通道差 > 阈值即视为前景
        dist = np.abs(reg - bg).max(axis=2)
        thr = int(os.environ.get("WIDE_TOP_POKE_BG_DIST", "45").strip() or "45")
        fg = dist > thr
        # 排除已铺白的白条行（min 通道 > 235）
        mn = reg.min(axis=2)
        fg = fg & (mn <= 235)
        rows = fg.sum(axis=1)
        min_cols = max(15, int(rw * 0.01))  # 至少 1% 宽或 15 列，滤噪
        nz = np.where(rows > min_cols)[0]
        if len(nz) == 0:
            return None
        return int(nz[0])
    except Exception:
        return None


def _wide_auto_top_poke(canvas_path: str) -> None:
    """
    A5b 前置：检测主体真实顶行，若主体够不到顶部白条（y=0-40），
    则把整张画布上移使主体顶部探入白条约 WIDE_TOP_POKE_TARGET 像素处（底部 edge 延展补齐）。
    自适应内容（API 两侧填充每次主体位置略变），无需手调 WIDE_TOP_EXTEND_PX。

    顶行检测优先用背景差异法（_detect_content_top_row，对全景超宽图稳健）；
    背景差异法失败时回退 BiRefNet 顶行。检测失败或已探入则原样保留。
    """
    from PIL import Image
    import numpy as np

    try:
        img = Image.open(canvas_path).convert("RGB")
        w, h = img.size
        if (w, h) != WIDE_CANVAS_SIZE:
            return
        strip_h = WIDE_TOP_STRIP_H
        x0, x1 = WIDE_STRIP_BIREFNET_X_MIN, WIDE_STRIP_BIREFNET_X_MAX
        context_h = min(_wide_a5b_context_h(), h)

        # 优先用背景差异法检测主体真实顶行（对全景超宽图稳健，
        # BiRefNet 常把上半主体漏判成 y=200+ 导致探顶失灵）。
        top_row = _detect_content_top_row(img, x0, x1, context_h)
        _detect_src = "背景差异"
        if top_row is None:
            # 回退 BiRefNet
            from birefnet_matting import load_birefnet_matting, _extract_alpha_region_padded
            model = load_birefnet_matting()
            crop = img.crop((x0, 0, x1, context_h))
            a = np.array(_extract_alpha_region_padded(crop, model=model), dtype=np.float32) / 255.0
            thr = _wide_a5b_alpha_threshold()
            rows = (a >= thr).sum(axis=1)
            # 忽略 <8px 的行噪点，找主体真实顶行
            nz = np.where(rows > 8)[0]
            if len(nz) == 0:
                print("  wide 自动探顶：抠图区未检出主体，跳过上移", flush=True)
                return
            top_row = int(nz[0])
            _detect_src = "BiRefNet"
        target = int(os.environ.get("WIDE_TOP_POKE_TARGET", "12").strip() or "12")
        # 已探入足够（顶行在白条内且高于 target）则不动
        if top_row <= target:
            print(f"  wide 自动探顶：主体顶行 y={top_row} 已探入白条，无需上移", flush=True)
            return
        shift = min(top_row - target, 120)  # 上移量，封顶 120px 防主体底部大量丢失
        arr = np.array(img)
        # 上移 shift：取 [shift:] 行，底部用 edge 延展补 shift 行
        arr_shifted = np.pad(arr[shift:, :, :], ((0, shift), (0, 0), (0, 0)), mode="edge")
        Image.fromarray(arr_shifted).save(canvas_path, "PNG")
        print(f"  wide 自动探顶（{_detect_src}）：主体顶行 y={top_row} → 上移 {shift}px 使其探入白条（target≈{target}）", flush=True)
    except Exception as e:
        print(f"  wide 自动探顶失败（跳过）：{e}", file=sys.stderr, flush=True)


def _wide_fill_sides_via_api(img_scaled, paste_x: int, paste_y: int, target_w: int, target_h: int):
    """
    wide 两侧空隙用 sentinel+mask API 延展填充，替代 edge-pad 拉伸。
    - 空隙区填 sentinel (1,0,254)，缩放图按 (paste_x, paste_y) 贴入（超出裁掉）；
    - 生成 mask（sentinel→透明可编辑，主体+已有背景→不透明保留）；
    - 按 BANNER_IMAGE_BACKEND 分发 edit_image / gpt-image-2 编辑，仅填两翼；
    - 尺寸兜底 cover-scale + center-crop；sentinel 残留超阈值或异常时返回 None（调用方回退 edge-pad）。
    成功返回 PIL.Image（target_w×target_h），失败返回 None。
    """
    from PIL import Image
    import numpy as np
    from gemini_image_edit import edit_image, OUTPAINT_FILL_REMAINING_BLACK_PROMPT

    # 1) sentinel 画布 + 贴入缩放图
    canvas = Image.new("RGB", (target_w, target_h), (1, 0, 254))
    sw, sh = img_scaled.size
    src_left = max(0, -paste_x)
    src_top = max(0, -paste_y)
    src_right = min(sw, target_w - paste_x)
    src_bottom = min(sh, target_h - paste_y)
    if src_right <= src_left or src_bottom <= src_top:
        return None
    patch = img_scaled.crop((src_left, src_top, src_right, src_bottom))
    canvas.paste(patch, (max(0, paste_x), max(0, paste_y)))

    fd, temp_canvas = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    mask_path = None
    fd2, temp_out = tempfile.mkstemp(suffix=".png")
    os.close(fd2)
    try:
        canvas.save(temp_canvas, "PNG")
        mask_path = _generate_sentinel_mask(temp_canvas)

        # wide 两翼是「保护主体只填两翼」的精细活，固定走 Gemini 系 edit_image（像素级 mask 最可靠），
        # 不跟随 gpt-image-2 生图后端（chat/completions 弱 mask 易整体重绘导致主体偏移）。
        # edit_image 内部按 key 路由：moxingpt+MOXINGEMINI→moxingemini、xingchengpt+XINGCHENGEMINI→xingchengemini、
        # micugemini→micugemini、其余→默认 Gemini generateContent（均支持 mask）。
        print(f"  wide_from_fill: 两侧 sentinel+mask API 延展填充（Gemini 系 edit_image，backend={BANNER_IMAGE_BACKEND}）...", flush=True)
        edit_image(temp_canvas, temp_out, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True, mask_path=mask_path)

        if not os.path.isfile(temp_out):
            return None
        out_img = Image.open(temp_out).convert("RGB")
        # 2) 尺寸兜底：cover-scale + center-crop（禁止直接 resize 拉伸）
        if out_img.size != (target_w, target_h):
            ow, oh = out_img.size
            scale = max(target_w / ow, target_h / oh)
            rw, rh = int(round(ow * scale)), int(round(oh * scale))
            out_img = out_img.resize((rw, rh), Image.Resampling.LANCZOS)
            cx0 = (rw - target_w) // 2
            cy0 = (rh - target_h) // 2
            out_img = out_img.crop((cx0, cy0, cx0 + target_w, cy0 + target_h))
            print(f"  wide_from_fill: API 返回 {ow}×{oh} → cover-crop 到 {target_w}×{target_h}", flush=True)
        # 3) sentinel 残留检查
        arr = np.array(out_img)
        sentinel = (arr[:, :, 0] == 1) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 254)
        pct = float(sentinel.sum()) / float(arr.shape[0] * arr.shape[1])
        if pct > 0.02:
            print(f"  wide_from_fill: API 填充后 sentinel 残留 {pct*100:.1f}% > 2%，判定失败 → 回退 edge-pad", flush=True)
            return None
        return out_img
    except Exception as e:
        print(f"  wide_from_fill: 两侧 API 填充失败（{e}）→ 回退 edge-pad", file=sys.stderr, flush=True)
        return None
    finally:
        for _p in (temp_canvas, temp_out, mask_path):
            if _p and os.path.isfile(_p):
                try:
                    os.unlink(_p)
                except OSError:
                    pass


def _wide_refine_bbox_bg_diff(image_path: str, iw: int, ih: int):
    """
    背景差异法收紧 bbox（不依赖 BiRefNet/网络）。
    从图像两侧极窄边列估计背景色，找前景像素的紧凑外接矩形，加松框边距返回归一化 bbox。
    失败返回 None。
    """
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        a = np.array(img).astype(np.int16)
        edge = max(10, int(iw * 0.025))
        side = np.concatenate(
            [a[:, :edge].reshape(-1, 3), a[:, -edge:].reshape(-1, 3)], axis=0
        )
        bg = np.median(side, axis=0)
        thr = int(os.environ.get("WIDE_TOP_POKE_BG_DIST", "45").strip() or "45")
        diff = np.abs(a - bg).max(axis=2)
        # 排除近白区（已铺白的白条或高光背景）
        mn = a.min(axis=2)
        fg = (diff > thr) & (mn <= 230)
        ys, xs = np.where(fg)
        if len(xs) < 50:
            return None
        # 松框边距
        mx, my = 0.04, 0.02
        rb = (
            max(0.0, float(xs.min()) / iw - mx),
            max(0.0, float(ys.min()) / ih - my),
            min(1.0, float(xs.max()) / iw + mx),
            min(1.0, float(ys.max()) / ih + my),
        )
        return rb
    except Exception:
        return None


def _wide_refine_bbox_if_suspicious(image_path: str, bbox):
    """
    bbox 退化守卫：Vision 有时返回近全帧框（如 y 跨度>=0.95 / x 跨度>=0.98），
    对齐时会把整幅当主体 -> 溢出安全区/白条空。

    策略（双重收紧）：
    1. 背景差异法（_wide_refine_bbox_bg_diff）：纯离线，稳健，不依赖模型。
       对深色底/纯色底（柜子、产品图）效果好。
    2. BiRefNet 法：模型感知，适合复杂背景。在背景差异法之后作为补充。
    3. 取两者并集（union bbox）作为最终框：宁松勿紧，避免任一方漏框主体部件。

    零 API；BiRefNet 不可用时退化到背景差异法单路；两者均失败则原样返回。
    可用 WIDE_BBOX_REFINE=0 关闭。
    """
    if os.environ.get("WIDE_BBOX_REFINE", "1").strip().lower() in ("0", "false", "no", "off"):
        return bbox
    x_min, y_min, x_max, y_max = bbox
    suspicious = (y_max - y_min) >= 0.95 or (x_max - x_min) >= 0.98
    if not suspicious:
        return bbox

    import numpy as np
    from PIL import Image
    try:
        img_check = Image.open(image_path)
        iw, ih = img_check.size
        img_check.close()
    except Exception as e:
        print(f"  wide_from_fill: bbox refine 读图失败（{e}），沿用原 bbox", flush=True)
        return bbox

    # ── 1. 背景差异法 ──
    bg_bbox = _wide_refine_bbox_bg_diff(image_path, iw, ih)
    _safe_print(f"  wide_from_fill: bbox refine bg-diff => {tuple(round(v,3) for v in bg_bbox) if bg_bbox else None}")

    # ── 2. BiRefNet 法 ──
    br_bbox = None
    try:
        from birefnet_matting import load_birefnet_matting, extract_alpha_pil
        arr = np.array(Image.open(image_path).convert("RGB"))
        side = max(iw, ih)
        pad_b, pad_r = side - ih, side - iw
        if pad_b > 0 or pad_r > 0:
            arr = np.pad(arr, ((0, pad_b), (0, pad_r), (0, 0)), mode="reflect")
        model = load_birefnet_matting()
        a = np.array(extract_alpha_pil(Image.fromarray(arr, "RGB"), model=model))[:ih, :iw]
        ys, xs = np.where(a > 100)
        if len(xs) >= 50:
            nx0, nx1 = float(xs.min()) / iw, float(xs.max()) / iw
            ny0, ny1 = float(ys.min()) / ih, float(ys.max()) / ih
            # 若 BiRefNet 仍返回近全帧（真主体确实占满），视为无有效收紧
            if not ((ny1 - ny0) >= 0.95 and (nx1 - nx0) >= 0.95):
                mx2, my2 = 0.03, 0.01
                br_bbox = (
                    max(0.0, nx0 - mx2), max(0.0, ny0 - my2),
                    min(1.0, nx1 + mx2), min(1.0, ny1 + my2),
                )
        _safe_print(f"  wide_from_fill: bbox refine BiRefNet => {tuple(round(v,3) for v in br_bbox) if br_bbox else None}")
    except Exception as e:
        _safe_print(f"  wide_from_fill: bbox refine BiRefNet 失败（{e}）")

    # ── 3. 取并集 ──
    candidates = [b for b in (bg_bbox, br_bbox) if b is not None]
    if not candidates:
        _safe_print("  wide_from_fill: bbox refine 两路均无结果，沿用原 bbox")
        return bbox

    # 并集：取所有候选框的最宽范围（宁松勿紧）
    ux0 = min(b[0] for b in candidates)
    uy0 = min(b[1] for b in candidates)
    ux1 = max(b[2] for b in candidates)
    uy1 = max(b[3] for b in candidates)
    rb = (ux0, uy0, ux1, uy1)

    # 若并集框仍≈全帧，说明无法收紧（主体真的占满），不改原始 bbox
    if (rb[3] - rb[1]) >= 0.95 and (rb[2] - rb[0]) >= 0.95:
        _safe_print(f"  wide_from_fill: bbox refine 并集仍≈全帧，沿用原 bbox")
        return bbox

    _safe_print(
        f"  wide_from_fill: [!] suspicious bbox {tuple(round(v,3) for v in bbox)}"
        f" -> refined (union) {tuple(round(v,3) for v in rb)}"
    )
    return rb


def wide_from_fill(fill_image_path: str, output_path: str, bbox_file: str | None = None) -> None:
    """
    专题长图 3320×500 背景合成。默认 bg-direct：fill_image_path 传 bg.png（去干扰后），
    bbox 传 shared_subject_bbox.txt（bg 上检测）；不再依赖 tianchong/A4。
    （WIDE_KEEP_TIANCHONG=1 时上游会改传 tianchong.png，本函数逻辑不变。）

    1. 读取 bbox
    2. fit-to-safe-zone 缩放（bbox 贴合安全区，WIDE_FIT_RATIO 留边距）+ 退化 bbox 守卫
    3. bbox 中心对齐安全区中心 (1967,250)；两侧空隙走 sentinel+mask API 填充（失败回退 edge-pad）
    4. crop/合成 3320×500
    5. A5b 顶部 40px 白条 BiRefNet 抠图（主体顶探入白条）
    """
    from PIL import Image

    target_w, target_h = WIDE_CANVAS_SIZE
    safe_x0, safe_x1, safe_y0, safe_y1 = (1470, 2464, 0, 500)
    safe_cx = (safe_x0 + safe_x1) / 2  # 1967
    safe_cy = (safe_y0 + safe_y1) / 2  # 250

    # 步骤 1：bbox
    bbox = None
    if bbox_file and Path(bbox_file).is_file():
        try:
            parts = Path(bbox_file).read_text(encoding="utf-8").strip().split(",")
            if len(parts) == 4:
                bbox = tuple(float(v) for v in parts)
                print(f"  wide_from_fill: bbox {bbox}", flush=True)
        except Exception as e:
            print(f"  wide_from_fill: bbox 文件解析失败 ({e})", flush=True)
    if bbox is None:
        from gemini_subject_detect import detect_subject_bbox
        print("  wide_from_fill: 检测 bbox...", flush=True)
        bbox = detect_subject_bbox(fill_image_path)
        if bbox is None:
            bbox = (0.3, 0.1, 0.9, 0.9)
            print(f"  wide_from_fill: 默认 bbox {bbox}", flush=True)

    x_min, y_min, x_max, y_max = bbox
    # bbox 退化守卫：Vision 返回近全帧框时，用 BiRefNet 在源图上复核收紧
    bbox = _wide_refine_bbox_if_suspicious(fill_image_path, bbox)
    x_min, y_min, x_max, y_max = bbox
    # sentinel 残留检测（除数必须用像素数 H*W，不能用 .size=H*W*3，否则占比被缩小 3 倍导致漏检）
    _warn_sentinel_residue(fill_image_path, "wide_from_fill(tianchong)")

    img = Image.open(fill_image_path).convert("RGB")
    iw, ih = img.size

    # 步骤 2：bbox 缩放到贴合安全区（高优先），使主体完整落安全区内，左侧/右侧空隙用 edge 延展背景填充
    # FIT_RATIO<1 留边距，吸收 bbox 与真实主体轮廓的偏差，避免主体轻微溢出安全区
    fit_ratio = float(os.environ.get("WIDE_FIT_RATIO", "0.9").strip() or "0.9")
    bbox_w_norm = x_max - x_min
    bbox_h_norm = y_max - y_min
    safe_w = safe_x1 - safe_x0
    safe_h = safe_y1 - safe_y0
    cover_scale = max(target_w / iw, target_h / ih)

    # 退化 bbox 守卫：检测失败常返回近全图 (0,0,1,1)。此时无可靠主体可 fit，
    # 若强行 fit-to-safe-zone 会把整张图缩成安全区大小的缩略图（大片 edge-pad）。
    # 回退到 cover 填充 + 图心对齐画布中心（经典 cover-crop 行为）。
    degenerate_bbox = bbox_w_norm >= 0.9 and bbox_h_norm >= 0.9
    if degenerate_bbox:
        fit_scale = cover_scale
        anchor_x_norm, anchor_y_norm = 0.5, 0.5
        align_cx, align_cy = target_w / 2.0, target_h / 2.0
        print(
            f"  wide_from_fill: ⚠ 退化 bbox {(x_min,y_min,x_max,y_max)}（检测失败？）→ 回退 cover 填充 + 图心对齐",
            flush=True,
        )
    else:
        scale_h = safe_h * fit_ratio / max(1e-6, bbox_h_norm * ih)  # 等高（留边距）
        scale_w = safe_w * fit_ratio / max(1e-6, bbox_w_norm * iw)  # 等宽（留边距）
        fit_scale = scale_h  # 高度优先贴合，保证主体纵向完整
        bbox_w_s = bbox_w_norm * iw * fit_scale
        # 如果水平也装不下，进一步缩到等宽
        if bbox_w_s > safe_w * fit_ratio:
            fit_scale = scale_w
        # 保底：fit 不应把图缩到比 cover 还小太多（否则大片 edge-pad）。至少保证能盖住画布高。
        # 例外：bbox 纵跨度>=0.85（接近满高，如柜子/人物贯穿全图），此时 fit-to-safe-zone
        # 已经把主体缩到安全区内，强行套 max(fit_scale, target_h/ih) 会把主体重新撑出安全区。
        # 两侧空隙由 API 填充或 edge-pad 补齐，不依赖"铺满画布高"这个保底。
        if bbox_h_norm < 0.85:
            fit_scale = max(fit_scale, target_h / ih)
        anchor_x_norm, anchor_y_norm = (x_min + x_max) / 2, (y_min + y_max) / 2
        align_cx, align_cy = safe_cx, safe_cy

    # 步骤 3：缩放
    scaled_w = int(round(iw * fit_scale))
    scaled_h = int(round(ih * fit_scale))
    img_scaled_raw = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    img.close()

    # 步骤 3b：锚点（bbox 中心 / 退化时图心）对齐目标中心，计算缩放图在画布上的粘贴偏移
    import numpy as np
    anchor_cx_s = anchor_x_norm * scaled_w
    anchor_cy_s = anchor_y_norm * scaled_h
    paste_x = int(round(align_cx - anchor_cx_s))
    paste_y = int(round(align_cy - anchor_cy_s))

    # WIDE_TOP_EXTEND_PX：正值=主体上移伸入白条 y=0-40（对 paste_y 是负向）
    _extend = int(os.environ.get("WIDE_TOP_EXTEND_PX", "0").strip())
    paste_y -= _extend

    # 步骤 3c：两侧空隙填充。默认走 sentinel+mask API 延展填充（背景自然延续）；
    # 失败/关闭/无空隙/退化 bbox 时回退 np.pad(mode="edge") 拉伸边列。
    pad_left = max(0, paste_x)
    pad_right = max(0, target_w - (paste_x + scaled_w))
    pad_top = max(0, paste_y)
    pad_bottom = max(0, target_h - (paste_y + scaled_h))
    has_gap = (pad_left + pad_right + pad_top + pad_bottom) > 0

    canvas = None
    if has_gap and not degenerate_bbox and _wide_side_fill_api_enabled():
        canvas = _wide_fill_sides_via_api(
            img_scaled_raw, paste_x, paste_y, target_w, target_h
        )

    if canvas is not None:
        print(
            f"  wide_from_fill: {iw}×{ih} → fit {scaled_w}×{scaled_h} (bbox 贴合安全区), "
            f"bbox中心→({safe_cx},{safe_cy}), paste=({paste_x},{paste_y}) "
            f"API-fill L{pad_left} R{pad_right} T{pad_top} B{pad_bottom}"
            f"{' extend +'+str(_extend) if _extend else ''}",
            flush=True,
        )
    else:
        # 回退：edge-pad 拉伸边列
        arr = np.array(img_scaled_raw)
        arr_pad = np.pad(
            arr,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            mode="edge",
        )
        crop_x = pad_left - paste_x
        crop_y = pad_top - paste_y
        canvas = Image.fromarray(
            arr_pad[crop_y:crop_y + target_h, crop_x:crop_x + target_w]
        )
        print(
            f"  wide_from_fill: {iw}×{ih} → fit {scaled_w}×{scaled_h} (bbox 贴合安全区), "
            f"bbox中心→({safe_cx},{safe_cy}), paste=({paste_x},{paste_y}) "
            f"edge-pad L{pad_left} R{pad_right} T{pad_top} B{pad_bottom}"
            f"{' extend +'+str(_extend) if _extend else ''}",
            flush=True,
        )

    # 步骤 4：保存
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    print(f"  wide_from_fill: {target_w}×{target_h} → {output_path}", flush=True)

    # 步骤 4b：自动探顶（若主体够不到白条则上移使其探入）
    if _wide_auto_top_poke_enabled():
        _wide_auto_top_poke(output_path)

    # 步骤 5：A5b
    _composite_wide_top_strip_birefnet(output_path)


def _wide_a5b_context_h() -> int:
    """A5b 抠图/检测使用的上下文源区高度（像素），默认 400；更高利于识别前景，仅贴回最上 40px 白条。"""
    raw = os.environ.get("WIDE_A5B_CONTEXT_H", "").strip()
    if not raw:
        return 400
    try:
        return max(WIDE_STRIP_BIREFNET_Y_MAX, int(float(raw)))
    except ValueError:
        return 400


def _wide_a5b_min_component_area() -> int:
    """A5b 去装饰碎屑的连通域最小面积（像素），默认 3000（游戏角色特效碎片通常 <3000px²）；设 0 关闭过滤。"""
    raw = os.environ.get("WIDE_A5B_MIN_COMPONENT_AREA", "").strip()
    if not raw:
        return 3000
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 3000


def _wide_a5b_semantic_enabled() -> bool:
    """A5b 是否启用 Gemini 语义 keep-mask（默认开）；设 WIDE_A5B_SEMANTIC=0 退回纯 BiRefNet。"""
    v = os.environ.get("WIDE_A5B_SEMANTIC", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _wide_a5b_binarize() -> bool:
    """A5b alpha 是否二值化（默认二值化）；设 WIDE_A5B_NO_BINARIZE=1 保留柔和边缘。"""
    v = os.environ.get("WIDE_A5B_NO_BINARIZE", "").strip().lower()
    return v not in ("1", "true", "yes", "on")


def _build_wide_a5b_keep_mask(img, x0: int, x1: int, y0: int, y1: int, context_prompt: str | None):
    """
    裁 context 区送 Gemini 检测前景物体框，构建该区尺寸的 'L' keep-mask（框内=255）。
    无框或 API 失败返回 None（调用方回退纯 BiRefNet）。
    """
    from PIL import Image, ImageDraw
    import tempfile
    region = img.crop((x0, y0, x1, y1))
    rw, rh = region.size
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    boxes = None
    try:
        region.save(tmp, "PNG")
        from gemini_subject_detect import detect_foreground_objects_bboxes
        boxes = detect_foreground_objects_bboxes(tmp, context_prompt=context_prompt)
    except Exception as e:
        print(f"  A5b 语义前景检测异常（{e}），回退纯 BiRefNet", flush=True)
        boxes = None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass
    if boxes is None:
        print("  A5b 语义前景检测失败/无返回，回退纯 BiRefNet", flush=True)
        return None
    if not boxes:
        print("  A5b 语义前景检测：未发现前景物体，回退纯 BiRefNet 判定", flush=True)
        return None
    mask = Image.new("L", (rw, rh), 0)
    d = ImageDraw.Draw(mask)
    pad_x = max(2, int(rw * 0.01))
    pad_y = max(2, int(rh * 0.02))
    for (bx0, by0, bx1, by1) in boxes:
        px0 = max(0, int(bx0 * rw) - pad_x)
        py0 = max(0, int(by0 * rh) - pad_y)
        px1 = min(rw, int(bx1 * rw) + pad_x)
        py1 = min(rh, int(by1 * rh) + pad_y)
        if px1 > px0 and py1 > py0:
            d.rectangle((px0, py0, px1, py1), fill=255)
    print(f"  A5b 语义前景检测：{len(boxes)} 个前景框 → keep-mask", flush=True)
    return mask


def _content_strip_rgba(img, x0: int, x1: int, y_min: int, strip_h: int, context_h: int):
    """
    A5b 背景差异兜底：BiRefNet 在全景超宽图上漏判上半主体时，
    用背景差异法在抠图区重建顶部白条的前景 RGBA（strip_h 高）。

    从抠图区两侧极窄边列估计背景色，与背景差异显著的像素判为前景，
    竖向做「首个前景行之下连续」约束（只取从顶探入的主体，不显影下方孤立内容）。
    返回 (x1-x0)×strip_h 的 RGBA（PIL），无前景返回 None。
    """
    import numpy as np
    from PIL import Image
    try:
        reg = np.asarray(img.convert("RGB"), dtype=np.int16)[y_min:y_min + context_h, x0:x1]
        band = reg[:strip_h]
        rw = band.shape[1]
        edge = max(8, int(rw * 0.04))
        side = np.concatenate(
            [reg[:, :edge].reshape(-1, 3), reg[:, -edge:].reshape(-1, 3)], axis=0
        )
        bg = np.median(side, axis=0)
        thr = int(os.environ.get("WIDE_TOP_POKE_BG_DIST", "45").strip() or "45")
        dist = np.abs(band - bg).max(axis=2)
        mn = band.min(axis=2)
        fg = (dist > thr) & (mn <= 235)
        if fg.sum() < 10:
            return None
        alpha = (fg.astype(np.uint8)) * 255
        rgba = Image.new("RGBA", (rw, strip_h), (255, 255, 255, 0))
        rgb_src = Image.fromarray(band.astype(np.uint8), "RGB")
        rgba.paste(rgb_src, (0, 0))
        rgba.putalpha(Image.fromarray(alpha, "L"))
        return rgba
    except Exception:
        return None


def _composite_wide_top_strip_birefnet(canvas_path: str) -> None:
    """
    仅用于 3320×500（A5b）：
    1. 在裁切上下文区（x=1032-2464、y=0-context_h）上跑 BiRefNet 抠前景（pad 方形防失真）；
       WIDE_A5B_SEMANTIC=1 时叠 Gemini 前景物体 keep-mask（剔除环境/装饰），并去连通域碎屑；
    2. 铺整条 x=0-3320、y=0-40 #FFFFFF（规范顶部白条）；
    3. 将前景 RGBA 原位贴回，让所有前景物件顶部探入白条；
    失败时回退到 Gemini 顶部条带伸入逻辑（仅 y=0-40）。
    """
    from PIL import Image, ImageDraw
    img = Image.open(canvas_path).convert("RGB")
    w, h = img.size
    if w != WIDE_CANVAS_SIZE[0] or h != WIDE_CANVAS_SIZE[1]:
        return
    strip_h = WIDE_TOP_STRIP_H
    x0 = WIDE_STRIP_BIREFNET_X_MIN
    x1 = WIDE_STRIP_BIREFNET_X_MAX
    mat_y_min = WIDE_STRIP_BIREFNET_Y_MIN
    mat_y_max = WIDE_STRIP_BIREFNET_Y_MAX
    context_h = min(_wide_a5b_context_h(), h - mat_y_min)
    ctx_prompt = None
    try:
        _pt = Path(canvas_path).parent / "prompt.txt"
        if _pt.is_file():
            ctx_prompt = _pt.read_text(encoding="utf-8").strip() or None
    except Exception:
        ctx_prompt = None
    try:
        from birefnet_matting import (
            load_birefnet_matting,
            composite_strip_with_matting,
        )
        model = load_birefnet_matting()

        keep_mask = None
        if _wide_a5b_semantic_enabled():
            keep_mask = _build_wide_a5b_keep_mask(
                img, x0, x1, mat_y_min, mat_y_min + context_h, ctx_prompt
            )

        strip_rgba, _ = composite_strip_with_matting(
            img,
            x0,
            x1,
            mat_y_min,
            mat_y_max,
            model=model,
            alpha_threshold=_wide_a5b_alpha_threshold(),
            keep_mask=keep_mask,
            min_component_area=_wide_a5b_min_component_area(),
            binarize=_wide_a5b_binarize(),
            context_h=context_h,
        )
        _mode = "BiRefNet+Gemini语义" if keep_mask is not None else "BiRefNet"

        # BiRefNet 在全景超宽图上常把上半主体漏判（strip 带内 alpha 近空），
        # 导致贴回后白条仍纯白。检测 strip_rgba 在 y=0-strip_h 的不透明列数，
        # 过少则用背景差异法兜底重建 strip alpha（主体探入部分显影）。
        if strip_rgba is not None:
            import numpy as _np
            _alpha_band = _np.asarray(strip_rgba)[:strip_h, :, 3]
            _opaque_cols = int((_alpha_band > 40).any(axis=0).sum())
            _band_w = strip_rgba.size[0]
            if _opaque_cols < max(20, int(_band_w * 0.02)):
                _fb = _content_strip_rgba(img, x0, x1, mat_y_min, strip_h, context_h)
                if _fb is not None:
                    strip_rgba = _fb
                    _mode += "+背景差异兜底"
                    print(
                        f"  A5b: BiRefNet strip 带 alpha 近空（不透明列 {_opaque_cols}），改用背景差异兜底",
                        flush=True,
                    )

        if strip_rgba is not None:
            # 白条精确 strip_h 像素（用 paste 的半开区间 [0,strip_h)，避免 ImageDraw.rectangle
            # 端点闭区间多铺 1px 造成白条底缘与内容区之间的接缝）
            img.paste((255, 255, 255), (0, 0, w, strip_h))
            # 贴回前景：透明处 y=0-strip_h 透出白底
            img.paste(strip_rgba, (x0, mat_y_min), strip_rgba)
            img.save(canvas_path, "PNG")
            print(
                f"Step 5b / 3320×500 {_mode}: 全条 y=0-{strip_h} 铺白, 抠图区 x={x0}-{x1} context_h={context_h} 前景贴回 → {canvas_path}",
                flush=True,
            )
            return
    except Exception as e:
        if _wide_a5b_no_gemini_fallback():
            print(
                f"Step 5b BiRefNet 抠图失败，且 WIDE_A5B_NO_GEMINI_FALLBACK 已开启，终止（不回退 Gemini）: {e}",
                flush=True,
            )
            raise
        print(f"Step 5b BiRefNet 抠图失败，回退 Gemini 伸入逻辑: {e}", flush=True)
    _composite_wide_top_strip(canvas_path)


def _composite_wide_top_strip(canvas_path: str) -> None:
    """
    仅用于 3320×500：识别应伸入顶部条带的主体部分，裁出并贴到 y=0-40、x=500-1600（与规范一致）；
    该条带其余区域填白。
    """
    from PIL import Image, ImageDraw
    img = Image.open(canvas_path).convert("RGB")
    w, h = img.size
    if w != WIDE_CANVAS_SIZE[0] or h != WIDE_CANVAS_SIZE[1]:
        return
    strip_w = WIDE_TOP_STRIP_X_MAX - WIDE_TOP_STRIP_X_MIN  # 1100
    strip_h = WIDE_TOP_STRIP_H

    from gemini_subject_detect import detect_protrusion_bbox
    bbox = detect_protrusion_bbox(canvas_path)
    if bbox is not None:
        x_min, y_min, x_max, y_max = bbox
        left = max(0, int(x_min * w))
        top = max(0, int(y_min * h))
        right = min(w, int(x_max * w))
        bottom = min(h, int(y_max * h))
        if right > left and bottom > top:
            region = img.crop((left, top, right, bottom))
            region = region.resize((strip_w, strip_h), Image.Resampling.LANCZOS)
            img.paste(region, (WIDE_TOP_STRIP_X_MIN, 0))

    draw = ImageDraw.Draw(img)
    # 顶部条带内：x < 500 与 x > 1600 填白
    if WIDE_TOP_STRIP_X_MIN > 0:
        draw.rectangle((0, 0, WIDE_TOP_STRIP_X_MIN, strip_h), fill=(255, 255, 255))
    if WIDE_TOP_STRIP_X_MAX < w:
        draw.rectangle((WIDE_TOP_STRIP_X_MAX, 0, w, strip_h), fill=(255, 255, 255))
    img.save(canvas_path, "PNG")
    print(f"Step 5b / 3320×500 顶部条带: 伸出主体 → y=0-40 x={WIDE_TOP_STRIP_X_MIN}-{WIDE_TOP_STRIP_X_MAX}，其余填白 → {canvas_path}", flush=True)


def _safe_zone_scale_outpaint(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    skip_a4_outpaint: bool = False,
    remove_text: bool = True,
    preset: str | None = None,
    context_prompt: str | None = None,
    direct_to_canvas: bool = False,
    bbox_override: tuple[float, float, float, float] | None = None,
    width_fit: bool = False,
) -> Path:
    """
    A1～A6 流程：
    A1 去干扰（--remove-text 时）→ A2 主体 bbox 检测 → A3 标注保存 zhuti.png
    → A4（skip_a4_outpaint=False 时）以 bbox 区域为中心、根据画面已有内容向四周延展填充，保持 bbox 内区域不变；不新增人物或文字；生成 2048×512；检查是否有未填充完整、画面是否合理无割裂、新生成内容与 bbox 内是否相关，不通过则重新填充。输出：output/tianchong.png
    → A5 按画布裁切：主体 bbox 等比缩放到安全区 90%，中心对齐后裁切 → step1_prepared_background.png
    → A5b 仅 3320×500：识别伸出主体，放入顶部条带 y=0-40、x=500-1600，其余填白
    → A6 画面检测：Gemini Vision 判断是否有未填充区域；若有则用 Object/Environment Editing 延展填充，不新增人物或文字
    → A6b 仅画布 1740×220 专题头图：Gemini Vision 全图检测割裂/重复拼接；若有则 Object/Environment 延展融补，修复后复检，至多 A6B_MAX_REPAIR_ROUNDS 次修复（二检二修），不新增人物或文字

    skip_a4_outpaint=True：文生图/有参考图文生图流程专用，跳过 A4（不生成 tianchong.png），A5 基于 A1 去干扰后的图裁切。
    direct_to_canvas=True：通用直达画布路径，跳过 A4→A5→A6，主体直接贴到目标画布 + API 填补 + 检测修补（仅 default 1976×464 时保留 A4 产出 tianchong.png 供 wide 消费）。
    width_fit=True：仅 direct_to_canvas 时有效，按宽匹配安全区缩放（subject_ratio = safe_w/width），超出画布顶/底自动裁切。
    bbox_override：预计算的主体 bbox（x1,y1,x2,y2 归一化），跳过 A2 Vision 检测。
    """
    if get_safe_zone(width, height, preset) is None:
        raise ValueError(f"画布 {width}×{height} 未配置安全区，无法使用 safe_zone_scale_outpaint")
    if not _has_image_edit_key():
        print(
            "Error: safe_zone_scale_outpaint 需设置 GEMINI_API_KEY，或 BANNER_IMAGE_BACKEND=t8star 且 T8STAR_API_KEY。",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from gemini_image_edit import (
            edit_image,
            image_has_black_bars,
            image_has_black_bars_full_image,
            OUTPAINT_FILL_TO_3840x1080_PROMPT,
            OUTPAINT_FILL_REMAINING_BLACK_PROMPT,
            A6B_SHOP_HEADER_EXTEND_PROMPT,
        )
    except ImportError as e:
        print("Error: gemini_image_edit 未找到:", e, file=sys.stderr)
        sys.exit(1)
    from gemini_subject_detect import (
        detect_subject_bbox,
        image_a4_need_refill_unfilled,
        image_a4_need_refill_seams,
        image_a6b_shop_header_need_repair,
        image_has_unfilled_blanks,
    )
    from safe_zone_scale_composite import composite_to_canvas_center

    out_dir = Path(output_path).parent
    current_input = image_path
    cleaned_path = None

    # A1) 去干扰（仅当 remove_text=True 时执行，避免 Gemini 返回错误比例导致变形）
    if remove_text:
        print("Step 1 / 去干扰 (Gemini remove-text)...", flush=True)
        _cleaned = _remove_text_with_gemini(image_path)
        if _cleaned is not None:
            cleaned_path = _cleaned
            current_input = str(cleaned_path)
    else:
        print("Step 1 / 跳过去干扰（--remove-text 未传）", flush=True)

    # A2) 主体 bbox 检测
    if bbox_override is not None:
        bbox = bbox_override
        print(f"Step 2 / 使用预计算 bbox: {bbox}", flush=True)
    else:
        print("Step 2 / 主体 bbox 检测 (Gemini Vision)...", flush=True)
        bbox = detect_subject_bbox(current_input, context_prompt=context_prompt)
        if bbox is None:
            raise RuntimeError("主体 bbox 检测失败，无法继续")

    # A3) 标注保存 → output/zhuti.png
    zhuti_path = out_dir / "zhuti.png"
    _draw_bbox_and_save(current_input, bbox, zhuti_path)
    print(f"Step 3 / 标注保存 → {zhuti_path}", flush=True)

    # Strip (1740×220) fast path: bypass A4→A5→A6→A6b, composite directly to target canvas
    if (width, height) == SHOP_TOPIC_HEADER_SIZE:
        print(
            "Step S4-S6 / strip 直达画布路径（绕过 A4 2048×512 → A5 裁切 → A6b 二轮修复）...",
            flush=True,
        )
        _strip_direct_to_canvas(current_input, output_path, width, height, bbox)
        if cleaned_path is not None and cleaned_path.is_file():
            cleaned_path.unlink(missing_ok=True)
        return Path(output_path)

    # 通用直达画布路径（非专属流程预设）
    if direct_to_canvas:
        print(
            f"Step S4-S6 / 直达画布路径（{width}×{height}，绕过 A4 2048×512 → A5 裁切）...",
            flush=True,
        )
        # 仅 default (1976×464) 且 WIDE_KEEP_TIANCHONG=1 时才产出 tianchong.png 供 wide 消费。
        # 默认（bg-direct）wide 直接用 bg，无需 tianchong → 跳过这次 4 轮 A4 图编，省一次 API。
        tianchong_path = out_dir / "tianchong.png"
        _keep_tianchong = os.environ.get("WIDE_KEEP_TIANCHONG", "0").strip().lower() in ("1", "true", "yes", "on")
        if (width, height) == (1976, 464) and _keep_tianchong:
            print("  default: [KEEP_TIANCHONG] 先跑 A4 产出 tianchong.png 供 wide 消费...", flush=True)
            from safe_zone_scale_composite import composite_to_canvas_center
            fd, temp_canvas = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                composite_to_canvas_center(
                    current_input,
                    temp_canvas,
                    subject_bbox=bbox,
                    subject_ratio=0.85,
                    center_y_ratio=0.5,
                )
                mask_path = _generate_sentinel_mask(temp_canvas)
                for r in range(4):
                    print(f"  A4 第 {r + 1}/4 轮...", flush=True)
                    try:
                        edit_image(
                            temp_canvas,
                            str(tianchong_path),
                            OUTPAINT_FILL_TO_3840x1080_PROMPT,
                            keep_returned_size=True,
                            mask_path=mask_path,
                        )
                    except Exception as e:
                        # 图编失败（内部已做多模型重试）：不放弃剩余轮次，下一轮重新尝试
                        print(f"  A4 第 {r + 1}/4 轮图编失败: {e}", file=sys.stderr)
                        if r < 3:
                            continue
                        # 4 轮全部失败才回退本地画布
                        print("  A4 全部轮次失败，使用本地画布（含 sentinel 未填充）", file=sys.stderr)
                        import shutil
                        shutil.copy2(temp_canvas, str(tianchong_path))
                        break
                    need_refill_unfilled = image_a4_need_refill_unfilled(str(tianchong_path))
                    if need_refill_unfilled is None:
                        need_refill_unfilled = image_has_black_bars_full_image(str(tianchong_path)) or image_has_black_bars(str(tianchong_path))
                    need_refill_seams = image_a4_need_refill_seams(str(tianchong_path))
                    need_refill = need_refill_unfilled or (need_refill_seams if need_refill_seams is not None else True)
                    if not need_refill:
                        break
                    if r < 3:
                        print(f"  A4 检测不通过，重新填充...", flush=True)
                print(f"  A4 产出 → {tianchong_path}", flush=True)
                _warn_sentinel_residue(str(tianchong_path), "A4 tianchong 2048x512")
                if os.path.isfile(mask_path):
                    try:
                        os.unlink(mask_path)
                    except OSError:
                        pass
            finally:
                if os.path.isfile(temp_canvas):
                    try:
                        os.unlink(temp_canvas)
                    except OSError:
                        pass
        _direct_to_canvas(current_input, output_path, width, height, bbox, width_fit=width_fit)
        if cleaned_path is not None and cleaned_path.is_file():
            cleaned_path.unlink(missing_ok=True)
        return Path(output_path)

    tianchong_path = out_dir / "tianchong.png"
    if not skip_a4_outpaint:
        # A4) 以 bbox 为中心向四周延展填充，保持 bbox 内不变；不新增人物或文字；2048×512；检查未填充完整/画面割裂/延展内容与 bbox 内无关则重新填充 → output/tianchong.png
        fd, temp_canvas = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            composite_to_canvas_center(
                current_input,
                temp_canvas,
                subject_bbox=bbox,
                subject_ratio=0.85,  # 主体占比加大，减少需延展的空白，降低重复/割裂
                center_y_ratio=0.5,
            )
            max_fill_rounds = 4
            fill_input = temp_canvas
            mask_path = _generate_sentinel_mask(temp_canvas)
            for r in range(max_fill_rounds):
                print(f"Step 4 / 填充画面 (Gemini 延展填满 2048×512) 第 {r + 1}/{max_fill_rounds} 轮...", flush=True)
                try:
                    edit_image(
                        fill_input,
                        str(tianchong_path),
                        OUTPAINT_FILL_TO_3840x1080_PROMPT,
                        keep_returned_size=True,
                        mask_path=mask_path,
                    )
                except Exception as e:
                    # 图编失败（edit_image 内部已做多模型重试）：不放弃剩余轮次，下一轮重新尝试；
                    # 全部轮次失败才回退本地合成画布（含 sentinel 未填充色）继续后续裁切/填充检测。
                    print(
                        f"  A4 第 {r + 1}/{max_fill_rounds} 轮图编失败: {e}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if r < max_fill_rounds - 1:
                        fill_input = temp_canvas
                        continue
                    print("  A4 全部轮次失败，改用本地画布继续（可能未填充）", file=sys.stderr, flush=True)
                    try:
                        shutil.copy2(temp_canvas, str(tianchong_path))
                    except Exception:
                        # copy 失败则让后续检测可能仍能运行（最坏情况下会在 Step5 兜底）
                        pass
                    break
                # A4 分步检测：(1) UNFILLED 未填满；(2) VISUAL QUALITY/SEAMS 接缝/割裂。任一项不满足即触发重填
                need_refill_unfilled = image_a4_need_refill_unfilled(str(tianchong_path))
                if need_refill_unfilled is None:
                    need_refill_unfilled = image_has_black_bars_full_image(str(tianchong_path)) or image_has_black_bars(str(tianchong_path))
                need_refill_seams = image_a4_need_refill_seams(str(tianchong_path))
                # 接缝检测返回 None（API/解析失败）时保守视为需重填，避免误放行带接缝的图
                need_refill = need_refill_unfilled or (need_refill_seams if need_refill_seams is not None else True)
                if need_refill:
                    if r < max_fill_rounds - 1:
                        which = []
                        if need_refill_unfilled:
                            which.append("未填满")
                        if need_refill_seams:
                            which.append("接缝/割裂")
                        elif need_refill_seams is None and not need_refill_unfilled:
                            which.append("接缝/割裂(检测未返回)")
                        print(f"  A4 检测不通过（{' + '.join(which)}），重新填充...", flush=True)
                    fill_input = temp_canvas
                    continue
                break
            print(f"Step 4 产出 → {tianchong_path}", flush=True)
            _warn_sentinel_residue(str(tianchong_path), "A4 tianchong 2048x512")
            # 若 tianchong.png 非规定 2048×512，打印实际尺寸
            try:
                from PIL import Image
                with Image.open(str(tianchong_path)) as img:
                    w, h = img.size
                    if (w, h) != (2048, 512):
                        print(f"tianchong.png 实际尺寸: {w}×{h}（非规定 2048×512）", flush=True)
            except Exception:
                pass
            if os.path.isfile(mask_path):
                try:
                    os.unlink(mask_path)
                except OSError:
                    pass
        finally:
            if os.path.isfile(temp_canvas):
                try:
                    os.unlink(temp_canvas)
                except OSError:
                    pass
    else:
        print("Step 4 / 跳过（--skip-a4-outpaint：文生图/有参考图流程，不生成 tianchong.png）", flush=True)

    # A5) 按画布裁切：skip_a4 时基于去干扰图，否则基于 A4 输出；Gemini Vision 识别主体，失败则报错结束
    # 允许输入小于画布：会按主体 bbox 缩放后贴到目标画布，确保 wide 也能执行“主体对齐安全区”的裁切逻辑。
    image_for_a5 = current_input if skip_a4_outpaint else str(tianchong_path)
    print("Step 5 / 按画布裁切（主体与安全区中心对齐）...", flush=True)
    _crop_step5_to_canvas(image_for_a5, output_path, width, height, preset=preset, context_prompt=context_prompt)

    # A5b) 仅 3320×500：先白条 0-3320×0-40，BiRefNet 在 x=1470-2464、y=0-40 抠图置于白条上；失败则回退 Gemini 伸入
    if (width, height) == WIDE_CANVAS_SIZE:
        _composite_wide_top_strip_birefnet(output_path)

    # A6) 画面检测：Gemini Vision 判断是否有未填充区域；若有则 Object/Environment Editing 延展填充，不新增人物或文字
    print("Step 6 / 画面检测（Gemini Vision 是否未填充完整）...", flush=True)
    has_unfilled = image_has_unfilled_blanks(output_path)
    if has_unfilled is None:
        has_unfilled = image_has_black_bars_full_image(output_path) or image_has_black_bars(output_path)
    if has_unfilled:
        print("  检测到未填充区域，使用 Object/Environment Editing 延展填充...", flush=True)
        try:
            if BANNER_IMAGE_BACKEND == "packygpt":
                _packygpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "moxingpt":
                _moxingpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xingchengpt":
                edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "xinchengpt":
                _xinchengpt_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
            elif BANNER_IMAGE_BACKEND == "micugpt2":
                _micugpt2_edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT)
            else:
                edit_image(output_path, output_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
        except Exception as e:
            print(f"  A6 填充失败（保留 A5 产出）: {e}", file=sys.stderr)
    else:
        print("  无未填充区域，跳过填充。", flush=True)

    # A6b) 仅商店专题头图 1740×220：固定运行修复→复检，至多 A6B_MAX_REPAIR_ROUNDS 轮（二检二修）
    if (width, height) == SHOP_TOPIC_HEADER_SIZE:
        print(
            "Step 6b / 专题头图 1740×220 画质修复（固定运行，Object/Environment 延展融补）...",
            flush=True,
        )
        for round_idx in range(1, A6B_MAX_REPAIR_ROUNDS + 1):
            print(
                f"  A6b 第 {round_idx}/{A6B_MAX_REPAIR_ROUNDS} 次修复（Object/Environment 延展融补）...",
                flush=True,
            )
            try:
                if BANNER_IMAGE_BACKEND == "packygpt":
                    _packygpt_edit_image(
                        output_path, output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "moxingpt":
                    _moxingpt_edit_image(
                        output_path, output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "xingchengpt":
                    _xingchengpt_edit_image(
                        output_path, output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "xinchengpt":
                    _xinchengpt_edit_image(
                        output_path, output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                        keep_returned_size=True,
                    )
                elif BANNER_IMAGE_BACKEND == "micugpt2":
                    _micugpt2_edit_image(
                        output_path, output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                    )
                else:
                    edit_image(
                        output_path,
                        output_path,
                        A6B_SHOP_HEADER_EXTEND_PROMPT,
                        keep_returned_size=True,
                    )
            except Exception as e:
                print(f"  A6b 第 {round_idx} 次修复失败（保留当前产出）: {e}", file=sys.stderr)
                break
            if round_idx < A6B_MAX_REPAIR_ROUNDS:
                print("  A6b 复检（割裂/重复拼接）...", flush=True)
                need_a6b = image_a6b_shop_header_need_repair(output_path)
                if need_a6b is False:
                    print("  A6b：复检通过，停止修复。", flush=True)
                    break
                if need_a6b is None:
                    print("  A6b：复检未返回明确结果，不再继续修复。", flush=True)
                    break
                print("  A6b：复检仍不通过，进行下一轮修复。", flush=True)
            else:
                print("  A6b 末检（割裂/重复拼接）...", flush=True)
                need_final = image_a6b_shop_header_need_repair(output_path)
                if need_final is True:
                    print(
                        f"  A6b：已完成 {A6B_MAX_REPAIR_ROUNDS} 次修复，末检仍建议继续处理（可人工或过片）。",
                        flush=True,
                    )
                elif need_final is False:
                    print("  A6b：末检通过。", flush=True)
                else:
                    print("  A6b：末检未返回明确结果。", flush=True)

    if cleaned_path is not None and cleaned_path.is_file():
        try:
            cleaned_path.unlink()
        except OSError:
            pass
    return Path(output_path)


def prepare_background(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    *,
    subject_center_y_ratio: float | None = None,
    subject_center_x_ratio: float | None = None,
    force_crop_only: bool = True,
    remove_text: bool = False,
    auto_subject: bool = True,
    align_image_center_to_safe_zone: bool = True,
    safe_zone_scale_outpaint: bool = False,
    skip_a4_outpaint: bool = False,
    direct_to_canvas: bool = False,
    bbox_override: tuple[float, float, float, float] | None = None,
    preset: str | None = None,
    context_prompt: str | None = None,
    width_fit: bool = False,
) -> Path:
    """
    Produce a W×H banner background from the source image.
    When safe_zone_scale_outpaint: scale by subject bbox to safe zone, composite to canvas, then Gemini outpaint blanks.
    When align_image_center_to_safe_zone (default): upload image center at safe zone center.
    Otherwise: subject (x,y) and place in safe zone. If remove_text: Gemini remove-text first.
    skip_a4_outpaint: 仅当 safe_zone_scale_outpaint 时有效；True 表示文生图/有参考图流程，跳过 A4，A5 基于去干扰图裁切。
    direct_to_canvas: 通用直达画布路径，跳过 A4→A5→A6，主体贴目标画布 + API 填补 + S6 检测修补。
    width_fit: 仅 direct_to_canvas 时有效，按宽匹配安全区缩放，超出画布顶/底自动裁切。
    bbox_override: 预计算 bbox，跳过 A2 Vision 检测。
    Returns path to saved file.
    """
    from PIL import Image

    current_input = image_path
    cleaned_path = None
    if remove_text and not safe_zone_scale_outpaint:
        cleaned_path = _remove_text_with_gemini(image_path)
        if cleaned_path is not None:
            current_input = str(cleaned_path)
        # else keep original

    if safe_zone_scale_outpaint:
        out = _safe_zone_scale_outpaint(
            current_input,
            output_path,
            width,
            height,
            skip_a4_outpaint=skip_a4_outpaint,
            remove_text=remove_text,
            preset=preset,
            context_prompt=context_prompt,
            direct_to_canvas=direct_to_canvas,
            bbox_override=bbox_override,
            width_fit=width_fit,
        )
        if cleaned_path and cleaned_path.is_file():
            try:
                cleaned_path.unlink()
            except OSError:
                pass
        return out

    # Subject (x,y) only used when not align_image_center_to_safe_zone；主体模式强制要求检测成功，禁止居中裁切回退
    subject_x = subject_center_x_ratio
    subject_y = subject_center_y_ratio
    if not align_image_center_to_safe_zone and (subject_x is None or subject_y is None):
        if auto_subject:
            xy = _detect_subject_xy(current_input)
            if subject_x is None:
                subject_x = xy[0]
            if subject_y is None:
                subject_y = xy[1]
        if subject_x is None or subject_y is None:
            print(
                "Error: 按主体落安全区裁切必须使用 Gemini 主体检测。检测失败或未设置 GEMINI_API_KEY 时无法继续，请设置 GEMINI_API_KEY 后重试。",
                file=sys.stderr,
            )
            sys.exit(1)

    img = Image.open(current_input)
    w0, h0 = img.size

    if force_crop_only or not _needs_expand(w0, h0, width, height):
        out = crop_to_target(
            current_input,
            output_path,
            width,
            height,
            subject_center_y_ratio=None if align_image_center_to_safe_zone else subject_y,
            subject_center_x_ratio=None if align_image_center_to_safe_zone else subject_x,
            align_image_center_to_safe_zone=align_image_center_to_safe_zone,
            preset=preset,
        )
        if cleaned_path and cleaned_path.is_file():
            try:
                cleaned_path.unlink()
            except OSError:
                pass
        return out

    out = _expand_with_gemini(
        current_input,
        width,
        height,
        output_path,
        subject_center_y_ratio=subject_y,
        subject_center_x_ratio=subject_x,
        align_image_center_to_safe_zone=align_image_center_to_safe_zone,
        preset=preset,
    )
    if cleaned_path and cleaned_path.is_file():
        try:
            cleaned_path.unlink()
        except OSError:
            pass
    if out is not None:
        return out
    return crop_to_target(
        current_input,
        output_path,
        width,
        height,
        subject_center_y_ratio=None if align_image_center_to_safe_zone else subject_y,
        subject_center_x_ratio=None if align_image_center_to_safe_zone else subject_x,
        align_image_center_to_safe_zone=align_image_center_to_safe_zone,
        preset=preset,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare banner background from image to target W×H (crop; expand via Gemini). Output: output/."
    )
    parser.add_argument(
        "--wide-from-fill",
        nargs=2,
        metavar=("FILL_IMAGE", "OUTPUT_PATH"),
        help="复用填充图：将 FILL_IMAGE 按 cover 缩放到 3320×500 并做顶部条带，输出到 OUTPUT_PATH；不跑去字/主体/填充（run_all_presets Step 1b 用）",
    )
    parser.add_argument(
        "--crop-from-image",
        nargs=2,
        metavar=("IMAGE", "OUTPUT"),
        dest="crop_from_image",
        help="仅 A5：从 IMAGE 做主体 bbox 检测，缩放到安全区 90%% 中心对齐裁切到目标尺寸，输出 OUTPUT；需配合 --preset 或 -W -H",
    )
    parser.add_argument("input", nargs="?", default=None, help="Source image path（使用 --wide-from-fill/--crop-from-image 时可省略）")
    parser.add_argument("output", nargs="?", default=None, help="Output path or filename（使用 --wide-from-fill 时可省略）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--preset", "-p", choices=list(PRESETS), default="default")
    group.add_argument("--width", "-W", type=int)
    parser.add_argument("--height", "-H", type=int)
    parser.add_argument("--subject-y", type=float, metavar="RATIO", help="Subject center Y in source 0..1")
    parser.add_argument("--subject-x", type=float, metavar="RATIO", help="Subject center X in source 0..1")
    parser.add_argument(
        "--try-expand",
        dest="crop_only",
        action="store_false",
        help="Try expand (Gemini outpaint) when source is smaller than target",
    )
    parser.add_argument(
        "--remove-text",
        action="store_true",
        help="Remove text/watermarks from image first (Gemini/t8star; requires GEMINI_API_KEY or T8STAR_API_KEY)",
    )
    parser.add_argument(
        "--no-auto-subject",
        action="store_true",
        help="Disable auto subject detection (use center crop instead of Gemini Vision)",
    )
    parser.add_argument(
        "--no-align-image-center",
        action="store_true",
        help="Do not place image center at safe zone center (use subject or center crop)",
    )
    parser.add_argument(
        "--safe-zone-scale-outpaint",
        action="store_true",
        help="Scale by subject bbox to safe zone, composite to canvas, then Gemini outpaint all blank areas",
    )
    parser.add_argument(
        "--skip-a4-outpaint",
        action="store_true",
        help="文生图/有参考图文生图流程：跳过 A4 延展填满，A5 基于去干扰图裁切；不传则保持原流程（含 tianchong）",
    )
    parser.add_argument(
        "--direct-to-canvas",
        action="store_true",
        dest="direct_to_canvas",
        help="通用直达画布路径：主体直接贴到目标画布 + API 填补空白 + 检测修补，绕过 A4 2048×512",
    )
    parser.add_argument(
        "--width-fit",
        action="store_true",
        help="仅 --direct-to-canvas 时有效，按宽匹配安全区缩放，超出画布顶/底自动裁切",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("X1", "Y1", "X2", "Y2"),
        dest="bbox_override",
        help="预计算的主体 bbox（归一化 0~1），跳过 A2 Vision 检测",
    )
    parser.add_argument(
        "--outpaint-after-crop",
        action="store_true",
        dest="outpaint_after_crop",
        help="裁切后若检测到未填充/黑边则用图编延展补齐（仅 --crop-from-image 时有效，兜底保证满铺）",
    )
    parser.add_argument(
        "--subject-bbox-norm",
        nargs=4,
        type=float,
        metavar=("X_MIN", "Y_MIN", "X_MAX", "Y_MAX"),
        help="共用主体 bbox（0~1，x_min y_min x_max y_max），传入时跳过 Vision 检测（仅 --crop-from-image 时有效）",
    )
    parser.add_argument(
        "--bbox-file",
        type=str,
        metavar="BBOX_FILE",
        help="主体 bbox 文件路径（shared_subject_bbox.txt），格式为 x_min,y_min,x_max,y_max（归一化坐标 0-1）；仅 --wide-from-fill 时有效，用于智能对齐",
    )
    parser.add_argument(
        "--context-prompt",
        type=str,
        metavar="PROMPT_FILE",
        help="原始生图描述文本文件路径，帮助 Vision 更准确识别画面预期主体",
    )
    args = parser.parse_args()
    args.crop_only = getattr(args, "crop_only", True)

    if getattr(args, "wide_from_fill", None) is not None:
        fill_path, out_path = args.wide_from_fill
        bbox_file = getattr(args, "bbox_file", None)
        wide_from_fill(fill_path, out_path, bbox_file=bbox_file)
        return
    if getattr(args, "crop_from_image", None) is not None:
        img_path, out_path = args.crop_from_image
        if args.width is not None and args.height is not None:
            width, height = args.width, args.height
            crop_preset = None
        else:
            width, height = PRESETS[args.preset]
            crop_preset = args.preset
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        bbox_norm = tuple(args.subject_bbox_norm) if getattr(args, "subject_bbox_norm", None) else None
        _crop_step5_to_canvas(img_path, out_path, width, height, preset=crop_preset, subject_bbox_norm=bbox_norm)
        if getattr(args, "outpaint_after_crop", False) and _has_image_edit_key():
            try:
                from gemini_image_edit import edit_image, OUTPAINT_FILL_REMAINING_BLACK_PROMPT
                from gemini_image_edit import image_has_black_bars, image_has_black_bars_full_image
                from gemini_subject_detect import image_has_unfilled_blanks
            except ImportError:
                pass
            else:
                has_unfilled = image_has_unfilled_blanks(out_path)
                if has_unfilled is None:
                    has_unfilled = image_has_black_bars_full_image(out_path) or image_has_black_bars(out_path)
                if has_unfilled:
                    print("  裁切后检测到未填充区域，延展补齐...", flush=True)
                    try:
                        edit_image(out_path, out_path, OUTPAINT_FILL_REMAINING_BLACK_PROMPT, keep_returned_size=True)
                    except Exception as e:
                        print(f"  裁切后补齐失败（保留裁切结果）: {e}", file=sys.stderr)
        return
    if args.input is None or args.output is None:
        parser.error("请提供 input 与 output，或使用 --wide-from-fill / --crop-from-image")

    if args.width is not None and args.height is not None:
        width, height = args.width, args.height
    else:
        width, height = PRESETS[args.preset]

    _ctx_file = getattr(args, "context_prompt", None)
    _ctx = None
    if _ctx_file:
        _ctx_path = Path(_ctx_file)
        if _ctx_path.is_file():
            _ctx = _ctx_path.read_text(encoding="utf-8").strip()
        else:
            _ctx = _ctx_file.strip()
    out = prepare_background(
        args.input,
        args.output,
        width,
        height,
        subject_center_y_ratio=getattr(args, "subject_y", None),
        subject_center_x_ratio=getattr(args, "subject_x", None),
        force_crop_only=args.crop_only,
        remove_text=args.remove_text,
        auto_subject=not args.no_auto_subject,
        align_image_center_to_safe_zone=not args.no_align_image_center,
        safe_zone_scale_outpaint=getattr(args, "safe_zone_scale_outpaint", False),
        skip_a4_outpaint=getattr(args, "skip_a4_outpaint", False),
        direct_to_canvas=getattr(args, "direct_to_canvas", False),
        bbox_override=tuple(args.bbox_override) if getattr(args, "bbox_override", None) else None,
        preset=args.preset if args.width is None or args.height is None else None,
        context_prompt=_ctx,
        width_fit=getattr(args, "width_fit", False),
    )


if __name__ == "__main__":
    main()
