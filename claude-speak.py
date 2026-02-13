#!/usr/bin/env python3
"""
claude-speak: Monitor Claude Code conversation logs and speak assistant output.

Runs as a BACKGROUND process alongside Claude Code (not as a wrapper).
Watches JSONL conversation logs for new assistant text messages and speaks them.

Usage:
    python claude-speak.py --cwd "C:\\Projects\\MyApp"    # Watch specific project
    python claude-speak.py --voice en-US-GuyNeural        # Specify voice
    python claude-speak.py --rate "+20%"                   # Faster speech
"""

import json
import sys
import os
import glob
import threading
import queue
import time
import tempfile
import shutil
import signal
import atexit

# Import cc-speak's TTS functionality
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib.util import spec_from_file_location, module_from_spec

cc_speak_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc-speak.py")
spec = spec_from_file_location("cc_speak", cc_speak_path)
cc_speak = module_from_spec(spec)
spec.loader.exec_module(cc_speak)


# Base directory where Claude stores all conversation logs
CLAUDE_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _normalize_path(path):
    """Normalize a file path for consistent comparison (case-insensitive on Windows)."""
    if path is None:
        return None
    p = os.path.normpath(os.path.abspath(path))
    if os.name == 'nt':
        p = p.lower()
    return p


def encode_cwd_to_dirname(cwd):
    """Encode a working directory path to Claude's project directory name.

    Example: C:\\Projects\\MyApp -> C--Projects-MyApp
    """
    path = os.path.normpath(cwd)
    return path.replace(":", "-").replace("\\", "-").replace("/", "-")


def is_speech_paused(cwd=None):
    """Check if speech is paused for a specific project (or globally)."""
    # Check per-project pause flag first
    if cwd:
        dirname = encode_cwd_to_dirname(cwd)
        project_flag = os.path.join(CLAUDE_PROJECTS_DIR, dirname, "speech-paused")
        if os.path.exists(project_flag):
            return True
    # Fall back to global pause flag
    global_flag = os.path.join(os.path.expanduser("~"), ".claude", "speech-paused")
    return os.path.exists(global_flag)


def get_voice_override(cwd=None):
    """Get voice override from per-project or global config file. Returns None if no override."""
    # Check per-project voice config first
    if cwd:
        dirname = encode_cwd_to_dirname(cwd)
        project_voice = os.path.join(CLAUDE_PROJECTS_DIR, dirname, "speech-voice")
        if os.path.exists(project_voice):
            try:
                with open(project_voice, "r") as f:
                    voice = f.read().strip()
                    if voice:
                        return voice
            except OSError:
                pass
    # Fall back to global voice config
    global_voice = os.path.join(os.path.expanduser("~"), ".claude", "speech-voice")
    if os.path.exists(global_voice):
        try:
            with open(global_voice, "r") as f:
                voice = f.read().strip()
                if voice:
                    return voice
        except OSError:
            pass
    return None


def find_project_jsonl_dir(cwd):
    """Find the JSONL directory for a specific project CWD."""
    dirname = encode_cwd_to_dirname(cwd)
    project_dir = os.path.join(CLAUDE_PROJECTS_DIR, dirname)
    if os.path.isdir(project_dir):
        return project_dir
    return None


