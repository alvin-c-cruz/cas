"""Sidebar section visibility for permission-scoped accountants."""
import pytest
from app.users.models import User

pytestmark = [pytest.mark.integration]


def _accountant(db_session, branch, perms, username='salesacct'):
    u = User(username=username, email=f'{username}@t.com', full_name='Sales Acct',
             role='accountant', is_active=True)
    u.set_password('Sup3rSecret!23')
    u.set_book_permissions(perms)
    db_session.add(u)
    db_session.flush()
    u.set_branches([branch])
    db_session.commit()
    return u


def _login(client, username, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': username, 'password': 'Sup3rSecret!23'},
                follow_redirects=True)


def test_sales_accountant_hides_empty_accounting_area(client, db_session, main_branch):
    # granted only sales-side modules — no Accounting / Compliance area modules
    _accountant(db_session, main_branch,
                {'accounts_receivable': True, 'collections': True, 'customers': True})
    _login(client, 'salesacct', main_branch)
    body = client.get('/dashboard').data.decode()
    assert 'data-area="sales"' in body          # has AR + collections + customers
    assert 'data-area="accounting"' not in body  # no accounting-area modules -> hidden
    assert 'data-area="compliance"' not in body  # no compliance-area modules -> hidden


def test_granting_a_ledger_module_shows_accounting_area(client, db_session, main_branch):
    _accountant(db_session, main_branch,
                {'accounts_receivable': True, 'general_ledger': True}, username='glacct')
    _login(client, 'glacct', main_branch)
    body = client.get('/dashboard').data.decode()
    assert 'data-area="accounting"' in body      # general_ledger is in Accounting/Ledger


def test_accountant_without_master_data_still_sees_audit_log(client, db_session, main_branch):
    # no customers/vendors granted — Audit Log must NOT disappear (it lives in Staff Mgmt section)
    _accountant(db_session, main_branch, {'accounts_receivable': True}, username='noacctmd')
    _login(client, 'noacctmd', main_branch)
    body = client.get('/dashboard').data.decode()
    assert '/audit-log' in body                  # audit log link present
    assert 'Audit Log' in body


def test_admin_sidebar_has_area_sections_and_admin(client, db_session, admin_user, main_branch):
    # Admin sees all four core areas via the tree, plus the pinned Admin section
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    body = client.get('/dashboard').data.decode()
    for area in ('sales', 'purchases', 'accounting', 'compliance'):
        assert f'data-area="{area}"' in body, f"Expected area '{area}' in admin sidebar"
    assert 'data-section="admin"' in body        # Admin section is pinned after the tree
