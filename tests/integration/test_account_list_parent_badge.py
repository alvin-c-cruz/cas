"""COA list: a parent account is badged 'PARENT' from creation.

A parent/group is an account that is top-level (no parent) OR has children.
Such accounts show a 'PARENT' badge in the Type column from the moment they are
created (i.e. before they have any children). Postable accounts (those with a
parent) show their account type instead.
"""
import pytest
from app.accounts.models import Account

pytestmark = [pytest.mark.accounts, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestParentBadge:
    def test_childless_top_level_is_badged_parent(self, client, db_session,
                                                  accountant_user, main_branch):
        login(client)
        # top-level header with NO children yet
        g = Account(code='90000', name='Test Header', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()
        resp = client.get('/accounts/')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'PARENT' in html          # badged from creation
        assert 'GROUP' not in html       # old label retired

    def test_child_account_shows_its_type_not_parent(self, client, db_session,
                                                     accountant_user, main_branch):
        login(client)
        g = Account(code='90000', name='Test Header', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()
        child = Account(code='90001', name='Postable', account_type='Asset',
                        normal_balance='debit', parent_id=g.id)
        db_session.add(child)
        db_session.commit()
        resp = client.get('/accounts/')
        html = resp.data.decode()
        assert 'PARENT' in html           # the header
        assert 'badge-asset' in html      # the child shows its type badge
