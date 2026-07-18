"""Inter-branch transfer posting: initiate/confirm/reject (R-04 slice 2)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _assign_clearing_accounts(db_session):
    from app.accounts.models import Account
    due_from = Account(code='10216', name='Inter-branch Due from', account_type='Asset',
                       normal_balance='Debit', is_active=True)
    due_to = Account(code='20111', name='Inter-branch Due to', account_type='Liability',
                     normal_balance='Credit', is_active=True)
    db.session.add_all([due_from, due_to]); db.session.commit()
    AppSettings.set_setting('inter_branch_due_from_account_code', due_from.code)
    AppSettings.set_setting('inter_branch_due_to_account_code', due_to.code)
    db.session.commit()
    return due_from, due_to


def _inter_transfer(db_session, from_branch, to_branch, cash_acct):
    from app.bank_accounts.models import BankAccount
    from app.bank_transfers.models import BankTransfer
    from_ba = BankAccount(branch_id=from_branch.id, code='BA-SEND', name='Send',
                          account_id=cash_acct.id, account_type='checking', opening_balance=0)
    db.session.add(from_ba); db.session.commit()
    # a second cash-like account for the receiving branch, distinct GL account required (unique)
    from app.accounts.models import Account
    recv_gl = Account(code='10117', name='Cash - Manila', account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db.session.add(recv_gl); db.session.commit()
    to_ba = BankAccount(branch_id=to_branch.id, code='BA-RECV', name='Recv',
                        account_id=recv_gl.id, account_type='checking', opening_balance=0)
    db.session.add(to_ba); db.session.commit()
    bt = BankTransfer(transfer_number='BT-2026-07-9002', from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=from_branch.id,
                      to_branch_id=to_branch.id, is_inter_branch=True, amount=Decimal('2000.00'),
                      transfer_date=date(2026, 7, 18), status='draft')
    db.session.add(bt); db.session.commit()
    return bt, from_ba, to_ba


def test_initiate_posts_sender_leg_only(db_session, main_branch, branch_manila, cash_account, admin_user):
    from app.bank_transfers.posting import post_transfer_initiate
    due_from, due_to = _assign_clearing_accounts(db_session)
    bt, from_ba, to_ba = _inter_transfer(db_session, main_branch, branch_manila, cash_account)
    je = post_transfer_initiate(bt, admin_user)
    db_session.commit()
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[due_from.id] == (Decimal('2000.00'), Decimal('0.00'))
    assert lines[from_ba.account_id] == (Decimal('0.00'), Decimal('2000.00'))
    assert je.branch_id == main_branch.id
    assert bt.status == 'in_transit'
    assert bt.sender_je_id == je.id
    assert bt.receiver_je_id is None


def test_confirm_posts_receiver_leg(db_session, main_branch, branch_manila, cash_account, admin_user):
    from app.bank_transfers.posting import post_transfer_initiate, post_transfer_confirm
    due_from, due_to = _assign_clearing_accounts(db_session)
    bt, from_ba, to_ba = _inter_transfer(db_session, main_branch, branch_manila, cash_account)
    post_transfer_initiate(bt, admin_user); db_session.commit()
    je = post_transfer_confirm(bt, admin_user)
    db_session.commit()
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in je.lines}
    assert lines[to_ba.account_id] == (Decimal('2000.00'), Decimal('0.00'))
    assert lines[due_to.id] == (Decimal('0.00'), Decimal('2000.00'))
    assert je.branch_id == branch_manila.id
    assert bt.status == 'completed'
    assert bt.receiver_je_id == je.id


def test_initiate_without_clearing_accounts_raises_fail_closed(db_session, main_branch, branch_manila,
                                                                cash_account, admin_user):
    from app.bank_transfers.posting import post_transfer_initiate
    from app.posting.control_accounts import ControlAccountError
    bt, from_ba, to_ba = _inter_transfer(db_session, main_branch, branch_manila, cash_account)
    with pytest.raises(ControlAccountError):
        post_transfer_initiate(bt, admin_user)


def test_reject_reverses_sender_leg_and_never_posts_receiver(db_session, main_branch, branch_manila,
                                                              cash_account, admin_user):
    from app.bank_transfers.posting import post_transfer_initiate, post_transfer_reversal
    due_from, due_to = _assign_clearing_accounts(db_session)
    bt, from_ba, to_ba = _inter_transfer(db_session, main_branch, branch_manila, cash_account)
    post_transfer_initiate(bt, admin_user); db_session.commit()
    reversal_je = post_transfer_reversal(bt, admin_user, new_status='rejected')
    db_session.commit()
    lines = {l.account_id: (l.debit_amount, l.credit_amount) for l in reversal_je.lines}
    # reversal is the mirror image of the sender leg
    assert lines[due_from.id] == (Decimal('0.00'), Decimal('2000.00'))
    assert lines[from_ba.account_id] == (Decimal('2000.00'), Decimal('0.00'))
    assert bt.status == 'rejected'
    assert bt.reversal_je_id == reversal_je.id
    assert bt.receiver_je_id is None
