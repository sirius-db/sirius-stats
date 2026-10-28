#!/usr/bin/env python3
"""One-time historical backfill of review-health metrics.

Fetches every PR in sirius-db/sirius via GraphQL, split into independent per-calendar-month
search queries (not one long cursor-walk across the whole history -- see _all_prs()), and writes
pre-aggregated weekly rows to data/review_backfill.json -- same convention as
activity_backfill.json: a static, hand-generated-once seed that build_review_weekly()
merges with live snapshots, live data winning on any overlapping week. See BOOTSTRAP.md
for the one-time-run instructions and the GraphQL rate-limit math this relies on
(~1 point per 50-PR batch; confirmed live against the real API during planning).

Month-chunked and run concurrently (max 4 at once) specifically because a single long
cursor-walk at larger batch sizes hit repeated 502s from GitHub's API partway through (confirmed
live: the same PR range succeeds reliably at a smaller batch size, so it's a query-cost/timeout
issue on GitHub's end, not bad data). Each month is cached to /tmp on success, so a failure in
one month doesn't lose progress on the others -- just re-run the script.

Not run by any workflow -- run manually once:
    SIRIUS_TRAFFIC_TOKEN=<token> uv run scripts/backfill_reviews.py

draft_pr_count/idle_pr_count are NOT backfillable here -- they're point-in-time gauges
("was this PR a draft as of week X") that aren't reconstructable from a PR's current
state, same reasoning DATA.md gives for why `repo.*`/`labels.*` aren't --date-backfillable
in fetch_metrics.py. Every backfilled week writes these as null; build_review_weekly()'s
live-overrides-backfill merge fills them in once real daily collection reaches that week.

Deliberately self-contained (duplicates REPO/graphql_query rather than importing
fetch_metrics.py) to match this repo's existing backfill-script convention -- see
backfill_traffic.py, which does the same for api_get. _dates.py is the one deliberate
exception (see its own docstring).
"""

import calendar
import concurrent.futures
import json
import os
import shutil
import statistics
import urllib.request
from datetime import date, datetime
from pathlib import Path

from _dates import week_start

REPO = "sirius-db/sirius"
API_ROOT = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "review_backfill.json"
# Pure scratch cache for resuming an interrupted backfill run -- never committed, deleted on a
# fully successful run. /tmp, not under the repo, so there's no risk of it ever being added to
# git even by accident.
_CHUNK_CACHE_DIR = Path("/tmp/sirius-stats-backfill-chunks")

_BACKFILL_PR_FIELDS = """
      number
      isDraft
      createdAt
      mergedAt
      closedAt
      additions
      deletions
      reviews(first: 1) { totalCount nodes { submittedAt } }
      timelineItems(itemTypes: [READY_FOR_REVIEW_EVENT], first: 1) {
        nodes { ... on ReadyForReviewEvent { createdAt } }
      }
"""

_GRAPHQL_SEARCH_PRS = (
    """
query($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: ISSUE, first: 50, after: $cursor) {
    nodes {
      ... on PullRequest {
"""
    + _BACKFILL_PR_FIELDS
    + """
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""
)


def graphql_query(query, variables, token):
    """Same shape as fetch_metrics.py's graphql_query() -- duplicated, not imported, per this
    file's own docstring on the self-contained-script convention."""
    headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json"}
    headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}/graphql", data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(request) as response:
        result = json.loads(response.read())
    if "errors" in result:
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result["data"]


def _search_prs(search_query, token):
    """Page through one search query's results. Each chunk's pagination is independent of every
    other chunk's (unlike repository.pullRequests' single shared cursor across all ~1750 PRs),
    which is what makes chunk-level concurrency and caching possible below.
    """
    prs = []
    cursor = None
    while True:
        data = graphql_query(_GRAPHQL_SEARCH_PRS, {"searchQuery": search_query, "cursor": cursor}, token)
        page = data["search"]
        prs.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return prs


def _month_chunks(start, end):
    """Calendar-month (first_day, last_day) pairs from `start` through `end`, inclusive."""
    chunks = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last_day = calendar.monthrange(year, month)[1]
        chunks.append((date(year, month, 1), date(year, month, last_day)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return chunks


def _fetch_chunk(chunk_start, chunk_end, token):
    """One month's PRs, cached to disk on success. A re-run after a failure skips every chunk
    that already succeeded and only re-fetches the ones that didn't -- that's the actual fix for
    "a failure shouldn't lose much progress," not just smaller batches on their own.
    """
    cache_file = _CHUNK_CACHE_DIR / f"{chunk_start.isoformat()}.json"
    if cache_file.exists():
        print(f"  [{chunk_start}..{chunk_end}] using cached result")
        return json.loads(cache_file.read_text())

    search_query = f"repo:{REPO} is:pr created:{chunk_start.isoformat()}..{chunk_end.isoformat()}"
    prs = _search_prs(search_query, token)
    _CHUNK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(prs))
    print(f"  [{chunk_start}..{chunk_end}] fetched {len(prs)} PRs")
    return prs


def _all_prs(token):
    """Fetches every PR, chunked by calendar month and run concurrently (max 4 at once -- modest,
    to stay well clear of GitHub's secondary rate limits for a PAT). Replaces a single long
    cursor-walk across the whole history (what originally hit repeated 502s from GitHub's API
    around PR 600-700, confirmed live to be a batch-size/query-cost issue, not bad data) with
    independent per-month queries that can fail and be retried individually.
    """
    # The project's actual first PR was created 2024-12-26; starting the chunk range a few weeks
    # earlier is harmless (that chunk just comes back empty) and avoids hardcoding the exact date.
    chunks = _month_chunks(date(2024, 12, 1), date.today())

    all_prs = []
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_fetch_chunk, chunk_start, chunk_end, token): (chunk_start, chunk_end)
            for chunk_start, chunk_end in chunks
        }
        for future in concurrent.futures.as_completed(futures):
            chunk_start, chunk_end = futures[future]
            try:
                all_prs.extend(future.result())
            except Exception as exc:
                print(f"  [{chunk_start}..{chunk_end}] FAILED: {exc}")
                failed.append((chunk_start, chunk_end))

    if failed:
        raise SystemExit(
            f"{len(failed)} of {len(chunks)} month(s) failed: "
            f"{[c.isoformat() for c, _ in failed]}. Successful months are cached under "
            f"{_CHUNK_CACHE_DIR} -- just re-run the script; it will skip every cached month and "
            f"only retry the ones that failed."
        )
    return all_prs


