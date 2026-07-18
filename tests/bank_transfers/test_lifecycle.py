"""End-to-end lifecycle + authz tests (R-04 slice 2)."""
from datetime import date
from decimal import Decimal
import pytest
from app import db
from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _enable(db_session):
    AppSettings.set_setting('module_enabled:bank_transfers', '1')
    AppSettings.set_setting('module_enabled:bank_accounts', '1')
    db_session.commit(); clear_module_config_cache()


def _clearing_accounts(db_session):
    from app.accounts.models import Account
    due_from = Account(code='10218', name='Due from', account_type='Asset', normal_balance='Debit', is_active=True)
    due_to = Account(code='20113', name='Due to', account_type='Liability', normal_balance='Credit', is_active=True)
    db.session.add_all([due_from, due_to]); db.session.commit()
    AppSettings.set_setting('inter_branch_due_from_account_code', due_from.code)
    AppSettings.set_setting('inter_branch_due_to_account_code', due_to.code)
    db.session.commit()


def _bank_accounts(db_session, from_branch, to_branch, cash_account):
    from app.bank_accounts.models import BankAccount
    from app.accounts.models import Account
    from_ba = BankAccount(branch_id=from_branch.id, code='BA-X', name='X',
                          account_id=cash_account.id, account_type='checking', opening_balance=0)
    recv_gl = Account(code='10118', name='Cash - Manila 2', account_type='Asset',
                      normal_balance='Debit', is_active=True)
    db.session.add_all([from_ba, recv_gl]); db.session.commit()
    to_ba = BankAccount(branch_id=to_branch.id, code='BA-Y', name='Y',
                        account_id=recv_gl.id, account_type='checking', opening_balance=0)
    db.session.add(to_ba); db.session.commit()
    return from_ba, to_ba


def test_staff_at_from_branch_cannot_initiate(client, staff_user, db_session, main_branch,
                                              branch_manila, cash_account):
    _enable(db_session); _clearing_accounts(db_session)
    from_ba, to_ba = _bank_accounts(db_session, main_branch, branch_manila, cash_account)
    # Grant staff the bank_transfers book so this test isolates the ROLE gate
    # (accountant+ only for money-moving transitions) from the per-user module
    # gate (mirrors the 'payroll': True precedent already in the staff_user
    # fixture for other optional+per_user modules). staff_user also carries no
    # branch assignment by default (unlike accountant_user) -- assign main_branch
    # so the branch-session validation before_request hook doesn't bounce the
    # login to the branch picker.
    staff_user.set_book_permissions({**staff_user.get_book_permissions(), 'bank_transfers': True})
    staff_user.set_branches([main_branch])
    db_session.commit()
    _login(client, staff_user, main_branch)

    # Staff CAN create a draft -- create()/edit() are staff+ (draft-only edit).
    resp = client.post('/bank-transfers/new', data={
        'from_bank_account_id': from_ba.id, 'to_bank_account_id': to_ba.id,
        'amount': '500.00', 'transfer_date': '2026-07-18', 'memo': '',
    }, follow_redirects=True)
    assert resp.status_code == 200

    from app.bank_transfers.models import BankTransfer
    bt = BankTransfer.query.filter_by(from_bank_account_id=from_ba.id,
                                      to_bank_account_id=to_ba.id).first()
    assert bt is not None
    assert bt.status == 'draft'

    # The money-moving transitions (initiate/confirm/reject/cancel/post) are
    # accountant+ only -- staff is rejected and the transfer stays untouched.
    resp2 = client.post(f'/bank-transfers/{bt.id}/initiate',
                        data={'row_version': bt.row_version}, follow_redirects=True)
    assert resp2.status_code == 200
    db_session.refresh(bt)
    assert bt.status == 'draft'


def test_full_inter_branch_round_trip(client, admin_user, db_session, main_branch,
                                      branch_manila, cash_account):
    _enable(db_session); _clearing_accounts(db_session)
    from_ba, to_ba = _bank_accounts(db_session, main_branch, branch_manila, cash_account)
    _login(client, admin_user, main_branch)
    from app.bank_transfers.models import BankTransfer
    from app.bank_transfers.numbering import generate_bank_transfer_number
    bt = BankTransfer(transfer_number=generate_bank_transfer_number(), from_bank_account_id=from_ba.id,
                      to_bank_account_id=to_ba.id, from_branch_id=main_branch.id,
                      to_branch_id=branch_manila.id, is_inter_branch=True, amount=Decimal('750.00'),
                      transfer_date=date(2026, 7, 18), status='draft')
    db_session.add(bt); db_session.commit()

    resp = client.post(f'/bank-transfers/{bt.id}/initiate', data={'row_version': bt.row_version},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(bt)
    assert bt.status == 'in_transit'

    _login(client, admin_user, branch_manila)   # admin has full access to all branches
    resp = client.post(f'/bank-transfers/{bt.id}/confirm', data={'row_version': bt.row_version},
                       follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(bt)
    assert bt.status == 'completed'
