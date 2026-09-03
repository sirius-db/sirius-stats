#!/usr/bin/env python3
"""Bootstrap/backfill: seed or refresh data/traffic_backfill.json from the live traffic API.

One-time historical seed for the pre-launch days (before 2026-08-31) that predate
collect.yml's daily collection and so have no data/snapshots/<date>.json to patch --
not run by any workflow, see BOOTSTRAP.md for manual usage. For days that *do* have a
snapshot file, refresh_traffic.py (run automatically by collect.yml, see #14) is the
one that keeps their traffic in sync instead. Requires SIRIUS_TRAFFIC_TOKEN (a
push-scoped token for sirius-db/sirius -- same one collect.yml uses).

/traffic/views and /traffic/clones always return a 14-day daily breakdown, but
fetch_metrics.py's recurring collection only keeps the latest complete day from each
call (see latest_complete_day() there) -- this script instead keeps every day the API
returns. Safe to rerun any time (e.g. to catch up after a missed collect.yml run): it
merges into the existing file rather than overwriting it, so days that have already
rolled out of GitHub's 14-day window aren't lost just because the window has since
shifted forward.
"""

import json
import os
import urllib.request
from pathlib import Path

REPO = "sirius-db/sirius"
API_ROOT = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "traffic_backfill.json"


def api_get(path, token):
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def main():
    token = os.environ.get("SIRIUS_TRAFFIC_TOKEN")
    if not token:
        raise SystemExit("SIRIUS_TRAFFIC_TOKEN must be set -- see BOOTSTRAP.md")

    views = api_get(f"/repos/{REPO}/traffic/views", token)["views"]
    clones = api_get(f"/repos/{REPO}/traffic/clones", token)["clones"]

    views_by_day = {v["timestamp"][:10]: v for v in views}
    clones_by_day = {c["timestamp"][:10]: c for c in clones}

    existing = {entry["date"]: entry for entry in _load_existing()}

    for day in sorted(set(views_by_day) | set(clones_by_day)):
        v = views_by_day.get(day, {"count": 0, "uniques": 0})
        c = clones_by_day.get(day, {"count": 0, "uniques": 0})
        existing[day] = {
            "date": day,
            "views": v["count"],
            "unique_views": v["uniques"],
            "clones": c["count"],
            "unique_clones": c["uniques"],
        }

    history = [existing[day] for day in sorted(existing)]
    OUT_PATH.write_text(json.dumps(history, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(history)} days)")


def _load_existing():
    if OUT_PATH.exists():
        return json.loads(OUT_PATH.read_text())
    return []


if __name__ == "__main__":
    main()
