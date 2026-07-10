# Banner 生成脚本 (PowerShell)
# 自动检测 Python 并运行 run_banner.py

Write-Host "Banner 生成工具" -ForegroundColor Green
Write-Host ""

# 自动检测 Python
$pythonExe = $null
$pythonCandidates = @("python", "python3", "py")

foreach ($cmd in $pythonCandidates) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $pythonExe = $found.Source
        break
    }
}

if (-not $pythonExe) {
    Write-Host "❌ 错误：未找到 Python" -ForegroundColor Red
    Write-Host "   请确保 Python 3.8+ 已安装并在 PATH 中" -ForegroundColor Yellow
    Write-Host "   下载地址：https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ 使用 Python: $pythonExe" -ForegroundColor Green
Write-Host ""

# 获取脚本目录并运行
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 运行脚本（传递所有参数）
& $pythonExe (Join-Path $scriptDir "run_banner.py") @args

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ 失败，退出码: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
