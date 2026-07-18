"""Receiving-branch action item for in_transit inter-branch transfers (R-04 slice 2)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _in_transit_transfer(db_session, from_branch, to_branch, cash_account):
    from app.bank_accounts.models import BankAccount
    from app.accounts.models import Account
    from app.bank_transfers.models import BankTransfer
    from_ba = BankAccount(branch_id=from_branch.id, code='BA-AI1', name='AI1',
                          account_id=cash_account.id, account_type='checking', opening_balance=0)
    recv_gl = Account(code='10120', name='Cash - AI', account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db.session.add_all([from_ba, recv_gl]); db.session.commit()
    to_ba = BankAccount(branch_id=to_branch.id, code='BA-AI2', name='AI2',
                        account_id=recv_gl.id, account_type='checking', opening_balance=0)
    db.session.add(to_ba); db.session.commit()
    bt = BankTransfer(transfer_number='BT-2026-07-9100', from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=from_branch.id,
                      to_branch_id=to_branch.id, is_inter_branch=True, amount=Decimal('400.00'),
                      transfer_date=date(2026, 7, 18), status='in_transit')
    db_session.add(bt); db_session.commit()
    return bt


def test_in_transit_transfer_appears_at_to_branch(db_session, main_branch, branch_manila,
                                                   cash_account, accountant_user):
    from app.dashboard.action_items_service import gather_incoming_transfer_items
    bt = _in_transit_transfer(db_session, main_branch, branch_manila, cash_account)
    items = gather_incoming_transfer_items(accountant_user, branch_manila.id)
    assert any(i['id'] == bt.transfer_number for i in items)


def test_in_transit_transfer_absent_at_from_branch(db_session, main_branch, branch_manila,
                                                    cash_account, accountant_user):
    from app.dashboard.action_items_service import gather_incoming_transfer_items
    bt = _in_transit_transfer(db_session, main_branch, branch_manila, cash_account)
    items = gather_incoming_transfer_items(accountant_user, main_branch.id)
    assert not any(i['id'] == bt.transfer_number for i in items)


def test_completed_transfer_does_not_appear(db_session, main_branch, branch_manila,
                                            cash_account, accountant_user):
    from app.dashboard.action_items_service import gather_incoming_transfer_items
    bt = _in_transit_transfer(db_session, main_branch, branch_manila, cash_account)
    bt.status = 'completed'
    db_session.commit()
    items = gather_incoming_transfer_items(accountant_user, branch_manila.id)
    assert not any(i['id'] == bt.transfer_number for i in items)


def test_count_action_items_includes_incoming_transfers(db_session, main_branch, branch_manila,
                                                         cash_account, accountant_user):
    from app.dashboard.action_items_service import count_action_items
    before = count_action_items(accountant_user, branch_manila.id)
    _in_transit_transfer(db_session, main_branch, branch_manila, cash_account)
    after = count_action_items(accountant_user, branch_manila.id)
    assert after == before + 1
