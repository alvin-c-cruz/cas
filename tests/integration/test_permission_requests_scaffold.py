import pytest

pytestmark = pytest.mark.integration


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _select_branch(client, branch_id):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch_id


def test_new_permission_request_route_exists_and_gates_non_ca(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/permission-requests/new', follow_redirects=False)
    # accountant (not chief_accountant) must be redirected away, not see the form
    assert resp.status_code == 302


def test_new_permission_request_route_reachable_by_ca(client, db_session, chief_accountant_user, main_branch):
    _login(client, chief_accountant_user)
    _select_branch(client, main_branch.id)
    resp = client.get('/permission-requests/new')
    assert resp.status_code == 200
    assert b'Reason' in resp.data
