#!/usr/bin/env python3
"""
cc-speak: Read Claude Code terminal output aloud using high-quality TTS.

Backends:
  - edge-tts (default, free) — Microsoft Neural voices
  - openai (paid) — gpt-4o-mini-tts, highest quality

Usage:
  claude "explain X" 2>/dev/null | cc-speak
  cc-speak output.txt
  cc-speak --follow /tmp/claude.log     # Real-time monitoring
  cc-speak --backend openai --voice coral < output.txt

Real-time mode:
  # Terminal 1: Start listener
  cc-speak --follow /tmp/claude-output.txt

  # Terminal 2: Run Claude with output capture
  claude 2>&1 | tee /tmp/claude-output.txt
"""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import queue
from pathlib import Path

# ─── Text Cleaning ────────────────────────────────────────────────────────────

# ANSI escape sequences (colors, cursor moves, etc.)
RE_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b[()][AB012]|\x1b\[[\d;]*m")

# Box-drawing and decorative Unicode chars
RE_BOX = re.compile(r"[─━│┃┌┐└┘├┤┬┴┼╭╮╰╯╔╗╚╝╠╣╦╩╬═║▀▄█▌▐░▒▓●○◆◇■□▪▫★☆✓✗✔✘⎿⎡⎣⎤⎦►▶◀◁▷▸▹◂◃]")

# Spinner and progress characters
RE_SPINNER = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾✻◐◑◒◓⏳⌛🔄]")

# Diff markers at line start
RE_DIFF = re.compile(r"^[+\-]{1,3}(?=\s)", re.MULTILINE)

# Lines that are purely decorative (only special chars and whitespace)
RE_DECORATIVE_LINE = re.compile(r"^[\s─━═╌╍┈┉•·…\-_~*#=+|<>\/\\]+$", re.MULTILINE)

# Tool use / XML-like tags from Claude output
RE_TOOL_TAGS = re.compile(r"</?(?:tool|artifact|function|parameter|result|content|antml)[^>]*>")

# File paths that look like absolute paths (common in Claude Code output)
RE_FILE_PATH = re.compile(r"(?:^|\s)(?:[A-Za-z]:)?(?:[/\\][\w.\-]+){2,}(?:\:\d+)?", re.MULTILINE)

# Windows paths
RE_WIN_PATH = re.compile(r"(?:^|\s)[A-Za-z]:\\(?:[\w.\-]+\\?)+", re.MULTILINE)

# Repeated blank lines
RE_MULTI_BLANK = re.compile(r"\n{3,}")

# Progress percentage patterns
RE_PROGRESS = re.compile(r"\d+%\s*[|█▓▒░\-=>#\[\]]+")

# Token/cost lines
RE_TOKENS = re.compile(r"^\s*[\d,.]+\s*(?:tokens?|tok)\b.*$", re.MULTILINE | re.IGNORECASE)

# Duration/timing lines from Claude Code
RE_TIMING = re.compile(r"^\s*(?:✻\s*)?(?:Worked|Completed|Duration|Elapsed)\s+(?:for\s+)?\d+.*$", re.MULTILINE | re.IGNORECASE)

# Tool invocation lines (Read, Write, Bash, etc.)
RE_TOOL_INVOKE = re.compile(r"^\s*(?:Read|Write|Edit|Bash|Glob|Grep|Task|TodoWrite)\s*\(.*\)\s*$", re.MULTILINE)

# Cost/token summary patterns
RE_COST = re.compile(r"^\s*(?:Cost|Tokens?|Input|Output|Cache)[\s:]+[\d$.,]+.*$", re.MULTILINE | re.IGNORECASE)


