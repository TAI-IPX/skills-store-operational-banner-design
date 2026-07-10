#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate the requested assets:
1. 日历图标 (calendar icon) - 卡通3D风格，从斜45度视角俯视，日历图标（绿色外框，中间白色且带勾号）
2. 商店弹泡新规 (store popup new rule) - 蓝色主题
3. 商店弹泡旧规 (store popup old rule) - 蓝色主题, 无关闭按钮
"""

import sys
import os
from pathlib import Path

# 项目根目录（scripts/ 的上一级）
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    print("=== Generating Requested Assets ===")
    
    # Ensure output directory exists
    output_dir = _SCRIPT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    
    # Try to import and use the jimeng API
    try:
        from jimeng_volc_api import t2i
        print("✓ Successfully imported jimeng_volc_api")
    except ImportError as e:
        print(f"✗ Failed to import jimeng_volc_api: {e}")
        # Fallback to using generate_bubble for popups
        from generate_bubble import make_bubble, SCALES, THEMES
        from datetime import datetime
        print("✓ Using generate_bubble as fallback")
        
        # Generate store popups using the existing bubble generator
        def create_popup(text, theme="蓝色", with_close=True, prefix=""):
            theme_data = THEMES[theme]
            grad_color = theme_data["grad"]
            text_color = theme_data["text"]
            
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if prefix:
                out_dir = _SCRIPT_ROOT / f"output/{prefix}_{ts}"
            else:
                out_dir = _SCRIPT_ROOT / f"output/popup_{ts}"
            out_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"Creating popup: '{text}' [{theme}] with_close={with_close}")
            
            for scale in SCALES:
                scale_names = {1: "@100", 1.5: "@150", 2: "@200", 3: "@300"}
                
                img = make_bubble(
                    text=text,
                    scale=scale,
                    grad_color=grad_color,
                    text_color=text_color,
                    with_icon=False,
                    with_close=with_close
                )
                
                prefix_text = "旧规-" if not with_close else "新规-"
                name = f"{prefix_text}{text}{scale_names[scale]}.png"
                path = out_dir / name
                img.save(path, "PNG")
                print(f"  Saved: {name} ({img.width}x{img.height})")
            
            print(f"✓ Completed: {out_dir}\n")
            return out_dir
        
        # Generate the requested popups
        print("\n--- Generating Store Popups ---")
        create_popup("今天上班了", theme="蓝色", with_close=True, prefix="店弹泡新规_蓝色")
        create_popup("今天上班了", theme="蓝色", with_close=False, prefix="店弹泡旧规_蓝色")
        
        print("\n=== Generation Complete ===")
        print("Note: Calendar icon generation requires jimeng API which failed to import.")
        print("Store popups have been generated using the existing bubble system.")
        return
    
    # If we got here, jimeng API is available
    print("Attempting to generate assets with jimeng API...")
    
    # 1. 日历图标 (calendar icon)
    print("\n1. Generating 日历图标 (calendar icon)...")
    calendar_prompt = """日历图标，卡通3D风格，从斜45度视角俯视，绿色外框，中间白色且带勾号，
使用鲜艳的颜色，带有柔和的渐变和微妙的高光，背景为纯白色，现代且俏皮的设计，
适合应用界面，简约简单，干净简洁，无文字"""
    
    calendar_path = output_dir / "calendar_icon_3d.png"
    success = t2i(calendar_prompt, str(calendar_path), 1024, 1024)
    if success:
        print(f"✓ 日历图标已保存: {calendar_path}")
    else:
        print("✗ 日历图标生成失败")
    
    # 2. 商店弹泡新规 (store popup new rule) - with close button
    print("\n2. Generating 商店弹泡新规 (store popup with close)...")
    popup_new_prompt = """商店弹泡新规，蓝色主题，带关闭按钮，文字：今天上班了，
卡通风格，现代俏皮设计，鲜艳颜色，柔和渐变，微妙高光，纯白色背景"""
    
    popup_new_path = output_dir / "popup_new_blue.png"
    success = t2i(popup_new_prompt, str(popup_new_path), 1024, 1024)
    if success:
        print(f"✓ 商店弹泡新规已保存: {popup_new_path}")
    else:
        print("✗ 商店弹泡新规生成失败")
    
    # 3. 商店弹泡旧规 (store popup old rule) - without close button
    print("\n3. Generating 商店弹泡旧规 (store popup without close)...")
    popup_old_prompt = """商店弹泡旧规，蓝色主题，无关闭按钮，文字：今天上班了，
卡通风格，现代俏皮设计，鲜艳颜色，柔和渐变，微妙高光，纯白色背景"""
    
    popup_old_path = output_dir / "popup_old_blue.png"
    success = t2i(popup_old_prompt, str(popup_old_path), 1024, 1024)
    if success:
        print(f"✓ 商店弹泡旧规已保存: {popup_old_path}")
    else:
        print("✗ 商店弹泡旧规生成失败")
    
    print("\n=== Generation Complete ===")

if __name__ == "__main__":
    main()