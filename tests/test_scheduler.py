"""Scheduler window-logic tests: pure date math, no DB.

`app/models.py` doesn't exist yet (schema/DB step still blocked on Neon
OAuth — see DECISIONS.md), so a minimal stand-in with the two fields
`is_due_today` actually reads (`day_of_month`, `window_days`) is used here
instead of importing a real `RecurringRule` ORM class.
"""

from dataclasses import dataclass
from datetime import date

from app.scheduler_logic import due_today, is_due_today


@dataclass
class FakeRule:
    id: str
    label: str
    day_of_month: int
    window_days: int


def test_due_on_exact_day():
    rule = FakeRule(id="r1", label="Salary", day_of_month=28, window_days=2)
    assert is_due_today(rule, date(2026, 7, 28)) is True


def test_due_on_window_start_and_end():
    rule = FakeRule(id="r1", label="Salary", day_of_month=28, window_days=2)
    assert is_due_today(rule, date(2026, 7, 26)) is True
    assert is_due_today(rule, date(2026, 7, 30)) is True


def test_not_due_outside_window():
    rule = FakeRule(id="r1", label="Salary", day_of_month=28, window_days=2)
    assert is_due_today(rule, date(2026, 7, 25)) is False
    assert is_due_today(rule, date(2026, 7, 31)) is False


def test_day_of_month_31_clamps_to_last_day_of_shorter_month():
    """April has 30 days — day_of_month=31 must clamp to 30, not crash."""
    rule = FakeRule(id="r1", label="Rent", day_of_month=31, window_days=2)

    assert is_due_today(rule, date(2026, 4, 30)) is True
    assert is_due_today(rule, date(2026, 4, 28)) is True
    assert is_due_today(rule, date(2026, 4, 25)) is False


def test_due_today_merges_recurring_and_manual_into_one_list():
    """Per SCHEMA_AND_FLOW_DESIGN.md §5: never split same-day pings —
    a due recurring rule and a manual entry due the same day must come
    back as one combined collection, not two separate structures."""
    today = date(2026, 7, 28)
    rule = FakeRule(id="r1", label="Salary", day_of_month=28, window_days=2)
    manual_entry = {"label": "Lunch", "amount": 120}

    result = due_today([rule], [manual_entry], today)

    assert isinstance(result, list)
    assert len(result) == 2
    assert rule in result
    assert manual_entry in result


def test_due_today_excludes_rule_not_in_window():
    today = date(2026, 7, 28)
    far_rule = FakeRule(id="r2", label="SIP", day_of_month=10, window_days=2)
    manual_entry = {"label": "Coffee", "amount": 50}

    result = due_today([far_rule], [manual_entry], today)

    assert result == [manual_entry]
