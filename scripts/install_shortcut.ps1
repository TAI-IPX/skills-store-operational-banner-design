# install_shortcut.ps1
# 将 run_from_a4_shortcut 安装到 PowerShell profile，实现任意窗口可用
# 用法：.\scripts\install_shortcut.ps1

# 动态推导路径（不依赖硬编码）
$scriptDir   = $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptDir
$shortcutPs1 = Join-Path $projectRoot "scripts\run_from_a4_shortcut.ps1"

Write-Host "============================================================" -ForegroundColor Green
Write-Host "安装 run_from_a4_shortcut 到 PowerShell profile" -ForegroundColor Green
Write-Host "项目根目录: $projectRoot" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# 检查快捷脚本是否存在
if (-not (Test-Path $shortcutPs1)) {
    Write-Host "Error: 未找到 $shortcutPs1" -ForegroundColor Red
    Write-Host "请确认项目结构完整" -ForegroundColor Yellow
    exit 1
}
Write-Host "快捷脚本: $shortcutPs1" -ForegroundColor Green

# 确保 profile 文件存在
if (-not (Test-Path $PROFILE)) {
    Write-Host "创建 PowerShell profile: $PROFILE" -ForegroundColor Cyan
    New-Item -Path $PROFILE -ItemType File -Force | Out-Null
}
Write-Host "Profile: $PROFILE" -ForegroundColor Green
Write-Host ""

# 检查是否已安装（避免重复写入）
$profileContent = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
$marker = "# TAI-IPX Banner Shortcut"
if ($profileContent -and $profileContent.Contains($marker)) {
    Write-Host "已安装（跳过重复写入）" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "使用方式:" -ForegroundColor Cyan
    Write-Host "  run_from_a4_shortcut" -ForegroundColor White
    Write-Host "  run_from_a4_shortcut -MainTitle `"游戏名`" -Subtitle `"副标题`"" -ForegroundColor White
    Write-Host "  run_from_a4_shortcut -A4Image `"output/xxx/tianchong.png`"" -ForegroundColor White
    exit 0
}

# 写入 profile（使用动态路径变量，不硬编码）
$installBlock = @"

$marker
`$_bannerRoot = "$projectRoot"
if (Test-Path "`$_bannerRoot\scripts\run_from_a4_shortcut.ps1") {
    . "`$_bannerRoot\scripts\run_from_a4_shortcut.ps1"
}
"@

Add-Content -Path $PROFILE -Value $installBlock -Encoding UTF8

Write-Host "安装成功!" -ForegroundColor Green
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "下一步：重新加载 profile 使命令生效" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  . `$PROFILE" -ForegroundColor White
Write-Host ""
Write-Host "或直接重新打开 PowerShell 窗口" -ForegroundColor White
Write-Host ""
Write-Host "使用方式:" -ForegroundColor Cyan
Write-Host "  run_from_a4_shortcut" -ForegroundColor White
Write-Host "  run_from_a4_shortcut -MainTitle `"游戏名`" -Subtitle `"副标题`"" -ForegroundColor White
Write-Host "  run_from_a4_shortcut -A4Image `"output/xxx/tianchong.png`"" -ForegroundColor White
Write-Host "  run_from_a4_shortcut -Genre `"商店日常`"" -ForegroundColor White
Write-Host "  run_from_a4_shortcut -Packy7s" -ForegroundColor White
Write-Host ""
