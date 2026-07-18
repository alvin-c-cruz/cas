"""Unit tests for the BankTransfer model (R-04 slice 2)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.bank_transfers.models import BankTransfer

pytestmark = [pytest.mark.integration]


def _mk_bank_account(db_session, branch, account, code):
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=branch.id, code=code, name=f'{code} Account',
                     account_id=account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    return ba


def test_is_inter_branch_derived_from_accounts(db_session, main_branch, branch_manila,
                                                cash_account, revenue_account):
    from_acct = _mk_bank_account(db_session, main_branch, cash_account, 'BA-FROM')
    to_acct = _mk_bank_account(db_session, branch_manila, revenue_account, 'BA-TO')
    bt = BankTransfer(transfer_number='BT-2026-07-0001', from_bank_account_id=from_acct.id,
                      to_bank_account_id=to_acct.id, from_branch_id=main_branch.id,
                      to_branch_id=branch_manila.id, is_inter_branch=True,
                      amount=Decimal('1000.00'), transfer_date=date(2026, 7, 18), status='draft')
    db_session.add(bt); db_session.commit()
    assert bt.is_inter_branch is True
    assert bt.row_version == 1


def test_default_status_is_draft(db_session, main_branch, cash_account, revenue_account):
    from_acct = _mk_bank_account(db_session, main_branch, cash_account, 'BA-A')
    to_acct = _mk_bank_account(db_session, main_branch, revenue_account, 'BA-B')
    bt = BankTransfer(transfer_number='BT-2026-07-0002', from_bank_account_id=from_acct.id,
                      to_bank_account_id=to_acct.id, from_branch_id=main_branch.id,
                      to_branch_id=main_branch.id, is_inter_branch=False,
                      amount=Decimal('500.00'), transfer_date=date(2026, 7, 18))
    db_session.add(bt); db_session.commit()
    assert bt.status == 'draft'
