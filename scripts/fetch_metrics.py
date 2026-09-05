#!/usr/bin/env python3
"""Fetch daily metrics for sirius-db/sirius and write a snapshot to data/snapshots/.

Collects repo stats, activity deltas, traffic, releases, and open issue/PR labels for
today by default, or for a specific past date via --date (see BOOTSTRAP.md for
recovering a missed day). collect.yml always passes --date -- it only ever finalizes
already fully-elapsed days, never today; the no-argument default here is for manual/
local use. Note: --date backfilling doesn't apply to `labels` -- like `repo`, it's a
point-in-time snapshot of currently-open items, not reconstructable for a past date.
"""

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


def paginate_all(path, token=None):
    """Follow Link headers to collect every item across all pages."""
    items = []
    next_path = f"{path}{'&' if '?' in path else '?'}per_page=100"
    while next_path:
        page_items, link_header = api_get(next_path, token)
        items.extend(page_items)
        next_path = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                next_path = url[len(API_ROOT):]
    return items


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
    rolling total, so activity/traffic stay on the same 1-day-granularity model. Only used
    when running this script with no --date (a live, current-moment run, e.g. manual local
    testing) -- collect.yml itself always passes --date now (it only ever finalizes
    already-fully-elapsed days, never "today"), so day_entry() below is what it actually
    uses. GitHub's traffic aggregation isn't guaranteed to have caught up even for a
    fully-elapsed day; scripts/refresh_traffic.py is what patches that gap after the fact.
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
    commits = paginate_all(f"/repos/{REPO}/commits?since={day_start}&until={day_end}", token)

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
        author = commit.get("author")
        # A real GitHub login only exists when the commit is linked to an account --
        # otherwise this falls back to the raw git author name, which isn't safe to
        # link to github.com/<name> (could 404, or worse, hit an unrelated real
        # user's profile). is_user tracks which case we're in.
        if author:
            login, is_user = author["login"], True
        else:
            login, is_user = commit["commit"]["author"]["name"], False
        if login not in committer_counts:
            committer_counts[login] = {"commits": 0, "is_user": is_user}
        committer_counts[login]["commits"] += 1

    top_committers = sorted(
        (
            {"login": login, "commits": v["commits"], "is_user": v["is_user"]}
            for login, v in committer_counts.items()
        ),
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


# Ordered P0 -> P3 (not a set) so severity can be sorted on, not just membership-checked.
PRIORITY_LABELS = ("! - P0", "! - P1", "! - P2", "! - P3")


def fetch_label_metrics(token=None):
    """Daily rollup of open issue/PR labels -- counts plus a bounded stale top-10.

    Fetches every open issue/PR (with labels) fresh each run, but only persists a small
    daily-appropriate summary, not the full item list: per-label counts (small, like
    every other metric in this repo) and the 10 most stale items per category (bounded).
    The full item list only ever exists transiently here, in memory, during this one
    collection run -- there's no way to reconstruct "yesterday's full item list" from a
    snapshot, which is deliberate (see DATA.md for the size/redundancy tradeoff this
    avoids: storing ~150+ full item records daily forever would be pure git bloat next
    to every other field in this file).
    """
    items = paginate_all(f"/repos/{REPO}/issues?state=open", token)

    priority_counts = {label: {"issues": 0, "prs": 0, "color": None} for label in PRIORITY_LABELS}
    other_counts = {}
    priority_candidates = []
    other_candidates = []

    for item in items:
        label_objs = item.get("labels", [])
        if not label_objs:
            continue
        labels = [label["name"] for label in label_objs]
        is_pr = "pull_request" in item
        entry = {
            "number": item["number"],
            "title": item["title"],
            "url": item["html_url"],
            "updated_at": item["updated_at"],
        }

        # Color lives on the count bucket, not a separate structure -- GitHub's real
        # per-label color (captured fresh every run, since it can change), used to
        # render a matching dot on the site instead of an arbitrary palette.
        for label in label_objs:
            if label["name"] in PRIORITY_LABELS:
                priority_counts[label["name"]]["color"] = label["color"]
            else:
                bucket = other_counts.setdefault(
                    label["name"], {"issues": 0, "prs": 0, "color": None}
                )
                bucket["color"] = label["color"]

        priority_labels_here = [l for l in labels if l in PRIORITY_LABELS]
        for label in priority_labels_here:
            priority_counts[label]["prs" if is_pr else "issues"] += 1
        if priority_labels_here:
            # An item could in principle carry more than one priority label -- pick the
            # most severe (lowest P-number) for display and sorting.
            most_severe = min(priority_labels_here, key=PRIORITY_LABELS.index)
            priority_candidates.append({**entry, "priority_label": most_severe, "is_pr": is_pr})

        other_labels_here = [l for l in labels if l not in PRIORITY_LABELS]
        for label in other_labels_here:
            other_counts[label]["prs" if is_pr else "issues"] += 1
        if other_labels_here:
            other_candidates.append({**entry, "labels": other_labels_here, "is_pr": is_pr})

    # P0 first regardless of staleness, then P1, etc. -- staleness only breaks ties
    # within the same priority level, so the table reads by severity, not just by age.
    priority_sort_key = lambda e: (PRIORITY_LABELS.index(e["priority_label"]), e["updated_at"])
    drop_is_pr = lambda e: {k: v for k, v in e.items() if k != "is_pr"}
    priority_issue_candidates = sorted(
        (drop_is_pr(e) for e in priority_candidates if not e["is_pr"]), key=priority_sort_key
    )
    priority_pr_candidates = sorted(
        (drop_is_pr(e) for e in priority_candidates if e["is_pr"]), key=priority_sort_key
    )
    other_issue_candidates = sorted(
        (drop_is_pr(e) for e in other_candidates if not e["is_pr"]), key=lambda e: e["updated_at"]
    )
    other_pr_candidates = sorted(
        (drop_is_pr(e) for e in other_candidates if e["is_pr"]), key=lambda e: e["updated_at"]
    )

    return {
        "priority_counts": priority_counts,
        "other_counts": other_counts,
        "priority_issues_stale_top10": priority_issue_candidates[:10],
        "priority_prs_stale_top10": priority_pr_candidates[:10],
        "other_issues_stale_top10": other_issue_candidates[:10],
        "other_prs_stale_top10": other_pr_candidates[:10],
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
        "labels": fetch_label_metrics(traffic_token),
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