def find_latest_jsonl_in_dir(directory):
    """Find the most recently modified JSONL file in a directory."""
    jsonl_files = glob.glob(os.path.join(directory, "*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=os.path.getmtime)


def find_active_jsonl_global():
    """Find the most recently modified JSONL file across ALL projects."""
    try:
        project_dirs = [
            os.path.join(CLAUDE_PROJECTS_DIR, d)
            for d in os.listdir(CLAUDE_PROJECTS_DIR)
            if os.path.isdir(os.path.join(CLAUDE_PROJECTS_DIR, d))
        ]
        if not project_dirs:
            return None
        latest_dir = max(project_dirs, key=os.path.getmtime)
        return find_latest_jsonl_in_dir(latest_dir)
    except (OSError, ValueError):
        return None


def extract_text_from_line(line):
    """Extract speakable text from a JSONL line. Returns (text, message_id).

    Uses message.id (not uuid) for deduplication because a single API response
    can be split across multiple JSONL lines with different uuids but the same
    message.id.
    """
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None, None

    # Only process assistant messages
    if data.get("type") != "assistant":
        return None, None

    message = data.get("message", {})
    content = message.get("content", [])
    # Use message.id for dedup (stable across split JSONL lines)
    # Fall back to uuid if message.id is missing
    message_id = message.get("id") or data.get("uuid")

    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text.strip():
                texts.append(text)

    return (" ".join(texts) if texts else None), message_id


# ─── PID File Lock ────────────────────────────────────────────────────────────


def _get_pid_file_path(cwd):
    """Get the PID file path for a project (or global)."""
    if cwd:
        dirname = encode_cwd_to_dirname(cwd)
        return os.path.join(CLAUDE_PROJECTS_DIR, dirname, "speech-monitor.pid")
    return os.path.join(os.path.expanduser("~"), ".claude", "speech-monitor.pid")


def _is_process_running(pid):
    """Check if a process with the given PID is still running."""
    try:
        if os.name == 'nt':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


def acquire_pid_lock(cwd):
    """Acquire PID file lock. Returns True if acquired, False if another monitor is running."""
    pid_file = _get_pid_file_path(cwd)

    # Check for existing monitor
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                old_pid = int(f.read().strip())
            if _is_process_running(old_pid) and old_pid != os.getpid():
                return False  # Another monitor is already running
        except (ValueError, OSError):
            pass  # Stale/corrupt PID file, overwrite it

    # Write our PID
    try:
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass  # Non-fatal

    return True


def release_pid_lock(cwd):
    """Release PID file lock."""
    pid_file = _get_pid_file_path(cwd)
    try:
        if os.path.exists(pid_file):
            with open(pid_file, "r") as f:
                stored_pid = int(f.read().strip())
            if stored_pid == os.getpid():
                os.remove(pid_file)
    except (ValueError, OSError):
        pass


class SpeechMonitor:
    """Watch JSONL conversation logs and speak new assistant messages."""

    def __init__(self, cwd=None, voice="en-US-GuyNeural", rate="+10%", debounce_ms=2000):
        self.voice = voice
        self.rate = rate
        self.debounce_ms = debounce_ms
        self.speech_queue = queue.Queue()
        self.running = True
        self.spoken_message_ids = set()
        self.temp_dir = tempfile.mkdtemp(prefix="claude_speak_")
        self.file_counter = 0

        # Scoped project directory (if cwd provided)
        self.project_jsonl_dir = None
        if cwd:
            self.project_jsonl_dir = find_project_jsonl_dir(cwd)
            # If dir doesn't exist yet, store cwd for retry
            self.cwd = cwd
        else:
            self.cwd = None

        # In global mode, tracks the config dir of the currently active project
        # (derived from the JSONL file path, so per-project settings still work)
        self.active_config_dir = None

        # Pending text accumulator for debounce
        self.pending_text = ""
        self.last_text_time = 0
        self.pending_lock = threading.Lock()

        # Start speech worker
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()

        # Start debounce flusher
        self.debounce_thread = threading.Thread(target=self._debounce_flusher, daemon=True)
        self.debounce_thread.start()

    def _is_paused(self):
        """Check if speech is paused, using active project config in global mode."""
        # Per-project check (scoped mode)
        if self.cwd:
            return is_speech_paused(self.cwd)
        # Global mode: check the active project's config dir directly
        if self.active_config_dir:
            if os.path.exists(os.path.join(self.active_config_dir, "speech-paused")):
                return True
        # Fall back to global pause flag
        global_flag = os.path.join(os.path.expanduser("~"), ".claude", "speech-paused")
        return os.path.exists(global_flag)

    def _get_voice(self):
        """Get voice override, using active project config in global mode."""
        # Per-project check (scoped mode)
        if self.cwd:
            return get_voice_override(self.cwd)
        # Global mode: check the active project's config dir directly
        if self.active_config_dir:
            voice_file = os.path.join(self.active_config_dir, "speech-voice")
            if os.path.exists(voice_file):
                try:
                    with open(voice_file, "r") as f:
                        voice = f.read().strip()
                        if voice:
                            return voice
                except OSError:
                    pass
        # Fall back to global voice
        global_voice = os.path.join(os.path.expanduser("~"), ".claude", "speech-voice")
        if os.path.exists(global_voice):
            try:
                with open(global_voice, "r") as f:
                    voice = f.read().strip()
                    if voice:
                        return voice
            except OSError:
                pass
        return None

    def _speech_worker(self):
        """Background worker that generates and plays speech."""
        while self.running or not self.speech_queue.empty():
            try:
                text = self.speech_queue.get(timeout=0.5)
                if text is None:
                    break

                # Skip speaking if paused (per-project or global)
                if self._is_paused():
                    self.speech_queue.task_done()
                    continue

                cleaned = cc_speak.clean_text(text, skip_code=True, skip_paths=True)
                if not cleaned.strip() or len(cleaned.split()) < 3:
                    self.speech_queue.task_done()
                    continue

                self.file_counter += 1
                output_path = os.path.join(self.temp_dir, f"speech_{self.file_counter}.mp3")

                try:
                    # Check for voice override (allows runtime voice changes)
                    voice = self._get_voice() or self.voice
                    cc_speak.tts_edge(cleaned, voice, self.rate, output_path)
                    if os.path.exists(output_path):
                        cc_speak.play_audio(output_path)
                        os.remove(output_path)
                except Exception:
                    pass  # Silent - we're a background process

                self.speech_queue.task_done()
            except queue.Empty:
                continue

    def _debounce_flusher(self):
        """Flush accumulated text after debounce period."""
        while self.running:
            time.sleep(0.1)
            with self.pending_lock:
                if self.pending_text and self.last_text_time > 0:
                    elapsed = (time.time() - self.last_text_time) * 1000
                    if elapsed > self.debounce_ms:
                        text = self.pending_text
                        self.pending_text = ""
                        self.last_text_time = 0
                        chunks = cc_speak.extract_speakable_chunks(text)
                        for chunk in chunks:
                            self.speech_queue.put(chunk)

    def add_text(self, text, message_id=None):
        """Add text to be spoken (with deduplication by message.id)."""
        if message_id:
            if message_id in self.spoken_message_ids:
                return
            self.spoken_message_ids.add(message_id)

        with self.pending_lock:
            self.pending_text += " " + text
            self.last_text_time = time.time()

    def _find_jsonl(self):
        """Find the right JSONL file based on scope."""
        # If scoped to a project, only look there
        if self.cwd:
            if not self.project_jsonl_dir:
                # Retry finding the directory (may not exist at startup)
                self.project_jsonl_dir = find_project_jsonl_dir(self.cwd)
            if self.project_jsonl_dir:
                return find_latest_jsonl_in_dir(self.project_jsonl_dir)
            return None

        # Global mode: find across all projects
        return find_active_jsonl_global()

    def watch(self):
        """Main watch loop - monitor JSONL files for new content."""
        current_file = None
        current_file_norm = None  # Normalized path for comparison
        file_pos = 0
        last_rescan_time = 0
        rescan_interval = 5

        while self.running:
            now = time.time()

            # Periodically rescan for new/different active file
            if now - last_rescan_time > rescan_interval or current_file is None:
                last_rescan_time = now
                latest = self._find_jsonl()
                latest_norm = _normalize_path(latest)

                if latest and latest_norm != current_file_norm:
                    current_file = latest
                    current_file_norm = latest_norm
                    # Track active project config dir (for per-project settings in global mode)
                    self.active_config_dir = os.path.dirname(latest)
                    try:
                        file_pos = os.path.getsize(current_file)
                    except OSError:
                        # Can't access new file yet — skip it, retry next cycle
                        current_file = None
                        current_file_norm = None
                    time.sleep(0.5)
                    continue

            if not current_file:
                time.sleep(1)
                continue

            # Check for new content (fast - just stat + read)
            try:
                current_size = os.path.getsize(current_file)
                if current_size > file_pos:
                    with open(current_file, "r", encoding="utf-8") as f:
                        f.seek(file_pos)
                        new_content = f.read()
                        file_pos = f.tell()

                    for line in new_content.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        text, msg_id = extract_text_from_line(line)
                        if text:
                            self.add_text(text, msg_id)

                elif current_size < file_pos:
                    # File was truncated — jump to new end, don't reset to 0
                    file_pos = current_size

            except (OSError, IOError):
                pass  # Transient error — keep current file_pos, retry next cycle

            time.sleep(0.5)

    def stop(self):
        """Stop the monitor and flush remaining text."""
        self.running = False

        with self.pending_lock:
            if self.pending_text.strip():
                chunks = cc_speak.extract_speakable_chunks(self.pending_text)
                for chunk in chunks:
                    self.speech_queue.put(chunk)
                self.pending_text = ""

        self.speech_queue.put(None)
        self.speech_thread.join(timeout=15)

        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitor Claude Code and speak assistant output")
    parser.add_argument("--cwd", "-c", help="Project working directory to scope monitoring to")
    parser.add_argument("--voice", "-v", default="en-US-GuyNeural", help="TTS voice")
    parser.add_argument("--rate", "-r", default="+10%", help="Speech rate")
    parser.add_argument("--debounce", "-d", type=int, default=2000, help="Debounce ms before speaking")

    args = parser.parse_args()

    # Prevent multiple monitors for the same project
    if not acquire_pid_lock(args.cwd):
        print(f"Another speech monitor is already running for this project.", file=sys.stderr)
        print(f"PID file: {_get_pid_file_path(args.cwd)}", file=sys.stderr)
        sys.exit(1)

    # Release PID lock on exit
    atexit.register(release_pid_lock, args.cwd)

    monitor = SpeechMonitor(
        cwd=args.cwd,
        voice=args.voice,
        rate=args.rate,
        debounce_ms=args.debounce
    )

    def signal_handler(sig, frame):
        monitor.stop()
        release_pid_lock(args.cwd)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        monitor.watch()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        release_pid_lock(args.cwd)


if __name__ == "__main__":
    main()
