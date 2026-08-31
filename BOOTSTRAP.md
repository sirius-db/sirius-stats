# Bootstrap

One-time setup steps for this repo. Run once by a maintainer; not part of any recurring
workflow.

## 1. Star history backfill

Daily collection (`collect.yml`) only starts capturing stars from whenever it first ran. To
show star history going back to when the repo was created, run a one-time backfill using
GitHub's own stargazers API instead of scraping a third-party site like star-history.com — the
`vnd.github.star+json` media type is documented and stable, whereas star-history.com's data
endpoint isn't a published API.

```bash
gh auth status                       # confirm you're logged in
uv run scripts/backfill_stars.py     # writes data/stars_backfill.json
```

No token needs to be minted — the script shells out to `gh api`, which uses your existing `gh`
authentication and reads public stargazer data.

Review the generated `data/stars_backfill.json`, then commit it. `build_site.py` prepends this
file to the star history series before the daily `data/snapshots/` data begins, so the site's
star chart shows continuous history.

## 2. Fork history backfill

Same idea as the star backfill: daily collection only starts capturing forks from whenever it
first ran. `GET /repos/{owner}/{repo}/forks` returns each fork's `created_at`, so a one-time
reconstruction works the same way as stars:

```bash
gh auth status                       # confirm you're logged in
uv run scripts/backfill_forks.py     # writes data/forks_backfill.json
```

Review the generated `data/forks_backfill.json`, then commit it. `build_site.py` prepends this
file to the fork history series, same as stars.

One caveat: this reconstruction is a cumulative running count of forks *ever created* — it can't
detect a fork being deleted afterward, so the final backfilled number can end up slightly higher
than the live `forks_count` from the repo API (observed once: backfill said 121, live said 120).
That's expected, not a bug — it means one fork existed at some point and was later removed.

## 3. Traffic token secret

GitHub's traffic endpoints (`/traffic/views`, `/traffic/clones`) require push access to
`sirius-db/sirius`, so they need a personal access token, not just an unauthenticated call:

1. Create a fine-grained PAT scoped to `sirius-db/sirius` with **Administration: read** (traffic
   stats live under repo administration) — or a classic PAT with `repo` scope if fine-grained
   access to org repos isn't available.
2. Add it as a repo secret in `sirius-stats` named `SIRIUS_TRAFFIC_TOKEN`
   (Settings → Secrets and variables → Actions → New repository secret).

Until this secret exists, `fetch_metrics.py` skips traffic collection gracefully — every
snapshot's `traffic` fields stay `null` and the site's traffic chart is omitted.

## 4. Traffic history backfill

`/traffic/views` and `/traffic/clones` always return a 14-day daily breakdown, but the recurring
`fetch_metrics.py` only keeps the latest complete day from each call (see `latest_complete_day()`
in that script) to match the daily-snapshot model. Run this once, after the traffic token secret
above exists, to capture the other 13 days GitHub still has on hand before they age out:

```bash
export SIRIUS_TRAFFIC_TOKEN=...        # same token as the repo secret above
uv run scripts/backfill_traffic.py     # writes data/traffic_backfill.json
```

Review and commit the generated file. `build_site.py` merges it into the traffic time series,
with live-collected days taking precedence over backfilled ones on any overlapping date.

## 5. Historical weekly activity seed

Daily issue/PR/commit activity tracking only goes back to whenever `collect.yml` first ran.
`data/activity_backfill.json` is a one-time, manually-seeded array of `{week_of, commits,
additions, deletions}` covering the weeks *before* that, sourced from a one-time export of
GitHub's Pulse graph for `sirius-db/sirius` (Insights → Pulse, or the weekly CSV downloads on
that page). Weeks start on Sunday, matching GitHub's own Pulse bucketing.

This file only needs to be seeded once. `build_site.py`'s `build_activity_weekly()` computes
every subsequent week directly from the daily `data/snapshots/` history (summing each day's
`activity.commits`/`additions`/`deletions` into the Sunday-starting week it falls in), and that
computed data always overrides the static seed on any overlapping week. So the "historical
weekly activity" chart keeps extending on its own from daily collection going forward — there's
no need to re-export Pulse or hand-edit this file again unless you want to extend the seeded
history further back than `2026-05-31`.
