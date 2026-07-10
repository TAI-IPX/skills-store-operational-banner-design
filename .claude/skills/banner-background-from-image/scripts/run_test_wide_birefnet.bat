@echo off
REM 使用指定 Python 路径运行 3320x500 顶部条带 BiRefNet 抠图测试
REM 用法: 拖入一张图片到本 bat，或 run_test_wide_birefnet.bat "图片路径"
set PY=D:\cursor\biyaozujian\Python\python.exe
if not exist "%PY%" (
    echo 未找到 Python: %PY%
    echo 请修改本 bat 中 PY= 为你的 python.exe 路径
    pause
    exit /b 1
)
cd /d "%~dp0"
if "%~1"=="" (
    echo 用法: run_test_wide_birefnet.bat "输入图片路径"
    echo 或直接拖入图片到本 bat
    pause
    exit /b 0
)
set OUT=output\test_wide_birefnet.png
"%PY%" test_wide_birefnet.py -i "%~1" -o "%OUT%"
echo.
echo 输出: %OUT%
pause
