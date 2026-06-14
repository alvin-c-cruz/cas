"""Account change-request history page (B-012).

A requester whose COA change was rejected must be able to see the rejection
and its notes. /accounts/change-requests lists every request with status,
reviewer, and review notes.
"""
import json

from app.accounts.approval_models import AccountChangeRequest
import pytest
pytestmark = [pytest.mark.accounts, pytest.mark.integration]




def login(client, username='accountant', password='accountant123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_request(db_session, status='rejected', **overrides):
    req = AccountChangeRequest(
        change_type='create',
        change_data=json.dumps({'code': '10199', 'name': 'Test Account',
                                'account_type': 'Asset', 'normal_balance': 'debit'}),
        requested_by=overrides.get('requested_by', 'accountant'),
        status=status,
        reviewed_by=overrides.get('reviewed_by', 'admin' if status != 'pending' else None),
        rejection_reason=overrides.get('rejection_reason',
                                       'Not needed' if status == 'rejected' else None),
        request_reason='History page test',
    )
    db_session.add(req)
    db_session.commit()
    return req


class TestAccountRequestHistory:
    def test_rejected_request_shows_status_reviewer_and_notes(self, client, db_session,
                                                              accountant_user, main_branch):
        accountant_user.add_branch(main_branch)
        make_request(db_session, status='rejected',
                     rejection_reason='Duplicate of existing account 10101')
        login(client)

        resp = client.get('/accounts/change-requests')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '10199' in html
        assert 'Rejected' in html
        assert 'admin' in html
        assert 'Duplicate of existing account 10101' in html
        assert 'History page test' in html

    def test_viewer_blocked(self, client, db_session, viewer_user, main_branch):
        viewer_user.add_branch(main_branch)
        db_session.commit()
        login(client, 'viewer', 'viewer123')
        resp = client.get('/accounts/change-requests', follow_redirects=True)
        html = resp.data.decode('utf-8')
        assert 'Only Accountants and Administrators can modify the Chart of Accounts.' in html
