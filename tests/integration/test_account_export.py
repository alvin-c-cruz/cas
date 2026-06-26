"""Export (download) tests for the Chart of Accounts — Excel + CSV.

The COA export is @login_required (same access as VIEWING the COA — non-PII reference
data), unlike the customer export which is accountant/admin-gated for PII reasons.
"""
import csv
import io

import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user, main_branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def _seed_group_and_leaf(db_session):
    """A group header (50220) with one postable child (50226)."""
    from app.accounts.models import Account
    parent = Account(code='50220', name='General and Administrative Expenses',
                     account_type='Administrative Expense', normal_balance='debit',
                     is_active=True)
    db_session.add(parent)
    db_session.flush()
    child = Account(code='50226', name='Office Supplies Expense',
                    account_type='Administrative Expense', normal_balance='debit',
                    is_active=True, parent_id=parent.id)
    db_session.add(child)
    db_session.commit()
    return parent, child


def test_coa_csv_export_includes_account_rows_and_flags(
        client, db_session, accountant_user, main_branch):
    """CSV carries code/name/type, the child's parent code, and the postable flag
    (group=No, leaf=Yes) — locks the export columns + the derived postable logic."""
    _seed_group_and_leaf(db_session)
    _login(client, accountant_user, main_branch, 'accountant123')

    resp = client.get('/accounts/export/csv')

    assert resp.status_code == 200
    assert resp.headers.get('Content-Type', '').startswith('text/csv')
    body = resp.data.decode()
    assert 'Office Supplies Expense' in body

    rows = {r['Code']: r for r in csv.DictReader(io.StringIO(body))}
    assert 'Postable' in next(iter(rows.values())), 'header row must include Postable'
    assert rows['50226']['Type'] == 'Administrative Expense'
    assert rows['50226']['Parent Code'] == '50220'
    assert rows['50226']['Postable'] == 'Yes', 'a leaf with a parent is postable'
    assert rows['50220']['Postable'] == 'No', 'a group header is non-postable'


def test_coa_excel_export_content_type(
        client, db_session, accountant_user, main_branch):
    """Excel export streams an .xlsx spreadsheet."""
    _seed_group_and_leaf(db_session)
    _login(client, accountant_user, main_branch, 'accountant123')

    resp = client.get('/accounts/export/excel', follow_redirects=False)

    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers.get('Content-Type', '')


def test_coa_export_requires_login(client, db_session):
    """Unauthenticated COA export redirects to login, does not stream a file."""
    resp = client.get('/accounts/export/csv', follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert '/login' in resp.headers.get('Location', '')
