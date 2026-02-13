#!/usr/bin/env python3
"""
claude-speak configuration server.

Provides a web UI for testing voices and configuring settings.
Run this, and it opens a browser with the settings page.

Usage:
    python configure.py              # Opens browser to settings page
    python configure.py --port 8910  # Custom port
    python configure.py --no-browser # Don't auto-open browser
"""

import asyncio
import hashlib
import http.server
import json
import os
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Import cc-speak's TTS functionality
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib.util import spec_from_file_location, module_from_spec

cc_speak_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc-speak.py")
spec = spec_from_file_location("cc_speak", cc_speak_path)
cc_speak = module_from_spec(spec)
spec.loader.exec_module(cc_speak)

CLAUDE_PROJECTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "projects")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "claude_speak_previews")


def encode_cwd_to_dirname(cwd):
    """Encode a working directory path to Claude's project directory name."""
    path = os.path.normpath(cwd)
    return path.replace(":", "-").replace("\\", "-").replace("/", "-")


def decode_dirname(dirname):
    """Best-effort decode of dirname back to a readable path."""
    if os.name == 'nt':
        parts = dirname.split('-')
        # Find drive letter pattern: single letter followed by empty string (from ::)
        if len(parts) >= 3 and len(parts[0]) == 1 and parts[0].isalpha() and parts[1] == '':
            drive = parts[0] + ':\\'
            rest = '\\'.join(p for p in parts[2:] if p)
            return drive + rest
    return '/' + '/'.join(p for p in dirname.split('-') if p)


def is_process_running(pid):
    """Check if a process with the given PID is still running."""
    try:
        if os.name == 'nt':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


class ConfigHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the settings UI and API."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/settings.html':
            self._serve_html()
        elif parsed.path == '/api/voices':
            self._api_list_voices()
        elif parsed.path == '/api/projects':
            self._api_list_projects()
        elif parsed.path == '/api/settings':
            params = parse_qs(parsed.query)
            project = params.get('project', [None])[0]
            self._api_get_settings(project)
        elif parsed.path == '/api/status':
            self._api_get_status()
        elif parsed.path.startswith('/audio/'):
            self._serve_audio(parsed.path)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length else b'{}'

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response({'error': 'Invalid JSON'}, 400)
            return

        if parsed.path == '/api/preview':
            self._api_preview(data)
        elif parsed.path == '/api/settings':
            self._api_save_settings(data)
        elif parsed.path == '/api/monitor/start':
            self._api_start_monitor(data)
        elif parsed.path == '/api/monitor/stop':
            self._api_stop_monitor(data)
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ─── Page Serving ────────────────────────────────────────────────────────

    def _serve_html(self):
        """Serve the settings.html page."""
        html_path = os.path.join(SCRIPT_DIR, 'settings.html')
        try:
            with open(html_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, 'settings.html not found')

    def _serve_audio(self, path):
        """Serve a generated audio preview file."""
        filename = path.split('/')[-1]
        # Sanitize filename to prevent directory traversal
        if '/' in filename or '\\' in filename or '..' in filename:
            self.send_error(403)
            return

        audio_path = os.path.join(PREVIEW_DIR, filename)
        if os.path.exists(audio_path):
            with open(audio_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', len(content))
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    # ─── API Endpoints ───────────────────────────────────────────────────────

    def _api_list_voices(self):
        """GET /api/voices - List all available edge-tts voices."""
        try:
            import edge_tts
            voices = asyncio.run(edge_tts.list_voices())
            self._json_response(voices)
        except ImportError:
            self._json_response({'error': 'edge-tts not installed. Run: pip install edge-tts'}, 500)
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _api_list_projects(self):
        """GET /api/projects - List recently active projects (last 24h)."""
        import time as _time
        now = _time.time()
        cutoff = now - 86400  # 24 hours ago

        projects = []
        if os.path.exists(CLAUDE_PROJECTS_DIR):
            for dirname in os.listdir(CLAUDE_PROJECTS_DIR):
                dirpath = os.path.join(CLAUDE_PROJECTS_DIR, dirname)
                if not os.path.isdir(dirpath):
                    continue

                # Find the most recently modified JSONL file
                jsonl_files = [
                    os.path.join(dirpath, f) for f in os.listdir(dirpath)
                    if f.endswith('.jsonl')
                ]
                if not jsonl_files:
                    continue

                last_active = max(os.path.getmtime(f) for f in jsonl_files)

                # Only include projects active in the last 24 hours
                if last_active < cutoff:
                    continue

                decoded_path = decode_dirname(dirname)
                is_paused = os.path.exists(os.path.join(dirpath, 'speech-paused'))

                voice = None
                voice_file = os.path.join(dirpath, 'speech-voice')
                if os.path.exists(voice_file):
                    try:
                        with open(voice_file, 'r') as f:
                            voice = f.read().strip()
                    except OSError:
                        pass

                projects.append({
                    'dirname': dirname,
                    'path': decoded_path,
                    'name': os.path.basename(decoded_path.rstrip('/\\')),
                    'voice': voice,
                    'paused': is_paused,
                    'last_active': last_active,
                })

        # Sort by most recently active first
        projects.sort(key=lambda p: p['last_active'], reverse=True)
        self._json_response(projects)

    def _api_get_settings(self, project_path):
        """GET /api/settings?project=<path> - Get settings for a project."""
        settings = {
            'paused': False,
            'voice': None,
            'global_voice': None,
        }

        if project_path:
            dirname = encode_cwd_to_dirname(project_path)
            project_dir = os.path.join(CLAUDE_PROJECTS_DIR, dirname)

            pause_file = os.path.join(project_dir, 'speech-paused')
            settings['paused'] = os.path.exists(pause_file)

            voice_file = os.path.join(project_dir, 'speech-voice')
            if os.path.exists(voice_file):
                try:
                    with open(voice_file, 'r') as f:
                        v = f.read().strip()
                    if v:
                        settings['voice'] = v
                except OSError:
                    pass

        # Check global voice
        global_voice_file = os.path.join(os.path.expanduser("~"), ".claude", "speech-voice")
        if os.path.exists(global_voice_file):
            try:
                with open(global_voice_file, 'r') as f:
                    v = f.read().strip()
                if v:
                    settings['global_voice'] = v
            except OSError:
                pass

        self._json_response(settings)

    def _api_save_settings(self, data):
        """POST /api/settings - Save settings for a project."""
        project_path = data.get('project')
        voice = data.get('voice')
        paused = data.get('paused')

        if project_path:
            dirname = encode_cwd_to_dirname(project_path)
            config_dir = os.path.join(CLAUDE_PROJECTS_DIR, dirname)
        else:
            # Global settings
            config_dir = os.path.join(os.path.expanduser("~"), ".claude")

        os.makedirs(config_dir, exist_ok=True)

        # Save voice
        if voice is not None:
            voice_file = os.path.join(config_dir, 'speech-voice')
            if voice == '' or voice == 'default':
                if os.path.exists(voice_file):
                    os.remove(voice_file)
            else:
                with open(voice_file, 'w') as f:
                    f.write(voice)

        # Save paused state
        if paused is not None:
            pause_file = os.path.join(config_dir, 'speech-paused')
            if paused:
                Path(pause_file).touch()
            elif os.path.exists(pause_file):
                os.remove(pause_file)

        self._json_response({'ok': True})

    def _api_preview(self, data):
        """POST /api/preview - Generate and return preview audio URL."""
        text = data.get('text', 'Hello! I am your Claude Code assistant. Let me help you write better code today.')
        voice = data.get('voice', 'en-US-GuyNeural')
        rate = data.get('rate', '+0%')

        os.makedirs(PREVIEW_DIR, exist_ok=True)

        # Cache by content hash
        cache_key = hashlib.md5(f"{text}|{voice}|{rate}".encode()).hexdigest()[:16]
        filename = f"preview_{cache_key}.mp3"
        output_path = os.path.join(PREVIEW_DIR, filename)

        if not os.path.exists(output_path):
            try:
                cc_speak.tts_edge(text, voice, rate, output_path)
            except Exception as e:
                self._json_response({'error': f'TTS generation failed: {e}'}, 500)
                return

        if not os.path.exists(output_path):
            self._json_response({'error': 'Audio file was not generated'}, 500)
            return

        self._json_response({'url': f'/audio/{filename}'})

    def _api_get_status(self):
        """GET /api/status - Check running speech monitors."""
        monitors = []

        # Check global monitor PID
        global_pid_file = os.path.join(os.path.expanduser("~"), ".claude", "speech-monitor.pid")
        if os.path.exists(global_pid_file):
            try:
                with open(global_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                monitors.append({
                    'project': None,
                    'name': 'Global (all projects)',
                    'pid': pid,
                    'running': is_process_running(pid),
                    'mode': 'global',
                })
            except (ValueError, OSError):
                pass

        # Check per-project monitor PIDs
        if os.path.exists(CLAUDE_PROJECTS_DIR):
            for dirname in os.listdir(CLAUDE_PROJECTS_DIR):
                pid_file = os.path.join(CLAUDE_PROJECTS_DIR, dirname, 'speech-monitor.pid')
                if os.path.exists(pid_file):
                    try:
                        with open(pid_file, 'r') as f:
                            pid = int(f.read().strip())
                        monitors.append({
                            'project': decode_dirname(dirname),
                            'name': os.path.basename(decode_dirname(dirname).rstrip('/\\')),
                            'pid': pid,
                            'running': is_process_running(pid),
                            'mode': 'project',
                        })
                    except (ValueError, OSError):
                        pass

        self._json_response({'monitors': monitors})

    def _api_start_monitor(self, data):
        """POST /api/monitor/start - Start a speech monitor process."""
        project = data.get('project')  # None = global mode
        voice = data.get('voice', 'en-US-GuyNeural')
        rate = data.get('rate', '+10%')

        script_path = os.path.join(SCRIPT_DIR, 'claude-speak.py')
        if not os.path.exists(script_path):
            self._json_response({'error': 'claude-speak.py not found'}, 500)
            return

        cmd = [sys.executable, script_path, '--voice', voice, '--rate', rate]
        if project:
            cmd.extend(['--cwd', project])

        try:
            if os.name == 'nt':
                # Windows: start hidden, detached from this process
                CREATE_NO_WINDOW = 0x08000000
                DETACHED_PROCESS = 0x00000008
                proc = subprocess.Popen(
                    cmd,
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            else:
                # Unix: start in new session
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )

            self._json_response({
                'ok': True,
                'pid': proc.pid,
                'mode': 'project' if project else 'global',
            })
        except Exception as e:
            self._json_response({'error': f'Failed to start monitor: {e}'}, 500)

    def _api_stop_monitor(self, data):
        """POST /api/monitor/stop - Stop a speech monitor by PID."""
        pid = data.get('pid')
        if not pid:
            self._json_response({'error': 'pid is required'}, 400)
            return

        pid = int(pid)
        try:
            if os.name == 'nt':
                # Windows: use ctypes to terminate (no shell needed)
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
                if handle:
                    kernel32.TerminateProcess(handle, 0)
                    kernel32.CloseHandle(handle)
                else:
                    self._json_response({'error': f'Cannot open process {pid}'}, 404)
                    return
            else:
                os.kill(pid, signal.SIGTERM)

            # Clean up PID files that reference this PID
            # (atexit handler doesn't fire on forced termination)
            self._cleanup_pid_files(pid)

            self._json_response({'ok': True})
        except (ProcessLookupError, PermissionError) as e:
            self._json_response({'error': str(e)}, 404)
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def _cleanup_pid_files(self, pid):
        """Remove PID files that reference a specific PID."""
        # Check global PID file
        global_pid = os.path.join(os.path.expanduser("~"), ".claude", "speech-monitor.pid")
        self._remove_pid_if_matches(global_pid, pid)

        # Check per-project PID files
        if os.path.exists(CLAUDE_PROJECTS_DIR):
            for dirname in os.listdir(CLAUDE_PROJECTS_DIR):
                pid_file = os.path.join(CLAUDE_PROJECTS_DIR, dirname, 'speech-monitor.pid')
                self._remove_pid_if_matches(pid_file, pid)

    def _remove_pid_if_matches(self, pid_file, pid):
        """Remove a PID file if it contains the given PID."""
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    stored = int(f.read().strip())
                if stored == pid:
                    os.remove(pid_file)
            except (ValueError, OSError):
                pass

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Suppress default request logging (too noisy)."""
        pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Allow concurrent requests (preview generation can be slow)."""
    allow_reuse_address = True
    daemon_threads = True


def cleanup_previews():
    """Clean up old preview audio files."""
    if os.path.exists(PREVIEW_DIR):
        try:
            shutil.rmtree(PREVIEW_DIR, ignore_errors=True)
        except Exception:
            pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="claude-speak configuration server")
    parser.add_argument('--port', '-p', type=int, default=8910, help='Port (default: 8910)')
    parser.add_argument('--no-browser', action='store_true', help="Don't auto-open browser")
    args = parser.parse_args()

    # Clean up old previews on start
    cleanup_previews()

    try:
        server = ThreadedTCPServer(("127.0.0.1", args.port), ConfigHandler)
    except OSError as e:
        if "Address already in use" in str(e) or "10048" in str(e):
            print(f"Port {args.port} is already in use. Try: python configure.py --port {args.port + 1}")
            sys.exit(1)
        raise

    url = f"http://localhost:{args.port}"
    print(f"claude-speak settings: {url}")
    print("Press Ctrl+C to stop\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.shutdown()
        cleanup_previews()


if __name__ == "__main__":
    main()
