"""Phase 0 baseline + Phase 2 amount-only coverage (Product+UoM Activation / R-01).

Proves that, with the Product and Unit-of-Measure modules ENABLED, a line that is
pure free-text + account + amount (no quantity / unit_price / product) posts
correctly on all four transaction documents: SI, APV, CDV, CRV. The typed
Description flows to the posted JE line. This is the regression floor the
additive-UI work must never break.
"""
import json
import pytest
from decimal import Decimal
from datetime import date

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.vendors.models import Vendor
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.accounts_payable.models import AccountsPayable, AccountsPayableItem
from app.cash_disbursements.models import CashDisbursementVoucher, CDVExpenseLine
from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
from app.journal_entries.models import JournalEntry, JournalEntryLine

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def modules_on(db_session):
    """Enable products + units_of_measure for the test; clear memoize cache both ends."""
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
        db_session.add(a)
        db_session.commit()
    return a


def _gl(db_session):
    """The GL accounts the four posting helpers resolve by code, plus a leaf expense/revenue."""
    return {
        'ar': _acct(db_session, '10201', 'Accounts Receivable - Trade', 'Asset', 'debit'),
        'ap': _acct(db_session, '20101', 'Accounts Payable - Trade', 'Liability', 'credit'),
        'wht_pay': _acct(db_session, '20301', 'WHT Payable - Expanded', 'Liability', 'credit'),
        'wht_recv': _acct(db_session, '10212', 'Creditable WHT Receivable', 'Asset', 'debit'),
        'cash': _acct(db_session, '10101', 'Cash on Hand', 'Asset', 'debit'),
        'rev': _acct(db_session, '40101', 'Service Revenue', 'Income', 'credit'),
        'exp': _acct(db_session, '60101', 'Electricity Expense', 'Expense', 'debit'),
    }


def _customer(db_session):
    c = Customer.query.filter_by(code='AOC1').first()
    if not c:
        c = Customer(code='AOC1', name='Amount-Only Customer', is_active=True)
        db_session.add(c)
        db_session.commit()
    return c


def _vendor(db_session):
    v = Vendor.query.filter_by(code='AOV1').first()
    if not v:
        v = Vendor(code='AOV1', name='Amount-Only Vendor', check_payee_name='Amount-Only Vendor',
                   is_active=True, payment_terms='Net 30')
        db_session.add(v)
        db_session.commit()
    return v


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


AMT = '5000.00'
DESC = 'Meralco electricity — June'


def _amount_only_line(account_id, extra=None):
    line = {
        'description': DESC, 'amount': AMT,
        'quantity': None, 'unit_price': None, 'uom_id': None, 'uom_text': None,
        'product_id': None, 'vat_category': '', 'account_id': account_id, 'wt_id': None,
    }
    if extra:
        line.update(extra)
    return line


def _je_has_desc(je, desc):
    return any(desc in (l.description or '') for l in je.lines.all())


# ---------------------------------------------------------------------------
# Sales Invoice
# ---------------------------------------------------------------------------

def test_si_amount_only_line_posts(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    cust = _customer(db_session)
    _login(client, accountant_user, main_branch)

    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-AO-0001', 'invoice_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'customer_id': str(cust.id),
        'payment_terms': 'Net 30', 'notes': 'AO test',
        'line_items': json.dumps([_amount_only_line(gl['rev'].id)]),
    }, follow_redirects=False)
    assert resp.status_code == 302

    inv = SalesInvoice.query.filter_by(invoice_number='SI-AO-0001').first()
    assert inv is not None
    line = inv.line_items[0]
    assert line.amount == Decimal(AMT)
    assert line.quantity is None and line.unit_price is None and line.product_id is None

    resp = client.post(f'/sales-invoices/{inv.id}/post', follow_redirects=False)
    assert resp.status_code == 302
    db_session.refresh(inv)
    assert inv.status == 'posted'
    je = db_session.get(JournalEntry, inv.journal_entry_id)
    assert je.status == 'posted'
    assert _je_has_desc(je, DESC)


# ---------------------------------------------------------------------------
# Accounts Payable Voucher
# ---------------------------------------------------------------------------

def test_apv_amount_only_line_posts(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    vend = _vendor(db_session)
    _login(client, accountant_user, main_branch)

    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-AO-0001', 'ap_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'vendor_id': str(vend.id),
        'payment_terms': 'Net 30', 'notes': 'AO test',
        'line_items': json.dumps([_amount_only_line(gl['exp'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    bill = AccountsPayable.query.filter_by(ap_number='AP-AO-0001').first()
    assert bill is not None
    line = bill.line_items[0]
    assert line.amount == Decimal(AMT)
    assert line.quantity is None and line.unit_price is None and line.product_id is None

    resp = client.post(f'/accounts-payable/{bill.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(bill)
    assert bill.status == 'posted'
    je = db_session.get(JournalEntry, bill.journal_entry_id)
    assert je.status == 'posted'
    assert _je_has_desc(je, DESC)


# ---------------------------------------------------------------------------
# Cash Disbursement Voucher
# ---------------------------------------------------------------------------

def test_cdv_amount_only_line_posts(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    vend = _vendor(db_session)
    _login(client, accountant_user, main_branch)

    resp = client.post('/cash-disbursements/create', data={
        'cdv_number': 'CD-AO-0001', 'cdv_date': date.today().isoformat(),
        'vendor_id': str(vend.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'AO test',
        'ap_lines': json.dumps([]),
        'expense_lines': json.dumps([_amount_only_line(gl['exp'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    cdv = CashDisbursementVoucher.query.filter_by(cdv_number='CD-AO-0001').first()
    assert cdv is not None
    line = cdv.expense_lines[0]
    assert line.amount == Decimal(AMT)
    assert line.quantity is None and line.unit_price is None and line.product_id is None

    resp = client.post(f'/cash-disbursements/{cdv.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(cdv)
    assert cdv.status == 'posted'
    je = db_session.get(JournalEntry, cdv.journal_entry_id)
    assert je.status == 'posted'
    assert _je_has_desc(je, DESC)


# ---------------------------------------------------------------------------
# Cash Receipt Voucher
# ---------------------------------------------------------------------------

def test_crv_amount_only_line_posts(client, db_session, accountant_user, main_branch, modules_on):
    gl = _gl(db_session)
    from tests.conftest import assign_control_accounts
    assign_control_accounts(db_session)
    cust = _customer(db_session)
    _login(client, accountant_user, main_branch)

    resp = client.post('/cash-receipts/create', data={
        'crv_number': 'CR-AO-0001', 'crv_date': date.today().isoformat(),
        'customer_id': str(cust.id), 'payment_method': 'cash',
        'cash_account_id': str(gl['cash'].id), 'notes': 'AO test',
        'ar_lines': json.dumps([]),
        'revenue_lines': json.dumps([_amount_only_line(gl['rev'].id)]),
        'vat_override': '0', 'vat_override_value': '0',
        'wt_override': '0', 'wt_override_value': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    crv = CashReceiptVoucher.query.filter_by(crv_number='CR-AO-0001').first()
    assert crv is not None
    line = crv.revenue_lines[0]
    assert line.amount == Decimal(AMT)
    assert line.quantity is None and line.unit_price is None and line.product_id is None

    resp = client.post(f'/cash-receipts/{crv.id}/post', follow_redirects=True)
    assert resp.status_code == 200
    db_session.refresh(crv)
    assert crv.status == 'posted'
    je = db_session.get(JournalEntry, crv.journal_entry_id)
    assert je.status == 'posted'
    assert _je_has_desc(je, DESC)
