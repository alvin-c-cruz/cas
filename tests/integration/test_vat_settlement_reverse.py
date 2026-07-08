import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.periods.models import AccountingPeriod
from app.vat_settlement.models import VatSettlement
from app.vat_settlement import service
from app.journal_entries.models import JournalEntry
from tests.integration.test_vat_settlement_compute import _vat_world, _je

pytestmark = [pytest.mark.integration]


def test_reverse_restores_balances_and_reopens(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()

    service.reverse_settlement(2025, 3, admin_user.id); db.session.commit()

    s = VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).first()
    assert s.status == 'reversed'
    assert JournalEntry.query.filter_by(entry_type='vat_settlement_reversal').count() == 1
    # output VAT back to 120k credit balance, VAT payable back to zero
    assert service._balance(service.output_account_ids(), date(2025, 12, 31), 'credit') == Decimal('120000.00')
    d, c = service._sum([w['payable'].id], upto=date(2025, 12, 31))
    assert (c - d) == Decimal('0')
    for m in (7, 8, 9):
        assert not AccountingPeriod.is_period_closed(2025, m)


def test_only_latest_quarter_reversible(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 100, 0), (w['out'].id, 0, 100)])
    _je(main_branch.id, date(2025, 10, 10), [(w['ar'].id, 100, 0), (w['out'].id, 0, 100)])
    db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    service.settle_quarter(2025, 4, admin_user.id); db.session.commit()
    with pytest.raises(ValueError):
        service.reverse_settlement(2025, 3, admin_user.id)  # Q4 is later


def test_reverse_writes_audit(db_session, main_branch, admin_user):
    from app.audit.models import AuditLog
    _vat_world(main_branch); db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    service.reverse_settlement(2025, 3, admin_user.id); db.session.commit()
    assert AuditLog.query.filter_by(module='vat_settlement', action='reverse').first() is not None
