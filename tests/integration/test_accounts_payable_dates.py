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
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    return a


class TestDueDateValidation:
    def _post_bill(self, client, vendor, account, ap_date, due_date,
                   vendor_invoice_date=None, ap_number='AP-2026-06-9999'):
        line_items = json.dumps([{'description': 'Item', 'amount': 100.0,
                                  'vat_category': '', 'account_id': account.id,
                                  'wt_id': None, 'wt_rate': None}])
        data = {
            'ap_number': ap_number,
            'ap_date': ap_date,
            'due_date': due_date,
            'vendor_id': vendor.id,
            'payment_terms': 'Net 30',
            'notes': 'Test particulars',
            'line_items': line_items,
            'vat_override': '0', 'vat_override_value': '0',
            'wt_override': '0', 'wt_override_value': '0',
        }
        if vendor_invoice_date is not None:
            data['vendor_invoice_date'] = vendor_invoice_date
        return client.post('/accounts-payable/create', data=data, follow_redirects=True)

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

    def test_due_after_invoice_but_before_voucher_allowed(self, client, db_session,
                                                          admin_user, main_branch):
        """New rule: due date is floored at the vendor invoice date, so a bill
        entered late (voucher after the invoice) may fall due before the voucher."""
        login(client)
        vendor = make_vendor(db_session)
        account = make_expense(db_session)
        # invoice 06-01, voucher 06-20, due 06-16 -> before voucher but after invoice
        resp = self._post_bill(client, vendor, account, '2026-06-20', '2026-06-16',
                               vendor_invoice_date='2026-06-01', ap_number='AP-2026-06-8001')
        assert resp.status_code == 200
        bill = AccountsPayable.query.filter_by(ap_number='AP-2026-06-8001').first()
        assert bill is not None and bill.due_date.isoformat() == '2026-06-16'

    def test_due_before_invoice_date_rejected(self, client, db_session,
                                              admin_user, main_branch):
        login(client)
        vendor = make_vendor(db_session)
        account = make_expense(db_session)
        # invoice 06-10, due 06-05 -> earlier than the invoice date -> rejected
        resp = self._post_bill(client, vendor, account, '2026-06-01', '2026-06-05',
                               vendor_invoice_date='2026-06-10', ap_number='AP-2026-06-8002')
        html = resp.data.decode('utf-8')
        assert 'Due date cannot be earlier than the vendor invoice date.' in html
        assert AccountsPayable.query.filter_by(ap_number='AP-2026-06-8002').first() is None