def clean_text(raw: str, skip_code: bool = True, skip_paths: bool = True) -> str:
    """Strip terminal formatting and noise from Claude Code output for natural speech."""
    text = raw

    # Strip ANSI escapes
    text = RE_ANSI.sub("", text)

    # Strip spinner/progress chars
    text = RE_SPINNER.sub("", text)

    # Strip box-drawing chars
    text = RE_BOX.sub(" ", text)

    # Strip tool tags
    text = RE_TOOL_TAGS.sub("", text)

    # Strip progress bars
    text = RE_PROGRESS.sub("", text)

    # Strip token counts, timing lines, costs
    text = RE_TOKENS.sub("", text)
    text = RE_TIMING.sub("", text)
    text = RE_COST.sub("", text)

    # Strip tool invocations
    text = RE_TOOL_INVOKE.sub("", text)

    # Strip diff markers
    text = RE_DIFF.sub("", text)

    # Strip decorative lines
    text = RE_DECORATIVE_LINE.sub("", text)

    # Optionally strip file paths (they sound awful read aloud)
    if skip_paths:
        text = RE_WIN_PATH.sub(" ", text)
        text = RE_FILE_PATH.sub(" ", text)

    # Optionally collapse code blocks
    if skip_code:
        # Fenced code blocks (```...```) — greedy match between fences
        text = re.sub(
            r"```[^\n]*\n.*?```",
            "\n[code block]\n",
            text,
            flags=re.DOTALL,
        )
        # Indented code blocks (4+ spaces, 3+ consecutive lines)
        text = re.sub(
            r"(?:^[ \t]{4,}\S.*\n){3,}",
            "[code block]\n",
            text,
            flags=re.MULTILINE,
        )
        # Inline backtick code (replace with just the content, no backticks)
        text = re.sub(r"`([^`]+)`", r"\1", text)

    # --- Markdown and formatting cleanup for natural speech ---

    # Markdown links [text](url) → just the text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Markdown images ![alt](url) → remove entirely
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

    # Markdown bold/italic: **text**, __text__, *text*, _text_
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(\S[^_]*\S)_{1,3}", r"\1", text)

    # Markdown headers (# Header) → just the text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Markdown horizontal rules
    text = re.sub(r"^[\-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Markdown bullet points: - item, * item → just the text
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)

    # Numbered lists: 1. item → just the text
    text = re.sub(r"^[\s]*\d+[.)]\s+", "", text, flags=re.MULTILINE)

    # HTML tags that might appear
    text = re.sub(r"<[^>]+>", "", text)

    # URLs (standalone) → skip them
    text = re.sub(r"https?://\S+", "", text)

    # Arrow characters → natural words
    text = text.replace("→", " to ")
    text = text.replace("←", " from ")
    text = text.replace("=>", " to ")
    text = text.replace("->", " to ")
    text = text.replace(">>", " ")
    text = text.replace("<<", " ")

    # Common symbols that get read literally
    text = text.replace("&amp;", " and ")
    text = text.replace("&", " and ")
    text = text.replace("|", " or ")
    text = text.replace("@", " at ")
    text = text.replace("~", " ")

    # Underscores in identifiers (snake_case → "snake case")
    # Only for words that look like identifiers (letters/digits with underscores)
    text = re.sub(r"\b(\w+)_(\w+)\b", lambda m: m.group(0).replace("_", " ") if not m.group(0).startswith("__") else m.group(0), text)

    # Dots in qualified names (e.g., "item.image_url") → spaces
    # But preserve decimal numbers and ellipsis
    text = re.sub(r"(?<![0-9])\.(?=[a-zA-Z])", " ", text)

    # Parenthetical references like (line 42) or (file.php:123) - keep meaningful ones
    text = re.sub(r"\([^)]*\.\w+:\d+\)", "", text)

    # Strip standalone special chars: $, ^, ~, `, \
    text = re.sub(r"(?<!\w)[\\$^`~](?!\w)", " ", text)

    # Curly braces, square brackets (outside of already-handled markdown)
    text = re.sub(r"[{}\[\]]", " ", text)

    # Multiple punctuation (... is ok, but ---- or ==== etc.)
    text = re.sub(r"([=\-_]){2,}", " ", text)

    # Collapse multiple spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Collapse all blank lines to single newline (reduces TTS pauses)
    text = re.sub(r"\n\s*\n", "\n", text)

    # Strip leading/trailing whitespace per line
    text = "\n".join(line.strip() for line in text.splitlines())

    # Final trim
    text = text.strip()

    return text


# ─── TTS Backends ─────────────────────────────────────────────────────────────


async def tts_edge_async(text: str, voice: str, rate: str, output_path: str) -> str:
    """Generate speech using edge-tts (free)."""
    try:
        import edge_tts
    except ImportError:
        print("ERROR: edge-tts not installed. Run: pip install edge-tts", file=sys.stderr)
        sys.exit(1)

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)
    except Exception as e:
        err = str(e)
        if "name resolution" in err or "connect" in err.lower():
            print("ERROR: Cannot reach Microsoft TTS service. Check internet connection.", file=sys.stderr)
        else:
            print(f"ERROR: edge-tts failed: {e}", file=sys.stderr)
        return None

    return output_path


def tts_edge(text: str, voice: str, rate: str, output_path: str) -> str:
    """Sync wrapper for edge-tts."""
    return asyncio.run(tts_edge_async(text, voice, rate, output_path))


