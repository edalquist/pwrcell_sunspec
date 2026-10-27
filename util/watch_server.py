#!/usr/bin/env python3
"""Auto-restarting server supervisor for PWRcell.

Watches the codebase for changes (from other conversations or local edits)
and gracefully restarts the PWRcell server.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

WATCH_DIRS = [
    "pwrcell",
    "config",
    "sunspec-models",
]
WATCH_EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".js", ".html", ".css"}
IGNORED_PATTERNS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    ".ha_published_topics.json",
}

ROOT_DIR = Path(__file__).resolve().parent.parent


def get_watched_files() -> dict[Path, int]:
    """Scan watched files and return dict mapping Path to mtime_ns."""
    files: dict[Path, int] = {}

    def scan_path(p: Path):
        try:
            if not p.exists():
                return
            if p.is_file():
                if p.suffix in WATCH_EXTENSIONS and not any(ign in str(p) for ign in IGNORED_PATTERNS):
                    files[p] = p.stat().st_mtime_ns
            elif p.is_dir():
                for root, dirs, filenames in os.walk(p):
                    # Filter out ignored directories in-place
                    dirs[:] = [d for d in dirs if d not in IGNORED_PATTERNS and not d.startswith(".")]
                    for fname in filenames:
                        if fname.startswith("."):
                            continue
                        fpath = Path(root) / fname
                        if fpath.suffix in WATCH_EXTENSIONS:
                            try:
                                files[fpath] = fpath.stat().st_mtime_ns
                            except OSError:
                                pass
        except OSError:
            pass

    # Root files
    for root_file in ["main.py", "config.yaml"]:
        scan_path(ROOT_DIR / root_file)

    # Watch dirs
    for dname in WATCH_DIRS:
        scan_path(ROOT_DIR / dname)

    return files


class ServerSupervisor:
    def __init__(self, server_args: list[str]):
        self.server_args = server_args
        self.process: subprocess.Popen | None = None
        self.running = True
        self.python_bin = sys.executable

    def start_server(self):
        """Start the server subprocess."""
        cmd = [self.python_bin, str(ROOT_DIR / "main.py")] + self.server_args
        print(f"\n[watch_server] Starting server: {' '.join(cmd)}", flush=True)
        self.process = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    def stop_server(self, timeout: float = 5.0):
        """Stop the running server subprocess gracefully."""
        if not self.process:
            return

        if self.process.poll() is None:
            print(f"[watch_server] Stopping server (PID {self.process.pid})...", flush=True)
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
                print(f"[watch_server] Server stopped cleanly.", flush=True)
            except subprocess.TimeoutExpired:
                print(f"[watch_server] Server did not exit in {timeout}s; killing (SIGKILL)...", flush=True)
                self.process.kill()
                self.process.wait()
            except Exception as e:
                print(f"[watch_server] Error stopping server: {e}", flush=True)
        self.process = None

    def run(self):
        """Main loop: start server, watch for file changes, and restart."""
        # Install signal handlers for clean supervisor shutdown
        def handle_signal(sig, frame):
            print(f"\n[watch_server] Received signal {sig}; shutting down supervisor...", flush=True)
            self.running = False
            self.stop_server()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        self.start_server()
        last_snapshot = get_watched_files()

        while self.running:
            time.sleep(1.0)

            # Check if server exited on its own
            if self.process and self.process.poll() is not None:
                exit_code = self.process.returncode
                print(f"[watch_server] Server process exited with code {exit_code}. Waiting for code change to restart...", flush=True)
                self.process = None

            current_snapshot = get_watched_files()
            changed_files: list[str] = []

            for path, mtime in current_snapshot.items():
                if path not in last_snapshot or last_snapshot[path] != mtime:
                    try:
                        rel = path.relative_to(ROOT_DIR)
                    except ValueError:
                        rel = path
                    changed_files.append(str(rel))

            for path in last_snapshot:
                if path not in current_snapshot:
                    try:
                        rel = path.relative_to(ROOT_DIR)
                    except ValueError:
                        rel = path
                    changed_files.append(f"{rel} (deleted)")

            if changed_files:
                print(f"\n[watch_server] Detected file changes ({len(changed_files)}): {', '.join(changed_files[:5])}{'...' if len(changed_files) > 5 else ''}", flush=True)
                # Debounce to let multiple edits or disk writes settle
                time.sleep(0.8)
                last_snapshot = get_watched_files()

                self.stop_server()
                self.start_server()
            else:
                last_snapshot = current_snapshot


def main():
    parser = argparse.ArgumentParser(description="Auto-reloading supervisor for PWRcell server.")
    parser.add_argument("server_args", nargs=argparse.REMAINDER, help="Arguments passed to main.py (default: explore)")
    args = parser.parse_args()

    server_args = args.server_args if args.server_args else ["explore"]
    # If first arg is '--', strip it
    if server_args and server_args[0] == "--":
        server_args = server_args[1:]

    supervisor = ServerSupervisor(server_args=server_args)
    supervisor.run()


if __name__ == "__main__":
    main()
