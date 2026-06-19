import pytest
from app import create_app, db
from app.users.models import User
from app.branches.models import Branch
import os
pytestmark = [pytest.mark.journals, pytest.mark.integration]




@pytest.fixture(scope='function')
def setup(db_session):
    branch = Branch(name='Main', code='MAIN')
    db_session.add(branch)
    db_session.commit()

    users = {
        'admin': User(username='admin', email='admin@t.com', full_name='Admin',
                      role='admin', is_active=True),
        'accountant': User(username='accountant', email='acc@t.com', full_name='Acc',
                           role='accountant', is_active=True),
        'staff': User(username='staff', email='staff@t.com', full_name='Staff',
                      role='staff', is_active=True),
        'viewer': User(username='viewer', email='viewer@t.com', full_name='Viewer',
                       role='viewer', is_active=True),
    }
    for u in users.values():
        u.set_password('pass')
        u.branches.append(branch)
        db_session.add(u)
    db_session.commit()
    return users, branch


def login(client, username):
    client.post('/login', data={'username': username, 'password': 'pass'},
                follow_redirects=True)


def test_ap_journal_requires_login(client, setup):
    res = client.get('/journals/ap')
    assert res.status_code in (302, 401)


# admin/accountant/viewer are ungated for journals; staff is gated per-module
# (each /journals/* endpoint maps to a book permission in module_access.py), so
# a staff user without that permission is redirected. The positive
# staff-with-permission path is covered in test_module_access.py.
UNGATED_ROLES = ['admin', 'accountant', 'viewer']


def _assert_journal_access(client, branch, path):
    for role in UNGATED_ROLES:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get(path)
        assert res.status_code == 200, f"{role} got {res.status_code} on {path}"
        client.get('/logout')
    # staff without the book permission is redirected (per-module access gate)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get(path)
    assert res.status_code == 302, f"staff should be gated on {path}, got {res.status_code}"
    client.get('/logout')


def test_ap_journal_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/ap')


def test_voucher_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/voucher')


def test_cd_journal_access_by_role(client, setup):
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/cd')


def test_cr_journal_access_by_role(client, setup):
    """CR journal was activated (cash_receipts module) — it no longer redirects to
    under-development; it is a live journal gated like the others."""
    users, branch = setup
    _assert_journal_access(client, branch, '/journals/cr')


def test_journal_entries_redirects_to_voucher(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    res = client.get('/journal-entries')
    assert res.status_code == 302
    assert 'voucher' in res.location
