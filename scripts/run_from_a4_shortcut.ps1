# run_from_a4_shortcut.ps1
# One-click banner pipeline: prompt → bg.png → A5 → A6 → compose
# Usage: run directly (auto-find latest bg.png), or with parameters
#
# After install, use in any PowerShell: run_from_a4_shortcut
# Install: . .\scripts\install_shortcut.ps1

function Run-FromA4-Shortcut {
    [CmdletBinding()]
    param(
        [string]$MainTitle       = "",
        [string]$Subtitle        = "",
        [string]$BgImage         = "",
        [string]$Genre           = "",
        [string]$Description     = "",
        [string]$DescriptionFile = "",
        [switch]$PromptEngine,
        [switch]$SkipA6,
        [switch]$Packy,
        [switch]$Packy7s,
        [switch]$Lovart,
        [switch]$Gemini,
        [switch]$T8star,
        [switch]$Micugpt2,
        [switch]$Micugemini
    )

    # Dynamic project root (script in scripts/, parent is root)
    $scriptDir   = $PSScriptRoot
    $projectRoot = Split-Path -Parent $scriptDir
    $pyScript    = Join-Path $projectRoot "scripts\run_from_a4.py"

    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "skills-store-operational-banner-design - run_from_a4 shortcut" -ForegroundColor Green
    Write-Host "Project: $projectRoot" -ForegroundColor DarkGray
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""

    # Check run_from_a4.py exists
    if (-not (Test-Path $pyScript)) {
        Write-Host "Error: $pyScript not found" -ForegroundColor Red
        return
    }

    # Detect Python
    $pythonExe = $null
    foreach ($cmd in @("py", "python", "python3")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { $pythonExe = $found.Source; break }
    }
    if (-not $pythonExe) {
        Write-Host "Error: Python not found. Please ensure Python 3.8+ is installed." -ForegroundColor Red
        return
    }
    Write-Host "Python: $pythonExe" -ForegroundColor DarkGray

    # Build argument list
    $pyArgs = @($pyScript)

    if ($BgImage) {
        if (-not (Test-Path $BgImage)) {
            Write-Host "Error: BgImage not found: $BgImage" -ForegroundColor Red
            return
        }
        $pyArgs += $BgImage
        Write-Host "BgImage: $BgImage" -ForegroundColor Cyan
    } elseif (-not $PromptEngine -and -not $Description -and -not $DescriptionFile) {
        Write-Host "BgImage: auto-find latest bg.png in output/" -ForegroundColor Cyan
    }

    if ($MainTitle)       { $pyArgs += "--main-title",       $MainTitle       }
    if ($Subtitle)        { $pyArgs += "--subtitle",         $Subtitle        }
    if ($Genre)           { $pyArgs += "--genre",            $Genre           }
    if ($Description)     { $pyArgs += "--description",      $Description     }
    if ($DescriptionFile) { $pyArgs += "--description-file", $DescriptionFile }
    if ($PromptEngine)    { $pyArgs += "--prompt-engine" }
    if ($Packy)           { $pyArgs += "--packy"    }
    if ($Packy7s)         { $pyArgs += "--packy7s"  }
    if ($Lovart)          { $pyArgs += "--lovart"   }
    if ($Gemini)          { $pyArgs += "--gemini"   }
    if ($T8star)          { $pyArgs += "--t8star"   }
    if ($Micugpt2)        { $pyArgs += "-micugpt2"  }
    if ($Micugemini)      { $pyArgs += "-micugemini"}

    Write-Host "Main Title: $(if ($MainTitle) { $MainTitle } else { '(none)' })" -ForegroundColor Cyan
    Write-Host "Subtitle: $(if ($Subtitle) { $Subtitle } else { '(none)' })" -ForegroundColor Cyan
    if ($PromptEngine)     { Write-Host "Mode: 生图 + 合成 (prompt-engine)" -ForegroundColor Yellow }
    elseif ($Description -or $DescriptionFile) { Write-Host "Mode: 生图 + 合成 (手动描述)" -ForegroundColor Yellow }
    else                   { Write-Host "Mode: 复用已有图" -ForegroundColor Cyan }
    if ($Lovart)           { Write-Host "Backend: Lovart" -ForegroundColor Magenta }
    elseif ($T8star)       { Write-Host "Backend: t8star" -ForegroundColor Magenta }
    elseif ($Gemini)       { Write-Host "Backend: Gemini" -ForegroundColor Magenta }
    elseif ($Micugpt2)     { Write-Host "Backend: micugpt2" -ForegroundColor Magenta }
    else                   { Write-Host "Backend: .env default" -ForegroundColor Cyan }
    Write-Host ""

    # Execute from project root (ensure relative paths work)
    Push-Location $projectRoot
    try {
        & $pythonExe @pyArgs
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "============================================================" -ForegroundColor Green
            Write-Host "Done! Output in output/ directory" -ForegroundColor Green
            Write-Host "============================================================" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "============================================================" -ForegroundColor Red
            Write-Host "Failed, exit code: $LASTEXITCODE" -ForegroundColor Red
            Write-Host "============================================================" -ForegroundColor Red
        }
    } finally {
        Pop-Location
    }
}

Set-Alias -Name run_from_a4_shortcut -Value Run-FromA4-Shortcut -Scope Global -Force
