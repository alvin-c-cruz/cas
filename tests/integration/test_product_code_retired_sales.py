"""The product code stays off the SALES side too (NULL-LABEL, 22 Nov 2026).

Owner, 8-9 Sep 2026: clients do not use the product code; it is optional and "retired from display"
(tests/integration/test_product_code_retired.py, which did the purchasing side). The sales side was never done: its
pickers still built "code: name", so every product made since 9 Sep -- none has a code -- read "null: NAME" on the Sales
Order, Sales Invoice, Cash Receipt and Quotation forms, and its pages printed "None — NAME". Found 22 Nov 2026 while
preparing the SO-DR trial (5 of Philgen's 7 trial products have no code).

Every document is checked separately, with one product that still has a code (it must not show) and one that has
none (no "None" or "null" in front of its name).
Work order: app-docs/bug-reports/2026-11-22-product-name-only-on-the-sales-side.md.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]

CODE = 'ZQXV-91001'
CODED = 'Coded Mango Slices 100g'
CODELESS = 'Codeless Papaya Chunks 100g'
NONE_BEFORE = re.compile(r'(None|null|undefined)\s*(:|—|&mdash;|-)\s*' + re.escape(CODELESS))


def _modules(db_session, *keys, **settings):
    from app.utils.cache_helpers import clear_module_config_cache
    for key in keys:
        AppSettings.set_setting(f'module_enabled:{key}', '1')
    for key, value in settings.items():
        AppSettings.set_setting(key, value)
    db_session.commit()
    clear_module_config_cache()


def _signed_in(client, admin_user, main_branch):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = main_branch.id


@pytest.fixture
def two_products(db_session):
    coded = Product(code=CODE, name=CODED, is_active=True)
    codeless = Product(code=None, name=CODELESS, is_active=True)
    cust = Customer(code='NL-C1', name='Name-Only Trading', is_active=True)
    db.session.add_all([coded, codeless, cust])
    db.session.commit()
    return coded, codeless, cust


def _names_only(body, where):
    assert CODED in body and CODELESS in body, f'{where}: a product name is missing'
    assert CODE not in body, f'{where}: the retired code is shown'
    assert not NONE_BEFORE.search(body), f'{where}: an empty code is shown in front of the name'


# --- the pickers on the forms (built in the browser, so their source is checked; the browser check covers the rest) --

@pytest.mark.parametrize('url, modules', [
    ('/sales-orders/create', ('products', 'sales_orders')),
    ('/sales-invoices/create', ('products',)),
    ('/cash-receipts/create', ('products',)),
    ('/quotations/create', ('products', 'quotations')),
])
def test_the_form_pickers_list_the_name_only(client, db_session, admin_user, main_branch, url, modules):
    _modules(db_session, *modules)
    _signed_in(client, admin_user, main_branch)
    body = client.get(url).get_data(as_text=True)
    assert 'escHtml(p.name)' in body or '${p.name}' in body, f'{url}: the picker was not found'
    assert 'escHtml(p.code)' not in body, url
    assert "p.code) + ': '" not in body and '${p.code} — ${p.name}' not in body, url


def test_the_dr_form_lists_the_name_only(app):
    from pathlib import Path
    js = (Path(app.root_path) / 'static' / 'js' / 'delivery_receipts.js').read_text(encoding='utf-8')
    assert 'r.product_code' not in js


# --- Sales Orders ---------------------------------------------------------------------------------------------------

def _so(main_branch, cust, products, status='confirmed'):
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    so = SalesOrder(so_number='SO-NL-0001', order_date=date(2026, 11, 22), customer_id=cust.id,
                    customer_name=cust.name, branch_id=main_branch.id, status=status, notes='')
    for n, p in enumerate(products, 1):
        li = SalesOrderItem(line_number=n, product_id=p.id, quantity=Decimal('2'), unit_price=Decimal('100'),
                            vat_category='V0', vat_rate=Decimal('0'))
        li.calculate_amounts()
        so.line_items.append(li)
    so.calculate_totals()
    db.session.add(so)
    db.session.commit()
    return so


def test_the_sales_order_page_shows_the_name_only(client, db_session, admin_user, main_branch, two_products):
    coded, codeless, cust = two_products
    _modules(db_session, 'products', 'sales_orders')
    so = _so(main_branch, cust, (coded, codeless))
    _signed_in(client, admin_user, main_branch)
    _names_only(client.get(f'/sales-orders/{so.id}').get_data(as_text=True), 'SO page')


def test_the_sales_order_pre_printed_print_shows_the_name_only(client, db_session, admin_user, main_branch,
                                                               two_products):
    coded, codeless, cust = two_products
    _modules(db_session, 'products', 'sales_orders', so_print_form='preprinted')
    so = _so(main_branch, cust, (coded, codeless))
    _signed_in(client, admin_user, main_branch)
    _names_only(client.get(f'/sales-orders/{so.id}/print').get_data(as_text=True), 'SO pre-printed print')


def test_a_sales_order_revision_shows_the_name_only(client, db_session, admin_user, main_branch, two_products):
    from app.sales_orders.revisions import write_revision
    coded, codeless, cust = two_products
    _modules(db_session, 'products', 'sales_orders')
    so = _so(main_branch, cust, (coded, codeless))
    write_revision(so, admin_user.id)
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/sales-orders/{so.id}/revisions/0')
    assert resp.status_code == 200
    _names_only(resp.get_data(as_text=True), 'SO revision')


def test_an_amendment_message_names_the_line_by_its_product_name(db_session, main_branch, two_products):
    from app.sales_orders.revisions import _line_label
    coded, codeless, cust = two_products
    so = _so(main_branch, cust, (coded, codeless))
    assert [_line_label(li) for li in so.line_items] == [CODED, CODELESS]


# --- Sales Invoices ------------------------------------------------------------------------------------------------

def test_the_sales_invoice_print_shows_the_name_only(client, db_session, admin_user, main_branch, two_products):
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    coded, codeless, cust = two_products
    _modules(db_session, 'products', sv_print_form='current')
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-NL-0001', invoice_date=date(2026, 11, 22),
                      due_date=date(2026, 12, 22), customer_id=cust.id, customer_name=cust.name,
                      payment_terms='30', status='posted', notes='')
    db.session.add(si)
    db.session.flush()
    for n, p in enumerate((coded, codeless), 1):
        db.session.add(SalesInvoiceItem(invoice_id=si.id, line_number=n, description='', amount=Decimal('200.00'),
                                        quantity=Decimal('2'), unit_price=Decimal('100.00'), product_id=p.id))
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/sales-invoices/{si.id}/print')
    assert resp.status_code == 200
    _names_only(resp.get_data(as_text=True), 'SI print')


# --- Cash Receipts -------------------------------------------------------------------------------------------------

def _crv(main_branch, cust, cash_account, products):
    from app.cash_receipts.models import CashReceiptVoucher, CRVRevenueLine
    crv = CashReceiptVoucher(branch_id=main_branch.id, crv_number='CRV-NL-0001', crv_date=date(2026, 11, 22),
                             customer_id=cust.id, customer_name=cust.name, cash_account_id=cash_account.id,
                             status='posted', total_amount=Decimal('400'))
    for n, p in enumerate(products, 1):
        crv.revenue_lines.append(CRVRevenueLine(line_number=n, product_id=p.id, description='',
                                                amount=Decimal('200'), line_total=Decimal('200')))
    db.session.add(crv)
    db.session.commit()
    return crv


@pytest.mark.parametrize('page', ['', '/print'])
def test_the_cash_receipt_pages_show_the_name_only(client, db_session, admin_user, main_branch, two_products,
                                                   cash_account, page):
    coded, codeless, cust = two_products
    _modules(db_session, 'products', cr_print_form='current')
    crv = _crv(main_branch, cust, cash_account, (coded, codeless))
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/cash-receipts/{crv.id}{page}')
    assert resp.status_code == 200
    _names_only(resp.get_data(as_text=True), f'CRV {page or "page"}')


# --- Quotations ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('page', ['', '/print'])
def test_the_quotation_pages_show_the_name_only(client, db_session, admin_user, main_branch, two_products, page):
    from app.quotations.models import Quotation, QuotationItem
    coded, codeless, cust = two_products
    _modules(db_session, 'products', 'quotations')
    qt = Quotation(quotation_number='QT-NL-0001', quotation_date=date(2026, 11, 22), customer_id=cust.id,
                   customer_name=cust.name, branch_id=main_branch.id, notes='', status='draft')
    db.session.add(qt)
    db.session.flush()
    for n, p in enumerate((coded, codeless), 1):
        db.session.add(QuotationItem(quotation_id=qt.id, line_number=n, product_id=p.id, amount=Decimal('200'),
                                     line_total=Decimal('200')))
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/quotations/{qt.id}{page}')
    assert resp.status_code == 200
    _names_only(resp.get_data(as_text=True), f'quotation {page or "page"}')


# --- Credit memos ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('page', ['', '/print'])
def test_the_credit_memo_pages_show_the_name_only(client, db_session, admin_user, main_branch, two_products, page):
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.sales_memos.models import SalesMemo, SalesMemoItem, generate_memo_number
    coded, codeless, cust = two_products
    _modules(db_session, 'products', 'credit_memos')
    si = SalesInvoice(branch_id=main_branch.id, invoice_number='SI-NL-0002', invoice_date=date(2026, 11, 22),
                      due_date=date(2026, 12, 22), customer_id=cust.id, customer_name=cust.name,
                      payment_terms='30', status='posted', notes='')
    db.session.add(si)
    db.session.flush()
    items = []
    for n, p in enumerate((coded, codeless), 1):
        item = SalesInvoiceItem(invoice_id=si.id, line_number=n, description='', amount=Decimal('200.00'),
                                quantity=Decimal('2'), unit_price=Decimal('100.00'), product_id=p.id)
        db.session.add(item)
        items.append(item)
    db.session.flush()
    memo = SalesMemo(memo_type='credit', memo_number=generate_memo_number('credit'), customer_id=cust.id,
                     sales_invoice_id=si.id, original_invoice_number=si.invoice_number, customer_name=cust.name,
                     branch_id=main_branch.id, memo_date=date(2026, 11, 22), destination='ar', reason='return',
                     status='draft')
    db.session.add(memo)
    db.session.flush()
    for n, item in enumerate(items, 1):
        memo.line_items.append(SalesMemoItem(sales_memo_id=memo.id, sales_invoice_item_id=item.id, line_number=n,
                                             product_id=item.product_id, quantity=Decimal('1'),
                                             amount=Decimal('100.00'), line_total=Decimal('100.00'),
                                             vat_category='V0', vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.commit()
    _signed_in(client, admin_user, main_branch)
    resp = client.get(f'/credit-memos/{memo.id}{page}')
    assert resp.status_code == 200
    _names_only(resp.get_data(as_text=True), f'credit memo {page or "page"}')
