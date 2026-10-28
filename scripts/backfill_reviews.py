#!/usr/bin/env python3
"""One-time historical backfill of review-health metrics.

Paginates every PR in sirius-db/sirius via GraphQL (not scoped to a date window, unlike
fetch_review_metrics()'s daily "touched" queries in fetch_metrics.py) and writes
pre-aggregated weekly rows to data/review_backfill.json -- same convention as
activity_backfill.json: a static, hand-generated-once seed that build_review_weekly()
merges with live snapshots, live data winning on any overlapping week. See BOOTSTRAP.md
for the one-time-run instructions and the GraphQL rate-limit math this relies on
(~1 point per 50-PR batch; confirmed live against the real API during planning).

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

import json
import os
import statistics
import urllib.request
from datetime import date, datetime
from pathlib import Path

from _dates import week_start

REPO = "sirius-db/sirius"
API_ROOT = "https://api.github.com"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "review_backfill.json"

_BACKFILL_PR_FIELDS = """
      number
      isDraft
      createdAt
      mergedAt
      closedAt
      reviews(first: 1) { totalCount nodes { submittedAt } }
      timelineItems(itemTypes: [READY_FOR_REVIEW_EVENT], first: 1) {
        nodes { ... on ReadyForReviewEvent { createdAt } }
      }
"""

_GRAPHQL_ALL_PRS = (
    """
query($cursor: String) {
  repository(owner: "sirius-db", name: "sirius") {
    pullRequests(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      nodes {
"""
    + _BACKFILL_PR_FIELDS
    + """
      }
      pageInfo { hasNextPage endCursor }
    }
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


def _all_prs(token):
    prs = []
    cursor = None
    while True:
        data = graphql_query(_GRAPHQL_ALL_PRS, {"cursor": cursor}, token)
        page = data["repository"]["pullRequests"]
        prs.extend(page["nodes"])
        print(f"  fetched {len(prs)} PRs so far...")
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return prs


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
    review_nodes = pr["reviews"]["nodes"]
    if not review_nodes:
        return None
    ready_nodes = pr["timelineItems"]["nodes"]
    baseline = ready_nodes[0]["createdAt"] if ready_nodes else pr["createdAt"]
    baseline_dt = datetime.fromisoformat(baseline.replace("Z", "+00:00"))
    first_review_dt = datetime.fromisoformat(review_nodes[0]["submittedAt"].replace("Z", "+00:00"))
    return (first_review_dt - baseline_dt).total_seconds() / 3600


def main():
    token = os.environ.get("SIRIUS_TRAFFIC_TOKEN")
    if not token:
        raise SystemExit("SIRIUS_TRAFFIC_TOKEN must be set -- see BOOTSTRAP.md")

    print("Fetching all PRs via GraphQL (one-time backfill, ~1 point per 50-PR batch)...")
    prs = _all_prs(token)
    print(f"Fetched {len(prs)} PRs total.")

    # Non-draft only, matching fetch_review_metrics()'s live scope (nondraft_touched_count /
    # zero_review_nondraft_count) so backfilled and live weeks merge on a consistent definition.
    buckets = {}
    for pr in prs:
        if pr["isDraft"]:
            continue
        week_of = week_start(date.fromisoformat(_bucket_date(pr))).isoformat()
        bucket = buckets.setdefault(
            week_of, {"latencies": [], "zero_review_count": 0, "pr_count": 0}
        )
        bucket["pr_count"] += 1
        latency = _first_review_latency_hours(pr)
        if latency is None:
            bucket["zero_review_count"] += 1
        else:
            bucket["latencies"].append(round(latency, 2))

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
                "draft_pr_count": None,
                "idle_pr_count": None,
            }
        )

    OUT_PATH.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(rows)} weeks)")


if __name__ == "__main__":
    main()
