import pytest
from app.periods.models import AccountingPeriod
from app import db


def _close(year, month):
    p = AccountingPeriod.get_or_create_period(year, month)
    p.status = 'closed'
    db.session.commit()


@pytest.mark.unit
class TestClosedThroughLock:
    def test_no_closed_periods_nothing_locked(self, db_session):
        assert AccountingPeriod.closed_through_ordinal() is None
        assert AccountingPeriod.is_period_closed(2026, 1) is False

    def test_closing_a_month_locks_that_month(self, db_session):
        _close(2026, 3)
        assert AccountingPeriod.is_period_closed(2026, 3) is True

    def test_earlier_month_locked_even_with_no_row(self, db_session):
        # March closed; Jan/Feb never had rows -> still locked (cascade, gap-safe)
        _close(2026, 3)
        assert AccountingPeriod.is_period_closed(2026, 1) is True
        assert AccountingPeriod.is_period_closed(2026, 2) is True

    def test_later_month_stays_open(self, db_session):
        _close(2026, 3)
        assert AccountingPeriod.is_period_closed(2026, 4) is False
        assert AccountingPeriod.is_period_closed(2027, 1) is False

    def test_prior_year_month_locked(self, db_session):
        _close(2026, 1)
        assert AccountingPeriod.is_period_closed(2025, 12) is True

    def test_cutoff_uses_latest_closed_across_gaps(self, db_session):
        _close(2026, 1)
        _close(2026, 5)   # latest closed -> cutoff May 2026
        assert AccountingPeriod.is_period_closed(2026, 4) is True   # below cutoff, no row
        assert AccountingPeriod.is_period_closed(2026, 6) is False  # above cutoff

    def test_reopening_latest_closed_recedes_the_cutoff(self, db_session):
        # Close Jan + May (cutoff = May), then reopen May via the real reopen path ->
        # the cutoff must recede to Jan on the very next query (stateless, no caching).
        _close(2026, 1)
        _close(2026, 5)
        may = AccountingPeriod.query.filter_by(year=2026, month=5).first()
        assert may.reopen_period() is True
        assert AccountingPeriod.closed_through_ordinal() == 2026 * 12 + 1  # Jan, not May
        assert AccountingPeriod.is_period_closed(2026, 5) is False  # the reopened month
        assert AccountingPeriod.is_period_closed(2026, 4) is False  # was sealed under May, now open
        assert AccountingPeriod.is_period_closed(2026, 1) is True   # Jan still the cutoff
