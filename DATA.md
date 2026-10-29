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
    "untriaged_history": [{"date": "...", "issues": 0, "prs": 0}],
    "untriaged_current": {"issues": 0, "prs": 0},
    "priority_issues_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P1"}],
    "priority_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P1"}],
    "other_issues_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}],
    "other_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}],
    "all_labels_current": {"bug": 0, "...": "every label -> current open count, sorted descending"},
    "label_colors": {"! - P0": "b60205", "bug": "d73a4a", "...": "every label -> GitHub's real hex color, no #"}
  },
  "review_weekly": [{"week_of": "...", "pr_count": 0, "zero_review_count": 0, "zero_review_rate": 0.0, "median_first_review_hours": 0.0, "p90_first_review_hours": null, "p95_first_review_hours": null}],
  "review_percentile_windows": {"1": {"p50": 0.0, "p90": null, "p95": null}, "4": "...", "13": "...", "26": "..."},
  "pr_size_vs_latency": [{"number": 0, "size": 0, "first_review_latency_hours": 0.0}],
  "review_current": {
    "pending_reviews_by_team": {"sirius-core": [{"number": 0, "title": "...", "url": "..."}]},
    "draft_pr_count": 0, "idle_prs": [{"number": 0, "title": "...", "url": "..."}],
    "zero_review_prs": [{"number": 0, "title": "...", "url": "..."}], "in_review_count": 0
  },
  "review_team_history": [{"date": "...", "sirius-core": 0, "...": "one key per team ever seen"}],
  "pr_health_history": [{"date": "...", "draft": 0, "idle": 0, "zero_review": 0, "in_review": 0}]
}
```

`activity_windows`, `top_referrers`/`top_paths`, `review_current`, and everything under `labels`
except the `*_history` arrays are always the *latest* computed values, not history -- there's no
historical time series of "what the 7d window looked like last week" or "who was in the stale
top-10 a month ago." If you need that, you'd compute it yourself from the raw daily snapshots
(below). The `*_history` arrays (`priority_issues_history`, `priority_prs_history`,
`other_history`, `untriaged_history`, `review_team_history`, `pr_health_history`) are real
day-by-day series, same as `stars`/`forks`. `review_weekly` and `review_percentile_windows` are
real weekly series too, just weekly-grained rather than daily (same as `activity_weekly`).
`pr_size_vs_latency` is pooled across the repo's entire PR history (backfill + live, deduped by
PR number), not a time series at all -- it's scatter-chart data, one point per reviewed PR ever.

## Raw source files

### `data/snapshots/<YYYY-MM-DD>.json` -- one file per day, committed by `collect.yml`

The only files with real point-in-time daily granularity for every field. `collect.yml` runs
once daily and never collects the current, still-in-progress day -- it only finalizes
fully-elapsed days, catching up every day missing within the last 7 days in one run so a
backlog from a missed firing actually closes (see `.github/workflows/collect.yml`).

```json
{
  "date": "2026-08-31",
  "collected_at": "2026-09-01T14:30:32Z",
  "trigger": "schedule",
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
    "untriaged_counts": {"issues": 24, "prs": 104},
    "priority_issues_stale_top10": [{"number": 727, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P2"}],
    "priority_prs_stale_top10": [{"number": 1548, "title": "...", "url": "...", "updated_at": "...", "priority_label": "! - P0"}],
    "other_issues_stale_top10": [{"number": 557, "title": "...", "url": "...", "updated_at": "...", "labels": ["duckdb"]}],
    "other_prs_stale_top10": [{"number": 0, "title": "...", "url": "...", "updated_at": "...", "labels": ["..."]}]
  },
  "reviews": {
    "first_review_latencies_hours": [1.53, 11.96],
    "zero_review_nondraft_count": 2,
    "nondraft_touched_count": 9,
    "pr_sizes_vs_latency": [{"number": 1965, "size": 42, "first_review_latency_hours": 1.53}],
    "pending_reviews_by_team": {"sirius-core": [{"number": 2201, "title": "...", "url": "..."}]},
    "draft_pr_count": 11,
    "idle_prs": [{"number": 1877, "title": "...", "url": "..."}],
    "zero_review_prs": [{"number": 2348, "title": "...", "url": "..."}],
    "in_review_count": 37
  },
  "releases": []
}
```

Field semantics that aren't obvious from the shape alone:

- **`trigger`** records how this snapshot was invoked: `"schedule"` (the real `collect.yml` cron
  firing), `"workflow_dispatch"` (a manual run of that workflow), or `"manual"` (a bare local run
  of `fetch_metrics.py` with no `--trigger` flag -- e.g. generated and committed by hand). Used by
  `collect.yml`'s Gate step to decide whether an existing day's file is still eligible to be
  superseded: a file tagged `"schedule"`, or one with no `trigger` field at all (every snapshot
  collected before this field existed), is trusted and left alone; anything else is fair game for
  the next scheduled firing to quietly redo. **Protect-by-default, not supersede-by-default** --
  treating a missing field as untrusted would make every pre-existing snapshot in the 7-day
  catch-up window eligible for overwrite on the very next firing, silently destroying point-in-time
  fields (`repo.*`, `labels.*`, `releases`, `reviews`' non-day-scoped fields) that can never be
  reconstructed for a past date once lost.
- **`repo.*`** is a point-in-time gauge as of `collected_at` -- there's no historical API for
  these fields, so a snapshot's `repo` values can never be reconstructed for a date other than
  when it was actually collected. This is why a missed collection day is only partially
  recoverable (see `BOOTSTRAP.md` §5).
- **`activity.*`** is a same-day *delta* (issues/PRs opened/closed/merged *that day*, commits
  *that day*), not a running total. Fully reconstructable for any past date via the GitHub Search
  API and commit history, since those retain full history -- this is what `fetch_metrics.py
  --date` uses to backfill a missed day.
- **`traffic.as_of_date`** is the real key for traffic data, **not** the snapshot's own `date`.
  GitHub's traffic aggregation can lag its rolling window by more than a day, so a snapshot can
  be written with `as_of_date: null` (and `views`/`clones` at `0`) if GitHub hasn't published
  that day yet. `scripts/refresh_traffic.py` patches the file in place with the real values on a
  later `collect.yml` run, and keeps re-checking every date still within GitHub's 14-day
  breakdown (not just once) since GitHub can also revise a day's numbers after first publishing
  them. `traffic.views`/`clones`/etc. describe `as_of_date`, not `date`.
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
- **`untriaged_counts`** counts open issues/PRs with zero labels -- items every other `labels.*`
  field silently excludes, since they only classify items that *have* a priority or other label.
  Same point-in-time-forward-only treatment as the rest of `labels.*`.
- **`reviews.*` is two different things stored side by side.** `first_review_latencies_hours`,
  `zero_review_nondraft_count`, `nondraft_touched_count`, and `pr_sizes_vs_latency` are day-scoped
  (only PRs *first-reviewed* that specific day, or touched that day with no review yet) --
  reconstructable for any past date via `fetch_metrics.py --date`, same as `activity.*`.
  `pending_reviews_by_team`, `draft_pr_count`, `idle_prs`, `zero_review_prs`, and
  `in_review_count` are point-in-time gauges over currently-open PRs, same limitation as
  `repo.*` -- a `--date`-backfilled snapshot's values for these five fields reflect whenever the
  backfill was actually run, not the target date. See `fetch_review_metrics()`'s docstring in
  `fetch_metrics.py` for the two-GraphQL-pass split this comes from. Every open PR is classified
  into exactly one of idle/zero-review/in-review (idle takes priority on overlap), so those three
  always sum to the non-draft open PR count with no double-counting.

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

### `data/review_backfill.json` -- weekly, one-time historical seed, pre-aggregated

```json
[{
  "week_of": "2024-12-22",
  "pr_count": 3,
  "zero_review_count": 1,
  "median_first_review_hours": 4.25,
  "first_review_latencies_hours": [1.53, 7.0],
  "pr_sizes_vs_latency": [{"number": 1, "size": 12, "first_review_latency_hours": 1.53}],
  "draft_pr_count": null,
  "idle_pr_count": null
}]
```

**Weekly, not daily** -- same granularity exception as `activity_backfill.json`. Built by
`scripts/backfill_reviews.py` from every PR in the repo's full history (~1,750 as of this
writing), fetched via independent per-calendar-month GraphQL `search` queries run concurrently
and cached to `/tmp` so a failed run only re-fetches the months that failed (see the script's own
docstring for why -- a single long cursor-walk over the full history hit repeated `502`s from
GitHub's API partway through). Non-draft PRs only, matching `fetch_review_metrics()`'s live
scope. `draft_pr_count`/`idle_pr_count` are always `null` here -- they're point-in-time gauges
("was this PR a draft as of week X"), not reconstructable from a PR's current state, same
reasoning as `repo.*`/`labels.*` not being `--date`-backfillable. `build_review_weekly()` in
`build_site.py` merges this with live-collected weeks, live winning on any overlapping week.
`pending_reviews_by_team` has no backfill at all (not even a null placeholder) -- it's entirely
point-in-time-forward-only, same as `labels.*`.

## Known limitations for historical analysis

- No historical data exists for `repo.*` fields (stars/forks/watchers/open issues/PRs/
  contributors) on any date without an actual snapshot from that day, except stars and forks
  specifically (reconstructable via the backfill scripts at any time, since they're derived from
  event timestamps rather than a point-in-time gauge). This includes `collect.yml`'s own
  multi-day catch-up: if it falls behind and recovers several missing days in one firing,
  `repo.*` and `labels.*` on every one of those days will reflect the collection moment's
  current values, not that day's real ones -- only `activity` and `traffic` are genuinely
  accurate for each backfilled day.
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
- `reviews.pending_reviews_by_team`/`draft_pr_count`/`idle_prs`/`zero_review_prs`/
  `in_review_count` only exist from whenever `fetch_review_metrics()` shipped forward, same as
  `labels.*` -- these are point-in-time gauges with no historical API, so `data/review_backfill.json`
  stores `null` for the two of these it tracks (`draft_pr_count`/`idle_pr_count`) rather than a
  reconstructed value. `reviews.first_review_latencies_hours`/`zero_review_nondraft_count`/
  `pr_sizes_vs_latency` don't have this limitation -- they're fully backfilled across the repo's
  entire PR history in `data/review_backfill.json`.
