"""TERMS-1 A: payment terms read "30 DAYS" (owner, 22 Nov 2026: "the change Net 30 to 30 DAYS, this is the convention
that the users wanted"; then "A: "30 DAYS" labels only, all clients (my pick)").

Labels only: every form, page and print shows 15 / 30 / 45 / 60 / 90 DAYS. The stored values stay "Net 30" etc. --
no record changes, and the due-date fill keeps reading the number out of them. Cash on Delivery and Advance Payment
are unchanged. Work order: app-docs/bug-reports/2026-11-22-payment-terms-read-as-days.md.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.settings import AppSettings
from app.utils.payment_terms import PAYMENT_TERMS_CHOICES, terms_label

pytestmark = [pytest.mark.integration]

#: What each stored term reads as.
READS = [('Net 15', '15 DAYS'), ('Net 30', '30 DAYS'), ('Net 45', '45 DAYS'), ('Net 60', '60 DAYS'),
         ('Net 90', '90 DAYS'), ('Cash on Delivery', 'Cash on Delivery'), ('Advance Payment', 'Advance Payment')]


# --- the label ---------------------------------------------------------------------------------------------------------

def test_each_term_reads_as_days_and_the_others_are_unchanged():
    assert [(v, terms_label(v)) for v, _ in READS] == READS
    assert PAYMENT_TERMS_CHOICES == READS


@pytest.mark.parametrize('value, reads', [(None, ''), ('', ''), ('Net 7', '7 DAYS'), ('net 30', '30 DAYS'),
                                          (' Net 30 ', '30 DAYS'), ('Due on receipt', 'Due on receipt')])
def test_an_unexpected_value_is_read_sensibly(value, reads):
    assert terms_label(value) == reads


# --- the forms: the pickers show the label and still post the stored value ----------------------------------------------

@pytest.mark.parametrize('module, form', [
    ('app.customers.forms', 'CustomerForm'), ('app.vendors.forms', 'VendorForm'),
    ('app.sales_orders.forms', 'SalesOrderForm'), ('app.sales_invoices.forms', 'SalesInvoiceForm'),
    ('app.accounts_payable.forms', 'AccountsPayableForm'), ('app.purchase_orders.forms', 'PurchaseOrderForm'),
    ('app.quotations.forms', 'QuotationForm'),
])
def test_every_form_offers_the_terms_as_days(app, module, form):
    import importlib
    cls = getattr(importlib.import_module(module), form)
    with app.test_request_context():
        assert list(cls().payment_terms.choices) == READS, form


# --- the pages and prints ---------------------------------------------------------------------------------------------

def _signed_in(client, admin_user, main_branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id


def _settings(db_session, *modules, **values):
    from app.utils.cache_helpers import clear_module_config_cache
    for m in modules:
        AppSettings.set_setting(f'module_enabled:{m}', '1')
    for k, v in values.items():
        AppSettings.set_setting(k, v)
    db_session.commit()
    clear_module_config_cache()


def _reads_days(body, where):
    assert '60 DAYS' in body, f'{where}: the term is not shown as days'
    assert 'Net 60' not in body, f'{where}: the stored text is shown'


@pytest.fixture
def parties(db_session):
    from app.customers.models import Customer
    from app.vendors.models import Vendor
    cust = Customer(code='T-C1', name='Days Trading', is_active=True, payment_terms='Net 60')
    vend = Vendor(code='T-V1', name='Days Supply', is_active=True, payment_terms='Net 60')
    db.session.add_all([cust, vend])
    db.session.commit()
    return cust, vend


@pytest.mark.parametrize('page', ['/customers', '/customers/{c}', '/vendors', '/vendors/{v}'])
def test_the_customer_and_vendor_pages(client, db_session, admin_user, main_branch, parties, page):
    cust, vend = parties
    _signed_in(client, admin_user, main_branch)
    resp = client.get(page.format(c=cust.id, v=vend.id))
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), page)


def _so(main_branch, cust):
    from app.sales_orders.models import SalesOrder
    so = SalesOrder(so_number='SO-DAYS-1', order_date=date(2026, 11, 23), customer_id=cust.id,
                    customer_name=cust.name, branch_id=main_branch.id, status='confirmed', notes='',
                    payment_terms='Net 60')
    db.session.add(so)
    db.session.commit()
    return so


@pytest.mark.parametrize('page, form', [('', 'current'), ('/print', 'current'), ('/print', 'preprinted'),
                                        ('/revisions/0', 'current')])
def test_the_sales_order_pages(client, db_session, admin_user, main_branch, parties, page, form):
    from app.sales_orders.revisions import write_revision
    cust, _ = parties
    _settings(db_session, 'sales_orders', so_print_form=form)
    so = _so(main_branch, cust)
    write_revision(so, admin_user.id)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/sales-orders/{so.id}{page}')
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), f'SO {page or "page"} ({form})')


@pytest.mark.parametrize('page, form', [('', 'current'), ('/print', 'current'), ('/print', 'preprinted')])
def test_the_sales_invoice_pages(client, db_session, admin_user, main_branch, parties, page, form):
    from app.sales_invoices.models import SalesInvoice
    cust, _ = parties
    _settings(db_session, sv_print_form=form)
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-DAYS-1', invoice_date=date(2026, 11, 23),
                      due_date=date(2027, 1, 22), customer_id=cust.id, customer_name=cust.name,
                      payment_terms='Net 60', status='posted', notes='')
    db.session.add(si)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/sales-invoices/{si.id}{page}')
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), f'SI {page or "page"} ({form})')


@pytest.mark.parametrize('page, form', [('', 'current'), ('/print', 'current'), ('/print', 'preprinted')])
def test_the_ap_voucher_pages(client, db_session, admin_user, main_branch, parties, page, form):
    from app.accounts_payable.models import AccountsPayable
    _, vend = parties
    _settings(db_session, ap_print_form=form)
    ap = AccountsPayable(branch_id=main_branch.id, ap_number='AP-DAYS-1', ap_date=date(2026, 11, 23),
                         due_date=date(2027, 1, 22), payee_type='vendor', payee_id=vend.id, vendor_id=vend.id,
                         vendor_name=vend.name, payment_terms='Net 60', status='posted')
    db.session.add(ap)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/accounts-payable/{ap.id}{page}')
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), f'AP {page or "page"} ({form})')


@pytest.mark.parametrize('page, form', [('', 'current'), ('/print', 'current'), ('/print', 'preprinted')])
def test_the_purchase_order_pages(client, db_session, admin_user, main_branch, parties, page, form):
    from app.purchase_orders.models import PurchaseOrder
    _, vend = parties
    _settings(db_session, 'purchase_orders', po_print_form=form)
    po = PurchaseOrder(po_number='PO-DAYS-1', order_date=date(2026, 11, 23), vendor_id=vend.id,
                       branch_id=main_branch.id, status='approved', payment_terms='Net 60')
    db.session.add(po)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/purchase-orders/{po.id}{page}')
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), f'PO {page or "page"} ({form})')


@pytest.mark.parametrize('page', ['', '/print'])
def test_the_quotation_pages(client, db_session, admin_user, main_branch, parties, page):
    from app.quotations.models import Quotation
    cust, _ = parties
    _settings(db_session, 'quotations')
    qt = Quotation(quotation_number='QT-DAYS-1', quotation_date=date(2026, 11, 23), customer_id=cust.id,
                   customer_name=cust.name, branch_id=main_branch.id, notes='', status='draft',
                   payment_terms='Net 60')
    db.session.add(qt)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/quotations/{qt.id}{page}')
    assert resp.status_code == 200
    _reads_days(resp.get_data(as_text=True), f'quotation {page or "page"}')


# --- nothing stored changes --------------------------------------------------------------------------------------------

def test_saving_a_customer_still_stores_the_old_value(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    _signed_in(client, admin_user, main_branch)
    client.post('/customers/create', data={'code': 'T-C9', 'name': 'Stored Value Co', 'payment_terms': 'Net 90',
                                           'is_active': '1'}, follow_redirects=True)
    assert Customer.query.filter_by(code='T-C9').one().payment_terms == 'Net 90'
