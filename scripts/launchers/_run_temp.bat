@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
py scripts/run_all_presets.py @ -m "无纸化进阶神器" -s "打造你的数字知识库" -g 商店移动端日常 --packy
