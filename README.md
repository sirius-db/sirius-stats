# sirius-stats

Tracks how [sirius-db/sirius](https://github.com/sirius-db/sirius) evolves over time — stars,
forks, traffic (including referrers and popular content), day-to-day issue/PR/commit activity,
open issue/PR label trends (priority and other, with stale-item drill-down), and (eventually)
release download counts.

GitHub's own Insights tab and traffic API only retain a rolling window (traffic data is dropped
after 14 days), so anything not collected is gone permanently. This repo collects a daily
snapshot and commits it to `main`, then publishes a static site from the accumulated history at
[www.sirius-db.com/sirius-stats](https://www.sirius-db.com/sirius-stats/).

## How it works

- **`.github/workflows/collect.yml`** fires every 15 min across a `2300-0159 UTC` window (plus
  manual `workflow_dispatch`) instead of once at a fixed time -- GitHub Actions scheduled runs
  have no timing guarantee and can be delayed or dropped, so the window gives the collector
  multiple chances to succeed each day. The window starts at `2300` (not earlier) so the normal
  case -- first firing succeeds right away -- still lands close to day-end; it only extends later
  to catch a multi-hour scheduler delay. Each firing checks whether the current UTC day's
  snapshot already exists and skips if so, so only the first successful firing per day actually
  runs `scripts/fetch_metrics.py` and commits to `data/snapshots/` (see `collect.yml` for the
  gating logic in detail).
- **`.github/workflows/deploy.yml`** runs on every push to `main` and on manual
  `workflow_dispatch`. Runs `scripts/build_site.py`, publishes the result to GitHub Pages.
- **`.github/workflows/verify.yml`** runs on every PR to `main` and on manual
  `workflow_dispatch`. Runs the same two scripts end-to-end without committing or deploying, so a
  broken change fails CI before merge -- including docs-only PRs, since `verify` is a required
  status check and a path-filtered trigger would leave those permanently blocked.

## Working on this repo

See [CONTRIBUTING.md](CONTRIBUTING.md) for local dev setup, running the scripts, previewing site
changes, and customizing the UI. See [DATA.md](DATA.md) for the full schema of everything under
`data/`, including the recommended `site/data.json` entry point for historical analysis or
search. See [BOOTSTRAP.md](BOOTSTRAP.md) for one-time setup steps (backfills, secrets, branch
protection) outside the recurring workflows.
