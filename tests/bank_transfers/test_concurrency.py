"""Optimistic-lock double-confirm guard (R-04 slice 2), mirroring test_lost_update_guard.py's pattern."""
import pytest
from app.utils.concurrency import claim_version

pytestmark = [pytest.mark.integration]


def test_double_confirm_second_writer_loses(db_session, main_branch, branch_manila, cash_account, admin_user):
    from datetime import date
    from decimal import Decimal
    from app import db
    from app.settings import AppSettings
    from app.bank_accounts.models import BankAccount
    from app.accounts.models import Account
    from app.bank_transfers.models import BankTransfer

    due_from = Account(code='10219', name='Due from', account_type='Asset', normal_balance='Debit', is_active=True)
    due_to = Account(code='20114', name='Due to', account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add_all([due_from, due_to]); db.session.commit()
    AppSettings.set_setting('inter_branch_due_from_account_code', due_from.code)
    AppSettings.set_setting('inter_branch_due_to_account_code', due_to.code)
    db.session.commit()

    recv_gl = Account(code='10119', name='Cash - Manila 3', account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db.session.add(recv_gl); db.session.commit()
    from_ba = BankAccount(branch_id=main_branch.id, code='BA-Z', name='Z',
                          account_id=cash_account.id, account_type='checking', opening_balance=0)
    to_ba = BankAccount(branch_id=branch_manila.id, code='BA-W', name='W',
                        account_id=recv_gl.id, account_type='checking', opening_balance=0)
    db.session.add_all([from_ba, to_ba]); db.session.commit()

    bt = BankTransfer(transfer_number='BT-2026-07-9099', from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=main_branch.id,
                      to_branch_id=branch_manila.id, is_inter_branch=True, amount=Decimal('300.00'),
                      transfer_date=date(2026, 7, 18), status='in_transit')
    db_session.add(bt); db_session.commit()
    submitted = bt.row_version   # both racers hold the SAME stale token

    first = claim_version(BankTransfer, bt.id, submitted)
    second = claim_version(BankTransfer, bt.id, submitted)
    assert first is True
    assert second is False   # the second racer, holding the same now-stale token, loses
