"""GET /sales-invoices/billable-drs -- the DR picker's data source."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.accounts.models import Account
from app.customers.models import Customer
from app.units_of_measure.models import UnitOfMeasure
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _setup(client, admin_user, main_branch):
    rev = Account(code='40101', name='Sales - Goods', account_type='Income',
                  classification='General', normal_balance='Credit')
    pc = UnitOfMeasure(code='PC', name='Piece', is_active=True)
    db.session.add_all([rev, pc]); db.session.commit()
    p = Product(code='P001', name='Widget', is_active=True, default_unit_of_measure_id=pc.id,
                default_unit_price=Decimal('100'), default_account_id=rev.id)
    c = Customer(code='C001', name='Acme', is_active=True)
    db.session.add_all([p, c]); db.session.commit()
    so = SalesOrder(so_number='SO-1', order_date=date(2026, 7, 1), customer_id=c.id,
                    customer_name='Acme', branch_id=main_branch.id, status='confirmed')
    soi = SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                         unit_price=Decimal('100'), unit_of_measure_id=pc.id,
                         vat_category='V12', vat_rate=Decimal('12'))
    soi.calculate_amounts(); so.line_items.append(soi)
    db.session.add(so); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as s:
        s['selected_branch_id'] = main_branch.id
    return c, p, so, soi, rev


def _dr(branch, customer, product, soi, number, status='delivered', sales_invoice_id=None, qty='10'):
    dr = DeliveryReceipt(dr_number=number, branch_id=branch.id, delivery_date=date(2026, 7, 9),
                         sales_order_id=soi.sales_order_id, customer_id=customer.id,
                         customer_name=customer.name, status=status,
                         sales_invoice_id=sales_invoice_id)
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id, delivered_quantity=Decimal(qty)))
    db.session.add(dr); db.session.commit()
    return dr


def test_billable_drs_returns_delivered_unbilled_with_priced_lines(client, db_session, admin_user, main_branch):
    c, p, so, soi, rev = _setup(client, admin_user, main_branch)
    dr = _dr(main_branch, c, p, soi, 'DR-1')
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['consolidate'] is False          # setting default OFF
    assert len(data['drs']) == 1
    d = data['drs'][0]
    assert d['id'] == dr.id and d['dr_number'] == 'DR-1'
    line = d['lines'][0]
    assert line['quantity'] == 10.0
    assert line['unit_price'] == 100.0           # from the SO line
    assert line['vat_category'] == 'V12'
    assert line['vat_rate'] == 12.0
    assert line['account_id'] == rev.id          # from the product default


def test_billable_drs_excludes_billed_and_other_customer(client, db_session, admin_user, main_branch):
    c, p, so, soi, rev = _setup(client, admin_user, main_branch)
    _dr(main_branch, c, p, soi, 'DR-1', status='delivered')                    # eligible
    _dr(main_branch, c, p, soi, 'DR-2', status='billed', sales_invoice_id=999)  # billed -> excluded
    _dr(main_branch, c, p, soi, 'DR-3', status='approved')                     # not yet delivered
    c2 = Customer(code='C002', name='Beta', is_active=True)
    db.session.add(c2); db.session.commit()
    _dr(main_branch, c2, p, soi, 'DR-4', status='delivered')                   # other customer
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert [d['dr_number'] for d in resp.get_json()['drs']] == ['DR-1']
