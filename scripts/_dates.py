"""Shared date-bucketing helper for weekly rollups (build_site.py, backfill_reviews.py).

Split out of build_site.py so backfill_reviews.py doesn't duplicate it -- the first
cross-script import in this codebase's scripts/ (every other backfill script is
deliberately self-contained, see backfill_traffic.py), used only for this one small,
easy-to-keep-in-sync helper.
"""

from datetime import timedelta


def week_start(day):
    """Sunday on-or-before `day`, matching GitHub Pulse's weekly bucket convention."""
    return day - timedelta(days=(day.weekday() + 1) % 7)
