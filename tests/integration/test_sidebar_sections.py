"""Sidebar section visibility for permission-scoped accountants."""
import pytest
from app import db
from app.users.models import User
from app.branches.models import Branch

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


def test_sales_accountant_hides_empty_ledger_and_financial_reports(client, db_session, main_branch):
    # granted only sales-side modules — no Ledger / Financial Reports modules
    _accountant(db_session, main_branch,
                {'accounts_receivable': True, 'collections': True, 'customers': True})
    _login(client, 'salesacct', main_branch)
    body = client.get('/dashboard').data.decode()
    assert 'data-section="transactions"' in body      # has AR + collections
    assert 'data-section="ledger"' not in body         # no ledger modules -> hidden
    assert 'data-section="financial-reports"' not in body  # none -> hidden


def test_granting_a_ledger_module_shows_ledger_section(client, db_session, main_branch):
    _accountant(db_session, main_branch,
                {'accounts_receivable': True, 'general_ledger': True}, username='glacct')
    _login(client, 'glacct', main_branch)
    body = client.get('/dashboard').data.decode()
    assert 'data-section="ledger"' in body             # general_ledger granted -> shown


def test_accountant_without_master_data_still_sees_audit_log(client, db_session, main_branch):
    # no customers/vendors granted — Audit Log must NOT disappear
    _accountant(db_session, main_branch, {'accounts_receivable': True}, username='noacctmd')
    _login(client, 'noacctmd', main_branch)
    body = client.get('/dashboard').data.decode()
    assert '/audit-log' in body                         # audit log link present
    assert 'Audit Log' in body


def test_admin_sidebar_unchanged(client, db_session, admin_user, main_branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    body = client.get('/dashboard').data.decode()
    for sec in ('transactions', 'ledger', 'financial-reports', 'maintenance', 'admin'):
        assert f'data-section="{sec}"' in body
