#!/usr/bin/env python3
"""Fetch daily metrics for sirius-db/sirius and write a snapshot to data/snapshots/."""

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "sirius-db/sirius"
API_ROOT = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"


def api_get(path, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)
    with urllib.request.urlopen(request) as response:
        body = response.read()
        link_header = response.headers.get("Link", "")
    return json.loads(body), link_header


def count_via_pagination(path, token=None):
    """Count total items across paginated results using per_page=1 and the Link header's last page."""
    items, link_header = api_get(f"{path}{'&' if '?' in path else '?'}per_page=1", token)
    if 'rel="last"' not in link_header:
        return len(items)
    for part in link_header.split(","):
        if 'rel="last"' in part:
            url = part.split(";")[0].strip().strip("<>")
            query = url.split("?", 1)[1]
            params = dict(pair.split("=") for pair in query.split("&"))
            return int(params.get("page", 1))
    return len(items)


def fetch_repo_metrics(token=None):
    repo, _ = api_get(f"/repos/{REPO}", token)
    open_prs = count_via_pagination(f"/repos/{REPO}/pulls?state=open", token)
    contributors = count_via_pagination(f"/repos/{REPO}/contributors?anon=true", token)
    return {
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "watchers": repo["subscribers_count"],
        "open_issues": repo["open_issues_count"] - open_prs,
        "open_prs": open_prs,
        "contributors": contributors,
    }


def latest_complete_day(daily_breakdown):
    """Pick the most recent fully-aggregated day from a traffic endpoint's daily breakdown.

    /traffic/views and /traffic/clones return both a 14-day rolling total (top-level
    count/uniques) and a per-day breakdown -- we want a single day's real count, not the
    rolling total, so activity/traffic stay on the same 1-day-granularity model. We can't
    assume "today" is already aggregated: collect.yml runs at 2330 UTC specifically to
    give GitHub most of the day to finish aggregating before we grab it, but that's not
    a guarantee -- aggregation can still lag. Taking whichever entry is most recent
    handles both cases: usually that's "today" given the 2330 UTC run time, but it falls
    back to "yesterday" if today's entry isn't aggregated yet.
    """
    if not daily_breakdown:
        return None, 0, 0
    latest = max(daily_breakdown, key=lambda e: e["timestamp"])
    return latest["timestamp"][:10], latest["count"], latest["uniques"]


def day_entry(daily_breakdown, target_date):
    """Exact-match lookup for --date backfills, instead of always picking the latest day."""
    for entry in daily_breakdown:
        if entry["timestamp"][:10] == target_date:
            return target_date, entry["count"], entry["uniques"]
    return None, 0, 0


def fetch_traffic_metrics(token, target_date=None):
    views, _ = api_get(f"/repos/{REPO}/traffic/views", token)
    clones, _ = api_get(f"/repos/{REPO}/traffic/clones", token)
    referrers, _ = api_get(f"/repos/{REPO}/traffic/popular/referrers", token)
    paths, _ = api_get(f"/repos/{REPO}/traffic/popular/paths", token)

    if target_date:
        views_date, views_count, views_uniques = day_entry(views["views"], target_date)
        clones_date, clones_count, clones_uniques = day_entry(clones["clones"], target_date)
        if views_date is None and clones_date is None:
            print(
                f"WARNING: {target_date} is no longer in GitHub's 14-day traffic window -- "
                "traffic fields will be zeroed. Use traffic_backfill.json for this day instead "
                "if it was captured before rolling out of the window."
            )
    else:
        views_date, views_count, views_uniques = latest_complete_day(views["views"])
        clones_date, clones_count, clones_uniques = latest_complete_day(clones["clones"])

    return {
        # The day these views/clones counts actually cover -- one day behind the
        # snapshot's own `date`, since that's the most recent complete day GitHub has
        # aggregated at collection time.
        "as_of_date": views_date or clones_date,
        "views": views_count,
        "unique_views": views_uniques,
        "clones": clones_count,
        "unique_clones": clones_uniques,
        "top_referrers": [
            {"referrer": r["referrer"], "count": r["count"], "uniques": r["uniques"]}
            for r in referrers
        ],
        "top_paths": [
            {"path": p["path"], "count": p["count"], "uniques": p["uniques"]}
            for p in paths
        ],
    }


