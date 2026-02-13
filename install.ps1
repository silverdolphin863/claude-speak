<#
.SYNOPSIS
    Install claude-speak for Windows.

.DESCRIPTION
    Installs edge-tts, copies scripts to ~/.claude/tools/,
    and installs the /speak skill for Claude Code.
#>

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  claude-speak installer" -ForegroundColor Cyan
Write-Host "  Free text-to-speech for Claude Code" -ForegroundColor DarkGray
Write-Host ""

# Determine source directory (where this script lives)
$SourceDir = $PSScriptRoot
if (-not $SourceDir) { $SourceDir = Get-Location }

# Target directories
$ClaudeDir = "$env:USERPROFILE\.claude"
$ToolsDir  = "$ClaudeDir\tools"
$SkillDir  = "$ClaudeDir\skills\speak"

# 1. Install edge-tts
Write-Host "[1/3] Installing edge-tts..." -ForegroundColor Yellow
try {
    pip install edge-tts --quiet 2>&1 | Out-Null
    Write-Host "  OK - edge-tts installed" -ForegroundColor Green
} catch {
    Write-Host "  WARN - pip install failed, trying pip3..." -ForegroundColor DarkYellow
    pip3 install edge-tts --quiet 2>&1 | Out-Null
    Write-Host "  OK - edge-tts installed via pip3" -ForegroundColor Green
}

# 2. Copy scripts to ~/.claude/tools/
Write-Host "[2/3] Copying scripts to $ToolsDir..." -ForegroundColor Yellow
New-Item -Path $ToolsDir -ItemType Directory -Force | Out-Null

$scripts = @("claude-speak.py", "cc-speak.py", "configure.py", "settings.html")
foreach ($script in $scripts) {
    $src = Join-Path $SourceDir $script
    if (Test-Path $src) {
        Copy-Item $src -Destination $ToolsDir -Force
        Write-Host "  OK - $script" -ForegroundColor Green
    } else {
        Write-Host "  SKIP - $script not found in $SourceDir" -ForegroundColor DarkYellow
    }
}

# 3. Install /speak skill
Write-Host "[3/3] Installing /speak skill..." -ForegroundColor Yellow
New-Item -Path $SkillDir -ItemType Directory -Force | Out-Null

$skillSrc = Join-Path $SourceDir "skill\SKILL.md"
if (Test-Path $skillSrc) {
    Copy-Item $skillSrc -Destination $SkillDir -Force
    Write-Host "  OK - /speak skill installed" -ForegroundColor Green
} else {
    Write-Host "  SKIP - skill/SKILL.md not found" -ForegroundColor DarkYellow
}

# Done
Write-Host ""
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick start:" -ForegroundColor Cyan
Write-Host "    # Start the speech monitor (all projects):" -ForegroundColor DarkGray
Write-Host "    python `"$ToolsDir\claude-speak.py`"" -ForegroundColor White
Write-Host ""
Write-Host "    # Open settings UI:" -ForegroundColor DarkGray
Write-Host "    python `"$ToolsDir\configure.py`"" -ForegroundColor White
Write-Host ""
Write-Host "    # In Claude Code, use /speak to toggle" -ForegroundColor DarkGray
Write-Host ""
