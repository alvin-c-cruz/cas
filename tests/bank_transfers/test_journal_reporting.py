"""Task 3 review fix: transfer JEs must be registered as a voucher-type entry_type
so they appear in the General Journal report and Books of Accounts (R-04 slice 2).

Mirrors tests/integration/test_opening_balances.py::test_opening_balance_is_a_registered_voucher_type.
"""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.journals.views import VOUCHER_TYPES
from app.reports.general_journal_data import VOUCHER_ENTRY_TYPES
from app.journal_entries.models import JournalEntry

pytestmark = [pytest.mark.integration]


def test_transfer_is_a_registered_voucher_type():
    assert 'transfer' in VOUCHER_TYPES
    assert 'transfer' in VOUCHER_ENTRY_TYPES


def _intra_transfer(db_session, branch, cash_acct, revenue_acct):
    from app.bank_accounts.models import BankAccount
    from app.bank_transfers.models import BankTransfer
    from_ba = BankAccount(branch_id=branch.id, code='BA-FROM', name='From',
                          account_id=cash_acct.id, account_type='checking', opening_balance=0)
    to_ba = BankAccount(branch_id=branch.id, code='BA-TO', name='To',
                        account_id=revenue_acct.id, account_type='checking', opening_balance=0)
    db.session.add_all([from_ba, to_ba]); db.session.commit()
    bt = BankTransfer(transfer_number='BT-2026-07-9002', from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=branch.id, to_branch_id=branch.id,
                      is_inter_branch=False, amount=Decimal('1000.00'),
                      transfer_date=date(2026, 7, 18), status='draft')
    db.session.add(bt); db.session.commit()
    return bt, from_ba, to_ba


def test_posted_intra_branch_transfer_je_appears_in_voucher_query(
        db_session, main_branch, cash_account, revenue_account, admin_user):
    """Proves the fix, not just the constant: a JE actually created by Task 3's
    post_intra_branch_transfer is picked up by the same
    JournalEntry.entry_type.in_(VOUCHER_ENTRY_TYPES) filter the General Journal /
    Books of Accounts reports use."""
    from app.bank_transfers.posting import post_intra_branch_transfer
    bt, from_ba, to_ba = _intra_transfer(db_session, main_branch, cash_account, revenue_account)
    je = post_intra_branch_transfer(bt, admin_user)
    db_session.commit()

    reportable_ids = {
        row.id for row in
        JournalEntry.query.filter(JournalEntry.entry_type.in_(VOUCHER_ENTRY_TYPES)).all()
    }
    assert je.id in reportable_ids
