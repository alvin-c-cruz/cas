"""Integration tests for WHT GL account picker fields (payable_account_id / receivable_account_id).

These tests verify that the WHT form exposes account picker inputs and that
the auto-approve path (single admin) persists the chosen GL account IDs.
"""
import pytest
from app.withholding_tax.models import WithholdingTax
from app.accounts.models import Account


def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


# Two-admin fixture so sole_admin_can_auto_approve() returns False for the
# form-fields test (which only checks HTML, not the approval outcome).
@pytest.fixture
def two_reviewers(admin_user, db_session, main_branch):
    """Two active admins — approval path goes to pending."""
    from app.users.models import User
    second_admin = User(username='admin2', email='admin2@example.com',
                        full_name='Second Admin', role='admin', is_active=True)
    second_admin.set_password('admin2pass')
    db_session.add(second_admin)
    db_session.commit()
    return admin_user, second_admin


def test_create_form_has_gl_account_fields(client, db_session, two_reviewers):
    """Both GL account picker inputs appear on the create form."""
    login(client)
    resp = client.get('/withholding-tax/create')
    assert resp.status_code == 200
    assert b'payable_account_id' in resp.data
    assert b'receivable_account_id' in resp.data


def test_auto_approve_sets_account_ids(client, db_session, admin_user, main_branch):
    """sole admin auto-approve path: payable and receivable account IDs are persisted."""
    payable_acct = Account(code='20301', name='WT Payable',
                           account_type='Liability', normal_balance='Credit',
                           is_active=True)
    recv_acct = Account(code='13501', name='WT Receivable',
                        account_type='Asset', normal_balance='Debit',
                        is_active=True)
    db_session.add_all([payable_acct, recv_acct])
    db_session.flush()

    login(client)  # sole admin → auto-approve
    resp = client.post('/withholding-tax/create', data={
        'code': 'WC010MA', 'name': 'Test WHT GL',
        'sales_name': '', 'description': '',
        'rate': '10.00', 'is_active': '1',
        'payable_account_id': str(payable_acct.id),
        'receivable_account_id': str(recv_acct.id),
        'request_reason': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    wt = WithholdingTax.query.filter_by(code='WC010MA').first()
    assert wt is not None
    assert wt.payable_account_id == payable_acct.id
    assert wt.receivable_account_id == recv_acct.id
