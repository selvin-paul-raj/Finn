"""What's due today: pure date-window logic, no DB access.

Called by the (not-yet-written) `/trigger` endpoint.
"""

from calendar import monthrange
from datetime import date
from typing import Any, Protocol


class _RuleLike(Protocol):
    day_of_month: int
    window_days: int


def is_due_today(rule: _RuleLike, today: date) -> bool:
    """True if `today` falls within `window_days` of `day_of_month` in
    `today`'s own month.

    `day_of_month` is clamped to that month's last day first, so a
    day_of_month=31 rule is "due" around the 30th in a 30-day month
    instead of raising.
    """
    last_day = monthrange(today.year, today.month)[1]
    target_day = min(rule.day_of_month, last_day)
    return abs(today.day - target_day) <= rule.window_days


def due_today(rules: list[_RuleLike], manual_entries: list[Any], today: date) -> list[Any]:
    """Merge due recurring rules and manual entries into one combined list.

    Per SCHEMA_AND_FLOW_DESIGN.md §5: a recurring ping and a manual entry
    due the same day are never split into two separate structures.
    """
    return [rule for rule in rules if is_due_today(rule, today)] + list(manual_entries)
