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
with live-collected days taking precedence over backfilled ones on any overlapping date. Safe to
rerun any time (e.g. to catch up after a missed `collect.yml` run) — it merges into the existing
file rather than overwriting it, so a day already captured isn't lost just because it's since
rolled out of GitHub's 14-day window.

## 5. Recovering a missed collection day

If `collect.yml` doesn't run on some day (e.g. it was stuck behind an unapproved fork-PR check),
that day isn't necessarily lost. Two commands, run after the fact, recover most of it:

```bash
export SIRIUS_TRAFFIC_TOKEN=...                          # same token as above
uv run scripts/backfill_traffic.py                       # re-catches traffic if still in the 14-day window
uv run scripts/fetch_metrics.py --date 2026-08-31         # backfills that day's activity + traffic
```

What's actually recoverable for a missed day, and why:

- **`activity`** (issues/PRs opened/closed/merged, commits, additions/deletions) — fully
  recoverable. It comes from GitHub's Search API and commit history, both queryable for any past
  date, not just "today" — `--date` just points the same queries at a specific day instead.
- **`traffic`** — recoverable as long as the day is still within GitHub's rolling 14-day window
  at the time you run the backfill.
- **`repo`** (stars, forks, watchers, open issues/PRs, contributors) and **`releases`** — **not**
  recoverable for the missed day specifically. These are point-in-time gauges with no historical
  API, so a `--date`-backfilled snapshot's `repo`/`releases` fields reflect whatever they are
  *when you run the backfill*, not what they were on the missed day. `stars` and `forks` are the
  one exception — `backfill_stars.py`/`backfill_forks.py` reconstruct those from event creation
  timestamps regardless of when you run them, so rerunning those two also repairs this gap for
  stars/forks specifically.

## 6. Branch protection on `main`

`main` uses **classic branch protection** (Settings → Branches → Branch protection rules in the
GitHub UI, or `gh api repos/sirius-db/sirius-stats/branches/main/protection`) — matching the
convention `sirius-db/sirius` itself uses, rather than the newer rulesets system. Configured via
`PUT /repos/{owner}/{repo}/branches/main/protection` with:

- **Required pull request reviews** — a PR is required before merging, with
  `required_approving_review_count: 0` (no minimum approvals enforced; this repo has one active
  reviewer, so requiring self-approval added no real protection).
- **Required status checks** — the `verify` check (from `.github/workflows/verify.yml`'s `verify`
  job) must pass. `strict: false` (the branch doesn't need to be re-synced with `main` before
  merging).
- **`enforce_admins: false`** — repository admins can push directly to `main`, bypassing the PR
  requirement. This is classic protection's only bypass mechanism (unlike rulesets, there's no
  per-user bypass list) — it's what lets the PAT-authenticated automated push through, at the
  cost of applying to every admin, not just the PAT's owner specifically.
- **`allow_force_pushes: false`**, **`allow_deletions: false`** — force pushes and branch
  deletion are blocked.

Merge method is enforced separately, at the **repository** level, not in branch protection at
all — classic branch protection has no merge-method setting (`allowed_merge_methods` is a
rulesets-only feature). `sirius-stats` has `allow_squash_merge: true`, `allow_merge_commit:
false`, `allow_rebase_merge: false` (Settings → General → Pull Requests), enforcing squash-only.

### Push token for the automated collection commit

Once `main` requires a pull request, `collect.yml`'s daily automated commit can no longer push
using the default `GITHUB_TOKEN` — that push would be rejected the same as any other direct
push. It needs a personal access token belonging to a repository admin instead, since
`enforce_admins: false` is what lets that push bypass the PR requirement:

1. Create a fine-grained PAT scoped to `sirius-db/sirius-stats` only (a different repo/purpose
   than `SIRIUS_TRAFFIC_TOKEN`, which targets `sirius-db/sirius`) with **Contents: Read and
   write**, owned by a repository admin account.
2. Add it as a repo secret in `sirius-stats` named `COLLECT_PUSH_TOKEN`.

`collect.yml` passes this token to `actions/checkout`, which configures the git remote's
credentials with it, so the later `git push` in the "Commit snapshot" step authenticates as the
PAT's owner automatically.

**Known tradeoff**: since classic protection's only bypass mechanism is the blanket
`enforce_admins` toggle, *any* repository admin (not just the PAT's owner) can push directly to
`main`, bypassing the PR requirement for their own changes too — there's no way to scope the
bypass to only the automated push. Rotate the PAT by generating a new one (owned by any
repository admin) and updating the secret.

## 7. Historical weekly activity seed

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
