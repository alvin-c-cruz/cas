"""Tests for the /customers/<id>/defaults AJAX endpoint.

Mirrors the vendor `/vendors/<id>/defaults` endpoint so the Sales Invoice
customer card can auto-fill line defaults the same way the APV vendor card does.
"""
from datetime import date

from app.customers.models import Customer
from app.withholding_tax.models import WithholdingTax
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem


def _login(client, user, branch):
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = branch.id
    client.post('/login', data={'username': user.username, 'password': 'admin123'},
                follow_redirects=True)


def test_customer_defaults_returns_vat_terms_and_single_wht(
        client, db_session, admin_user, main_branch):
    """A customer's default VAT category, payment terms, and single M2M WHT
    are returned as a 1-item withholding_taxes list."""
    wt = WithholdingTax(code='WC010', name='Professional Fees', rate=10.00, is_active=True)
    db_session.add(wt)
    cust = Customer(code='C001', name='Acme Corp', payment_terms='Net 15',
                    default_vat_category='SVAT-G', is_active=True)
    cust.withholding_taxes = [wt]
    db_session.add(cust)
    db_session.commit()

    _login(client, admin_user, main_branch)
    resp = client.get(f'/customers/{cust.id}/defaults')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['default_vat_category'] == 'SVAT-G'
    assert data['payment_terms'] == 'Net 15'
    assert data['last_account_id'] is None
    assert isinstance(data['withholding_taxes'], list)
    assert len(data['withholding_taxes']) == 1
    assert data['withholding_taxes'][0]['code'] == 'WC010'
    assert data['withholding_taxes'][0]['id'] == wt.id
    assert data['withholding_taxes'][0]['rate'] == 10.0


def test_customer_defaults_no_wht_returns_empty_list(
        client, db_session, admin_user, main_branch):
    """A customer with no withholding_taxes assigned returns an empty list,
    and a blank payment_terms falls back to 'Net 30'."""
    cust = Customer(code='C002', name='Beta Inc', default_vat_category='SVAT-S', is_active=True)
    db_session.add(cust)
    db_session.commit()

    _login(client, admin_user, main_branch)
    data = client.get(f'/customers/{cust.id}/defaults').get_json()

    assert data['withholding_taxes'] == []
    assert data['default_vat_category'] == 'SVAT-S'
    assert data['payment_terms'] == 'Net 30'


def test_customer_defaults_last_account_from_recent_invoice(
        client, db_session, admin_user, main_branch, revenue_account):
    """last_account_id is the account of the most recent non-voided invoice line."""
    cust = Customer(code='C003', name='Gamma Ltd', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()
    si = SalesInvoice(invoice_number='SI-2026-06-0001', invoice_date=date(2026, 6, 1),
                      due_date=date(2026, 7, 1), customer_id=cust.id,
                      customer_name='Gamma Ltd', branch_id=main_branch.id, status='draft')
    db_session.add(si)
    db_session.commit()
    item = SalesInvoiceItem(invoice_id=si.id, line_number=1, description='Consulting',
                            amount=1000, account_id=revenue_account.id)
    db_session.add(item)
    db_session.commit()

    _login(client, admin_user, main_branch)
    data = client.get(f'/customers/{cust.id}/defaults').get_json()

    assert data['last_account_id'] == revenue_account.id


def test_customer_defaults_voided_invoice_excluded(
        client, db_session, admin_user, main_branch, revenue_account):
    """A voided invoice's line account is not used for last_account_id."""
    cust = Customer(code='C004', name='Delta Co', payment_terms='Net 30', is_active=True)
    db_session.add(cust)
    db_session.commit()
    si = SalesInvoice(invoice_number='SI-2026-06-0002', invoice_date=date(2026, 6, 2),
                      due_date=date(2026, 7, 2), customer_id=cust.id,
                      customer_name='Delta Co', branch_id=main_branch.id, status='voided')
    db_session.add(si)
    db_session.commit()
    item = SalesInvoiceItem(invoice_id=si.id, line_number=1, description='Voided line',
                            amount=500, account_id=revenue_account.id)
    db_session.add(item)
    db_session.commit()

    _login(client, admin_user, main_branch)
    data = client.get(f'/customers/{cust.id}/defaults').get_json()

    assert data['last_account_id'] is None


def test_customer_defaults_returns_multiple_whts(
        client, db_session, admin_user, main_branch):
    a = WithholdingTax(code='WC100', name='Rentals', rate=5.00, is_active=True)
    b = WithholdingTax(code='WC158', name='Goods', rate=1.00, is_active=True)
    db_session.add_all([a, b])
    cust = Customer(code='C005', name='Multi', is_active=True)
    cust.withholding_taxes = [a, b]
    db_session.add(cust)
    db_session.commit()
    _login(client, admin_user, main_branch)
    data = client.get(f'/customers/{cust.id}/defaults').get_json()
    assert sorted(w['code'] for w in data['withholding_taxes']) == ['WC100', 'WC158']


def test_customer_defaults_requires_login(client, db_session):
    """Anonymous users are redirected to login, not served the JSON."""
    resp = client.get('/customers/1/defaults')
    assert resp.status_code in (301, 302)
    assert '/login' in resp.headers.get('Location', '')
