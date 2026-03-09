# Roadmap

Planned features and improvements for claude-speak.

## Near Term

- [ ] **Claude Code hooks integration** -- Optional hook-based mode as an alternative to JSONL monitoring, for lower latency
- [ ] **PyPI package** -- `pip install claude-speak` for easier installation
- [ ] **Speech rate per-project** -- Save rate preference alongside voice in config files
- [ ] **Voice preview command** -- `/speak preview <voice>` to hear a sample without changing settings

## Medium Term

- [ ] **Local TTS backends** -- Support for offline engines:
  - [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (ONNX, high quality, ~300MB model)
  - [Piper](https://github.com/rhasspy/piper) (fast, lightweight, many languages)
  - System TTS (Windows SAPI, macOS `say`)
- [ ] **Streaming TTS** -- Start speaking before the full response is complete
- [ ] **MCP server mode** -- Run as an MCP server for tighter Claude Code integration

## Long Term

- [ ] **Sentence-level streaming** -- Speak each sentence as it arrives, not after debounce
- [ ] **Multi-agent support** -- Different voices for different Claude instances
- [ ] **Audio ducking** -- Lower system audio while speaking
- [ ] **Notification sounds** -- Optional sound effects for tool usage, errors, completion

## Non-Goals

- **Speech-to-text input** -- There are dedicated tools for voice input (VoiceMode, claude_code_voice). claude-speak focuses on output only.
- **GUI application** -- claude-speak is a CLI tool. The settings UI is a lightweight web page, not a desktop app.
- **Replacing Claude Code's UI** -- claude-speak adds audio on top of the existing terminal experience.

## Contributing

Want to work on something from this list? Open an issue to discuss the approach before submitting a PR.
