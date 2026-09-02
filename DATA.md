# Data model

Reference for everything under `data/`, the merge rules `scripts/build_site.py` applies to
combine them, and the recommended entry point for analysis. Read this before writing anything
that reads `data/` directly, whether that's a script, a one-off query, or an agent doing
historical analysis -- the raw files alone don't explain their own merge/precedence rules, and
misreading them has caused real bugs earlier in this repo's history (see git log for
`merge_point_series()` and the traffic `as_of_date` fix).

**Keep this file in sync with the code.** If a change touches `fetch_metrics.py`'s snapshot
shape, `build_site.py`'s merge logic, or adds a new backfill file, update this doc in the same
PR -- the same discipline already applied to `README.md`/`BOOTSTRAP.md`. A stale schema doc is
worse than no schema doc, since it actively misleads instead of just being silent.

## Recommended entry point for analysis

Don't parse the raw files below by hand if you can avoid it. Run:

```bash
uv run scripts/build_site.py
```

This produces `site/data.json` -- the merged, deduped, already-computed view (backfills merged
with live snapshots, activity rolled into windows, traffic reconciled to real per-day counts).
It's the same data the site itself renders, so it's guaranteed to reflect the actual merge rules
correctly. **It is not committed to git** (`site/` is `.gitignore`'d as build output) -- regenerate
it locally rather than looking for it in the repo.

`site/data.json` shape:

```json
{
  "stars": [{"date": "...", "value": 0}],
  "forks": [{"date": "...", "value": 0}],
  "traffic": [{"date": "...", "views": 0, "unique_views": 0, "clones": 0, "unique_clones": 0}],
  "activity_windows": {
    "24h": {"issues_opened": 0, "...": "...", "top_committers": [{"login": "...", "commits": 0}]},
    "3d": "...", "7d": "...", "1mo": "..."
  },
  "activity_weekly": [{"week_of": "...", "commits": 0, "additions": 0, "deletions": 0}],
  "top_referrers": [{"referrer": "...", "count": 0, "uniques": 0}],
  "top_paths": [{"path": "...", "count": 0, "uniques": 0}],
  "labels": {
    "as_of_date": "...",
    "priority_issues_history": [{"date": "...", "! - P0": 0, "! - P1": 0, "! - P2": 0, "! - P3": 0}],
    "priority_prs_history": [{"date": "...", "! - P0": 0, "! - P1": 0, "! - P2": 0, "! - P3": 0}],
    "other_history": [{"date": "...", "bug": 0, "...": "one key per non-priority label ever seen"}],
    "priority_issues_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P1"}],
    "priority_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P1"}],
    "other_issues_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}],
    "other_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}],
    "all_labels_current": {"bug": 0, "...": "every label -> current open count, sorted descending"},
    "label_colors": {"! - P0": "b60205", "bug": "d73a4a", "...": "every label -> GitHub's real hex color, no #"}
  }
}
```

`activity_windows`, `top_referrers`/`top_paths`, and everything under `labels` except the two
`*_history` arrays are always the *latest* computed values, not history -- there's no historical
time series of "what the 7d window looked like last week" or "who was in the stale top-10 a month
ago." If you need that, you'd compute it yourself from the raw daily snapshots (below). The two
`*_history` arrays (and `other_history`) are real day-by-day series, same as `stars`/`forks`.

## Raw source files

### `data/snapshots/<YYYY-MM-DD>.json` -- one file per day, committed by `collect.yml`

The only files with real point-in-time daily granularity for every field. One snapshot is
collected per day, targeting `2300 UTC` (see `.github/workflows/collect.yml`).

```json
{
  "date": "2026-08-31",
  "collected_at": "2026-09-01T14:30:32Z",
  "repo": {
    "stars": 1056, "forks": 121, "watchers": 13,
    "open_issues": 112, "open_prs": 107, "contributors": 43
  },
  "activity": {
    "issues_opened": 0, "issues_closed": 0,
    "prs_opened": 5, "prs_merged": 1, "prs_closed": 1,
    "commits": 1, "files_changed": 3, "additions": 26, "deletions": 2,
    "top_committers": [{"login": "mike-wendt", "commits": 1}]
  },
  "traffic": {
    "as_of_date": "2026-08-31",
    "views": 384, "unique_views": 77, "clones": 112, "unique_clones": 40,
    "top_referrers": [{"referrer": "github.com", "count": 741, "uniques": 61}],
    "top_paths": [{"path": "/sirius-db/sirius", "count": 1146, "uniques": 295}]
  },
  "labels": {
    "priority_counts": {"! - P0": {"issues": 0, "prs": 3, "color": "b60205"}, "! - P1": "...", "! - P2": "...", "! - P3": "..."},
    "other_counts": {"dependencies": {"issues": 0, "prs": 5, "color": "0366d6"}, "...": "one key per non-priority label seen today"},
    "priority_issues_stale_top10": [{"number": 727, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P2"}],
    "priority_prs_stale_top10": [{"number": 1548, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P0"}],
    "other_issues_stale_top10": [{"number": 557, "title": "...", "url": "...", "updated_at": "...", "labels": ["duckdb"]}],
    "other_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}]
  },
  "releases": []
}
```

Field semantics that aren't obvious from the shape alone:

- **`repo.*`** is a point-in-time gauge as of `collected_at` -- there's no historical API for
  these fields, so a snapshot's `repo` values can never be reconstructed for a date other than
  when it was actually collected. This is why a missed collection day is only partially
  recoverable (see `BOOTSTRAP.md` §5).
- **`activity.*`** is a same-day *delta* (issues/PRs opened/closed/merged *that day*, commits
  *that day*), not a running total. Fully reconstructable for any past date via the GitHub Search
  API and commit history, since those retain full history -- this is what `fetch_metrics.py
  --date` uses to backfill a missed day.
- **`traffic.as_of_date`** is the real key for traffic data, **not** the snapshot's own `date`.
  GitHub doesn't finish aggregating a day's traffic until after that day ends, so `as_of_date`
  normally lags `date` by under a day (collection targets `2300 UTC` specifically to keep that
  lag small). `traffic.views`/`clones`/etc. describe `as_of_date`, not `date`.
- **`traffic.top_referrers`/`top_paths`** are GitHub's own current top-10 snapshot over its
  trailing 14-day window, not a delta -- there's no "today's referrers" to sum across days.
- **`labels.*`** is a point-in-time gauge, same as `repo.*` -- and deliberately small. Every open
  issue/PR (with labels) is fetched fresh each run to compute this, but the full item list is
  never persisted, only: per-label counts, and the 10 most stale items per category (priority vs.
  other). Classification and stale ranking happen in `fetch_metrics.py`'s `fetch_label_metrics()`
  at collection time -- unlike most of this file's fields, there's no raw-vs-derived split here,
  because the raw full item list only exists transiently in memory during that one run and can
  never be reconstructed from a snapshot afterward. This is a deliberate tradeoff: storing
  ~150+ full item records (title, URL, timestamp) every day forever would be pure git bloat next
  to every other field here, which is why only bounded/aggregated data is kept. Not
  `--date`-backfillable, for the same reason `repo.*` isn't.
- **`priority_counts.*.color`/`other_counts.*.color`** is GitHub's actual hex color for that
  label (no leading `#`), captured fresh every run from the same API response -- not hardcoded,
  so it stays correct if a label's color is ever changed on GitHub. Lives on the count bucket
  itself rather than a separate structure, matching how `priority_counts` and `other_counts` are
  otherwise shaped the same way.

### `data/stars_backfill.json`, `data/forks_backfill.json` -- one-time historical seed

```json
[{"date": "2025-06-17", "stars": 2}]
[{"date": "2025-06-28", "forks": 1}]
```

Cumulative running counts reconstructed from stargazer/fork creation timestamps (see
`scripts/backfill_stars.py`/`backfill_forks.py`). Covers every day from repo creation up to
whenever the backfill was last run -- full history, not limited to a rolling window. Can include
a day that's also covered by a live snapshot; `build_site.py` dedupes by date with the live
snapshot's value winning (`merge_point_series()`).

### `data/traffic_backfill.json` -- 14-day rolling seed, mergeable/rerunnable

```json
[{"date": "2026-08-17", "views": 781, "unique_views": 45, "clones": 589, "unique_clones": 50}]
```

Real per-day counts (not the rolling-total field GitHub's API also returns) for whatever's still
inside GitHub's 14-day traffic window as of when `scripts/backfill_traffic.py` was last run.
Unlike the stars/forks backfills, this one is **not** a complete historical record -- it only
ever covers the days GitHub itself still retains. Safe to rerun any time; merges into the
existing file (keyed by date) rather than overwriting, so days already captured aren't lost as
the window slides forward. `build_site.py` merges this with live snapshot traffic the same way
as stars/forks -- live wins on an overlapping date, keyed by `as_of_date`.

### `data/activity_backfill.json` -- weekly, hand-seeded, one-time only for the pre-history

```json
[{"week_of": "2026-05-31", "commits": 56, "additions": 28777, "deletions": 18519}]
```

**Weekly, not daily** -- a different granularity than everything else in `data/`. `week_of` is
always a Sunday, matching GitHub's own Pulse bucketing convention. Only covers weeks *before*
daily collection began (currently `2026-05-31` onward); every week since is computed live from
daily snapshots by `build_site.py`'s `build_activity_weekly()`, which overrides this file's data
on any overlapping week. There's no script for extending this file -- it's a one-time manual
export from GitHub's Pulse graph (see `BOOTSTRAP.md` §7 if you need to extend it further back).

## Known limitations for historical analysis

- No historical data exists for `repo.*` fields (stars/forks/watchers/open issues/PRs/
  contributors) on any date without an actual snapshot from that day, except stars and forks
  specifically (reconstructable via the backfill scripts at any time, since they're derived from
  event timestamps rather than a point-in-time gauge).
- Traffic history beyond what's been captured in `traffic_backfill.json` + `data/snapshots/` is
  permanently gone -- GitHub's API only exposes a trailing 14-day window, full stop.
- `activity_windows` in `site/data.json` reflects only the current moment -- there's no committed
  historical record of what a given window looked like on a past date. If that's ever needed,
  it'd have to be computed from `data/snapshots/` directly (each snapshot's `activity` field is a
  real daily delta, so this is possible, just not precomputed anywhere today).
- `labels` history only exists from whenever `fetch_label_metrics()` shipped forward -- there's
  no way to reconstruct past label states retroactively (unlike stars/forks, label changes aren't
  exposed via a creation-timestamp-style API without walking each issue/PR's Timeline API
  individually, which is a real N+1 cost -- see issue #5 for the tradeoff discussion).
