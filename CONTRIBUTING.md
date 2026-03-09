# Contributing to claude-speak

Thanks for your interest in contributing.

## Reporting Bugs

Open an issue with:
- Your OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Any error output from stderr

## Suggesting Features

Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Alternatives you've considered

## Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test on your platform:
   - `python cc-speak.py --preview "Test text with **markdown** and \`code\`"` (text cleaning)
   - `python cc-speak.py "Hello world"` (audio playback)
   - `python claude-speak.py` (monitor mode)
5. Commit with a clear message
6. Open a PR

## Code Style

- Python 3.8+ compatible (no walrus operator, no `match` statements)
- Use `argparse` for CLI arguments
- Keep dependencies minimal -- `edge-tts` is the only required dependency
- Cross-platform: test or guard platform-specific code (`sys.platform`)

## Architecture

```
claude-speak.py  -- Background monitor, watches JSONL logs
cc-speak.py      -- Core TTS engine, text cleaning, audio playback
configure.py     -- Web-based settings UI
settings.html    -- Frontend for configure.py
skill/SKILL.md   -- Claude Code /speak skill definition
```

**Text cleaning** lives in `cc-speak.py`. If Claude Code output has a new pattern that shouldn't be spoken (new tool format, new status line, etc.), add a regex pattern there.

**Audio playback** is platform-specific: Windows uses MCI via ctypes, macOS uses afplay, Linux uses ffplay. New platforms need a new playback function.

## What's Welcome

- New TTS backends (local engines like Kokoro, Piper, etc.)
- Better text cleaning patterns for Claude Code output
- Bug fixes and platform-specific fixes
- Documentation improvements
- Performance improvements

## What to Avoid

- Adding heavy dependencies
- Breaking changes to the flag-file config system
- Features that require Claude Code modifications
