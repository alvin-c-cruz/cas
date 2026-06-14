"""Unit tests for calculate_age_bucket helper in app/reports/views.py."""
import pytest
from datetime import date
from app.reports.views import calculate_age_bucket

pytestmark = [pytest.mark.unit]


@pytest.mark.usefixtures("app")
class TestCalculateAgeBucket:
    """Cover all 5 bucket transitions plus edge cases."""

    # ── None / future / current-day ──────────────────────────────────────────

    def test_none_due_date_returns_current(self):
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(None, as_of) == 'current'

    def test_future_due_date_returns_current(self):
        # Due tomorrow — not yet overdue
        due = date(2026, 6, 15)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == 'current'

    def test_due_today_returns_current(self):
        # 0 days overdue — boundary
        today = date(2026, 6, 14)
        assert calculate_age_bucket(today, today) == 'current'

    # ── 1-30 bucket ──────────────────────────────────────────────────────────

    def test_1_day_overdue_returns_1_30(self):
        due = date(2026, 6, 13)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '1-30'

    def test_30_days_overdue_returns_1_30(self):
        due = date(2026, 5, 15)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '1-30'

    # ── 31-60 bucket ─────────────────────────────────────────────────────────

    def test_31_days_overdue_returns_31_60(self):
        due = date(2026, 5, 14)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '31-60'

    def test_60_days_overdue_returns_31_60(self):
        due = date(2026, 4, 15)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '31-60'

    # ── 61-90 bucket ─────────────────────────────────────────────────────────

    def test_61_days_overdue_returns_61_90(self):
        due = date(2026, 4, 14)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '61-90'

    def test_90_days_overdue_returns_61_90(self):
        due = date(2026, 3, 16)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '61-90'

    # ── 90+ bucket ───────────────────────────────────────────────────────────

    def test_91_days_overdue_returns_90_plus(self):
        due = date(2026, 3, 15)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '90+'

    def test_large_overdue_returns_90_plus(self):
        due = date(2025, 6, 14)
        as_of = date(2026, 6, 14)
        assert calculate_age_bucket(due, as_of) == '90+'
