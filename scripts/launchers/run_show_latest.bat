@echo off
cd /d "%~dp0..\..\input"
echo === 最新文件列表 ===
dir /o-d | findstr /i "upload"
echo.
echo 最新: upload_current.png
pause