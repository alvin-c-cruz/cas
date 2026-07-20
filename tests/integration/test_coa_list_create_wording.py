"""BUG-COA-LIST-ADD-VS-CREATE-WORDING: the COA list page's launch button and
matching true-empty message said "Add Account", inconsistent with sibling
master-data list pages (Customers/Vendors say "Create X") and with
projects/cas/CLAUDE.md's own documented convention -- "Reference/master
records (vendors, customers, accounts, branches, users) keep 'Create'"."""
import pytest

pytestmark = [pytest.mark.integration]


def _login(client, user, main_branch, password):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/login', data={'username': user.username, 'password': password},
                follow_redirects=True)


def test_launch_button_says_create_not_add(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = client.get('/accounts/')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Create Account' in html
    assert 'Add Account' not in html


def test_true_empty_message_says_create_not_add(client, db_session, accountant_user, main_branch):
    """Zero accounts in the DB -- the server-rendered true-empty message
    must echo the same 'Create Account' wording as the launch button."""
    _login(client, accountant_user, main_branch, 'accountant123')
    resp = client.get('/accounts/')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'Click "Create Account" to create your first account.' in html
    assert 'Add Account' not in html
