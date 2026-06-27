"""
End-to-end integration tests for per-module permission gating.

Exercises the before_request gate (Task 3) end-to-end:
- viewer blocked from a module not in their book_permissions
- viewer reaches a module that IS in their book_permissions
- admin is never gated (reaches everything)
"""
import pytest
from app import db
from app.users.models import User

pytestmark = [pytest.mark.integration]


def _login(client, username, password):
    client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def test_viewer_without_module_is_blocked(client, db_session, admin_user, main_branch):
    v = User(username='v_block', email='v_block@t.com', full_name='V', role='viewer', is_active=True)
    v.set_password('viewerpass123X!')
    v.set_book_permissions({'general_ledger': True})   # NOT accounts_payable
    db_session.add(v)
    db_session.flush()
    v.set_branches([main_branch])
    db_session.commit()

    _login(client, 'v_block', 'viewerpass123X!')
    resp = client.get('/accounts-payable', follow_redirects=True)
    assert b'do not have access to this module' in resp.data


def test_viewer_with_module_reaches_it(client, db_session, admin_user, main_branch):
    v = User(username='v_ok', email='v_ok@t.com', full_name='V', role='viewer', is_active=True)
    v.set_password('viewerpass123X!')
    v.set_book_permissions({'general_ledger': True})
    db_session.add(v)
    db_session.flush()
    v.set_branches([main_branch])
    db_session.commit()

    _login(client, 'v_ok', 'viewerpass123X!')
    resp = client.get('/reports/general-ledger')
    assert resp.status_code == 200


def test_admin_reaches_everything(client, db_session, admin_user, main_branch):
    _login(client, 'admin', 'admin123')
    assert client.get('/accounts-payable').status_code == 200
