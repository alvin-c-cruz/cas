"""Half-filled-line guard (Product+UoM Activation / R-01, Task 1).

`validate_line_mode` rejects a line where EXACTLY ONE of quantity / unit_price is
present — the case where `calculate_amounts()` would silently keep the typed
`amount` while the user believes an itemized qty x price will be computed (or
vice-versa). A fully-itemized line (both set) and a fully amount-only line (both
None) are valid. Wired into all four document line parsers so a half-filled POST
is flashed and NOT saved.
"""
import json
import pytest
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice
from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher
from app.cash_receipts.models import CashReceiptVoucher

pytestmark = [pytest.mark.integration]

EXPECTED_MSG = 'enter a unit price with the quantity, or clear both and type the amount'


# ---------------------------------------------------------------------------
# Unit tests — the helper in isolation
# ---------------------------------------------------------------------------

class TestValidateLineModeUnit:
    def test_qty_without_price_raises(self):
        from app.utils.line_mode import validate_line_mode
        with pytest.raises(ValueError) as ei:
            validate_line_mode(product_id=None, quantity=3, unit_price=None, amount=100)
        assert EXPECTED_MSG in str(ei.value)

    def test_price_without_qty_raises(self):
        from app.utils.line_mode import validate_line_mode
        with pytest.raises(ValueError) as ei:
            validate_line_mode(product_id=None, quantity=None, unit_price=50, amount=100)
        assert EXPECTED_MSG in str(ei.value)

    def test_both_set_ok(self):
        from app.utils.line_mode import validate_line_mode
        # returns None, no raise
        assert validate_line_mode(product_id=None, quantity=3, unit_price=50, amount=150) is None

    def test_both_none_ok(self):
        from app.utils.line_mode import validate_line_mode
        assert validate_line_mode(product_id=None, quantity=None, unit_price=None, amount=100) is None

    def test_line_number_appears_in_message(self):
        from app.utils.line_mode import validate_line_mode
        with pytest.raises(ValueError) as ei:
            validate_line_mode(None, 3, None, 100, line_number=2)
        assert 'Line 2' in str(ei.value)


# ---------------------------------------------------------------------------
# Integration — a half-filled POST is rejected on each of the four documents
# ---------------------------------------------------------------------------

def _acct(db_session, code, name, atype, nb):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
        db_session.add(a)
        db_session.commit()
    return a


def _gl(db_session):
    return {
        'ar': _acct(db_session, '10201', 'AR - Trade', 'Asset', 'debit'),
        'ap': _acct(db_session, '20101', 'AP - Trade', 'Liability', 'credit'),
        'cash': _acct(db_session, '10101', 'Cash on Hand', 'Asset', 'debit'),
        'rev': _acct(db_session, '40101', 'Service Revenue', 'Income', 'credit'),
        'exp': _acct(db_session, '60101', 'Electricity Expense', 'Expense', 'debit'),
    }


def _customer(db_session):
    c = Customer.query.filter_by(code='HFC1').first()
    if not c:
        c = Customer(code='HFC1', name='Half Filled Customer', is_active=True)
        db_session.add(c); db_session.commit()
    return c


def _vendor(db_session):
    v = Vendor.query.filter_by(code='HFV1').first()
    if not v:
        v = Vendor(code='HFV1', name='Half Filled Vendor', check_payee_name='Half Filled Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v); db_session.commit()
    return v


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _half_line(account_id):
    # qty set, unit_price blank -> half-filled
    return {'description': 'Half filled', 'amount': '1000.00',
            'quantity': '3', 'unit_price': None, 'uom_id': None, 'uom_text': None,
            'product_id': None, 'vat_category': '', 'account_id': account_id, 'wt_id': None}


def test_si_half_filled_rejected(client, db_session, accountant_user, main_branch):
    gl = _gl(db_session); cust = _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-HF-0001', 'invoice_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'customer_id': str(cust.id),
        'payment_terms': 'Net 30', 'notes': 'x',
        'line_items': json.dumps([_half_line(gl['rev'].id)]),
    }, follow_redirects=True)
    assert SalesInvoice.query.filter_by(invoice_number='SI-HF-0001').first() is None
    assert EXPECTED_MSG in resp.data.decode('utf-8', 'replace')


def test_apv_half_filled_rejected(client, db_session, accountant_user, main_branch):
    gl = _gl(db_session); vend = _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-HF-0001', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'vendor_id': str(vend.id),
        'payment_terms': 'Net 30', 'notes': 'x',
        'line_items': json.dumps([_half_line(gl['exp'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert AccountsPayable.query.filter_by(ap_number='AP-HF-0001').first() is None
    assert EXPECTED_MSG in resp.data.decode('utf-8', 'replace')


def test_cdv_half_filled_rejected(client, db_session, accountant_user, main_branch):
    gl = _gl(db_session); vend = _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/cash-disbursements/create', data={
        'cdv_number': 'CD-HF-0001', 'cdv_date': date.today().isoformat(),
        'vendor_id': str(vend.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'x',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps([_half_line(gl['exp'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert CashDisbursementVoucher.query.filter_by(cdv_number='CD-HF-0001').first() is None
    assert EXPECTED_MSG in resp.data.decode('utf-8', 'replace')


def test_crv_half_filled_rejected(client, db_session, accountant_user, main_branch):
    gl = _gl(db_session); cust = _customer(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/cash-receipts/create', data={
        'crv_number': 'CR-HF-0001', 'crv_date': date.today().isoformat(),
        'customer_id': str(cust.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'x',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps([_half_line(gl['rev'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert CashReceiptVoucher.query.filter_by(crv_number='CR-HF-0001').first() is None
    assert EXPECTED_MSG in resp.data.decode('utf-8', 'replace')
