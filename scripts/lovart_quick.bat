@echo off
REM Lovart 后端快捷命令。在 cmd 中执行：scripts\lovart_quick.bat
REM 之后可直接用 lovart-on / lovart-off / lovart-seedream 等命令切换后端和模型。

doskey lovart-on=set BANNER_IMAGE_BACKEND=lovart
doskey lovart-off=set BANNER_IMAGE_BACKEND=
doskey lovart-seedream=set LOVART_PREFER_MODELS=generate_image_seedream_v4
doskey lovart-seedream45=set LOVART_PREFER_MODELS=generate_image_seedream_v4
doskey lovart-banana=set LOVART_PREFER_MODELS=generate_image_nano_banana_pro
doskey lovart-banana2=set LOVART_PREFER_MODELS=generate_image_nano_banana_2
doskey lovart-midjourney=set LOVART_PREFER_MODELS=generate_image_midjourney
doskey lovart-both=set LOVART_PREFER_MODELS=generate_image_seedream_v4,generate_image_nano_banana_pro
doskey lovart-fast=python scripts\agent_skill.py set-mode --fast
doskey lovart-unlimited=python scripts\agent_skill.py set-mode --unlimited
doskey lovart-mode=python scripts\agent_skill.py query-mode

echo Lovart 快捷命令已加载：
echo   lovart-on        启用 Lovart 后端
echo   lovart-off       关闭 Lovart 后端
echo   lovart-seedream  使用 Seedream 3.0 模型
echo   lovart-banana    使用 nano-banana-pro 模型
echo   lovart-midjourney 使用 Midjourney 模型
echo   lovart-fast      切换 fast 模式（消耗积分）
echo   lovart-unlimited 切换 unlimited 模式（免费排队）
echo   lovart-mode      查询当前模式
