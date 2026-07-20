"""Dynamic submit-button label on the account form.

The account create/edit form serves both group (parent) headers (top-level,
no parent) and postable child accounts. The submit button reflects which one
is being created/edited:

- create, no parent  -> "Save Parent Account"
- create, has parent -> "Save Account"
- edit,   no parent  -> "Update Parent Account"
- edit,   has parent -> "Update Account"

BUG-COA-CREATE-GROUP-WORDING: the button used to say "Create Group"/"Update
Group", inconsistent with every other label on the same form ("PARENT
ACCOUNT" field label, its help text, the COA list's "PARENT" badge) which all
say "parent account", never "group". Renamed to "Create Parent Account" /
"Create Account" first, then app-wide (2026-07-20, owner directive) the
create-mode verb across ALL master-data forms changed from "Create" to
"Save" -- matching the transaction-document Save/Update pairing while still
keeping the record noun (unlike transaction docs, which stay plain).

Only the server-rendered *initial* label is unit-tested here; the live toggle
on parent-dropdown change is JS (covered manually via the browser).
"""
import pytest
from app.accounts.models import Account

pytestmark = [pytest.mark.accounts, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_group(db_session, code='90000', name='Test Group'):
    g = Account(code=code, name=name, account_type='Asset',
                normal_balance='debit', classification='Current')
    db_session.add(g)
    db_session.commit()
    return g


class TestAccountFormButtonLabel:
    def test_create_defaults_to_save_parent_account(self, client, db_session,
                                            accountant_user, main_branch):
        login(client)
        resp = client.get('/accounts/create')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Default create form has no parent selected -> it's a parent account.
        assert 'Save Parent Account' in html
        assert 'Save Account<' not in html

    def test_edit_group_shows_update_parent_account(self, client, db_session,
                                           accountant_user, main_branch):
        login(client)
        group = make_group(db_session)
        resp = client.get(f'/accounts/{group.id}/edit')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Update Parent Account' in html
        assert 'Update Account<' not in html

    def test_edit_child_shows_update_account(self, client, db_session,
                                             accountant_user, main_branch):
        login(client)
        group = make_group(db_session)
        child = Account(code='90001', name='Test Child', account_type='Asset',
                        normal_balance='debit', classification='Current',
                        parent_id=group.id)
        db_session.add(child)
        db_session.commit()
        resp = client.get(f'/accounts/{child.id}/edit')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Update Account<' in html
        assert 'Update Parent Account' not in html
