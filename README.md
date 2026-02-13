# claude-speak

**Free text-to-speech for Claude Code.** Hear responses read aloud using Microsoft Neural voices -- zero cost, zero API keys, zero configuration.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#platform-support)

<!-- TODO: Add demo GIF here -->
<!-- ![claude-speak demo](demo.gif) -->

---

## Why claude-speak?

There are several TTS tools for Claude Code. Here's why claude-speak is different:

| | claude-speak | [VoiceMode](https://github.com/mbailey/voicemode) | [AgentVibes](https://github.com/paulpreibisch/AgentVibes) | [claude-code-tts](https://github.com/ybouhjira/claude-code-tts) |
|---|:---:|:---:|:---:|:---:|
| **Cost** | **Free** | Free or paid | Free or paid | ~$0.015/1K chars |
| **API key needed** | **No** | Yes (OpenAI) | Optional | Yes (OpenAI) |
| **Model download** | **No** | Yes (Kokoro) | Yes (Piper) | No |
| **Voices** | **400+** | ~20 | 50+ | 6 |
| **Integration** | None required | MCP server | MCP server | MCP + hooks |
| **Setup steps** | **1 command** | 3-5 | 3-5 | 3-5 |
| **Works offline** | No | Yes (Kokoro) | Yes (Piper) | No |

claude-speak uses [edge-tts](https://github.com/rany2/edge-tts), which provides free access to Microsoft's Neural TTS voices (the same ones powering Edge's Read Aloud). No signup, no billing, no model files to download.

**Trade-off:** Requires internet. If you need offline TTS, check out VoiceMode (Kokoro) or AgentVibes (Piper).

## Quick Start

```bash
# Clone
git clone https://github.com/silverdolphin863/claude-speak.git
cd claude-speak

# Install (Linux/macOS)
chmod +x install.sh && ./install.sh

# Install (Windows PowerShell)
.\install.ps1
```

Then start the speech monitor:

```bash
python ~/.claude/tools/claude-speak.py
```

That's it. Open Claude Code in another terminal and start working -- responses are read aloud automatically.

## How It Works

```
Claude Code  ──>  JSONL logs  ──>  claude-speak  ──>  edge-tts  ──>  speaker
(you work       ~/.claude/       (background        (Microsoft      (your
 normally)      projects/         monitor)            Neural TTS)     speakers)
                *.jsonl                                FREE
```

1. Claude Code writes every message to JSONL log files in `~/.claude/projects/`
2. claude-speak watches these files for new assistant messages
3. Text is cleaned (strips code blocks, ANSI codes, markdown, file paths, tool output)
4. Cleaned text is sent to edge-tts for neural speech synthesis
5. Audio plays through your speakers

The monitor is **completely decoupled** from Claude Code. No hooks, no MCP server, no API proxy -- it just reads the log files. This means it works with any Claude Code version without breaking on updates.

## Features

- **Zero cost** -- Microsoft's free Neural TTS voices
- **400+ voices** in 50+ languages
- **Zero config** -- works out of the box, no API keys needed
- **Per-project settings** -- different voice or on/off per project
- **Smart text cleaning** -- strips code blocks, file paths, ANSI escapes, markdown, spinners, box-drawing, tool invocations, token counts
- **Debounce** -- batches rapid output to prevent stuttering (configurable, default 2s)
- **Deduplication** -- uses `message.id` to prevent double-speaking
- **Global mode** -- run once, monitors whichever project is currently active
- **Settings UI** -- web-based voice browser with audio preview
- **`/speak` skill** -- toggle speech, change voices from within Claude Code
- **Cross-platform** -- Windows (MCI), macOS (afplay), Linux (ffplay)

## Settings UI

Browse voices, preview audio, and configure per-project settings:

```bash
python ~/.claude/tools/configure.py
# Opens http://localhost:8910
```

## Using the `/speak` Skill

Once installed, control speech from within Claude Code:

```
/speak            Toggle speech on/off
/speak on         Enable speech
/speak off        Disable speech
/speak status     Show current voice and state
/speak voices     List recommended voices
/speak voice <n>  Set voice for this project
```

## Voices

### Recommended (English)

| Voice | Gender | Accent | Voice ID |
|-------|--------|--------|----------|
| Guy | Male | US | `en-US-GuyNeural` |
| Andrew | Male | US | `en-US-AndrewMultilingualNeural` |
| Brian | Male | US | `en-US-BrianMultilingualNeural` |
| Ryan | Male | UK | `en-GB-RyanNeural` |
| Aria | Female | US | `en-US-AriaNeural` |
| Jenny | Female | US | `en-US-JennyNeural` |
| Ava | Female | US | `en-US-AvaMultilingualNeural` |
| Sonia | Female | UK | `en-GB-SoniaNeural` |

47 English voices across US, UK, AU, CA, IN, IE, NZ, SG, ZA. 400+ voices total in 50+ languages. Browse them all in the Settings UI or run:

```bash
python -m edge_tts --list-voices
```

## CLI Reference

### claude-speak.py (Background Monitor)

```
python claude-speak.py [options]

Options:
  --cwd, -c PATH      Scope to specific project directory
  --voice, -v NAME     TTS voice (default: en-US-GuyNeural)
  --rate, -r RATE      Speech rate, e.g. "+20%", "-10%" (default: +10%)
  --debounce, -d MS    Debounce delay before speaking (default: 2000)
```

**Global mode** (no `--cwd`): Monitors whichever project is currently active. Rescans every 5 seconds.

**Scoped mode** (`--cwd`): Only monitors the specified project.

### cc-speak.py (TTS Engine)

```
python cc-speak.py [options] [file]

# Read a file aloud
python cc-speak.py output.txt

# Pipe text
echo "Hello world" | python cc-speak.py

# Preview cleaned text without speaking
python cc-speak.py --preview "Some **markdown** with `code`"

# Real-time file monitoring
python cc-speak.py --follow /tmp/claude.log

# Use OpenAI TTS instead (requires OPENAI_API_KEY)
python cc-speak.py --backend openai --voice coral output.txt

Options:
  --follow, -f FILE    Watch file for new content (real-time mode)
  --backend, -b NAME   TTS backend: "edge" (free) or "openai" (paid)
  --voice, -v NAME     Voice name
  --rate, -r RATE      Edge-tts rate adjustment (e.g. "+20%")
  --speed, -s FLOAT    OpenAI speed multiplier (0.25-4.0)
  --output, -o FILE    Save audio to file instead of playing
  --keep-code          Don't strip code blocks
  --keep-paths         Don't strip file paths
  --raw                Skip all text cleaning
  --preview            Print cleaned text instead of speaking
  --debounce, -d MS    Debounce delay in follow mode (default: 2000)
```

### configure.py (Settings Server)

```
python configure.py [options]

Options:
  --port, -p PORT      Server port (default: 8910)
  --no-browser         Don't auto-open browser
```

## Configuration

### Per-Project Config Files

Settings are stored as simple flag files in `~/.claude/projects/<encoded-dir>/`:

| File | Purpose |
|------|---------|
| `speech-paused` | When this file exists, speech is paused for this project |
| `speech-voice` | Contains the voice name (e.g. `en-GB-RyanNeural`) |

Project directory names are derived from the CWD with `:`, `\`, `/` replaced by `-`.
Example: `C:\Projects\MyApp` becomes `C--Projects-MyApp`

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CC_SPEAK_BACKEND` | TTS backend | `edge` |
| `CC_SPEAK_VOICE` | Default voice | `en-US-GuyNeural` |
| `CC_SPEAK_RATE` | Speech rate | `+0%` |
| `CC_SPEAK_SPEED` | OpenAI speed | `1.0` |
| `OPENAI_API_KEY` | Required for OpenAI backend | - |

## Windows Launcher

Start both the speech monitor and Claude Code together:

```powershell
.\Start-ClaudeWithSpeech.ps1 -ProjectPath "C:\Projects\MyApp" -ClaudeHome "C:\Projects\MyApp\.claude"
```

The monitor starts as a hidden background process and stops automatically when Claude Code exits.

## Platform Support

| Platform | Audio Playback | Status |
|----------|---------------|--------|
| Windows | MCI (built-in, windowless) | Full support |
| macOS | afplay (built-in) | Full support |
| Linux | ffplay (install ffmpeg) | Full support |

## Troubleshooting

**No sound?**
- Check if speech is paused: `/speak status`
- Test TTS directly: `python cc-speak.py "Hello test"`
- On Linux, install ffmpeg: `sudo apt install ffmpeg`

**Double speaking?**
- Only run one monitor per project (PID lock prevents this, but check for stale `.pid` files)
- Delete stale PID files in `~/.claude/projects/<project>/speech-monitor.pid`

**Monitor not picking up output?**
- Ensure Claude Code is writing to `~/.claude/projects/`
- Check the encoded directory name matches your project path

**edge-tts errors?**
- Check internet connection (edge-tts requires Microsoft's servers)
- Update edge-tts: `pip install --upgrade edge-tts`

## How It Compares Architecturally

Most Claude Code TTS tools use MCP servers or hooks. claude-speak takes a different approach:

| Approach | How it works | Pros | Cons |
|----------|-------------|------|------|
| **JSONL monitoring** (claude-speak) | Reads Claude's log files | Zero integration needed, survives updates | Slight delay, requires internet |
| **MCP server** | Claude calls TTS as a tool | Official extension point | Setup required, breaks on MCP changes |
| **Hooks** | Runs on stop/notification events | Event-driven, low latency | Config in settings.json, version-dependent |
| **API proxy** | Intercepts Claude API traffic | Full control | Complex setup, fragile |

## Requirements

- Python 3.8+
- [edge-tts](https://github.com/rany2/edge-tts) (`pip install edge-tts`)
- Internet connection (for Microsoft Neural TTS)
- ffplay on Linux only (for audio playback): `sudo apt install ffmpeg`

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features.

## License

MIT License. See [LICENSE](LICENSE) for details.
