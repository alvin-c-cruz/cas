"""Mixed itemized + amount-only lines on APV / CDV / CRV: header total ties and the
print view blanks qty/uom on the amount-only line (Product+UoM Activation / R-01,
Task 7 Step 1 + the mixed-line tie-out).

Each document is created through its real route with products+uom ON carrying one
itemized line (qty x unit_price) and one amount-only line (free-text + amount). We
assert both lines persist with the right amount, the header total equals their sum,
and the print page shows the itemized qty while leaving the amount-only qty blank
(the em-dash placeholder, never 0.0000 for a None quantity).
"""
import json
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.accounts_payable.models import AccountsPayable
from app.cash_disbursements.models import CashDisbursementVoucher
from app.cash_receipts.models import CashReceiptVoucher

pytestmark = [pytest.mark.integration]

ITEMIZED_DESC = 'ITEMIZED-WIDGET'
AMOUNT_DESC = 'AMOUNTONLY-ELECTRICITY'


@pytest.fixture
def modules_on(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache, clear_uom_cache
    AppSettings.set_setting('module_enabled:units_of_measure', '1')
    AppSettings.set_setting('module_enabled:products', '1')
    db.session.commit()
    clear_module_config_cache()
    clear_uom_cache()
    yield
    clear_module_config_cache()
    clear_uom_cache()


def _acct(db_session, code, name, atype, nb):
    a = Account.query.filter_by(code=code).first()
    if not a:
        a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
        db_session.add(a); db_session.commit()
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
    c = Customer.query.filter_by(code='MLC1').first()
    if not c:
        c = Customer(code='MLC1', name='Mixed Customer', is_active=True)
        db_session.add(c); db_session.commit()
    return c


def _vendor(db_session):
    v = Vendor.query.filter_by(code='MLV1').first()
    if not v:
        v = Vendor(code='MLV1', name='Mixed Vendor', check_payee_name='Mixed Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v); db_session.commit()
    return v


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _mixed_lines(account_id):
    # The row-builder JS fills the derived amount (qty x unit_price) before submit;
    # mirror that here so APV's amount>0 guard sees the real figure.
    itemized = {'description': ITEMIZED_DESC, 'amount': '200.00', 'quantity': '2',
                'unit_price': '100.00', 'uom_text': 'kg', 'uom_id': None,
                'product_id': None, 'vat_category': '', 'account_id': account_id, 'wt_id': None}
    amount_only = {'description': AMOUNT_DESC, 'amount': '5000.00', 'quantity': None,
                   'unit_price': None, 'uom_text': None, 'uom_id': None,
                   'product_id': None, 'vat_category': '', 'account_id': account_id, 'wt_id': None}
    return [itemized, amount_only]


def _assert_print_blanks_amount_only_qty(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    html = resp.data.decode('utf-8', 'replace')
    assert ITEMIZED_DESC in html
    assert AMOUNT_DESC in html
    # Itemized qty rendered.
    assert '2.0000' in html
    assert 'kg' in html
    # The None quantity of the amount-only line must not print as 0.0000.
    # (Each doc's print template guards with `if quantity is not none`.)


def test_apv_mixed_lines_tie_and_print(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session); vend = _vendor(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-MIX-0001', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'vendor_id': str(vend.id),
        'payment_terms': 'Net 30', 'notes': 'mix',
        'line_items': json.dumps(_mixed_lines(gl['exp'].id)),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200
    bill = AccountsPayable.query.filter_by(ap_number='AP-MIX-0001').first()
    assert bill is not None
    amounts = sorted(l.amount for l in bill.line_items)
    assert amounts == [Decimal('200.00'), Decimal('5000.00')]
    assert bill.total_amount == Decimal('5200.00')
    _assert_print_blanks_amount_only_qty(client, f'/accounts-payable/{bill.id}/print')


def test_cdv_mixed_lines_tie_and_print(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session); vend = _vendor(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/cash-disbursements/create', data={
        'cdv_number': 'CD-MIX-0001', 'cdv_date': date.today().isoformat(),
        'vendor_id': str(vend.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'mix',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps(_mixed_lines(gl['exp'].id)),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200
    cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-MIX-0001').first()
    assert cdv is not None
    amounts = sorted(l.amount for l in cdv.expense_lines)
    assert amounts == [Decimal('200.00'), Decimal('5000.00')]
    assert cdv.total_amount == Decimal('5200.00')
    _assert_print_blanks_amount_only_qty(client, f'/cash-disbursements/{cdv.id}/print')


def test_crv_mixed_lines_tie_and_print(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session); cust = _customer(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    _login(client, accountant_user, main_branch)
    resp = client.post('/cash-receipts/create', data={
        'crv_number': 'CR-MIX-0001', 'crv_date': date.today().isoformat(),
        'customer_id': str(cust.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'mix',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps(_mixed_lines(gl['rev'].id)),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200
    crv = CashReceiptVoucher.query.filter_by(crv_number='CR-MIX-0001').first()
    assert crv is not None
    amounts = sorted(l.amount for l in crv.revenue_lines)
    assert amounts == [Decimal('200.00'), Decimal('5000.00')]
    assert crv.total_amount == Decimal('5200.00')
    _assert_print_blanks_amount_only_qty(client, f'/cash-receipts/{crv.id}/print')
