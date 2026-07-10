"""SI create bills the pulled DRs (+ consolidate guard); void/cancel unbills them."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.units_of_measure.models import UnitOfMeasure
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_invoices.models import SalesInvoice
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem

pytestmark = [pytest.mark.integration]


def _login(client, user, branch):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id); s['_fresh'] = True; s['selected_branch_id'] = branch.id


def _setup(db_session, branch):
    rev = Account(code='40101', name='Service Revenue', account_type='Income',
                  classification='General', normal_balance='Credit')
    ar = Account(code='10201', name='Accounts Receivable - Trade', account_type='Asset',
                 classification='General', normal_balance='Debit')
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    db.session.add_all([rev, ar, pc]); db.session.commit()
    p = Product(code='P001', name='Widget', is_active=True, default_unit_of_measure_id=pc.id,
                default_unit_price=Decimal('100'), default_account_id=rev.id)
    c = Customer(code='C1', name='Acme', is_active=True)
    db.session.add_all([p, c]); db.session.commit()
    so = SalesOrder(so_number='SO-1', order_date=date(2026, 7, 1), customer_id=c.id,
                    customer_name='Acme', branch_id=branch.id, status='confirmed')
    soi = SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                         unit_price=Decimal('100'), unit_of_measure_id=pc.id,
                         vat_category='V12', vat_rate=Decimal('12'))
    soi.calculate_amounts(); so.line_items.append(soi); db.session.add(so); db.session.commit()
    return c, p, soi, rev


def _delivered_dr(branch, c, p, soi, number):
    dr = DeliveryReceipt(dr_number=number, branch_id=branch.id, delivery_date=date(2026, 7, 9),
                         sales_order_id=soi.sales_order_id, customer_id=c.id,
                         customer_name=c.name, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=p.id, delivered_quantity=Decimal('10')))
    db.session.add(dr); db.session.commit()
    return dr


def _line(account_id, amount='1000'):
    return {'description': 'Billed line', 'amount': amount, 'quantity': None, 'unit_price': None,
            'uom_id': None, 'uom_text': None, 'product_id': None, 'vat_category': '',
            'account_id': account_id, 'wt_id': None}


def _create_si(client, cust, rev, dr_ids, number='SI-DR-1'):
    return client.post('/sales-invoices/create', data={
        'invoice_number': number, 'invoice_date': date.today().isoformat(),
        'due_date': date.today().isoformat(), 'customer_id': str(cust.id),
        'payment_terms': 'Net 30', 'notes': 'billing',
        'line_items': json.dumps([_line(rev.id)]),
        'source_dr_ids': json.dumps(dr_ids),
    }, follow_redirects=False)


def test_si_create_bills_the_dr(client, db_session, accountant_user, main_branch):
    c, p, soi, rev = _setup(db_session, main_branch)
    dr = _delivered_dr(main_branch, c, p, soi, 'DR-1')
    _login(client, accountant_user, main_branch)
    resp = _create_si(client, c, rev, [dr.id])
    assert resp.status_code == 302
    si = SalesInvoice.query.filter_by(invoice_number='SI-DR-1').first()
    assert si is not None
    dr2 = db.session.get(DeliveryReceipt, dr.id)
    assert dr2.status == 'billed' and dr2.sales_invoice_id == si.id


def test_consolidate_off_rejects_two_drs(client, db_session, accountant_user, main_branch):
    c, p, soi, rev = _setup(db_session, main_branch)
    dr1 = _delivered_dr(main_branch, c, p, soi, 'DR-1')
    dr2 = _delivered_dr(main_branch, c, p, soi, 'DR-2')
    _login(client, accountant_user, main_branch)
    _create_si(client, c, rev, [dr1.id, dr2.id])
    assert SalesInvoice.query.filter_by(invoice_number='SI-DR-1').first() is None  # rolled back
    assert db.session.get(DeliveryReceipt, dr1.id).status == 'delivered'           # untouched


def test_consolidate_on_bills_two_drs(client, db_session, accountant_user, main_branch):
    from app.settings import AppSettings
    AppSettings.set_setting('si_dr_billing_consolidate', '1'); db.session.commit()
    c, p, soi, rev = _setup(db_session, main_branch)
    dr1 = _delivered_dr(main_branch, c, p, soi, 'DR-1')
    dr2 = _delivered_dr(main_branch, c, p, soi, 'DR-2')
    _login(client, accountant_user, main_branch)
    resp = _create_si(client, c, rev, [dr1.id, dr2.id])
    assert resp.status_code == 302
    assert db.session.get(DeliveryReceipt, dr1.id).status == 'billed'
    assert db.session.get(DeliveryReceipt, dr2.id).status == 'billed'


def test_si_void_unbills_the_dr(client, db_session, accountant_user, main_branch):
    c, p, soi, rev = _setup(db_session, main_branch)
    dr = _delivered_dr(main_branch, c, p, soi, 'DR-1')
    _login(client, accountant_user, main_branch)
    _create_si(client, c, rev, [dr.id])
    si = SalesInvoice.query.filter_by(invoice_number='SI-DR-1').first()
    client.post(f'/sales-invoices/{si.id}/void',
                data={'void_reason': 'Wrong billing test'}, follow_redirects=False)
    dr2 = db.session.get(DeliveryReceipt, dr.id)
    assert dr2.status == 'delivered' and dr2.sales_invoice_id is None


def test_si_cancel_unbills_the_dr(client, db_session, accountant_user, main_branch):
    c, p, soi, rev = _setup(db_session, main_branch)
    dr = _delivered_dr(main_branch, c, p, soi, 'DR-1')
    _login(client, accountant_user, main_branch)
    _create_si(client, c, rev, [dr.id])
    si = SalesInvoice.query.filter_by(invoice_number='SI-DR-1').first()
    client.post(f'/sales-invoices/{si.id}/post', follow_redirects=False)
    client.post(f'/sales-invoices/{si.id}/cancel',
                data={'cancel_reason': 'Cancel billing test',
                      'reversal_date': date.today().isoformat()}, follow_redirects=False)
    dr2 = db.session.get(DeliveryReceipt, dr.id)
    assert dr2.status == 'delivered' and dr2.sales_invoice_id is None