def tts_openai(text: str, voice: str, speed: float, output_path: str) -> str:
    """Generate speech using OpenAI gpt-4o-mini-tts (paid, best quality)."""
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # gpt-4o-mini-tts supports max 2000 tokens input per request.
    # For longer texts, chunk and concatenate.
    max_chars = 4000  # conservative limit (~2000 tokens)
    chunks = _chunk_text(text, max_chars)

    temp_files = []
    for i, chunk in enumerate(chunks):
        chunk_path = output_path.replace(".mp3", f"_chunk{i}.mp3")
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=chunk,
            speed=speed,
            instructions="Read this text naturally and clearly. It is output from a coding assistant. Skip any formatting artifacts, read code-related terms clearly.",
        )
        response.stream_to_file(chunk_path)
        temp_files.append(chunk_path)

    if len(temp_files) == 1:
        os.rename(temp_files[0], output_path)
    else:
        _concat_mp3(temp_files, output_path)
        for f in temp_files:
            os.remove(f)

    return output_path


def _chunk_text(text: str, max_chars: int) -> list:
    """Split text into chunks at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chars]]


def _concat_mp3(files: list, output: str):
    """Concatenate MP3 files using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Fallback: just cat the files (works for MP3)
        with open(output, "wb") as out:
            for f in files:
                with open(f, "rb") as inp:
                    out.write(inp.read())
        return

    list_file = output + ".list"
    with open(list_file, "w") as lf:
        for f in files:
            lf.write(f"file '{f}'\n")

    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output],
        capture_output=True,
    )
    os.remove(list_file)


# ─── Audio Playback ───────────────────────────────────────────────────────────


def _play_audio_mci(path: str):
    """Play MP3 using Windows MCI - completely windowless."""
    import ctypes
    winmm = ctypes.windll.winmm
    buf = ctypes.create_unicode_buffer(256)

    # Use a unique alias to avoid conflicts
    alias = f"snd{id(path) % 99999}"
    abs_path = os.path.abspath(path)

    # Open, play (blocking), close
    err = winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias {alias}', buf, 256, 0)
    if err != 0:
        return False
    winmm.mciSendStringW(f'play {alias} wait', buf, 256, 0)
    winmm.mciSendStringW(f'close {alias}', buf, 256, 0)
    return True


def play_audio(path: str, blocking: bool = True):
    """Play audio file without opening any visible window."""
    # On Windows, use MCI (zero windows, built-in MP3 support)
    if os.name == 'nt' and blocking:
        if _play_audio_mci(path):
            return True

    # Unix/macOS fallback or non-blocking
    players = [
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]),
        ("afplay", ["afplay", path]),  # macOS
    ]

    for name, cmd in players:
        if shutil.which(cmd[0]):
            try:
                if blocking:
                    subprocess.run(cmd, check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                continue

    print(f"WARNING: No audio player found. Audio saved to: {path}", file=sys.stderr)
    return False


# ─── Real-time Follow Mode ────────────────────────────────────────────────────


class SpeechQueue:
    """Queue-based speech system for real-time output."""

    def __init__(self, backend: str, voice: str, rate: str, speed: float, skip_code: bool, skip_paths: bool):
        self.backend = backend
        self.voice = voice
        self.rate = rate
        self.speed = speed
        self.skip_code = skip_code
        self.skip_paths = skip_paths
        self.queue = queue.Queue()
        self.running = True
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.temp_dir = tempfile.mkdtemp(prefix="cc_speak_")
        self.file_counter = 0

    def _worker(self):
        """Background worker that processes speech queue."""
        while self.running or not self.queue.empty():
            try:
                text = self.queue.get(timeout=0.5)
                if text is None:  # Poison pill
                    break
                self._speak(text)
                self.queue.task_done()
            except queue.Empty:
                continue

    def _speak(self, text: str):
        """Generate and play speech for text."""
        cleaned = clean_text(text, skip_code=self.skip_code, skip_paths=self.skip_paths)
        if not cleaned.strip():
            return

        # Skip very short fragments
        if len(cleaned.split()) < 3:
            return

        self.file_counter += 1
        output_path = os.path.join(self.temp_dir, f"speech_{self.file_counter}.mp3")

        try:
            if self.backend == "edge":
                result = tts_edge(cleaned, self.voice, self.rate, output_path)
            else:
                result = tts_openai(cleaned, self.voice, self.speed, output_path)

            if result and os.path.exists(output_path):
                play_audio(output_path)
                os.remove(output_path)
        except Exception as e:
            print(f"Speech error: {e}", file=sys.stderr)

    def enqueue(self, text: str):
        """Add text to speech queue."""
        self.queue.put(text)

    def stop(self):
        """Stop the speech worker."""
        self.running = False
        self.queue.put(None)  # Poison pill
        self.worker.join(timeout=5)
        # Cleanup temp dir
        try:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except:
            pass


def extract_speakable_chunks(text: str) -> list:
    """Extract speakable chunks from text, splitting at natural boundaries."""
    # Split on paragraph boundaries (double newlines) or sentence endings
    chunks = []

    # First split on paragraphs
    paragraphs = re.split(r'\n\s*\n', text)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If paragraph is short enough, use as-is
        if len(para) < 500:
            chunks.append(para)
        else:
            # Split long paragraphs into sentences
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) < 400:
                    current = f"{current} {sent}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)

    return chunks


