"""BT-YYYY-MM-NNNN numbering (R-04 slice 2)."""
import pytest
from app.utils import ph_now

pytestmark = [pytest.mark.integration]


def test_generate_bank_transfer_number_format(db_session):
    from app.bank_transfers.numbering import generate_bank_transfer_number
    n = generate_bank_transfer_number()
    today = ph_now().date()
    assert n == f'BT-{today.year:04d}-{today.month:02d}-0001'


def test_generate_bank_transfer_number_increments(db_session, main_branch, cash_account, revenue_account):
    from app.bank_accounts.models import BankAccount
    from app.bank_transfers.models import BankTransfer
    from app.bank_transfers.numbering import generate_bank_transfer_number
    from datetime import date
    from decimal import Decimal
    from app import db
    from_acct = BankAccount(branch_id=main_branch.id, code='BA-A', name='A',
                            account_id=cash_account.id, account_type='checking', opening_balance=0)
    to_acct = BankAccount(branch_id=main_branch.id, code='BA-B', name='B',
                          account_id=revenue_account.id, account_type='checking', opening_balance=0)
    db.session.add_all([from_acct, to_acct]); db.session.commit()
    first = generate_bank_transfer_number()
    bt = BankTransfer(transfer_number=first, from_bank_account_id=from_acct.id,
                      to_bank_account_id=to_acct.id, from_branch_id=main_branch.id,
                      to_branch_id=main_branch.id, is_inter_branch=False,
                      amount=Decimal('100'), transfer_date=date.today(), status='draft')
    db.session.add(bt); db.session.commit()
    second = generate_bank_transfer_number()
    assert second != first
    assert second.endswith('0002')
