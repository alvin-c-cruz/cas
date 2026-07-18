"""Recording a voucher posts zero JE (R-04 slice 4)."""
from decimal import Decimal
import pytest
from app.journal_entries.models import JournalEntry

pytestmark = [pytest.mark.integration]


def test_record_voucher_posts_no_je(db_session, main_branch, cash_account, revenue_account, staff_user):
    from app.petty_cash.models import PettyCashFund
    from app.petty_cash.posting import record_voucher
    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-VNJ', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(fund); db_session.commit()

    before = JournalEntry.query.count()
    v = record_voucher(fund, payee='Jollibee', expense_account_id=revenue_account.id,
                       amount=Decimal('250.00'), description='snacks', receipt_ref='OR-99',
                       created_by=staff_user)
    db_session.commit()
    assert JournalEntry.query.count() == before
    assert v.status == 'held'


def test_expected_cash_is_float_minus_held_vouchers(db_session, main_branch, cash_account,
                                                     revenue_account, staff_user):
    from app.petty_cash.models import PettyCashFund
    from app.petty_cash.posting import record_voucher
    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-EXP', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('3000.00'))
    db_session.add(fund); db_session.commit()
    record_voucher(fund, payee='A', expense_account_id=revenue_account.id, amount=Decimal('500.00'),
                   description='', receipt_ref='', created_by=staff_user)
    record_voucher(fund, payee='B', expense_account_id=revenue_account.id, amount=Decimal('300.00'),
                   description='', receipt_ref='', created_by=staff_user)
    db_session.commit()
    held_total = sum((v.amount for v in fund.vouchers if v.status == 'held'), start=type(fund.float_amount)('0'))
    expected_cash = fund.float_amount - held_total
    assert expected_cash == Decimal('2200.00')
