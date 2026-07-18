"""Establish/adjust-float/close funding JEs (R-04 slice 4)."""
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _mk_fund(db_session, branch, account, float_amount=Decimal('5000.00')):
    from app.petty_cash.models import PettyCashFund
    f = PettyCashFund(branch_id=branch.id, code='PCF-EST', name='Fund',
                      account_id=account.id, float_amount=float_amount, custodian='Juan')
    db_session.add(f); db_session.commit()
    return f


def test_establish_posts_dr_petty_cash_cr_bank(db_session, main_branch, cash_account,
                                               revenue_account, admin_user):
    from app.petty_cash.posting import post_establish
    from app.bank_accounts.models import BankAccount
    fund = _mk_fund(db_session, main_branch, cash_account)
    bank_ba = BankAccount(branch_id=main_branch.id, code='BA-EST', name='Funding',
                          account_id=revenue_account.id, account_type='checking', opening_balance=0)
    db_session.add(bank_ba); db_session.commit()
    fund.funding_bank_account_id = bank_ba.id
    db_session.commit()
    je = post_establish(fund, actor=admin_user)
    db_session.commit()
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[cash_account.id] == (Decimal('5000.00'), Decimal('0.00'))
    assert je.total_debit == je.total_credit == Decimal('5000.00')


def test_close_refuses_while_held_vouchers_exist(db_session, main_branch, cash_account,
                                                 revenue_account, admin_user, staff_user):
    from app.petty_cash.posting import post_close, record_voucher
    fund = _mk_fund(db_session, main_branch, cash_account)
    record_voucher(fund, payee='Store', expense_account_id=revenue_account.id, amount=Decimal('100'),
                   description='test', receipt_ref='OR-1', created_by=staff_user)
    db_session.commit()
    with pytest.raises(ValueError):
        post_close(fund, actor=admin_user)


def test_close_succeeds_with_no_held_vouchers(db_session, main_branch, cash_account,
                                              revenue_account, admin_user):
    from app.petty_cash.posting import post_close
    from app.bank_accounts.models import BankAccount
    fund = _mk_fund(db_session, main_branch, cash_account, float_amount=Decimal('1000.00'))
    bank_ba = BankAccount(branch_id=main_branch.id, code='BA-CLOSE', name='Funding',
                          account_id=revenue_account.id, account_type='checking', opening_balance=0)
    db_session.add(bank_ba); db_session.commit()
    fund.funding_bank_account_id = bank_ba.id
    db_session.commit()
    je = post_close(fund, actor=admin_user)
    db_session.commit()
    assert fund.status == 'closed'
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[cash_account.id] == (Decimal('0.00'), Decimal('1000.00'))