def _bucket_date(pr):
    """Date a PR contributes to: first-review date if reviewed (bucketed by week_start() of
    that date), else the PR's terminal date (merged, else closed, else -- for the rare
    still-open, never-reviewed PR -- createdAt) -- a never-reviewed PR has no first-review date
    to bucket by, and its terminal date is the closest equivalent to the daily collector's
    "touched" signal that a one-time historical pass can reconstruct.
    """
    review_nodes = pr["reviews"]["nodes"]
    if review_nodes:
        return review_nodes[0]["submittedAt"][:10]
    return (pr["mergedAt"] or pr["closedAt"] or pr["createdAt"])[:10]


def _first_review_latency_hours(pr):
    """Same shape as fetch_metrics.py's version -- duplicated, not imported, per this file's own
    docstring on the self-contained-script convention. createdAt is always a safe lower bound (a
    review can't predate PR creation); the ready-for-review event is only used as the baseline
    when it's actually before the first review, since a review (often COMMENTED) can land while
    the PR is still in draft, before any ReadyForReviewEvent exists -- using that event anyway
    would make the baseline later than the review it's supposed to precede, producing a negative
    latency.
    """
    review_nodes = pr["reviews"]["nodes"]
    if not review_nodes:
        return None
    first_review_dt = datetime.fromisoformat(review_nodes[0]["submittedAt"].replace("Z", "+00:00"))
    baseline_dt = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
    ready_nodes = pr["timelineItems"]["nodes"]
    if ready_nodes:
        ready_dt = datetime.fromisoformat(ready_nodes[0]["createdAt"].replace("Z", "+00:00"))
        if ready_dt <= first_review_dt:
            baseline_dt = ready_dt
    return (first_review_dt - baseline_dt).total_seconds() / 3600


def main():
    token = os.environ.get("SIRIUS_TRAFFIC_TOKEN")
    if not token:
        raise SystemExit("SIRIUS_TRAFFIC_TOKEN must be set -- see BOOTSTRAP.md")

    print("Fetching all PRs via GraphQL (one-time backfill, ~1 point per 50-PR batch)...")
    prs = _all_prs(token)
    print(f"Fetched {len(prs)} PRs total.")
    # Only reached on full success (_all_prs raises if any month failed) -- the cache has done
    # its job for this run, so there's nothing left worth keeping it around for.
    shutil.rmtree(_CHUNK_CACHE_DIR, ignore_errors=True)

    # Non-draft only, matching fetch_review_metrics()'s live scope (nondraft_touched_count /
    # zero_review_nondraft_count) so backfilled and live weeks merge on a consistent definition.
    buckets = {}
    for pr in prs:
        if pr["isDraft"]:
            continue
        week_of = week_start(date.fromisoformat(_bucket_date(pr))).isoformat()
        bucket = buckets.setdefault(
            week_of, {"latencies": [], "zero_review_count": 0, "pr_count": 0, "pr_sizes": []}
        )
        bucket["pr_count"] += 1
        latency = _first_review_latency_hours(pr)
        if latency is None:
            bucket["zero_review_count"] += 1
        else:
            latency = round(latency, 2)
            bucket["latencies"].append(latency)
            # number carried through so build_site.py can dedupe against live-collected points
            # for the same PR (one point per PR, not one per source) when pooling for the
            # size-vs-latency scatter chart.
            bucket["pr_sizes"].append(
                {
                    "number": pr["number"],
                    "size": pr["additions"] + pr["deletions"],
                    "first_review_latency_hours": latency,
                }
            )

    rows = []
    for week_of in sorted(buckets):
        b = buckets[week_of]
        rows.append(
            {
                "week_of": week_of,
                "pr_count": b["pr_count"],
                "zero_review_count": b["zero_review_count"],
                "median_first_review_hours": (
                    round(statistics.median(b["latencies"]), 2) if b["latencies"] else None
                ),
                # Raw samples, not just the median -- needed so build_site.py's pooled-percentile
                # windows (p90/p95 across trailing weeks) can pool real backfilled samples too,
                # not just whatever live collection has gathered since this field was added.
                "first_review_latencies_hours": sorted(b["latencies"]),
                "pr_sizes_vs_latency": b["pr_sizes"],
                "draft_pr_count": None,
                "idle_pr_count": None,
            }
        )

    OUT_PATH.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(rows)} weeks)")


if __name__ == "__main__":
    main()
