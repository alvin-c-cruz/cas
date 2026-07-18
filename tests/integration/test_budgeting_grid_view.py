import pytest
from decimal import Decimal

from app.settings import AppSettings
from app.utils.cache_helpers import clear_module_config_cache
from app.accounts.models import Account
from app.budgeting.models import BudgetLine

pytestmark = [pytest.mark.integration]


def _enable_budgeting(db_session):
    AppSettings.set_setting('module_enabled:budgeting', '1')
    db_session.commit()
    clear_module_config_cache()


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def _revenue_leaf(db_session, code='4001', name='Sales Revenue'):
    # A top-level account with no parent is always a header (hierarchy is derived --
    # top-level or has-children -> header), matching real COA convention -- a leaf
    # fixture needs a parent group account, not a bare top-level Account.
    group = Account(code='4000', name='Revenue', account_type='Revenue',
                    normal_balance='Credit', is_active=True)
    db_session.add(group)
    db_session.commit()
    leaf = Account(code=code, name=name, account_type='Revenue',
                   normal_balance='Credit', is_active=True, parent_id=group.id)
    db_session.add(leaf)
    db_session.commit()
    return leaf


def _asset_leaf(db_session, code='1001', name='Cash on Hand'):
    group = Account(code='1000', name='Assets', account_type='Asset',
                    normal_balance='Debit', is_active=True)
    db_session.add(group)
    db_session.commit()
    leaf = Account(code=code, name=name, account_type='Asset',
                   normal_balance='Debit', is_active=True, parent_id=group.id)
    db_session.add(leaf)
    db_session.commit()
    return leaf


def test_grid_shows_eligible_accounts_only(client, db_session, main_branch, admin_user,
                                           login_user):
    _enable_budgeting(db_session)
    rev = _revenue_leaf(db_session)
    asset = _asset_leaf(db_session)

    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/budgeting')
    assert resp.status_code == 200
    assert b'Sales Revenue' in resp.data
    assert b'Cash on Hand' not in resp.data


def test_grid_prefills_existing_amounts(client, db_session, main_branch, admin_user, login_user):
    _enable_budgeting(db_session)
    rev = _revenue_leaf(db_session)
    db_session.add(BudgetLine(branch_id=main_branch.id, account_id=rev.id,
                              fiscal_year=2027, month=1, amount=Decimal('15000.00')))
    db_session.commit()

    login_user(client, 'admin', 'admin123')
    _select_branch(client, main_branch.id)
    resp = client.get('/budgeting?fiscal_year=2027')
    assert resp.status_code == 200
    assert b'15000.00' in resp.data


def test_grid_denies_staff(client, db_session, main_branch, staff_user, login_user):
    # full_access_required redirects to dashboard.index, which does not render
    # flashed messages -- so the flash text is asserted where it IS rendered
    # (the save-view test in Task 4), and here we just prove access was denied.
    _enable_budgeting(db_session)
    staff_user.set_branches([main_branch])
    db_session.commit()
    login_user(client, 'staff', 'staff123')
    resp = client.get('/budgeting')
    assert resp.status_code == 302  # full_access_required denies -> redirect, not the grid


def test_grid_denies_viewer(client, db_session, main_branch, viewer_user, login_user):
    _enable_budgeting(db_session)
    viewer_user.set_branches([main_branch])
    db_session.commit()
    login_user(client, 'viewer', 'viewer123')
    resp = client.get('/budgeting')
    assert resp.status_code == 302  # full_access_required denies -> redirect, not the grid


def test_grid_allows_chief_accountant(client, db_session, main_branch, chief_accountant_user,
                                      login_user):
    _enable_budgeting(db_session)
    login_user(client, 'chief', 'chief123')
    _select_branch(client, main_branch.id)
    resp = client.get('/budgeting')
    assert resp.status_code == 200
