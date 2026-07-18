"""Intra-branch transfer posting (R-04 slice 2)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _intra_transfer(db_session, branch, cash_acct, revenue_acct):
    from app.bank_accounts.models import BankAccount
    from app.bank_transfers.models import BankTransfer
    from_ba = BankAccount(branch_id=branch.id, code='BA-FROM', name='From',
                          account_id=cash_acct.id, account_type='checking', opening_balance=0)
    to_ba = BankAccount(branch_id=branch.id, code='BA-TO', name='To',
                        account_id=revenue_acct.id, account_type='checking', opening_balance=0)
    db.session.add_all([from_ba, to_ba]); db.session.commit()
    bt = BankTransfer(transfer_number='BT-2026-07-9001', from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=branch.id, to_branch_id=branch.id,
                      is_inter_branch=False, amount=Decimal('1000.00'),
                      transfer_date=date(2026, 7, 18), status='draft')
    db.session.add(bt); db.session.commit()
    return bt, from_ba, to_ba


def test_intra_branch_posts_one_balanced_je(db_session, main_branch, cash_account, revenue_account, admin_user):
    from app.bank_transfers.posting import post_intra_branch_transfer
    bt, from_ba, to_ba = _intra_transfer(db_session, main_branch, cash_account, revenue_account)
    je = post_intra_branch_transfer(bt, admin_user)
    db_session.commit()
    assert je.total_debit == je.total_credit == Decimal('1000.00')
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[to_ba.account_id] == (Decimal('1000.00'), Decimal('0.00'))
    assert lines[from_ba.account_id] == (Decimal('0.00'), Decimal('1000.00'))
    assert bt.status == 'completed'
    assert bt.sender_je_id == je.id
