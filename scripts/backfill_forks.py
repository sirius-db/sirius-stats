#!/usr/bin/env python3
"""One-time bootstrap: reconstruct sirius-db/sirius's daily fork history via `gh api`.

Not run by any workflow. See BOOTSTRAP.md for usage. Requires the `gh` CLI to be
installed and authenticated (`gh auth status`) -- no token needs to be minted.
"""

import json
import subprocess
from collections import Counter
from pathlib import Path

REPO = "sirius-db/sirius"
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "forks_backfill.json"


def fetch_forks():
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{REPO}/forks?sort=oldest"],
        check=True,
        capture_output=True,
        text=True,
    )
    # --paginate concatenates one JSON array per page back-to-back on stdout.
    decoder = json.JSONDecoder()
    forks = []
    text = result.stdout.strip()
    idx = 0
    while idx < len(text):
        page, end = decoder.raw_decode(text, idx)
        forks.extend(page)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return forks


def main():
    forks = fetch_forks()
    per_day = Counter(entry["created_at"][:10] for entry in forks)

    cumulative = 0
    history = []
    for day in sorted(per_day):
        cumulative += per_day[day]
        history.append({"date": day, "forks": cumulative})

    OUT_PATH.write_text(json.dumps(history, indent=2) + "\n")
    print(f"wrote {OUT_PATH} ({len(history)} days, {cumulative} total forks)")


if __name__ == "__main__":
    main()
