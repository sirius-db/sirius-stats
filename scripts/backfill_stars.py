#!/usr/bin/env python3
"""One-time bootstrap: reconstruct sirius-db/sirius's daily star history via `gh api`.

Not run by any workflow. See BOOTSTRAP.md for usage. Requires the `gh` CLI to be
installed and authenticated (`gh auth status`) -- no token needs to be minted.
"""

import json
import subprocess
from collections import Counter
from pathlib import Path

REPO = "sirius-db/sirius"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "stars_backfill.json"


def fetch_stargazers():
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "-H",
            "Accept: application/vnd.github.star+json",
            f"repos/{REPO}/stargazers",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # --paginate concatenates one JSON array per page back-to-back on stdout.
    decoder = json.JSONDecoder()
    stargazers = []
    text = result.stdout.strip()
    idx = 0
    while idx < len(text):
        page, end = decoder.raw_decode(text, idx)
        stargazers.extend(page)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return stargazers


def main():
    stargazers = fetch_stargazers()
    per_day = Counter(entry["starred_at"][:10] for entry in stargazers)

    cumulative = 0
    history = []
    for day in sorted(per_day):
        cumulative += per_day[day]
        history.append({"date": day, "stars": cumulative})

    OUT_PATH.write_text(json.dumps(history, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(history)} days, {cumulative} total stars)")


if __name__ == "__main__":
    main()
