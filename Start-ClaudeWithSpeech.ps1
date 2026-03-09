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

# Validate claude-speak.py exists
if (-not (Test-Path $ClaudeSpeak)) {
    Write-Error "claude-speak.py not found at $ClaudeSpeak. Run install.ps1 first."
    exit 1
}

# Validate Claude Code is installed
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "Claude Code CLI not found. Install it from https://docs.anthropic.com/claude-code"
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

# Normalize project path for matching against --cwd in command lines
$normalizedProject = $ProjectPath.TrimEnd('\', '/').ToLower()

# Kill existing speech monitors for THIS project only (prevents duplicates)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*claude-speak*" -and $_.CommandLine -like "*$normalizedProject*" } |
    ForEach-Object {
        Write-Host "Killing existing speech monitor for this project (PID: $($_.ProcessId))" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# Also check python3.exe on systems where it's named differently
Get-CimInstance Win32_Process -Filter "Name='python3.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*claude-speak*" -and $_.CommandLine -like "*$normalizedProject*" } |
    ForEach-Object {
        Write-Host "Killing existing speech monitor for this project (PID: $($_.ProcessId))" -ForegroundColor DarkYellow
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

# Brief delay to let the monitor initialize before Claude starts
Start-Sleep -Milliseconds 500

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
