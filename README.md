# sirius-stats

Tracks how [sirius-db/sirius](https://github.com/sirius-db/sirius) evolves over time — stars,
forks, traffic (including referrers and popular content), day-to-day issue/PR/commit activity,
and (eventually) release download counts.

GitHub's own Insights tab and traffic API only retain a rolling window (traffic data is dropped
after 14 days), so anything not collected is gone permanently. This repo collects a daily
snapshot and commits it to `main`, then publishes a static site from the accumulated history at
[www.sirius-db.com/sirius-stats](https://www.sirius-db.com/sirius-stats/).

## How it works

- **`.github/workflows/collect.yml`** runs daily at `2330 UTC` and on manual `workflow_dispatch`.
  Runs `scripts/fetch_metrics.py`, commits any new snapshot to `data/snapshots/`.
- **`.github/workflows/deploy.yml`** runs on every push to `main` and on manual
  `workflow_dispatch`. Runs `scripts/build_site.py`, publishes the result to GitHub Pages.
- **`.github/workflows/verify.yml`** runs on PRs touching the pipeline and on manual
  `workflow_dispatch`. Runs the same two scripts end-to-end without committing or deploying, so a
  broken change fails CI before merge.

## Working on this repo

See [CONTRIBUTING.md](CONTRIBUTING.md) for local dev setup, running the scripts, previewing site
changes, and customizing the UI. See [DATA.md](DATA.md) for the full schema of everything under
`data/`. See [BOOTSTRAP.md](BOOTSTRAP.md) for one-time setup steps (backfills, secrets, branch
protection) outside the recurring workflows.
