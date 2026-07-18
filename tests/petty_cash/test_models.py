"""Unit tests for the 3 Petty Cash models (R-04 slice 4)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.petty_cash.models import PettyCashFund, PettyCashVoucher, PettyCashReplenishment

pytestmark = [pytest.mark.integration]


def test_fund_account_id_unique(db_session, main_branch, cash_account):
    f1 = PettyCashFund(branch_id=main_branch.id, code='PCF-1', name='Main Office Petty Cash',
                       account_id=cash_account.id, float_amount=Decimal('5000.00'))
    db_session.add(f1); db_session.commit()
    f2 = PettyCashFund(branch_id=main_branch.id, code='PCF-2', name='Duplicate',
                       account_id=cash_account.id, float_amount=Decimal('1000.00'))
    db_session.add(f2)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_fund_default_status_active(db_session, main_branch, cash_account):
    f = PettyCashFund(branch_id=main_branch.id, code='PCF-3', name='Fund',
                      account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(f); db_session.commit()
    assert f.status == 'active'


def test_voucher_default_status_held(db_session, main_branch, cash_account, revenue_account):
    f = PettyCashFund(branch_id=main_branch.id, code='PCF-4', name='Fund',
                      account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(f); db_session.commit()
    v = PettyCashVoucher(fund_id=f.id, voucher_number='PCV-2026-07-0001', voucher_date=date(2026, 7, 18),
                         payee='Jollibee', expense_account_id=revenue_account.id, amount=Decimal('250.00'))
    db_session.add(v); db_session.commit()
    assert v.status == 'held'
    assert v.replenishment_id is None


def test_replenishment_row_versioned(db_session, main_branch, cash_account):
    f = PettyCashFund(branch_id=main_branch.id, code='PCF-5', name='Fund',
                      account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(f); db_session.commit()
    r = PettyCashReplenishment(fund_id=f.id, replenishment_number='PCR-2026-07-0001',
                               replenishment_date=date(2026, 7, 18), physical_cash_counted=Decimal('1800.00'),
                               vouchers_total=Decimal('200.00'), short_over_amount=Decimal('0.00'),
                               replenish_amount=Decimal('200.00'))
    db_session.add(r); db_session.commit()
    assert r.row_version == 1
    assert r.status == 'draft'
