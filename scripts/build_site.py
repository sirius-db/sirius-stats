#!/usr/bin/env python3
"""Build the static site/ directory: renders templates/index.html and templates/labels.html
(Jinja2) using data/snapshots/ history merged with the one-time stars/forks/traffic
backfills and weekly activity seed in data/, and copies static/ assets alongside the
rendered output.
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
STARS_BACKFILL_PATH = REPO_ROOT / "data" / "stars_backfill.json"
FORKS_BACKFILL_PATH = REPO_ROOT / "data" / "forks_backfill.json"
TRAFFIC_BACKFILL_PATH = REPO_ROOT / "data" / "traffic_backfill.json"
ACTIVITY_BACKFILL_PATH = REPO_ROOT / "data" / "activity_backfill.json"
TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"
SITE_DIR = REPO_ROOT / "site"
LOGO_CANDIDATES = ["logo.svg", "logo.png"]

# One snapshot is collected per day, so a window is just "the last N snapshots".
ACTIVITY_WINDOWS = {"24h": 1, "3d": 3, "7d": 7, "1mo": 30}
ACTIVITY_COUNT_FIELDS = [
    "issues_opened",
    "issues_closed",
    "prs_opened",
    "prs_merged",
    "prs_closed",
    "commits",
    "files_changed",
    "additions",
    "deletions",
]


def load_snapshots():
    snapshots = []
    for path in sorted(SNAPSHOTS_DIR.glob("*.json")):
        snapshots.append(json.loads(path.read_text()))
    return snapshots


def load_json_if_exists(path):
    if path.exists():
        return json.loads(path.read_text())
    return []


def merge_point_series(backfill, backfill_key, snapshots, snapshot_value_fn):
    """Merge a backfill series with live snapshots, deduped by date.

    Live snapshot values win on any date that appears in both -- same pattern as the
    traffic merge below. Needed because a backfill's last day and a snapshot's first
    day can land on the same date (observed with stars: both landed on 2026-08-31),
    which would otherwise produce a duplicate point in the chart.
    """
    by_date = {p["date"]: {"date": p["date"], "value": p[backfill_key]} for p in backfill}
    for s in snapshots:
        by_date[s["date"]] = {"date": s["date"], "value": snapshot_value_fn(s)}
    return [by_date[d] for d in sorted(by_date)]


def build_data(snapshots, stars_backfill, forks_backfill, traffic_backfill, activity_backfill):
    stars = merge_point_series(
        stars_backfill, "stars", snapshots, lambda s: s["repo"]["stars"]
    )
    forks = merge_point_series(
        forks_backfill, "forks", snapshots, lambda s: s["repo"]["forks"]
    )

    # traffic["as_of_date"] is the last complete day GitHub had aggregated at collection
    # time (collect.yml runs at 2330 UTC, so this is usually still one day behind
    # s["date"]) -- use it for the x-axis so the chart reflects the day the counts
    # actually cover.
    traffic_by_date = {p["date"]: p for p in traffic_backfill}
    for s in snapshots:
        if s["traffic"]["views"] is None:
            continue
        # Live collection wins over backfill on an overlapping date.
        traffic_by_date[s["traffic"]["as_of_date"]] = {
            "date": s["traffic"]["as_of_date"],
            "views": s["traffic"]["views"],
            "unique_views": s["traffic"]["unique_views"],
            "clones": s["traffic"]["clones"],
            "unique_clones": s["traffic"]["unique_clones"],
        }
    traffic = [traffic_by_date[d] for d in sorted(traffic_by_date)]

    activity_windows = build_activity_windows(snapshots)
    activity_weekly = build_activity_weekly(snapshots, activity_backfill)
    labels = build_label_data(snapshots)

    latest_traffic = next(
        (s["traffic"] for s in reversed(snapshots) if s["traffic"]["views"] is not None),
        None,
    )
    top_referrers = latest_traffic["top_referrers"] if latest_traffic else []
    top_paths = latest_traffic["top_paths"] if latest_traffic else []

    return {
        "stars": stars,
        "forks": forks,
        "traffic": traffic,
        "activity_windows": activity_windows,
        "activity_weekly": activity_weekly,
        "labels": labels,
        "top_referrers": top_referrers,
        "top_paths": top_paths,
    }


def build_label_data(snapshots):
    """Merge each day's label count rollup into history; pass the latest day's stale
    top-10 tables straight through.

    fetch_metrics.py already does the priority/other classification and stale ranking
    at collection time (see fetch_label_metrics()) -- there's no full item list here to
    reprocess, only the small daily counts and the already-bounded top-10s.
    """
    priority_issues_history = []
    priority_prs_history = []
    other_counts_by_date = {}
    latest_date = None
    latest_labels_data = None

    for s in snapshots:
        labels_data = s.get("labels")
        if not labels_data:
            continue
        snapshot_date = s["date"]

        priority_issue_counts = {
            label: counts["issues"] for label, counts in labels_data["priority_counts"].items()
        }
        priority_pr_counts = {
            label: counts["prs"] for label, counts in labels_data["priority_counts"].items()
        }
        priority_issues_history.append({"date": snapshot_date, **priority_issue_counts})
        priority_prs_history.append({"date": snapshot_date, **priority_pr_counts})
        other_counts_by_date[snapshot_date] = labels_data["other_counts"]

        # Snapshots are already in date order (load_snapshots() sorts by filename), so
        # the last one processed is the latest.
        latest_date = snapshot_date
        latest_labels_data = labels_data

    def total(counts):
        return counts["issues"] + counts["prs"]

    all_other_labels = sorted(
        {label for counts in other_counts_by_date.values() for label in counts}
    )
    other_history = [
        {
            "date": d,
            **{
                label: total(other_counts_by_date[d][label])
                for label in all_other_labels
                if label in other_counts_by_date[d]
            },
        }
        for d in sorted(other_counts_by_date)
    ]

    all_labels_current = {}
    label_colors = {}
    if latest_labels_data:
        for label, counts in latest_labels_data["priority_counts"].items():
            all_labels_current[label] = total(counts)
            label_colors[label] = counts["color"]
        for label, counts in latest_labels_data["other_counts"].items():
            all_labels_current[label] = total(counts)
            label_colors[label] = counts["color"]
        all_labels_current = dict(
            sorted(all_labels_current.items(), key=lambda kv: kv[1], reverse=True)
        )

    return {
        "as_of_date": latest_date,
        "priority_issues_history": priority_issues_history,
        "priority_prs_history": priority_prs_history,
        "other_history": other_history,
        "priority_issues_stale_top10": latest_labels_data["priority_issues_stale_top10"] if latest_labels_data else [],
        "priority_prs_stale_top10": latest_labels_data["priority_prs_stale_top10"] if latest_labels_data else [],
        "other_issues_stale_top10": latest_labels_data["other_issues_stale_top10"] if latest_labels_data else [],
        "other_prs_stale_top10": latest_labels_data["other_prs_stale_top10"] if latest_labels_data else [],
        "all_labels_current": all_labels_current,
        "label_colors": label_colors,
    }


def week_start(day):
    """Sunday on-or-before `day`, matching GitHub Pulse's weekly bucket convention."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def build_activity_weekly(snapshots, activity_backfill):
    """Merge the static historical seed with weeks computed from live daily snapshots.

    activity_backfill only covers weeks before daily collection existed; every week a
    live snapshot falls in is instead computed fresh here, so the chart keeps growing
    on its own without ever needing another manual Pulse export.
    """
    weekly_by_date = {w["week_of"]: dict(w) for w in activity_backfill}

    computed = {}
    for s in snapshots:
        activity = s.get("activity")
        if not activity:
            continue
        key = week_start(date.fromisoformat(s["date"])).isoformat()
        bucket = computed.setdefault(key, {"commits": 0, "additions": 0, "deletions": 0})
        bucket["commits"] += activity.get("commits", 0)
        bucket["additions"] += activity.get("additions", 0)
        bucket["deletions"] += activity.get("deletions", 0)

    for week_of, totals in computed.items():
        # Live-computed data wins over the static backfill on an overlapping week.
        weekly_by_date[week_of] = {"week_of": week_of, **totals}

    return [weekly_by_date[d] for d in sorted(weekly_by_date)]


