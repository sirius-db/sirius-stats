#!/usr/bin/env python3
"""Patch already-collected data/snapshots/*.json files with GitHub's latest traffic.

Run automatically by collect.yml on every firing (see #14). GitHub's traffic
aggregation can lag more than a day, and can still revise a day's numbers while that
day remains within GitHub's rolling 14-day breakdown -- so a snapshot's own traffic
fields can be null or stale even after collection. This patches every date still
within the current 14-day window in place, whether previously null or already
populated; a date stops being touched only once it rolls out of GitHub's returned
breakdown, at which point whatever's already recorded is final (mirrors
backfill_traffic.py's frozen-once-aged-out behavior for its own file).

Not for pre-launch history (before 2026-08-31, no snapshot file exists yet) -- that's
backfill_traffic.py's one-time job, unchanged.

Requires SIRIUS_TRAFFIC_TOKEN (a push-scoped token for sirius-db/sirius -- same one
collect.yml uses for the main collection).
"""

import json
import os
import urllib.request
from pathlib import Path

REPO = "sirius-db/sirius"
API_ROOT = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"


def api_get(path, token):
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def main():
    token = os.environ.get("SIRIUS_TRAFFIC_TOKEN")
    if not token:
        print("SIRIUS_TRAFFIC_TOKEN not set -- skipping traffic refresh")
        return

    views = api_get(f"/repos/{REPO}/traffic/views", token)["views"]
    clones = api_get(f"/repos/{REPO}/traffic/clones", token)["clones"]
    views_by_day = {v["timestamp"][:10]: v for v in views}
    clones_by_day = {c["timestamp"][:10]: c for c in clones}

    patched = []
    for day in sorted(set(views_by_day) | set(clones_by_day)):
        snapshot_path = SNAPSHOTS_DIR / f"{day}.json"
        if not snapshot_path.exists():
            continue

        v = views_by_day.get(day, {"count": 0, "uniques": 0})
        c = clones_by_day.get(day, {"count": 0, "uniques": 0})
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["traffic"]["as_of_date"] = day
        snapshot["traffic"]["views"] = v["count"]
        snapshot["traffic"]["unique_views"] = v["uniques"]
        snapshot["traffic"]["clones"] = c["count"]
        snapshot["traffic"]["unique_clones"] = c["uniques"]
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n")
        patched.append(day)

    if patched:
        print(f"refreshed traffic for: {', '.join(patched)}")
    else:
        print("no snapshots to refresh")


if __name__ == "__main__":
    main()
