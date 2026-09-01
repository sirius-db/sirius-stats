# sirius-stats — agent operating notes

Tracks `sirius-db/sirius`'s stars, forks, traffic, activity, and issue/PR label trends over time
via daily GitHub Actions collection, publishing a static site to GitHub Pages. See `README.md`
for what this is, `CONTRIBUTING.md` for the dev workflow, `DATA.md` for the data model,
`BOOTSTRAP.md` for one-time setup. This file is operating rules only — don't duplicate their
content here.

## Non-negotiable rules

- **Push branches to `origin` directly, never a fork.** Repo secrets (`SIRIUS_TRAFFIC_TOKEN`,
  `COLLECT_PUSH_TOKEN`) aren't exposed to fork-triggered workflow runs — a fork PR silently gets
  partial `verify` check coverage (no traffic collection tested), which already caused PR #1 to
  be abandoned and redone as #2 from a same-repo branch.
- **Commit messages are Conventional Commits** (`type(scope): description`, lowercase type,
  imperative). This is a `sirius-db` org (home-org) repo.
- **Merges are squash-only** — matches `sirius-db/sirius`'s own convention. Keep PRs scoped to
  one coherent concern; a squash commit collapses the whole PR into one commit on `main`, so a
  tightly-scoped PR keeps that commit meaningful for future `git blame`.
- **`verify` is a required status check on `main`** (classic branch protection, not rulesets —
  see `BOOTSTRAP.md` §6 for why and the exact config). It runs `fetch_metrics.py` and
  `build_site.py` end-to-end on every PR to `main` (no path filter — one blocked docs-only PRs
  permanently, since the check never ran to satisfy the requirement), without committing or
  deploying.

## Core dev loop

```bash
uv run scripts/fetch_metrics.py   # writes data/snapshots/<today>.json
uv run scripts/build_site.py      # writes site/index.html, site/labels.html, and site/data.json
cd site && python3 -m http.server 8000   # preview locally -- file:// URLs don't work (CORS)
```

`site/` is `.gitignore`'d build output — never commit anything under it. Regenerate it locally
to verify a change instead of looking for it in the repo.

## Before considering a change done

1. Run `uv run scripts/build_site.py` and confirm it exits cleanly.
2. If the change touches `fetch_metrics.py`, run it for real (with `SIRIUS_TRAFFIC_TOKEN` set if
   touching traffic code) and inspect the actual output JSON — don't assume correctness from
   reading the diff alone. This repo has a history of subtle data-shape bugs (duplicate points at
   backfill/snapshot boundaries, dropped fields on merge, stale docstrings) that only surfaced by
   actually running the pipeline and checking output.
3. If the change touches `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `BOOTSTRAP.md`, or
   `DATA.md`, check the other four for now-stale or now-contradictory statements — this repo has
   had a real instance of two docs directly contradicting each other after an edit to only one.
4. Never commit or push without explicit instruction in that message — this repo follows the
   same read-only-by-default posture as the user's global instructions.
