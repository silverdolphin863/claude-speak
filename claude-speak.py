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
import hashlib
import base64
import collections
import logging

logger = logging.getLogger("claude-speak")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s", stream=sys.stderr)

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

    Uses URL-safe base64 encoding for a fully reversible, unambiguous mapping.
    Example: C:\\Projects\\MyApp -> Qzpc... (base64)
    """
    path = os.path.normpath(cwd)
    encoded = base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")
    # Strip padding '=' which is safe since we can re-add on decode
    return encoded.rstrip("=")


def decode_dirname_to_cwd(dirname):
    """Decode a base64-encoded directory name back to the original CWD path.

    Inverse of encode_cwd_to_dirname().
    """
    # Re-add padding
    padded = dirname + "=" * (-len(dirname) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


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

    combined = " ".join(texts) if texts else None

    # If no message_id available, derive one from the text content hash
    if combined and message_id is None:
        message_id = "_hash_" + hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
        logger.warning("No message.id or uuid found; using text hash for deduplication: %s", message_id)

    return combined, message_id


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
    """Acquire PID file lock atomically. Returns True if acquired, False if another monitor is running.

    Uses open(..., 'x') for atomic exclusive creation to eliminate TOCTOU race conditions.
    """
    pid_file = _get_pid_file_path(cwd)
    our_pid = str(os.getpid())

    os.makedirs(os.path.dirname(pid_file), exist_ok=True)

    # Attempt atomic exclusive creation first
    try:
        fd = os.open(pid_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.write(fd, our_pid.encode())
        os.close(fd)
        return True
    except (FileExistsError, PermissionError, OSError):
        pass  # File already exists — check if the owner is still alive

    # PID file exists — read it and check if the process is still running
    try:
        with open(pid_file, "r") as f:
            old_pid = int(f.read().strip())
        if _is_process_running(old_pid) and old_pid != os.getpid():
            return False  # Another monitor is genuinely running
    except (ValueError, OSError):
        pass  # Stale/corrupt PID file — safe to reclaim

    # Stale lock — remove and retry atomically
    try:
        os.remove(pid_file)
    except OSError:
        pass
    try:
        fd = os.open(pid_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.write(fd, our_pid.encode())
        os.close(fd)
        return True
    except (FileExistsError, PermissionError, OSError):
        # Another process beat us in the race — they win
        return False


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
        # Bounded LRU dedup: OrderedDict keeps insertion order; evict oldest half at 2000
        self._spoken_ids_max = 2000
        self.spoken_message_ids = collections.OrderedDict()
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

        # Register atexit handler to clean temp dir even on unhandled crash
        atexit.register(self._cleanup_temp_dir)

        # Start speech worker
        self.speech_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.speech_thread.start()

        # Start debounce flusher
        self.debounce_thread = threading.Thread(target=self._debounce_flusher, daemon=True)
        self.debounce_thread.start()

    def _cleanup_temp_dir(self):
        """Remove temp directory. Safe to call multiple times."""
        try:
            if os.path.isdir(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

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
                    logger.error("Speech worker error", exc_info=True)

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

    def _record_spoken_id(self, message_id):
        """Record a message_id in the bounded LRU dedup set.

        Evicts the oldest half when the set exceeds _spoken_ids_max entries.
        """
        self.spoken_message_ids[message_id] = True
        if len(self.spoken_message_ids) > self._spoken_ids_max:
            # Evict oldest half
            to_remove = self._spoken_ids_max // 2
            for _ in range(to_remove):
                self.spoken_message_ids.popitem(last=False)

    def add_text(self, text, message_id=None):
        """Add text to be spoken (with deduplication by message.id)."""
        if message_id:
            if message_id in self.spoken_message_ids:
                return
            self._record_spoken_id(message_id)

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

    @staticmethod
    def _get_file_identity(filepath):
        """Get a file identity marker to detect replacement vs truncation.

        On Unix, uses inode number. On Windows, uses mtime as a proxy since
        inodes are not reliably available.
        """
        try:
            st = os.stat(filepath)
            if os.name == 'nt':
                return st.st_mtime
            else:
                return st.st_ino
        except OSError:
            return None

    def watch(self):
        """Main watch loop - monitor JSONL files for new content."""
        current_file = None
        current_file_norm = None  # Normalized path for comparison
        file_pos = 0
        file_identity = None  # inode (Unix) or mtime (Windows) to detect file replacement
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
                        file_identity = self._get_file_identity(current_file)
                    except OSError:
                        # Can't access new file yet — skip it, retry next cycle
                        current_file = None
                        current_file_norm = None
                        file_identity = None
                    time.sleep(0.5)
                    continue

            if not current_file:
                time.sleep(1)
                continue

            # Fix 6: If current file no longer exists, force immediate rescan
            if not os.path.exists(current_file):
                logger.warning("Tracked JSONL file no longer exists, forcing rescan: %s", current_file)
                current_file = None
                current_file_norm = None
                file_identity = None
                last_rescan_time = 0  # Force immediate rescan
                continue

            # Check for new content (fast - just stat + read)
            try:
                current_size = os.path.getsize(current_file)

                # Fix 5: Detect file replacement (different inode/mtime means new file at same path)
                new_identity = self._get_file_identity(current_file)
                if file_identity is not None and new_identity != file_identity:
                    logger.info("File replaced (identity changed), re-reading from start: %s", current_file)
                    file_pos = 0
                    file_identity = new_identity

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

        self._cleanup_temp_dir()


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
