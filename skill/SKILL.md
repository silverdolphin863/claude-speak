---
name: speak
description: Toggle voice output (text-to-speech) on or off for the current project, list voices, or change voice
---

# Speech Control (Per-Project)

Control the background text-to-speech voice output for the current project.

## Usage
```
/speak            # Toggle speech on/off for this project
/speak on         # Enable speech
/speak off        # Disable speech
/speak status     # Check current status and voice
/speak voices     # List available voices
/speak voice <name>  # Set voice for this project
/speak voice reset   # Reset to default voice
```

## How It Works

The speech system uses per-project files in `~/.claude/projects/<project-dir>/`:
- `speech-paused` — when this file exists, speech is paused for this project
- `speech-voice` — contains the voice name override for this project

The project directory name is derived from the CWD by replacing `:` `\` `/` with `-`.
Example: `C:\Projects\MyApp` → `C--Projects-MyApp`

## Available Voices (Top Picks)

| Voice | Gender | Accent | ID |
|-------|--------|--------|----|
| Guy | Male | US | `en-US-GuyNeural` |
| Andrew | Male | US | `en-US-AndrewMultilingualNeural` |
| Ryan | Male | UK | `en-GB-RyanNeural` |
| Aria | Female | US | `en-US-AriaNeural` |
| Jenny | Female | US | `en-US-JennyNeural` |
| Sonia | Female | UK | `en-GB-SoniaNeural` |

For the full list, run: `python -m edge_tts --list-voices`

## Instructions

When this skill is invoked, determine the current project directory and encoded name:
- CWD example: `C:\Projects\MyApp`
- Encoded: `C--Projects-MyApp`
- Config dir: `~/.claude/projects/C--Projects-MyApp/`

### `/speak` (no args) — Toggle
```powershell
$flagFile = "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused"
if (Test-Path $flagFile) {
    Remove-Item $flagFile -Force
    # Speech is now ON
} else {
    New-Item $flagFile -ItemType File -Force
    # Speech is now OFF
}
```

### `/speak on`
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -Force -ErrorAction SilentlyContinue
```

### `/speak off`
```powershell
New-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -ItemType File -Force
```

### `/speak status`
Check both `speech-paused` and `speech-voice` files. Report:
- Speech: ON/OFF
- Voice: <current voice or "default (en-US-GuyNeural)">

### `/speak voices`
Show the voice table above. Mention that `python -m edge_tts --list-voices` shows all available voices.

### `/speak voice <name>`
Write the voice name to the config file:
```powershell
Set-Content "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" "<VOICE_NAME>" -NoNewline
```
The change takes effect on the next spoken message (no restart needed).

### `/speak voice reset`
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" -Force -ErrorAction SilentlyContinue
```

### Response format
Always be concise. Examples:
- "Speech for MyApp: ON"
- "Speech for MyApp: OFF"
- "Voice for MyApp set to: en-GB-RyanNeural"
- "Voice for MyApp reset to default (en-US-GuyNeural)"