def build_activity_windows(snapshots):
    windows = {}
    for label, num_days in ACTIVITY_WINDOWS.items():
        window_snapshots = snapshots[-num_days:]
        totals = {field: 0 for field in ACTIVITY_COUNT_FIELDS}
        committer_counts = {}
        for snapshot in window_snapshots:
            activity = snapshot.get("activity")
            if not activity:
                continue
            for field in ACTIVITY_COUNT_FIELDS:
                totals[field] += activity.get(field, 0)
            for committer in activity.get("top_committers", []):
                login = committer["login"]
                committer_counts[login] = committer_counts.get(login, 0) + committer["commits"]

        top_committers = sorted(
            ({"login": login, "commits": count} for login, count in committer_counts.items()),
            key=lambda c: c["commits"],
            reverse=True,
        )[:10]

        windows[label] = {**totals, "top_committers": top_committers}
    return windows


def find_logo():
    for name in LOGO_CANDIDATES:
        if (STATIC_DIR / name).exists():
            return f"static/{name}"
    return None


def main():
    snapshots = load_snapshots()
    stars_backfill = load_json_if_exists(STARS_BACKFILL_PATH)
    forks_backfill = load_json_if_exists(FORKS_BACKFILL_PATH)
    traffic_backfill = load_json_if_exists(TRAFFIC_BACKFILL_PATH)
    activity_backfill = load_json_if_exists(ACTIVITY_BACKFILL_PATH)
    data = build_data(snapshots, stars_backfill, forks_backfill, traffic_backfill, activity_backfill)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "data.json").write_text(json.dumps(data, indent=2) + "\n")

    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, SITE_DIR / "static", dirs_exist_ok=True)

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    last_collected = snapshots[-1]["collected_at"] if snapshots else "never"
    render_kwargs = {"last_collected": last_collected, "logo_path": find_logo()}

    for page in ("index.html", "labels.html"):
        html = env.get_template(page).render(**render_kwargs)
        (SITE_DIR / page).write_text(html)

    print(f"wrote {SITE_DIR / 'index.html'}, {SITE_DIR / 'labels.html'}, and {SITE_DIR / 'data.json'}")


if __name__ == "__main__":
    main()
