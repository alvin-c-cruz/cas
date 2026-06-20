"""TDD gate: VAT Categories, Sales VAT Categories, and Withholding Tax nav links
must be admin-only; accountants must NOT see them in the rendered sidebar."""


def _login(client, user, password):
    return client.post('/login', data={'username': user.username, 'password': password},
                       follow_redirects=True)


def test_accountant_does_not_see_tax_nav(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, 'accountant123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/', follow_redirects=True)
    assert b'/vat-categories' not in resp.data
    assert b'/withholding-tax' not in resp.data
    assert b'/sales-vat-categories' not in resp.data


def test_admin_sees_tax_nav(client, db_session, admin_user, main_branch):
    _login(client, admin_user, 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/', follow_redirects=True)
    assert b'/sales-vat-categories' in resp.data
