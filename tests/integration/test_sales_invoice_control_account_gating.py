"""BUG-SI-CONTROL-ACCOUNT-OVERRIDE-NOT-GATED: Creditable WHT/AR Trade
Account override fields must be hidden from and unusable by staff/accountant
users -- only admin/chief_accountant (has_full_access) may see or set them."""
import json
import pytest
from app import db
from app.accounts.models import Account
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _account(code, name='Ctrl', atype='Asset', nb='Debit'):
    a = Account(code=code, name=name, account_type=atype, normal_balance=nb, is_active=True)
    db.session.add(a); db.session.commit()
    return a


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_staff_create_form_does_not_render_override_fields(client, db_session, staff_user, main_branch):
    from app.settings import AppSettings
    staff_user.branches.append(main_branch)
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/sales-invoices/create')
    body = resp.get_data(as_text=True)
    assert 'name="ar_trade_account_id"' not in body
    assert 'name="creditable_wht_account_id"' not in body


def test_admin_create_form_renders_override_fields(client, db_session, admin_user, main_branch):
    from app.settings import AppSettings
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/sales-invoices/create')
    body = resp.get_data(as_text=True)
    assert 'name="ar_trade_account_id"' in body
    assert 'name="creditable_wht_account_id"' in body


def test_staff_submitted_override_is_ignored_falls_back_to_company_default(
        client, db_session, staff_user, main_branch, customer):
    ar = _account('9001', 'AR Override')
    wt = _account('9002', 'WT Override')
    default_ar = _account('9003', 'AR Default')
    default_wt = _account('9004', 'WT Default')
    revenue_acct = _account('9005', 'Sales Revenue', 'Income', 'Credit')
    staff_user.branches.append(main_branch)
    AppSettings.set_setting('ar_trade_account_code', '9003', updated_by='test')
    AppSettings.set_setting('creditable_wht_account_code', '9004', updated_by='test')
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    _login(client, staff_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    line_items = json.dumps([{
        'description': 'Item', 'amount': 1000.00, 'vat_category': '',
        'account_id': revenue_acct.id, 'wt_id': None, 'wt_rate': None,
    }])
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-TEST-0001', 'invoice_date': '2026-07-24', 'due_date': '2026-08-23',
        'customer_id': customer.id, 'payment_terms': 'Net 30', 'notes': 'Test notes',
        'ar_trade_account_id': str(ar.id), 'creditable_wht_account_id': str(wt.id),
        'line_items': line_items, 'source_dr_ids': '[]',
    }, follow_redirects=False)
    from app.sales_invoices.models import SalesInvoice
    invoice = SalesInvoice.query.filter_by(invoice_number='SI-TEST-0001').first()
    assert invoice is not None
    assert invoice.ar_trade_account_id == default_ar.id
    assert invoice.creditable_wht_account_id == default_wt.id


def test_admin_submitted_override_is_honored(
        client, db_session, admin_user, main_branch, customer):
    ar = _account('9101', 'AR Override 2')
    wt = _account('9102', 'WT Override 2')
    revenue_acct = _account('9103', 'Sales Revenue 2', 'Income', 'Credit')
    AppSettings.set_setting('module_enabled:sales_invoices', '1')
    db_session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    line_items = json.dumps([{
        'description': 'Item', 'amount': 1000.00, 'vat_category': '',
        'account_id': revenue_acct.id, 'wt_id': None, 'wt_rate': None,
    }])
    resp = client.post('/sales-invoices/create', data={
        'invoice_number': 'SI-TEST-0002', 'invoice_date': '2026-07-24', 'due_date': '2026-08-23',
        'customer_id': customer.id, 'payment_terms': 'Net 30', 'notes': 'Test notes',
        'ar_trade_account_id': str(ar.id), 'creditable_wht_account_id': str(wt.id),
        'line_items': line_items, 'source_dr_ids': '[]',
    }, follow_redirects=False)
    from app.sales_invoices.models import SalesInvoice
    invoice = SalesInvoice.query.filter_by(invoice_number='SI-TEST-0002').first()
    assert invoice is not None
    assert invoice.ar_trade_account_id == ar.id
    assert invoice.creditable_wht_account_id == wt.id
