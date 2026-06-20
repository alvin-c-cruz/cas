"""TDD gate: withholding_tax blueprint must be admin-only + sales_name persisted."""
from app.withholding_tax.models import WithholdingTax


def _login(client, user, password):
    return client.post('/login', data={'username': user.username, 'password': password},
                       follow_redirects=True)


def test_accountant_denied(client, db_session, accountant_user, main_branch):
    _login(client, accountant_user, 'accountant123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/withholding-tax/', follow_redirects=False).status_code == 302


def test_admin_create_persists_sales_name(client, db_session, admin_user, main_branch):
    _login(client, admin_user, 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/withholding-tax/create', data={
        'code': 'WC010', 'name': 'Professional Fees - Individuals',
        'sales_name': 'Professional Fees Income - Individual', 'description': '',
        'rate': '10.00', 'is_active': '1'}, follow_redirects=True)
    wt = WithholdingTax.query.filter_by(code='WC010').first()
    assert wt is not None and wt.sales_name == 'Professional Fees Income - Individual'
