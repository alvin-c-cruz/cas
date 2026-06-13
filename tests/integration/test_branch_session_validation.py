"""Integration tests for branch session validation before_request hook."""
import pytest
from flask import session


def login(client, password='admin123'):
    resp = client.post('/login', data={'username': 'admin', 'password': password},
                       follow_redirects=True)
    return resp


class TestBranchSessionValidation:
    def test_stale_branch_id_redirects_to_select_branch(self, client, db_session,
                                                         admin_user, main_branch):
        login(client)
        # Inject a non-existent branch ID into the session
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = 99999
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']

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
        extra = Branch(name='Extra', code='EXT', is_active=True)
        db_session.add(extra)
        db_session.commit()
        login(client)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = extra.id
        # Now deactivate that branch
        extra.is_active = False
        db_session.commit()
        resp = client.get('/dashboard', follow_redirects=False)
        assert resp.status_code == 302
        assert '/select-branch' in resp.headers['Location']
