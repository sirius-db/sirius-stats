#!/usr/bin/env python3
"""Local dev server: serves site/ at http://localhost:8000 and rebuilds automatically whenever
a file that affects the build changes (templates/, static/, data/, or build_site.py itself).

Polling-based (stdlib only, no watch library) rather than a filesystem-events library like
watchfiles -- this repo is intentionally one-dependency-total (see CONTRIBUTING.md), and a 0.5s
poll over a repo this size costs nothing noticeable.

Run:
    uv run scripts/dev_server.py
"""

import http.server
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_site.py"
PORT = 8000
POLL_INTERVAL_SECONDS = 0.5

# Everything build_site.py actually reads -- not scripts/ broadly, since most scripts there
# (fetch_metrics.py, the backfill scripts) don't affect build output at all. site/ itself is
# deliberately excluded: watching the build's own output would trigger an infinite rebuild loop.
WATCH_PATHS = [
    REPO_ROOT / "templates",
    REPO_ROOT / "static",
    REPO_ROOT / "data",
    BUILD_SCRIPT,
]


def snapshot_mtimes():
    """Latest mtime across every watched file -- one number to compare between polls, cheaper
    than diffing full directory listings each time."""
    latest = 0.0
    for path in WATCH_PATHS:
        if path.is_file():
            latest = max(latest, path.stat().st_mtime)
        elif path.is_dir():
            for f in path.rglob("*"):
                if f.is_file():
                    latest = max(latest, f.stat().st_mtime)
    return latest


def build():
    result = subprocess.run(["uv", "run", str(BUILD_SCRIPT)], cwd=REPO_ROOT)
    if result.returncode != 0:
        print("build failed -- see error above; still serving the last good build", file=sys.stderr)


def serve():
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SITE_DIR), **kwargs)

        def log_message(self, *args):
            pass  # noisy by default (one line per asset); the rebuild messages are enough signal

    server = http.server.ThreadingHTTPServer(("localhost", PORT), Handler)
    print(f"serving http://localhost:{PORT} (Ctrl+C to stop)")
    server.serve_forever()


def main():
    build()
    threading.Thread(target=serve, daemon=True).start()

    last_mtime = snapshot_mtimes()
    try:
        while True:
            time.sleep(POLL_INTERVAL_SECONDS)
            current_mtime = snapshot_mtimes()
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                print("change detected, rebuilding...")
                build()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
