"""Integration tests for the Books of Accounts hub page (Task 7)."""
import pytest
from app import db
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_books_hub_lists_six_books(client, db_session, main_branch, admin_user):
    db.session.add(AppSettings(key='company_name', value='Acme Trading Inc.'))
    db.session.commit()
    _login(client, admin_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/books-of-accounts')
    assert resp.status_code == 200
    for label in [b'General Journal', b'General Ledger', b'Sales Journal',
                  b'Purchase Journal', b'Cash Receipts Book', b'Cash Disbursements Book']:
        assert label in resp.data
    assert b'Print All' in resp.data and b'Export All' in resp.data


def test_books_hub_requires_login(client, db_session):
    resp = client.get('/reports/books-of-accounts')
    assert resp.status_code in (302, 401)


def test_books_hub_requires_accountant_or_admin(client, db_session, main_branch, staff_user):
    _login(client, staff_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/reports/books-of-accounts', follow_redirects=False)
    assert resp.status_code == 302
