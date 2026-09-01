# sirius-stats

Tracks how [sirius-db/sirius](https://github.com/sirius-db/sirius) evolves over time — stars,
forks, traffic (including referrers and popular content), day-to-day issue/PR/commit activity,
and (eventually) release download counts.

GitHub's own Insights tab and traffic API only retain a rolling window (traffic data is dropped
after 14 days), so anything not collected is gone permanently. This repo collects a daily
snapshot and commits it to `main`, then publishes a static site from the accumulated history.

## How it works

- **`.github/workflows/collect.yml`** runs daily at `2330 UTC`, not `0000`, for two reasons: (1)
  GitHub Actions scheduled runs can start late (documented queue delay/jitter), so `0000` risked
  slipping into the next calendar day — `2330` leaves buffer so the run still lands within the
  intended day; (2) global-team neutrality across India/Europe working hours. It also runs on
  manual `workflow_dispatch`. It runs `scripts/fetch_metrics.py` and commits any new snapshot to
  `data/snapshots/`.
- **`.github/workflows/deploy.yml`** runs on every push to `main` and on manual
  `workflow_dispatch`. It runs `scripts/build_site.py` to produce `site/`, then publishes it via
  the GitHub Pages artifact-based deploy actions.
- **`.github/workflows/verify.yml`** runs on PRs to `main` that touch the pipeline (`scripts/**`,
  `templates/**`, `static/**`, `pyproject.toml`, `uv.lock`, `.github/workflows/**`) and on manual
  `workflow_dispatch`. It runs `scripts/fetch_metrics.py` then `scripts/build_site.py`, without
  making a commit, so a broken change fails CI before merge. `verify` is a required check to
  merge to `main`.
  - **NOTE:** This does run on PRs from forks, but repo secrets (`SIRIUS_TRAFFIC_TOKEN`) aren't
    exposed to them, so a fork PR only gets partial coverage (no traffic collection). Push
    branches to `origin` directly, not a fork, for full verification coverage before merging.

## Dependencies

Managed with [`uv`](https://docs.astral.sh/uv/) — install it once
(`curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`), then `uv run` handles
creating the virtualenv and installing pinned dependencies (from `uv.lock`) automatically, no
separate install step needed. `uv` was chosen over `pixi` (which sirius itself uses) because
`pixi` is for resolving conda-forge/native packages (CUDA, C++ toolchains) that sirius needs and
this repo doesn't — `sirius-stats` is pure Python with one dependency (`jinja2`), which is
exactly what `uv` is for.

## Running locally

```bash
uv run scripts/fetch_metrics.py   # writes data/snapshots/<today>.json
uv run scripts/build_site.py      # writes site/index.html and site/data.json
```

`fetch_metrics.py` collects repo stats (stars, forks, watchers, open issues/PRs, contributors),
same-day activity deltas (issues/PRs opened/closed/merged, commits, files changed,
additions/deletions, top committers), and release download counts — all unauthenticated, though
the activity deltas use the GitHub Search API which has a lower unauthenticated rate limit, so
setting `SIRIUS_TRAFFIC_TOKEN` (see below) speeds this up too even though it's not required for
activity.

Traffic stats (`views`/`clones`/top referrers/popular content) require a `SIRIUS_TRAFFIC_TOKEN`
env var with push access to `sirius-db/sirius` — see [BOOTSTRAP.md](BOOTSTRAP.md). Without it,
traffic fields in the snapshot stay `null` and the traffic chart/tables on the site are omitted.

`traffic.views`/`clones` come from the most recent *complete* day in GitHub's own daily
breakdown, recorded as `traffic.as_of_date` — not the snapshot's own `date`. GitHub doesn't
finish aggregating a day's traffic until sometime after that day ends, so `as_of_date` normally
lags `date` by under a day (collection runs at `2330 UTC` specifically to keep that lag small).

`build_site.py` rolls up each day's activity deltas into 24h/3d/7d/1mo windows by summing the
trailing N daily snapshots — there's no separate query per window, so a missed collection day
just means one fewer data point in that window rather than a gap.

## Previewing site changes before merging

The fastest way to iterate on chart layout, colors, or the page shell is entirely local:

```bash
uv run scripts/build_site.py
cd site && python3 -m http.server 8000   # then open http://localhost:8000
```

Opening `site/index.html` directly as a `file://` URL doesn't work — the page's
`fetch('data.json')` call gets blocked by the browser's CORS policy for local files (browsers
treat `file://` as an opaque origin with no access to fetch other local files). Serving `site/`
over a local HTTP server sidesteps that; `python3 -m http.server` needs no extra dependencies.

No deploy and no merge to `main` is needed to see the result — do this on your PR branch.

## Customizing the UI

`build_site.py` renders the page from Jinja2 templates rather than building HTML in Python
strings, so most visual changes don't touch any `.py` file:

- **CSS/colors** — edit `static/style.css` directly. Chart colors are CSS custom properties
  (`--color-stars`, `--color-forks`, `--color-views`, `--color-clones` in `:root`) that the
  page's JS reads at render time, so changing a chart's color is a one-line CSS edit.
- **Logo** — drop a `logo.svg` or `logo.png` into `static/`; `build_site.py` picks up whichever
  exists automatically and adds it to the header. No file means no logo, no template change
  needed either way.
- **Page structure** — `templates/base.html` holds the shared shell (head, header, CSS link);
  `templates/index.html` extends it with the actual charts/tables. Adding a new page later means
  a new template extending `base.html`, not a new Python string.

## One-time setup

See [BOOTSTRAP.md](BOOTSTRAP.md) for the star-history backfill, the traffic token secret, the
traffic history backfill, and the historical weekly activity seed — all one-time setup steps
outside the recurring workflows.

## Data model

See [DATA.md](DATA.md) for the full schema of everything under `data/`, the merge rules
`build_site.py` applies to combine them, and the recommended entry point (`site/data.json`) for
any historical analysis or search over the collected data.
