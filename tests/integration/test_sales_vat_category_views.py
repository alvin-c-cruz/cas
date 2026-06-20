"""Integration tests for sales_vat_categories blueprint (admin-only access)."""
from app.sales_vat_categories.models import SalesVATCategory
from app.audit.models import AuditLog


def _login_admin(client, admin_user):
    return client.post('/login', data={
        'username': admin_user.username, 'password': 'admin123'
    }, follow_redirects=True)


def _login_accountant(client, accountant_user):
    return client.post('/login', data={
        'username': accountant_user.username, 'password': 'accountant123'
    }, follow_redirects=True)


class TestSalesVatAccess:
    def test_accountant_denied_list(self, client, db_session, accountant_user):
        _login_accountant(client, accountant_user)
        resp = client.get('/sales-vat-categories/', follow_redirects=False)
        # admin_required redirects non-admins to dashboard
        assert resp.status_code == 302

    def test_admin_allowed_list(self, client, db_session, admin_user, db_with_data):
        _login_admin(client, admin_user)
        # Set branch session so validate_branch_session doesn't redirect
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = db_with_data['branch'].id
        resp = client.get('/sales-vat-categories/')
        assert resp.status_code == 200


class TestSalesVatCreate:
    def test_sole_admin_create_applies_and_audits(self, client, db_session, admin_user, db_with_data):
        from app.accounts.models import Account
        acct = Account.query.filter_by(is_active=True).first()
        _login_admin(client, admin_user)
        resp = client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-G',
            'name': 'Sale of Goods (12%)',
            'description': '',
            'rate': '12.00',
            'transaction_nature': 'regular',
            'output_vat_account_id': str(acct.id),
            'is_active': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        row = SalesVATCategory.query.filter_by(code='SVAT-G').first()
        assert row is not None, 'Sole admin should auto-apply the create'
        audit = AuditLog.query.filter_by(
            module='sales_vat_category', action='create'
        ).first()
        assert audit is not None, 'Audit row with module=sales_vat_category, action=create must exist'
