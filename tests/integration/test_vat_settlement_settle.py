import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.periods.models import AccountingPeriod
from app.vat_settlement.models import VatSettlement
from app.vat_settlement import service
from app.journal_entries.models import JournalEntry, JournalEntryLine
from tests.integration.test_vat_settlement_compute import _vat_world, _je

pytestmark = [pytest.mark.integration]

TODAY = date(2026, 1, 15)  # after 2025-Q3 and Q4


def test_settle_payable_posts_je_zeroes_accounts_locks_periods(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 120000, 0), (w['out'].id, 0, 120000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 50000, 0), (w['ap'].id, 0, 50000)])
    db.session.commit()

    s = service.settle_quarter(2025, 3, admin_user.id)
    db.session.commit()

    assert s.net_payable == Decimal('70000.00')
    # JE posted, balanced, dated Sep 30
    jes = JournalEntry.query.filter_by(entry_type='vat_settlement').all()
    assert len(jes) == 1 and jes[0].is_balanced and jes[0].entry_date == date(2025, 9, 30)
    # output + input accounts now net to zero as of qend
    assert service._balance(w2 := service.output_account_ids(), date(2025, 9, 30), 'credit') == Decimal('0')
    assert service._balance(service.input_account_ids(), date(2025, 9, 30), 'debit') == Decimal('0')
    # VAT Payable credited 70k
    pay_id = w['payable'].id
    d, c = service._sum([pay_id], upto=date(2025, 9, 30))
    assert (c - d) == Decimal('70000.00')
    # 3 months locked
    for m in (7, 8, 9):
        assert AccountingPeriod.is_period_closed(2025, m)


def test_settle_creditable_raises_carryover(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 20000, 0), (w['out'].id, 0, 20000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 100000, 0), (w['ap'].id, 0, 100000)])
    db.session.commit()
    s = service.settle_quarter(2025, 3, admin_user.id)
    db.session.commit()
    assert s.new_carryover == Decimal('80000.00') and s.net_payable == Decimal('0.00')
    carry_id = w['carry'].id
    d, c = service._sum([carry_id], upto=date(2025, 9, 30))
    assert (d - c) == Decimal('80000.00')


def test_carryover_chains_across_two_quarters(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    # Q3 creditable 80k
    _je(main_branch.id, date(2025, 7, 10), [(w['ar'].id, 20000, 0), (w['out'].id, 0, 20000)])
    _je(main_branch.id, date(2025, 8, 10), [(w['inp'].id, 100000, 0), (w['ap'].id, 0, 100000)])
    db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    # Q4 output 30k, input 10k -> creditable 90k -> carryover 60k
    _je(main_branch.id, date(2025, 10, 10), [(w['ar'].id, 30000, 0), (w['out'].id, 0, 30000)])
    _je(main_branch.id, date(2025, 11, 10), [(w['inp'].id, 10000, 0), (w['ap'].id, 0, 10000)])
    db.session.commit()
    pos = service.compute_vat_position(2025, 4)
    assert pos['prior_carryover'] == Decimal('80000.00')
    s4 = service.settle_quarter(2025, 4, admin_user.id); db.session.commit()
    assert s4.new_carryover == Decimal('60000.00')


def test_no_activity_quarter_records_zero_row_no_je(db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    s = service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    assert s.output_vat == Decimal('0.00') and s.net_payable == Decimal('0.00')
    assert JournalEntry.query.filter_by(entry_type='vat_settlement').count() == 0
    assert VatSettlement.query.filter_by(fiscal_year=2025, quarter=3).count() == 1


def test_cannot_settle_unfinished_quarter(db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    with pytest.raises(ValueError):
        service.assert_settleable(2025, 4, date(2025, 11, 1))  # Q4 not ended


def test_cannot_settle_before_prior_quarter(db_session, main_branch, admin_user):
    w = _vat_world(main_branch)
    _je(main_branch.id, date(2025, 4, 10), [(w['ar'].id, 1000, 0), (w['out'].id, 0, 1000)])  # Q2 data
    db.session.commit()
    with pytest.raises(ValueError):
        service.assert_settleable(2025, 3, TODAY)  # Q2 unsettled


def test_cannot_settle_twice(db_session, main_branch, admin_user):
    _vat_world(main_branch); db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    with pytest.raises(ValueError):
        service.assert_settleable(2025, 3, TODAY)


def test_settle_writes_audit(db_session, main_branch, admin_user):
    from app.audit.models import AuditLog
    _vat_world(main_branch); db.session.commit()
    service.settle_quarter(2025, 3, admin_user.id); db.session.commit()
    assert AuditLog.query.filter_by(module='vat_settlement', action='settle').first() is not None
