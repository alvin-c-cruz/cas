"""Integration tests for branch session validation before_request hook."""
import pytest
from flask import session
pytestmark = [pytest.mark.branches, pytest.mark.integration]



def login(client, password='admin123'):
    resp = client.post('/login', data={'username': 'admin', 'password': password},
                       follow_redirects=True)
    return resp


class TestBranchSessionValidation:
    def test_stale_branch_id_redirects_to_select_branch(self, client, db_session,
                                                         admin_user, main_branch):
        from app.branches.models import Branch
        extra = Branch(name='Extra2', code='EX2', is_active=True)
        db_session.add(extra)
        db_session.commit()
        login(client)
        # Inject a non-existent branch ID; multiple branches exist so no auto-select
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = 99999
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']

    def test_stale_branch_id_auto_selects_when_single_branch(self, client, db_session,
                                                               admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = 99999  # non-existent branch
        resp = client.get('/dashboard', follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('selected_branch_id') == main_branch.id

    def test_missing_branch_id_auto_selects_single_branch(self, client, db_session,
                                                           admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess.pop('selected_branch_id', None)
        resp = client.get('/dashboard', follow_redirects=True)
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('selected_branch_id') == main_branch.id

    def test_valid_branch_id_passes_through(self, client, db_session,
                                             admin_user, main_branch):
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = main_branch.id
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 200

    def test_exempt_routes_skip_validation(self, client, db_session, admin_user):
        # /login should not be redirected even with no branch in session
        resp = client.get('/login', follow_redirects=False)
        assert resp.status_code == 200

    def test_deactivated_branch_redirects_to_select_branch(self, client, db_session,
                                                             admin_user, main_branch):
        from app.branches.models import Branch

        # Create two extra branches so that after deactivating one,
        # multiple active branches remain (preventing auto-select)
        extra = Branch(name='Extra', code='EXT', is_active=True)
        extra2 = Branch(name='Extra3', code='EX3', is_active=True)
        db_session.add_all([extra, extra2])
        db_session.commit()
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = extra.id
        # Now deactivate that branch; main_branch + extra2 still active → redirect
        extra.is_active = False
        db_session.commit()
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']
