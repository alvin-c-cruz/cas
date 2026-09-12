"""The Job Order Slips page shows each order's DR / SI / CR document chain.

Owner request 2026-09-12: the Purchase Requests list's PO/RR/AP/CD columns, on the
sell side. Columns only -- the page stays operations-facing and unpriced, so the
Sales Invoice and Cash Receipt appear as numbers, never as amounts.
Spec: docs/design/2026-09-12-job-order-chain-columns-design.md.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app import db

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

SI_TOTAL = Decimal('98765.43')     # distinctive: must NOT leak into the row


def _login(client, user, branch):
    # The slips page is its own optional module (default off) -- enable it the way
    # test_job_order_slips_list.py does, then sign in with the branch selected.
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:sales_orders', '1')
    AppSettings.set_setting('module_enabled:job_order_slips', '1')
    clear_module_config_cache()
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True
        s['selected_branch_id'] = branch.id


def _so(branch, number):
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrder
    cust = Customer.query.filter_by(code='JOC').first()
    if cust is None:
        cust = Customer(code='JOC', name='Job Order Co', is_active=True)
        db.session.add(cust); db.session.commit()
    so = SalesOrder(so_number=number, order_date=date(2026, 9, 1), customer_id=cust.id,
                    customer_name=cust.name, branch_id=branch.id, status='confirmed')
    db.session.add(so); db.session.commit()
    return so


def _chain(so):
    """Delivered DR, billed by a posted SI, collected by a posted CRV."""
    from app.accounts.models import Account
    from app.cash_receipts.models import CashReceiptVoucher, CRVArLine
    from app.delivery_receipts.models import DeliveryReceipt
    from app.sales_invoices.models import SalesInvoice
    si = SalesInvoice(invoice_number='SI-7001', invoice_date=date(2026, 9, 3), due_date=date(2026, 10, 3),
                      customer_id=so.customer_id, customer_name=so.customer_name,
                      branch_id=so.branch_id, status='posted', total_amount=SI_TOTAL)
    db.session.add(si); db.session.commit()
    dr = DeliveryReceipt(dr_number='70001', delivery_date=date(2026, 9, 2), sales_order_id=so.id,
                         customer_id=so.customer_id, customer_name=so.customer_name,
                         branch_id=so.branch_id, status='billed', sales_invoice_id=si.id)
    cash = Account.query.filter_by(code='1011').first()
    if cash is None:
        cash = Account(code='1011', name='Cash in Bank', account_type='Asset',
                       normal_balance='debit', is_active=True)
        db.session.add(cash); db.session.commit()
    crv = CashReceiptVoucher(branch_id=so.branch_id, crv_number='CR-7001', crv_date=date(2026, 9, 5),
                             customer_id=so.customer_id, customer_name=so.customer_name,
                             cash_account_id=cash.id, status='posted', total_amount=SI_TOTAL)
    db.session.add_all([dr, crv]); db.session.commit()
    db.session.add(CRVArLine(crv_id=crv.id, line_number=1, invoice_id=si.id,
                             invoice_number=si.invoice_number,
                             original_balance=SI_TOTAL, amount_applied=SI_TOTAL))
    db.session.commit()
    return dr, si, crv


def _row(html, so_number):
    """The whole <tr> for one order -- assertions are scoped to it, not the page."""
    m = re.search(r'<tr>(?:(?!</tr>).)*?' + re.escape(so_number) + r'(?:(?!</tr>).)*?</tr>', html, re.S)
    assert m, f'no row for {so_number}'
    return m.group(0)


def test_headers_add_the_chain_between_status_and_actions(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-JO-1')
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    heads = re.findall(r'<th(?:\s[^>]*)?>(.*?)</th>', html, re.S)   # not <thead>
    assert heads == ['SO #', 'Customer', 'Order Date', 'Expected Delivery', 'Status',
                     'DR #', 'SI #', 'CR #', 'Actions']


def test_order_with_full_chain_links_all_three(client, db_session, admin_user, main_branch):
    so = _so(main_branch, 'SO-JO-2')
    dr, si, crv = _chain(so)
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    row = _row(html, 'SO-JO-2')
    assert f'href="/delivery-receipts/{dr.id}"' in row and '70001' in row
    assert f'href="/sales-invoices/{si.id}"' in row and 'SI-7001' in row
    assert f'href="/cash-receipts/{crv.id}"' in row and 'CR-7001' in row


def test_order_with_nothing_shows_em_dashes(client, db_session, admin_user, main_branch):
    _so(main_branch, 'SO-JO-3')
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    row = _row(html, 'SO-JO-3')
    # Cells: SO#, Customer, Order Date, Expected Delivery, Status, DR#, SI#, CR#, Actions.
    # An em dash, not a blank: an undelivered row reads as answered, not as a gap.
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
    assert [c.strip() for c in cells[5:8]] == ['—', '—', '—']


def test_no_amount_leaks_into_the_row(client, db_session, admin_user, main_branch):
    """SI and CR are money documents; the slips page is unpriced by design."""
    so = _so(main_branch, 'SO-JO-4')
    _chain(so)
    _login(client, admin_user, main_branch)
    html = client.get('/sales-orders/job-order-slips').get_data(as_text=True)
    row = _row(html, 'SO-JO-4')
    assert '98,765.43' not in row and '98765.43' not in row and '98765' not in row
