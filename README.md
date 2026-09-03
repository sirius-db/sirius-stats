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

- **`.github/workflows/collect.yml`** runs once daily at `0030 UTC` (plus manual
  `workflow_dispatch`) and never collects the current, still-in-progress day -- it only ever
  finalizes fully-elapsed days. Each firing scans the last 7 days for every currently-missing
  snapshot (not just the most recent) and collects all of them in one run, so a backlog from a
  missed/delayed firing actually closes instead of the pipeline staying permanently behind.
  `scripts/refresh_traffic.py` also runs every firing to keep already-collected snapshots' traffic
  fields in sync with GitHub's own rolling 14-day breakdown, which can lag or later revise a day's
  numbers. Both are committed together in a single commit -- see `collect.yml` for the exact
  gating logic and `BOOTSTRAP.md` §5 for manually recovering a day that's aged out of the 7-day
  catch-up window.
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