def follow_file(filepath: str, speech_queue: SpeechQueue, debounce_ms: int = 2000):
    """Monitor a file for new content and speak it."""
    filepath = Path(filepath)

    # Create file if it doesn't exist
    if not filepath.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.touch()
        print(f"Created watch file: {filepath}", file=sys.stderr)

    print(f"Watching: {filepath}", file=sys.stderr)
    print("Press Ctrl+C to stop\n", file=sys.stderr)

    last_size = filepath.stat().st_size
    last_change = time.time()
    pending_text = ""
    spoken_length = 0

    try:
        while True:
            try:
                current_size = filepath.stat().st_size
            except FileNotFoundError:
                time.sleep(0.2)
                continue

            if current_size > last_size:
                # New content added
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_size)
                    new_content = f.read()

                pending_text += new_content
                last_size = current_size
                last_change = time.time()

            elif current_size < last_size:
                # File was truncated/reset
                last_size = 0
                pending_text = ""
                spoken_length = 0

            # Check if we should speak (debounce: wait for pause in output)
            if pending_text and (time.time() - last_change) * 1000 > debounce_ms:
                chunks = extract_speakable_chunks(pending_text)
                for chunk in chunks:
                    speech_queue.enqueue(chunk)
                pending_text = ""

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        # Speak any remaining text
        if pending_text.strip():
            chunks = extract_speakable_chunks(pending_text)
            for chunk in chunks:
                speech_queue.enqueue(chunk)


