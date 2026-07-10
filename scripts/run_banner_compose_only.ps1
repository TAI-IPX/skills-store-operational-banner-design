# 仅叠渐变与标题（不跑 prepare_background）
# 自动检测 Python

$pythonExe = $null
foreach ($cmd in @("python", "python3", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { $pythonExe = $found.Source; break }
}
if (-not $pythonExe) {
    Write-Host "❌ 未找到 Python，请确保 Python 3.8+ 已安装并在 PATH 中" -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& $pythonExe (Join-Path $scriptDir "run_banner_compose_only.py") @args
