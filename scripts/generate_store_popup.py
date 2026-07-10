#!/usr/bin/env python3
"""
Generate store popup - new and old versions
Based on existing generate_bubble.py functionality
"""
import sys
from pathlib import Path

# 项目根目录（scripts/ 的上一级）
_SCRIPT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).parent))
from scripts.generate_bubble import main as bubble_main
import argparse


def generate_new_rule(text="今天上班了", theme="蓝色"):
    """Generate new rule store popup (with close button)"""
    print(f"Generating NEW RULE popup: {text} [{theme}]")
    original_argv = sys.argv.copy()
    sys.argv = [
        'generate_bubble.py',
        '--text', text,
        '--theme', theme,
        '--output-dir', str(_SCRIPT_ROOT / f'output/store_popup_new_{theme}')
    ]
    try:
        bubble_main()
    finally:
        sys.argv = original_argv


def generate_old_rule(text="今天上班了", theme="蓝色"):
    """Generate old rule store popup (without close button)"""
    print(f"Generating OLD RULE popup: {text} [{theme}]")
    original_argv = sys.argv.copy()
    sys.argv = [
        'generate_bubble.py',
        '--text', text,
        '--theme', theme,
        '--no-close',
        '--output-dir', str(_SCRIPT_ROOT / f'output/store_popup_old_{theme}')
    ]
    try:
        bubble_main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate store popups')
    parser.add_argument('--text', default='今天上班了', help='Text to display')
    parser.add_argument('--theme', default='蓝色', help='Theme color')
    parser.add_argument('--type', choices=['new', 'old', 'both'], default='both', help='Type of popup')
    
    args = parser.parse_args()
    
    if args.type in ['new', 'both']:
        generate_new_rule(args.text, args.theme)
    
    if args.type in ['old', 'both']:
        generate_old_rule(args.text, args.theme)
    
    print("Done!")