def follow_stdin(speech_queue: SpeechQueue, debounce_ms: int = 2000):
    """Read from stdin in real-time and speak."""
    print("Reading from stdin... Press Ctrl+C to stop\n", file=sys.stderr)

    pending_text = ""
    last_input = time.time()

    # Use select on Unix, threading on Windows
    if sys.platform == "win32":
        # Windows: use threading for non-blocking stdin
        input_queue = queue.Queue()

        def stdin_reader():
            for line in sys.stdin:
                input_queue.put(line)
            input_queue.put(None)  # EOF

        reader_thread = threading.Thread(target=stdin_reader, daemon=True)
        reader_thread.start()

        try:
            while True:
                try:
                    line = input_queue.get(timeout=0.1)
                    if line is None:  # EOF
                        break
                    pending_text += line
                    last_input = time.time()
                except queue.Empty:
                    pass

                # Debounce and speak
                if pending_text and (time.time() - last_input) * 1000 > debounce_ms:
                    chunks = extract_speakable_chunks(pending_text)
                    for chunk in chunks:
                        speech_queue.enqueue(chunk)
                    pending_text = ""

        except KeyboardInterrupt:
            pass

    else:
        # Unix: use select for non-blocking stdin
        import select

        try:
            while True:
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable:
                    line = sys.stdin.readline()
                    if not line:  # EOF
                        break
                    pending_text += line
                    last_input = time.time()

                # Debounce and speak
                if pending_text and (time.time() - last_input) * 1000 > debounce_ms:
                    chunks = extract_speakable_chunks(pending_text)
                    for chunk in chunks:
                        speech_queue.enqueue(chunk)
                    pending_text = ""

        except KeyboardInterrupt:
            pass

    # Speak remaining
    if pending_text.strip():
        chunks = extract_speakable_chunks(pending_text)
        for chunk in chunks:
            speech_queue.enqueue(chunk)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Read Claude Code output aloud using high-quality TTS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # One-shot mode
  claude "explain this" 2>/dev/null | cc-speak
  cc-speak output.txt --backend openai --voice coral

  # Real-time follow mode (run in separate terminal)
  cc-speak --follow /tmp/claude.log

  # Then in another terminal:
  claude 2>&1 | tee /tmp/claude.log

  # Or pipe directly with real-time:
  claude 2>&1 | cc-speak --follow -""",
    )
    parser.add_argument("file", nargs="?", help="Text file to read (or pipe via stdin)")
    parser.add_argument(
        "--follow", "-f",
        metavar="FILE",
        help="Watch file for new content (real-time mode). Use '-' for stdin.",
    )
    parser.add_argument(
        "--debounce", "-d",
        type=int,
        default=2000,
        help="Debounce delay in ms before speaking (default: 2000)",
    )
    parser.add_argument(
        "--backend", "-b",
        default=os.environ.get("CC_SPEAK_BACKEND", "edge"),
        choices=["edge", "openai"],
        help="TTS backend: 'edge' (free, default) or 'openai' (paid, best quality)",
    )
    parser.add_argument(
        "--voice", "-v",
        default=None,
        help="Voice name (default: en-US-GuyNeural for edge, coral for openai)",
    )
    parser.add_argument(
        "--rate", "-r",
        default=os.environ.get("CC_SPEAK_RATE", "+0%"),
        help="Speaking rate adjustment for edge-tts (e.g. '+20%%', '-10%%')",
    )
    parser.add_argument(
        "--speed", "-s",
        type=float,
        default=float(os.environ.get("CC_SPEAK_SPEED", "1.0")),
        help="Speed multiplier for OpenAI (0.25-4.0, default 1.0)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save audio to file instead of playing",
    )
    parser.add_argument(
        "--keep-code",
        action="store_true",
        help="Don't strip code blocks from output",
    )
    parser.add_argument(
        "--keep-paths",
        action="store_true",
        help="Don't strip file paths from output",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Skip all text cleaning (read raw input)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print cleaned text to stderr instead of speaking",
    )

    args = parser.parse_args()

    # Set default voice per backend
    if args.voice is None:
        if args.backend == "edge":
            args.voice = os.environ.get("CC_SPEAK_VOICE", "en-US-GuyNeural")
        else:
            args.voice = os.environ.get("CC_SPEAK_VOICE", "coral")

    # Real-time follow mode
    if args.follow:
        speech_queue = SpeechQueue(
            backend=args.backend,
            voice=args.voice,
            rate=args.rate,
            speed=args.speed,
            skip_code=not args.keep_code,
            skip_paths=not args.keep_paths,
        )

        try:
            if args.follow == "-":
                follow_stdin(speech_queue, args.debounce)
            else:
                follow_file(args.follow, speech_queue, args.debounce)
        finally:
            speech_queue.stop()

        return

    # One-shot mode: Read input
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()
        except FileNotFoundError:
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
    elif not sys.stdin.isatty():
        raw_text = sys.stdin.read()
    else:
        print("ERROR: No input. Pipe text or provide a filename.", file=sys.stderr)
        print("  Usage: claude 'explain X' 2>/dev/null | cc-speak", file=sys.stderr)
        print("  Real-time: cc-speak --follow /tmp/claude.log", file=sys.stderr)
        sys.exit(1)

    if not raw_text.strip():
        print("WARNING: Empty input, nothing to read.", file=sys.stderr)
        sys.exit(0)

    # Clean text
    if args.raw:
        text = raw_text
    else:
        text = clean_text(raw_text, skip_code=not args.keep_code, skip_paths=not args.keep_paths)

    if not text.strip():
        print("WARNING: After cleaning, no readable text remains.", file=sys.stderr)
        sys.exit(0)

    # Preview mode
    if args.preview:
        print("─── Cleaned text ───", file=sys.stderr)
        print(text, file=sys.stderr)
        print(f"─── {len(text)} chars, ~{len(text.split())} words ───", file=sys.stderr)
        sys.exit(0)

    # Generate audio
    output_path = args.output or os.path.join(tempfile.gettempdir(), "cc_speak_output.mp3")

    print(f"Generating speech ({args.backend}, voice: {args.voice})...", file=sys.stderr)

    if args.backend == "edge":
        asyncio.run(tts_edge_async(text, args.voice, args.rate, output_path))
    else:
        tts_openai(text, args.voice, args.speed, output_path)

    # Play or save
    if args.output:
        print(f"Audio saved to: {args.output}", file=sys.stderr)
    else:
        play_audio(output_path)
        # Clean up temp file
        try:
            os.remove(output_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
