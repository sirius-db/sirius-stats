#!/usr/bin/env python3
"""Build the static site/ directory: renders templates/index.html and templates/labels.html
(Jinja2) using data/snapshots/ history merged with the one-time stars/forks/traffic
backfills and weekly activity seed in data/, and copies static/ assets alongside the
rendered output.
"""

import json
import shutil
import statistics
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from _dates import week_start

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
STARS_BACKFILL_PATH = REPO_ROOT / "data" / "stars_backfill.json"
FORKS_BACKFILL_PATH = REPO_ROOT / "data" / "forks_backfill.json"
TRAFFIC_BACKFILL_PATH = REPO_ROOT / "data" / "traffic_backfill.json"
ACTIVITY_BACKFILL_PATH = REPO_ROOT / "data" / "activity_backfill.json"
REVIEW_BACKFILL_PATH = REPO_ROOT / "data" / "review_backfill.json"
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
BACKLOG_FIELDS = ["issues_opened", "issues_closed", "prs_opened", "prs_merged", "prs_closed"]

# Trailing windows for the pooled time-to-first-review percentile chart, and the minimum pooled
# sample size each percentile needs before it's trustworthy rather than noise -- a p95 computed
# from 6 samples is really just "whichever PR took second-longest," not a real percentile.
PERCENTILE_WINDOWS_WEEKS = [1, 4, 13, 26]
PERCENTILE_MIN_SAMPLES = {"p50": 5, "p90": 10, "p95": 20}


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


