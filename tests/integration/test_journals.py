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


def test_ap_journal_accessible_all_roles(client, setup):
    users, branch = setup
    for role in ['admin', 'accountant', 'staff', 'viewer']:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get('/journals/ap')
        assert res.status_code == 200, f"{role} got {res.status_code} on /journals/ap"
        client.get('/logout')


def test_voucher_accessible_all_roles(client, setup):
    users, branch = setup
    for role in ['admin', 'accountant', 'staff', 'viewer']:
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = branch.id
        login(client, role)
        res = client.get('/journals/voucher')
        assert res.status_code == 200, f"{role} got {res.status_code} on /journals/voucher"
        client.get('/logout')


def test_cr_redirects_to_under_development(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get('/journals/cr')
    assert res.status_code == 302
    assert 'under_development' in res.location or 'Cash+Receipts' in res.location or 'Cash' in res.location


def test_cd_redirects_to_under_development(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'staff')
    res = client.get('/journals/cd')
    assert res.status_code == 302
    assert 'under_development' in res.location or 'Cash' in res.location


def test_journal_entries_redirects_to_voucher(client, setup):
    users, branch = setup
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    login(client, 'accountant')
    res = client.get('/journal-entries')
    assert res.status_code == 302
    assert 'voucher' in res.location
