@echo off
REM BiRefNet 顶条抠图依赖：CPU 版 PyTorch（体积小）+ transformers
cd /d "%~dp0.."
echo [install_birefnet_deps] 安装 PyTorch CPU 轮子与 transformers ...
py -3 -m pip install --upgrade pip
py -3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
  echo 若 py -3 不可用，请改为 python 或指定解释器路径后重试。
  exit /b 1
)
REM transformers 5.x 可能与其它包（如 prompt-optimizer）冲突，固定 4.x
py -3 -m pip install "transformers>=4.38.0,<5.0.0" "huggingface_hub>=0.20.0"
if errorlevel 1 exit /b 1
REM transformers 依赖 regex；若遇 _regex 导入失败可修复坏掉的 wheel
py -3 -m pip install --upgrade "regex>=2024.5.0"
if errorlevel 1 exit /b 1
echo 完成。首次运行 wide A5b 时会从 HuggingFace 下载 BiRefNet-matting 权重。
