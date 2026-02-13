<#
.SYNOPSIS
    Starts Claude Code with real-time speech output.

.DESCRIPTION
    Launches claude-speak.py as a background monitor that watches Claude's
    JSONL conversation logs for new assistant messages and speaks them.
    Claude Code runs normally in the foreground with full interactivity.

.PARAMETER ProjectPath
    The project directory to work in.

.PARAMETER ClaudeHome
    The .claude directory for this project.

.EXAMPLE
    .\Start-ClaudeWithSpeech.ps1 -ProjectPath "C:\Projects\MyApp" -ClaudeHome "C:\Projects\MyApp\.claude"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectPath,

    [Parameter(Mandatory=$true)]
    [string]$ClaudeHome,

    [string]$Voice = "en-US-GuyNeural",
    [string]$Rate = "+10%",
    [int]$Debounce = 2000
)

$ErrorActionPreference = "Stop"

$ToolsDir = "$env:USERPROFILE\.claude\tools"
$ClaudeSpeak = "$ToolsDir\claude-speak.py"

if (-not (Test-Path $ClaudeSpeak)) {
    Write-Error "claude-speak.py not found at $ClaudeSpeak"
    exit 1
}

# Set environment
$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE = "1"
$env:CLAUDE_HOME = $ClaudeHome

# Change to project directory
Set-Location $ProjectPath

Write-Host "Starting Claude Code with speech..." -ForegroundColor Cyan
Write-Host "Voice: $Voice | Rate: $Rate | Debounce: ${Debounce}ms" -ForegroundColor DarkGray
Write-Host ""

# Kill any existing speech monitors (prevents duplicates)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*claude-speak*" } |
    ForEach-Object {
        Write-Host "Killing existing speech monitor (PID: $($_.ProcessId))" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Start speech monitor in background (watches JSONL conversation logs)
# Scoped to this project's CWD so it only speaks THIS session's output
$speechProcess = Start-Process -FilePath "python" -ArgumentList @(
    "`"$ClaudeSpeak`"",
    "--cwd", "`"$ProjectPath`"",
    "--voice", $Voice,
    "--rate", $Rate,
    "--debounce", $Debounce
) -PassThru -WindowStyle Hidden

Write-Host "Speech monitor started (PID: $($speechProcess.Id))" -ForegroundColor DarkGray
Write-Host ""

try {
    # Run Claude interactively in foreground (full TTY, no piping)
    # Add flags as needed, e.g.: --continue, --resume
    & claude --continue
}
finally {
    Write-Host ""
    Write-Host "Stopping speech monitor..." -ForegroundColor DarkGray

    if (-not $speechProcess.HasExited) {
        Stop-Process -Id $speechProcess.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Done." -ForegroundColor Green
}
