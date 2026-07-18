"""End-to-end petty cash lifecycle + authz (R-04 slice 4)."""
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
    AppSettings.set_setting('module_enabled:petty_cash', '1')
    AppSettings.set_setting('module_enabled:bank_accounts', '1')
    db_session.commit(); clear_module_config_cache()


def _bank_account(db_session, branch, account, code='BA-FUND'):
    from app.bank_accounts.models import BankAccount
    ba = BankAccount(branch_id=branch.id, code=code, name='Funding',
                     account_id=account.id, account_type='checking', opening_balance=0)
    db_session.add(ba); db_session.commit()
    return ba


def _leaf_account(code, name, account_type, normal_balance):
    """get_postable_accounts() (used by this module's account_id/expense_account_id
    SelectFields) requires parent_id NOT NULL -- a bare top-level account (like the
    conftest cash_account/revenue_account fixtures) counts as a PARENT, not a leaf,
    under this app's derived-hierarchy rule, and so is silently excluded from form
    choices. Give every account posted through a real form its own parent."""
    from app.accounts.models import Account
    parent = Account(code=code + '00', name=name + ' (Group)', account_type=account_type,
                     normal_balance=normal_balance, is_active=True)
    db.session.add(parent); db.session.commit()
    leaf = Account(code=code, name=name, account_type=account_type,
                   normal_balance=normal_balance, parent_id=parent.id, is_active=True)
    db.session.add(leaf); db.session.commit()
    return leaf


def _grant_staff_petty_cash(staff_user, branch, db_session):
    """staff_user carries no branch assignment by default (unlike accountant_user) --
    without one, the branch-session before_request gate bounces the login to the
    picker and force-logs-out a user with zero accessible branches (same trap
    documented in bank_transfers' test_lifecycle.py). petty_cash is optional+per_user,
    so also grant the book permission (mirrors the existing 'payroll'/'bank_transfers'
    precedents already baked into the staff_user fixture)."""
    staff_user.set_book_permissions({**staff_user.get_book_permissions(), 'petty_cash': True})
    staff_user.set_branches([branch])
    db_session.commit()


def test_staff_can_record_a_voucher(client, staff_user, db_session, main_branch, cash_account):
    _enable(db_session)
    _grant_staff_petty_cash(staff_user, main_branch, db_session)
    expense_leaf = _leaf_account('5010', 'Office Supplies', 'Expense', 'Debit')
    from app.petty_cash.models import PettyCashFund
    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-V1', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(fund); db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post(f'/petty-cash/funds/{fund.id}/vouchers/new', data={
        'payee': 'Store', 'expense_account_id': expense_leaf.id, 'amount': '150.00',
        'description': 'Supplies', 'receipt_ref': 'OR-500',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.petty_cash.models import PettyCashVoucher
    assert PettyCashVoucher.query.filter_by(fund_id=fund.id, payee='Store').count() == 1


def test_staff_cannot_establish_a_fund(client, staff_user, db_session, main_branch,
                                       revenue_account):
    _enable(db_session)
    _grant_staff_petty_cash(staff_user, main_branch, db_session)
    gl_leaf = _leaf_account('1005', 'Petty Cash Fund', 'Asset', 'Debit')
    ba = _bank_account(db_session, main_branch, revenue_account)
    _login(client, staff_user, main_branch)
    resp = client.post('/petty-cash/funds/new', data={
        'code': 'PCF-NOPE', 'name': 'Nope', 'account_id': gl_leaf.id,
        'custodian': 'X', 'float_amount': '1000.00', 'funding_bank_account_id': ba.id,
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.petty_cash.models import PettyCashFund
    assert PettyCashFund.query.filter_by(code='PCF-NOPE').count() == 0
    assert b'permission' in resp.data.lower()


def test_accountant_can_establish_a_fund(client, accountant_user, db_session, main_branch,
                                         revenue_account):
    _enable(db_session)
    gl_leaf = _leaf_account('1005', 'Petty Cash Fund', 'Asset', 'Debit')
    ba = _bank_account(db_session, main_branch, revenue_account)
    _login(client, accountant_user, main_branch)
    resp = client.post('/petty-cash/funds/new', data={
        'code': 'PCF-EST1', 'name': 'Established Fund', 'account_id': gl_leaf.id,
        'custodian': 'Juan', 'float_amount': '2000.00', 'funding_bank_account_id': ba.id,
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.petty_cash.models import PettyCashFund
    fund = PettyCashFund.query.filter_by(code='PCF-EST1').first()
    assert fund is not None
    from app.journal_entries.models import JournalEntry
    assert JournalEntry.query.filter_by(description=f'Establish Petty Cash Fund {fund.code}').count() == 1


def test_staff_cannot_replenish(client, staff_user, db_session, main_branch, cash_account):
    _enable(db_session)
    _grant_staff_petty_cash(staff_user, main_branch, db_session)
    from app.petty_cash.models import PettyCashFund
    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-V2', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(fund); db_session.commit()
    _login(client, staff_user, main_branch)
    resp = client.post(f'/petty-cash/funds/{fund.id}/replenish', data={
        'physical_cash_counted': '2000.00', 'selected_voucher_ids': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'permission' in resp.data.lower()


def test_full_replenish_round_trip(client, accountant_user, db_session, main_branch, cash_account,
                                   revenue_account, staff_user):
    _enable(db_session)
    from app.petty_cash.models import PettyCashFund
    from app.petty_cash.posting import record_voucher
    from app.accounts.models import Account
    due_to_gl = Account(code='20122', name='Due to Petty Cash Custodian', account_type='Liability',
                        normal_balance='Credit', is_active=True)
    db.session.add(due_to_gl); db.session.commit()
    AppSettings.set_setting('petty_cash_due_to_custodian_account_code', due_to_gl.code)
    db_session.commit()

    fund = PettyCashFund(branch_id=main_branch.id, code='PCF-RT', name='Fund',
                         account_id=cash_account.id, float_amount=Decimal('2000.00'))
    db_session.add(fund); db_session.commit()
    v1 = record_voucher(fund, payee='Store', expense_account_id=revenue_account.id, amount=Decimal('300.00'),
                        description='', receipt_ref='', created_by=staff_user)
    db_session.commit()

    _login(client, accountant_user, main_branch)
    resp = client.post(f'/petty-cash/funds/{fund.id}/replenish', data={
        'physical_cash_counted': '1700.00', 'selected_voucher_ids': str(v1.id),
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.petty_cash.models import PettyCashReplenishment, PettyCashVoucher
    rep = PettyCashReplenishment.query.filter_by(fund_id=fund.id).first()
    assert rep is not None and rep.status == 'posted'
    v1_after = db.session.get(PettyCashVoucher, v1.id)
    assert v1_after.status == 'replenished'