def build_data(
    snapshots,
    stars_backfill,
    forks_backfill,
    traffic_backfill,
    activity_backfill,
    review_backfill,
):
    stars = merge_point_series(
        stars_backfill, "stars", snapshots, lambda s: s["repo"]["stars"]
    )
    forks = merge_point_series(
        forks_backfill, "forks", snapshots, lambda s: s["repo"]["forks"]
    )

    # traffic["as_of_date"] is the day GitHub had actually aggregated at collection time,
    # which can be null (not yet published) even for a fully-elapsed s["date"] until
    # refresh_traffic.py patches it in on a later run -- use as_of_date for the x-axis so
    # the chart reflects the day the counts actually cover, not when they were captured.
    traffic_by_date = {p["date"]: p for p in traffic_backfill}
    for s in snapshots:
        # as_of_date, not views, is the real null signal -- day_entry()/
        # latest_complete_day() return (None, 0, 0) when GitHub hasn't aggregated a
        # day's traffic yet (its rolling breakdown can legitimately lag more than a
        # day), so views is 0, not None, in that case. Keying traffic_by_date by a
        # None date crashes the later sorted() call.
        if s["traffic"]["as_of_date"] is None:
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
    review_weekly = build_review_weekly(snapshots, review_backfill)
    review_current = build_review_current(snapshots)
    review_team_history = build_review_team_history(snapshots)
    pr_health_history = build_pr_health_history(snapshots)
    review_percentile_windows = build_review_percentile_windows(snapshots, review_backfill)
    pr_size_vs_latency = build_pr_size_vs_latency(snapshots, review_backfill)

    # as_of_date, not views, is the real null signal here too (see the identical
    # comment above) -- without this, latest_traffic always resolves to the newest
    # snapshot regardless of whether its traffic is actually valid.
    latest_traffic = next(
        (s["traffic"] for s in reversed(snapshots) if s["traffic"]["as_of_date"] is not None),
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
        "review_weekly": review_weekly,
        "review_current": review_current,
        "review_team_history": review_team_history,
        "pr_health_history": pr_health_history,
        "review_percentile_windows": review_percentile_windows,
        "pr_size_vs_latency": pr_size_vs_latency,
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
    untriaged_history = []
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

        # untriaged_counts is only present on snapshots collected after this field was added --
        # older snapshots simply don't contribute a point, same as every other field added
        # mid-history in this codebase.
        if "untriaged_counts" in labels_data:
            untriaged_history.append({"date": snapshot_date, **labels_data["untriaged_counts"]})

        # Snapshots are already in date order (load_snapshots() sorts by filename), so
        # the last one processed is the latest.
        latest_date = snapshot_date
        latest_labels_data = labels_data

    def total(counts):
        return counts["issues"] + counts["prs"]

    # Every entry gets every label ever seen, defaulting to 0 -- not just the labels
    # present on that specific day. A label that first appears on day 3 still needs a
    # key (0) on days 1-2, or a client-side chart deriving its series from day 1 alone
    # would never plot that label at all (real bug, caught in PR #7 review).
    all_other_labels = sorted(
        {label for counts in other_counts_by_date.values() for label in counts}
    )
    other_history = [
        {
            "date": d,
            **{
                label: total(other_counts_by_date[d][label]) if label in other_counts_by_date[d] else 0
                for label in all_other_labels
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

    untriaged_current = (
        latest_labels_data["untriaged_counts"]
        if latest_labels_data and "untriaged_counts" in latest_labels_data
        else {"issues": 0, "prs": 0}
    )

    return {
        "as_of_date": latest_date,
        "priority_issues_history": priority_issues_history,
        "priority_prs_history": priority_prs_history,
        "other_history": other_history,
        "untriaged_history": untriaged_history,
        "untriaged_current": untriaged_current,
        "priority_issues_stale_top10": latest_labels_data["priority_issues_stale_top10"] if latest_labels_data else [],
        "priority_prs_stale_top10": latest_labels_data["priority_prs_stale_top10"] if latest_labels_data else [],
        "other_issues_stale_top10": latest_labels_data["other_issues_stale_top10"] if latest_labels_data else [],
        "other_prs_stale_top10": latest_labels_data["other_prs_stale_top10"] if latest_labels_data else [],
        "all_labels_current": all_labels_current,
        "label_colors": label_colors,
    }


def build_activity_weekly(snapshots, activity_backfill):
    """Merge the static historical seed with weeks computed from live daily snapshots.

    activity_backfill only covers weeks before daily collection existed; every week a
    live snapshot falls in is instead computed fresh here, so the chart keeps growing
    on its own without ever needing another manual Pulse export.

    activity_backfill only ever carried commits/additions/deletions (the original Pulse export
    didn't include issue/PR counts) -- BACKLOG_FIELDS only exist for weeks with real daily
    snapshots, so backfill-only weeks get null for those fields (and null net_change), not 0:
    a 0 means "we tracked this week and nothing happened," which is a different claim than "we
    didn't track this week at all." Collapsing those to the same 0 would read as "no PR activity
    in the repo's early months," which isn't true -- it just predates backlog-count tracking.
    """
    weekly_by_date = {w["week_of"]: dict(w) for w in activity_backfill}

    computed = {}
    for s in snapshots:
        activity = s.get("activity")
        if not activity:
            continue
        key = week_start(date.fromisoformat(s["date"])).isoformat()
        bucket = computed.setdefault(
            key, {"commits": 0, "additions": 0, "deletions": 0, **{f: 0 for f in BACKLOG_FIELDS}}
        )
        bucket["commits"] += activity.get("commits", 0)
        bucket["additions"] += activity.get("additions", 0)
        bucket["deletions"] += activity.get("deletions", 0)
        for field in BACKLOG_FIELDS:
            bucket[field] += activity.get(field, 0)

    for week_of, totals in computed.items():
        # Live-computed data wins over the static backfill on an overlapping week.
        weekly_by_date[week_of] = {"week_of": week_of, **totals}

    for entry in weekly_by_date.values():
        tracked = BACKLOG_FIELDS[0] in entry
        for field in BACKLOG_FIELDS:
            entry.setdefault(field, None)
        entry["issue_net_change"] = (
            entry["issues_opened"] - entry["issues_closed"] if tracked else None
        )
        entry["pr_net_change"] = (
            entry["prs_opened"] - entry["prs_merged"] - entry["prs_closed"] if tracked else None
        )

    return [weekly_by_date[d] for d in sorted(weekly_by_date)]


def _current_incomplete_review_week():
    """The week_of bucket that's still in progress as of right now -- not a finished week yet,
    so its own aggregate is a partial sample, not a real data point. This also matters because
    the live-overrides-backfill merge replaces a backfilled week's full sample wholesale the
    moment even one live snapshot lands in it -- while that week is still in progress, "live" can
    mean "1 day," which is a worse sample than the backfill it replaced. Excluding the in-progress
    week sidesteps that; once a week is actually complete, it will have been fully live-collected
    day by day with no backfill involved at all.

    Anchored on the real current date, not on whether a live snapshot happens to exist for today
    -- collect.yml not having run yet today (or this script simply being run standalone, without
    a fresh fetch_metrics.py pass first) must not make the exclusion silently no-op and let a
    backfilled row for the in-progress week show through as if it were a finished week.
    """
    return week_start(date.today()).isoformat()


def build_review_weekly(snapshots, review_backfill):
    """Weekly review-health rollup.

    median/p90/p95_first_review_hours and zero_review_rate are all derived in one final pass
    below from each entry's own first_review_latencies_hours/zero_review_count/pr_count -- that
    keeps backfilled and live weeks on identical math instead of only live weeks getting fields
    computed directly. p90/p95 are null below PERCENTILE_MIN_SAMPLES (same thresholds as
    build_review_percentile_windows) -- median isn't gated, since even a 1-2-sample median is a
    real (if volatile) number, unlike a percentile computed from too few points. See DATA.md for
    why the bounded raw list is stored at all (a weekly median/percentile can't be derived from
    daily partial medians). draft_pr_count/idle_pr_count are point-in-time gauges, like repo.* --
    latest-in-week, not summed (matches build_activity_windows' point-in-time treatment).

    The current in-progress week (see _current_incomplete_review_week) is dropped entirely, not
    just nulled -- a partial week isn't a real data point, and showing one invites exactly the
    kind of misread a negative median produced here once (a PR reviewed before it was marked
    ready for review, pulling that single-sample week's median below zero).
    """
    weekly_by_date = {w["week_of"]: dict(w) for w in review_backfill}

    computed = {}
    for s in snapshots:
        reviews = s.get("reviews")
        if not reviews:
            continue
        key = week_start(date.fromisoformat(s["date"])).isoformat()
        bucket = computed.setdefault(
            key,
            {
                "first_review_latencies_hours": [],
                "zero_review_count": 0,
                "pr_count": 0,
                "draft_pr_count": None,
                "idle_pr_count": None,
            },
        )
        bucket["first_review_latencies_hours"].extend(
            reviews.get("first_review_latencies_hours", [])
        )
        bucket["zero_review_count"] += reviews.get("zero_review_nondraft_count", 0)
        bucket["pr_count"] += reviews.get("nondraft_touched_count", 0)
        # Snapshots are date-ordered, so the last one processed in the week wins.
        bucket["draft_pr_count"] = reviews.get("draft_pr_count")
        # idle_prs is the full PR list (for the donut chart's drill-down column); this field only
        # ever needs the count.
        bucket["idle_pr_count"] = len(reviews.get("idle_prs", []))

    for week_of, bucket in computed.items():
        # Live-computed data wins over the static backfill on an overlapping week.
        weekly_by_date[week_of] = {"week_of": week_of, **bucket}

    weekly_by_date.pop(_current_incomplete_review_week(), None)

    for entry in weekly_by_date.values():
        latencies = entry.get("first_review_latencies_hours", [])
        entry["median_first_review_hours"] = (
            round(statistics.median(latencies), 2) if latencies else None
        )
        entry["p90_first_review_hours"] = (
            _percentile(latencies, 90) if len(latencies) >= PERCENTILE_MIN_SAMPLES["p90"] else None
        )
        entry["p95_first_review_hours"] = (
            _percentile(latencies, 95) if len(latencies) >= PERCENTILE_MIN_SAMPLES["p95"] else None
        )
        entry["zero_review_rate"] = (
            round(entry["zero_review_count"] / entry["pr_count"], 4)
            if entry.get("pr_count")
            else None
        )

    return [weekly_by_date[d] for d in sorted(weekly_by_date)]


def _percentile(values, pct):
    """pct-th percentile of values (pct in [1, 99]), inclusive method -- matches the intuitive
    "value at this rank within a bounded, already-collected sample" reading rather than
    extrapolating beyond the sample's own range.
    """
    if len(values) < 2:
        return round(values[0], 2) if values else None
    return round(statistics.quantiles(values, n=100, method="inclusive")[pct - 1], 2)


def _review_latencies_by_week(snapshots, review_backfill):
    """Per-week pooled raw first-review latency samples, live snapshots overriding backfill on
    any week with at least one live snapshot -- same all-or-nothing override semantics as every
    other weekly merge in this file (build_activity_weekly, build_review_weekly). Excludes the
    current in-progress week (see _current_incomplete_review_week) -- "last 1w" should mean the
    most recent *complete* week, not however many days of the still-accumulating current week
    happen to exist when this build ran.
    """
    by_week = {w["week_of"]: list(w.get("first_review_latencies_hours", [])) for w in review_backfill}

    live_weeks = {}
    for s in snapshots:
        reviews = s.get("reviews")
        if not reviews:
            continue
        key = week_start(date.fromisoformat(s["date"])).isoformat()
        live_weeks.setdefault(key, []).extend(reviews.get("first_review_latencies_hours", []))
    by_week.update(live_weeks)
    by_week.pop(_current_incomplete_review_week(), None)
    return by_week


def build_review_percentile_windows(snapshots, review_backfill):
    """Pooled p50/p90/p95 time-to-first-review across the trailing 1/4/13 *complete weeks*.

    Week-bucketed (Sunday-start, same convention as every other weekly rollup here), not a
    sliding 7-day calendar window -- keeps this consistent with how "last N weeks" already means
    N week-buckets everywhere else on the dashboard, and sidesteps having to reconcile backfill's
    week-only granularity against live collection's daily granularity.

    Pools raw samples from both review_backfill.json and live snapshots (see
    _review_latencies_by_week) rather than averaging each week's own percentile -- percentiles
    don't average into a meaningful combined percentile, so this is what gives p90/p95 a real
    sample size instead of depending on any single thin week.
    """
    by_week = _review_latencies_by_week(snapshots, review_backfill)
    if not by_week:
        return []
    sorted_weeks = sorted(by_week)

    windows = []
    for n in PERCENTILE_WINDOWS_WEEKS:
        pooled = [v for w in sorted_weeks[-n:] for v in by_week[w]]
        windows.append(
            {
                "window": f"{n}w",
                "sample_size": len(pooled),
                "p50": _percentile(pooled, 50) if len(pooled) >= PERCENTILE_MIN_SAMPLES["p50"] else None,
                "p90": _percentile(pooled, 90) if len(pooled) >= PERCENTILE_MIN_SAMPLES["p90"] else None,
                "p95": _percentile(pooled, 95) if len(pooled) >= PERCENTILE_MIN_SAMPLES["p95"] else None,
            }
        )
    return windows


def build_pr_size_vs_latency(snapshots, review_backfill):
    """Pooled (size, first-review-latency) points for the scatter chart -- one point per PR,
    deduped by PR number (live snapshots override a backfilled entry for the same PR, same
    live-wins convention as every other merge in this file), not a running total that would
    double-count a PR appearing in both sources.
    """
    by_number = {}
    for w in review_backfill:
        for pr in w.get("pr_sizes_vs_latency", []):
            by_number[pr["number"]] = pr
    for s in snapshots:
        reviews = s.get("reviews")
        if not reviews:
            continue
        for pr in reviews.get("pr_sizes_vs_latency", []):
            by_number[pr["number"]] = pr
    return sorted(by_number.values(), key=lambda pr: pr["number"])


def build_review_team_history(snapshots):
    """Daily history of pending review requests by team, for the historical stacked-line chart
    (same shape/zero-fill treatment as build_label_data()'s other_history).

    NOT backfillable -- pending_reviews_by_team is point-in-time current state (like
    repo.open_prs), so there's no way to reconstruct "which team had a pending request on day X"
    after the fact. Starts sparse and builds up one real day of collection at a time.
    """
    counts_by_date = {}
    for s in snapshots:
        reviews = s.get("reviews")
        if not reviews:
            continue
        counts_by_date[s["date"]] = {
            team: len(prs) for team, prs in reviews.get("pending_reviews_by_team", {}).items()
        }

    all_teams = sorted({team for counts in counts_by_date.values() for team in counts})
    return [
        {"date": d, **{team: counts_by_date[d].get(team, 0) for team in all_teams}}
        for d in sorted(counts_by_date)
    ]


def build_pr_health_history(snapshots):
    """Daily history of the four mutually-exclusive PR health counts (draft/idle/zero_review/
    in_review), for the stacked-line "PR health over time" chart -- same discipline as
    build_review_team_history(): NOT backfillable (point-in-time current state, like
    repo.open_prs), so it starts sparse and builds up one real day of collection at a time.
    """
    history = []
    for s in snapshots:
        reviews = s.get("reviews")
        if not reviews:
            continue
        history.append(
            {
                "date": s["date"],
                "draft": reviews["draft_pr_count"],
                "idle": len(reviews["idle_prs"]),
                "zero_review": len(reviews["zero_review_prs"]),
                "in_review": reviews["in_review_count"],
            }
        )
    return history


def build_review_current(snapshots):
    """Point-in-time review state from the latest snapshot that has a `reviews` block -- pending
    reviews by team (actual PRs, for a linkable triage table), and the mutually-exclusive PR
    health breakdown (draft_pr_count, idle_prs, zero_review_prs, in_review_count) that feeds the
    "current repo health" donut chart. Every non-draft open PR is classified into exactly one of
    idle/zero_review/in_review by fetch_metrics.py, so these four counts always sum to the total
    open PR count -- percentages are computed client-side from that total, not precomputed here.
    Rendered as current-state tables/tiles (like activity_windows), not a history chart.
    """
    latest = next((s for s in reversed(snapshots) if s.get("reviews")), None)
    if not latest:
        return {
            "pending_reviews_by_team": {},
            "draft_pr_count": 0,
            "idle_prs": [],
            "zero_review_prs": [],
            "in_review_count": 0,
        }
    reviews = latest["reviews"]
    return {
        "pending_reviews_by_team": reviews["pending_reviews_by_team"],
        "draft_pr_count": reviews["draft_pr_count"],
        "idle_prs": reviews["idle_prs"],
        "zero_review_prs": reviews["zero_review_prs"],
        "in_review_count": reviews["in_review_count"],
    }


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
    review_backfill = load_json_if_exists(REVIEW_BACKFILL_PATH)
    data = build_data(
        snapshots,
        stars_backfill,
        forks_backfill,
        traffic_backfill,
        activity_backfill,
        review_backfill,
    )

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
