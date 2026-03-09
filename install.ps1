# encoding: utf-8
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

# ── Pre-flight checks ──────────────────────────────────────────────

# Check Python is installed
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
} else {
    Write-Host "  ERROR: Python 3 is required but not found." -ForegroundColor Red
    Write-Host "  Install Python 3.8+ from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# Check Python version >= 3.8
$pyVersion = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
$pyMajor   = & $pythonCmd -c "import sys; print(sys.version_info.major)" 2>$null
$pyMinor   = & $pythonCmd -c "import sys; print(sys.version_info.minor)" 2>$null

if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 8)) {
    Write-Host "  ERROR: Python 3.8+ is required (found $pyVersion)." -ForegroundColor Red
    Write-Host "  Please upgrade Python: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

Write-Host "  Python $pyVersion detected ($pythonCmd)" -ForegroundColor DarkGray

# Warn if tools directory already exists with claude-speak
if ((Test-Path "$ToolsDir\claude-speak.py")) {
    Write-Host ""
    Write-Host "  NOTE: Existing installation found in $ToolsDir" -ForegroundColor DarkYellow
    Write-Host "  Files will be overwritten." -ForegroundColor DarkYellow
    Write-Host ""
}

# ── Step 1: Install edge-tts ───────────────────────────────────────

Write-Host "[1/3] Installing edge-tts..." -ForegroundColor Yellow
$pipInstalled = $false

# Try pip first, then pip3
foreach ($pipCmd in @("pip", "pip3")) {
    if (Get-Command $pipCmd -ErrorAction SilentlyContinue) {
        try {
            & $pipCmd install edge-tts --quiet 2>&1 | Out-Null
            $pipInstalled = $true
            break
        } catch {
            # Try next pip variant
        }
    }
}

if (-not $pipInstalled) {
    Write-Host "  ERROR: Failed to install edge-tts. Ensure pip is available." -ForegroundColor Red
    exit 1
}

# Verify edge-tts is importable
$edgeCheck = & $pythonCmd -c "import edge_tts" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: edge-tts installed but cannot be imported." -ForegroundColor Red
    Write-Host "  Try: $pythonCmd -m pip install edge-tts" -ForegroundColor Red
    exit 1
}

Write-Host "  OK - edge-tts installed" -ForegroundColor Green

# ── Step 2: Copy scripts ───────────────────────────────────────────

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

# ── Step 3: Install /speak skill ───────────────────────────────────

Write-Host "[3/3] Installing /speak skill..." -ForegroundColor Yellow
New-Item -Path $SkillDir -ItemType Directory -Force | Out-Null

$skillSrc = Join-Path $SourceDir "skill\SKILL.md"
if (Test-Path $skillSrc) {
    Copy-Item $skillSrc -Destination $SkillDir -Force
    Write-Host "  OK - /speak skill installed" -ForegroundColor Green
} else {
    Write-Host "  SKIP - skill/SKILL.md not found" -ForegroundColor DarkYellow
}

# ── Done ────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick start:" -ForegroundColor Cyan
Write-Host "    # Start the speech monitor (all projects):" -ForegroundColor DarkGray
Write-Host "    $pythonCmd `"$ToolsDir\claude-speak.py`"" -ForegroundColor White
Write-Host ""
Write-Host "    # Open settings UI:" -ForegroundColor DarkGray
Write-Host "    $pythonCmd `"$ToolsDir\configure.py`"" -ForegroundColor White
Write-Host ""
Write-Host "    # In Claude Code, use /speak to toggle" -ForegroundColor DarkGray
Write-Host ""
