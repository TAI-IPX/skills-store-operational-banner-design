@echo off
cd /d "%~dp0..\.."
python scripts/run_all_presets.py @ -g "Lengion zone 弹窗 656*360" -m "巴拉巴拉巴拉巴" --skip-remove-text --packy
echo.
echo Press any key to exit...
pause >nul
