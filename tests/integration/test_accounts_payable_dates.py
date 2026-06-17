"""Due date must not be earlier than the voucher date (B-013).

Neither the client validation gate nor the WTForms form blocked a due date
before the voucher date; an APV could be saved due-before-issued.
"""
import json

from app.accounts.models import Account
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
import pytest
pytestmark = [pytest.mark.accounts_payable, pytest.mark.integration]




def login(client, username='admin', password='admin123'):
    client.post('/login', data={'username': username, 'password': password},
                follow_redirects=True)


def make_vendor(db_session):
    v = Vendor(code='DDV01', name='Due Date Vendor',
               check_payee_name='Due Date Vendor', is_active=True)
    db_session.add(v)
    db_session.commit()
    return v


def make_expense(db_session):
    a = Account(code='69901', name='Test Expense', account_type='Expense',
                normal_balance='debit', is_active=True)
    ap = Account(code='20101', name='Accounts Payable - Trade',
                 account_type='Liability', normal_balance='credit', is_active=True)
    db_session.add_all([a, ap])
    db_session.commit()
    return a


class TestDueDateValidation:
    def _post_bill(self, client, vendor, account, ap_date, due_date):
        line_items = json.dumps([{'description': 'Item', 'amount': 100.0,
                                  'vat_category': '', 'account_id': account.id,
                                  'wt_id': None, 'wt_rate': None}])
        return client.post('/accounts-payable/create', data={
            'ap_number': 'AP-2026-06-9999',
            'ap_date': ap_date,
            'due_date': due_date,
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': line_items,
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }, follow_redirects=True)

    def test_due_date_before_voucher_date_rejected(self, client, db_session,
                                                   admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)
        account = make_expense(db_session)
        resp = self._post_bill(client, vendor, account,
                               '2026-06-12', '2026-06-01')
        html = resp.data.decode('utf-8')
        # once in the client-validation JS source, once as the rendered form error
        assert html.count('Due date cannot be earlier than the voucher date.') >= 2
        assert AccountsPayable.query.first() is None

    def test_due_date_equal_or_after_voucher_date_allowed(self, client, db_session,
                                                          admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)
        account = make_expense(db_session)
        resp = self._post_bill(client, vendor, account,
                               '2026-06-12', '2026-06-12')
        assert resp.status_code == 200
        bill = AccountsPayable.query.order_by(AccountsPayable.id.desc()).first()
        assert bill is not None
        assert bill.status == 'draft'