def search_count(query, token):
    """Count results for a GitHub Search API query (used for issue/PR daily deltas)."""
    result, _ = api_get(f"/search/issues?q={urllib.parse.quote(query)}&per_page=1", token)
    return result["total_count"]


def fetch_activity_metrics(today, token):
    q = f"repo:{REPO}"
    issues_opened = search_count(f"{q} type:issue created:{today}", token)
    issues_closed = search_count(f"{q} type:issue closed:{today}", token)
    prs_opened = search_count(f"{q} type:pr created:{today}", token)
    prs_merged = search_count(f"{q} type:pr merged:{today}", token)
    prs_closed_total = search_count(f"{q} type:pr closed:{today}", token)

    day_start = f"{today}T00:00:00Z"
    day_end = f"{today}T23:59:59Z"
    commits, _ = api_get(
        f"/repos/{REPO}/commits?since={day_start}&until={day_end}&per_page=100", token
    )

    files_changed = 0
    additions = 0
    deletions = 0
    committer_counts = {}
    for commit in commits:
        detail, _ = api_get(f"/repos/{REPO}/commits/{commit['sha']}", token)
        stats = detail.get("stats", {})
        additions += stats.get("additions", 0)
        deletions += stats.get("deletions", 0)
        files_changed += len(detail.get("files", []))
        login = (commit.get("author") or {}).get("login") or commit["commit"]["author"]["name"]
        committer_counts[login] = committer_counts.get(login, 0) + 1

    top_committers = sorted(
        ({"login": login, "commits": count} for login, count in committer_counts.items()),
        key=lambda c: c["commits"],
        reverse=True,
    )

    return {
        "issues_opened": issues_opened,
        "issues_closed": issues_closed,
        "prs_opened": prs_opened,
        "prs_merged": prs_merged,
        "prs_closed": prs_closed_total - prs_merged,
        "commits": len(commits),
        "files_changed": files_changed,
        "additions": additions,
        "deletions": deletions,
        "top_committers": top_committers,
    }


def fetch_releases(token=None):
    releases, _ = api_get(f"/repos/{REPO}/releases", token)
    entries = []
    for release in releases:
        for asset in release.get("assets", []):
            entries.append(
                {
                    "tag": release["tag_name"],
                    "asset": asset["name"],
                    "download_count": asset["download_count"],
                }
            )
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help=(
            "Backfill a specific past date (YYYY-MM-DD) instead of today. Only "
            "`activity` (issues/PRs/commits) and `traffic` (if still within GitHub's "
            "14-day window) can be reconstructed for a past date -- `repo` and "
            "`releases` are point-in-time and will reflect current values, not the "
            "target date's."
        ),
    )
    args = parser.parse_args()

    traffic_token = os.environ.get("SIRIUS_TRAFFIC_TOKEN")
    now = datetime.now(timezone.utc)
    target_date = args.date or now.strftime("%Y-%m-%d")

    if args.date:
        print(f"Backfilling {args.date} -- repo/releases fields will reflect today's values")

    snapshot = {
        "date": target_date,
        "collected_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": fetch_repo_metrics(traffic_token),
        "activity": fetch_activity_metrics(target_date, traffic_token),
        "traffic": {
            "as_of_date": None,
            "views": None,
            "unique_views": None,
            "clones": None,
            "unique_clones": None,
            "top_referrers": [],
            "top_paths": [],
        },
        "releases": fetch_releases(traffic_token),
    }

    if traffic_token:
        snapshot["traffic"] = fetch_traffic_metrics(traffic_token, target_date=args.date)
    else:
        print("SIRIUS_TRAFFIC_TOKEN not set, skipping traffic collection")

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOTS_DIR / f"{target_date}.json"
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
