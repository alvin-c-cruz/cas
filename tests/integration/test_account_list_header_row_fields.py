"""COA list: a header row (top-level or has-children) still shows its own
real per-account data/actions when those don't actually depend on grouping.

Two BIR-tracked bugs, same root cause class (is_header conflated with
"suppress/block real per-account data or actions"):

- BUG-COA-LIST-HIDES-PARENT-NORMAL-BALANCE: every account has a real
  normal_balance (required at create); the list blanked it to '-' for any
  header row instead of showing the account's actual Dr/Cr.
- BUG-COA-CHILDLESS-PARENT-UNDELETABLE: the backend delete route
  (_account_delete_blockers) already refuses a delete when an account has
  actual children -- but the UI disabled the trash icon for ANY header row
  (top-level OR has-children), even a childless top-level account with
  nothing blocking its delete.
"""
import pytest
from app.accounts.models import Account

pytestmark = [pytest.mark.accounts, pytest.mark.integration]


def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


class TestHeaderRowNormalBalance:
    def test_childless_top_level_shows_real_normal_balance(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        g = Account(code='91000', name='Test Header', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()

        resp = client.get('/accounts/')
        html = resp.data.decode()
        assert '<span class="balance-debit">Dr</span>' in html, \
            'header row must show its real Dr/Cr, not "-"'


class TestHeaderRowDelete:
    def test_childless_top_level_delete_button_is_enabled(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        g = Account(code='91001', name='Test Header 2', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()

        resp = client.get('/accounts/')
        html = resp.data.decode()
        assert f'showDeleteModal({g.id},' in html, \
            'a childless top-level account has nothing blocking its delete -- ' \
            'the trash icon must be a clickable button, not the disabled span'

    def test_parent_with_children_delete_button_stays_disabled(
            self, client, db_session, accountant_user, main_branch):
        login(client)
        g = Account(code='91002', name='Real Parent', account_type='Asset',
                    normal_balance='debit', classification='Current')
        db_session.add(g)
        db_session.commit()
        child = Account(code='91003', name='Child', account_type='Asset',
                        normal_balance='debit', parent_id=g.id)
        db_session.add(child)
        db_session.commit()

        resp = client.get('/accounts/')
        html = resp.data.decode()
        assert f'showDeleteModal({g.id},' not in html, \
            'an account that actually has children must stay non-deletable in the UI'
        assert 'btn-icon-disabled' in html
