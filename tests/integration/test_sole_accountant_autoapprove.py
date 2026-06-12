"""B-011: the sole-accountant auto-approve rule.

Owner decision 2026-06-12: admins are separate from accountants.
- The single active accountant auto-approves their own COA/VAT/WHT changes
  even when admins exist
- Admins never auto-approve (always pending)
- With two or more active accountants, requests go pending
"""
from app.accounts.models import Account
from app.accounts.approval_models import AccountChangeRequest
from app.users.models import User


def login(client, username, password):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def account_form_data(code='10199'):
    return {
        'code': code,
        'name': 'Auto Approve Test',
        'account_type': 'Asset',
        'normal_balance': 'debit',
        'request_reason': 'B-011 rule test',
    }


def make_second_accountant(db_session):
    user = User(username='accountant2', email='acct2@test.com',
                full_name='Second Accountant', role='accountant', is_active=True)
    user.set_password('accountant123')
    db_session.add(user)
    db_session.commit()
    return user


class TestSoleAccountantAutoApprove:
    def test_sole_accountant_auto_approves_despite_admin(self, client, db_session,
                                                         admin_user, accountant_user,
                                                         main_branch):
        login(client, 'accountant', 'accountant123')
        client.post('/accounts/create', data=account_form_data(), follow_redirects=True)

        account = Account.query.filter_by(code='10199').first()
        assert account is not None, 'sole accountant should auto-approve instantly'
        req = AccountChangeRequest.query.order_by(AccountChangeRequest.id.desc()).first()
        assert req.status == 'approved'
        assert req.reviewed_by == 'accountant'

    def test_admin_always_goes_pending(self, client, db_session, admin_user,
                                       accountant_user, main_branch):
        login(client, 'admin', 'admin123')
        client.post('/accounts/create', data=account_form_data(), follow_redirects=True)

        assert Account.query.filter_by(code='10199').first() is None
        req = AccountChangeRequest.query.order_by(AccountChangeRequest.id.desc()).first()
        assert req.status == 'pending'

    def test_two_accountants_go_pending(self, client, db_session, admin_user,
                                        accountant_user, main_branch):
        make_second_accountant(db_session)
        login(client, 'accountant', 'accountant123')
        client.post('/accounts/create', data=account_form_data(), follow_redirects=True)

        assert Account.query.filter_by(code='10199').first() is None
        req = AccountChangeRequest.query.order_by(AccountChangeRequest.id.desc()).first()
        assert req.status == 'pending'

    def test_inactive_accountant_not_counted(self, client, db_session, admin_user,
                                             accountant_user, main_branch):
        second = make_second_accountant(db_session)
        second.is_active = False
        db_session.commit()

        login(client, 'accountant', 'accountant123')
        client.post('/accounts/create', data=account_form_data(), follow_redirects=True)

        assert Account.query.filter_by(code='10199').first() is not None
