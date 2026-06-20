"""TDD gate: vat_categories blueprint must be admin-only on every route."""


def _login(client, user, password):
    return client.post('/login', data={'username': user.username, 'password': password},
                       follow_redirects=True)


def test_accountant_denied_vat_list(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, 'accountant123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/vat-categories/', follow_redirects=False)
    assert resp.status_code == 302


def test_admin_allowed_vat_list(client, db_session, admin_user, main_branch):
    _login(client, admin_user, 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/vat-categories/').status_code == 200
