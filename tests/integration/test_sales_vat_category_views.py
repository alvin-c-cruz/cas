"""Integration tests for sales_vat_categories blueprint (admin-only access)."""
from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest
from app.audit.models import AuditLog
from app.users.models import User


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

    def test_list_shows_nature_label_not_raw_code(self, client, db_session, admin_user, db_with_data):
        """BUG-SALES-VAT-NATURE-RAW-VALUE: the TRANSACTION NATURE column used
        to render the bare DB token ('regular') instead of the friendly
        label the create form itself uses ('Regular VATable')."""
        cat = SalesVATCategory(code='V12', name='VATable Sales - 12%', rate=12.00,
                               transaction_nature='regular', is_active=True)
        db_session.add(cat)
        db_session.commit()
        _login_admin(client, admin_user)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = db_with_data['branch'].id
        resp = client.get('/sales-vat-categories/')
        assert b'Regular VATable' in resp.data
        assert b'>regular<' not in resp.data


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

    def test_create_audit_note_says_single_admin(self, client, db_session, admin_user, db_with_data):
        from app.accounts.models import Account
        acct = Account.query.filter_by(is_active=True).first()
        _login_admin(client, admin_user)
        client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-S', 'name': 'Services', 'description': '', 'rate': '12.00',
            'transaction_nature': 'regular', 'output_vat_account_id': str(acct.id),
            'is_active': '1'}, follow_redirects=True)
        audit = AuditLog.query.filter_by(module='sales_vat_category', action='create').first()
        assert 'single admin' in (audit.notes or '')


class TestSalesVatSelfReviewBlock:
    """Four-eyes rule: with >= 2 active admins, admin A cannot review their own
    change request; admin B can."""

    def _create_second_admin(self, db_session, password='admin2pw'):
        second = User(username='admin2', email='admin2@test.com',
                      full_name='Admin Two', role='admin', is_active=True)
        second.set_password(password)
        db_session.add(second)
        db_session.commit()
        return second

    def test_admin_a_blocked_from_own_review(self, client, db_session, admin_user, db_with_data):
        """Admin A submits a create → pending (2 admins). Admin A then tries to
        review it and should get 302 + self-review flash."""
        from app.accounts.models import Account
        second_admin = self._create_second_admin(db_session)

        acct = Account.query.filter_by(is_active=True).first()

        # Log in as admin A and set branch session
        _login_admin(client, admin_user)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = db_with_data['branch'].id

        # POST create — 2 full-access users exist so sole_full_access_user_can_auto_approve() is False
        # → a SalesVATCategoryChangeRequest is created with status=pending
        client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-TEST1',
            'name': 'Test VAT 1',
            'description': '',
            'rate': '12.00',
            'transaction_nature': 'regular',
            'output_vat_account_id': str(acct.id),
            'is_active': '1',
        }, follow_redirects=True)

        cr = SalesVATCategoryChangeRequest.query.filter_by(
            status='pending', action='create').order_by(
            SalesVATCategoryChangeRequest.id.desc()).first()
        assert cr is not None, 'A pending change request must exist after create with 2 admins'
        assert cr.requested_by_id == admin_user.id

        # Admin A tries to review their own request
        resp = client.get(f'/sales-vat-categories/change-requests/{cr.id}/review',
                          follow_redirects=False)
        assert resp.status_code == 302, (
            'Admin A should be redirected (blocked) from reviewing their own request')
        # Confirm the flash message
        resp_follow = client.get(f'/sales-vat-categories/change-requests/{cr.id}/review',
                                 follow_redirects=True)
        assert b'cannot review your own change request' in resp_follow.data

    def test_admin_b_allowed_to_review(self, client, db_session, admin_user, db_with_data):
        """Admin B (a different admin) can load the review page for A's pending request."""
        from app.accounts.models import Account
        second_admin = self._create_second_admin(db_session)

        acct = Account.query.filter_by(is_active=True).first()

        # Admin A submits create → pending
        _login_admin(client, admin_user)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = db_with_data['branch'].id

        client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-TEST2',
            'name': 'Test VAT 2',
            'description': '',
            'rate': '12.00',
            'transaction_nature': 'regular',
            'output_vat_account_id': str(acct.id),
            'is_active': '1',
        }, follow_redirects=True)

        cr = SalesVATCategoryChangeRequest.query.filter_by(
            status='pending', action='create').order_by(
            SalesVATCategoryChangeRequest.id.desc()).first()
        assert cr is not None, 'A pending change request must exist'

        # Log in as admin B
        client.get('/logout')
        client.post('/login', data={'username': 'admin2', 'password': 'admin2pw'},
                    follow_redirects=True)
        with client.session_transaction() as sess:
            sess['selected_branch_id'] = db_with_data['branch'].id

        # Admin B should be able to load the review page
        resp = client.get(f'/sales-vat-categories/change-requests/{cr.id}/review')
        assert resp.status_code == 200, 'Admin B should be allowed to review admin A\'s request'
