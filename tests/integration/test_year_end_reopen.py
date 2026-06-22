import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.journal_entries.models import JournalEntry
from app.audit.models import AuditLog
from tests.integration.test_year_end_close import _world  # reuse builder

pytestmark = [pytest.mark.integration]


def test_reopen_reverses_closing_entries_and_unlocks(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.periods.models import AccountingPeriod
    _world(main_branch.id)
    db.session.commit()
    service.close_fiscal_year(2025, admin_user.id)
    db.session.commit()

    service.reopen_fiscal_year(2025, admin_user.id)
    db.session.commit()

    # net posted effect of closing + reversal on RE is zero again
    re = Account.query.filter_by(code='30201').first()
    d, c = service._posted_sums(re.id, date(2025, 12, 31), main_branch.id)
    assert (d - c) == Decimal('0.00')
    assert JournalEntry.query.filter_by(entry_type='closing_reversal').count() >= 1

    dec = AccountingPeriod.query.filter_by(year=2025, month=12).first()
    assert dec.status == 'open'
    fc = service.FiscalYearClose.query.filter_by(fiscal_year=2025, branch_id=main_branch.id).first()
    assert fc.status == 'reopened'
    assert AuditLog.query.filter_by(module='year_end', action='reopen').first() is not None


def test_reopen_only_latest_year(db_session, admin_user, main_branch):
    from app.year_end import service
    from app.year_end.models import FiscalYearClose
    # 2024 + 2025 both closed; reopening 2024 must be refused
    for y in (2024, 2025):
        db.session.add(FiscalYearClose(fiscal_year=y, branch_id=main_branch.id, status='closed',
                                       net_income=Decimal('0'), closed_by_id=admin_user.id))
    db.session.commit()
    with pytest.raises(ValueError, match='latest closed year'):
        service.reopen_fiscal_year(2024, admin_user.id)
