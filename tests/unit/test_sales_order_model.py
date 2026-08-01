import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.customers.models import Customer, CustomerDeliverySite

pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.sales_orders]


def test_item_derived_amount_and_vat():
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'),
                        unit_price=Decimal('112.00'), vat_rate=Decimal('12.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('1120.00')        # 10 × 112.00
    assert li.vat_amount == Decimal('120.00')     # extracted from 1120 @12%
    assert li.line_total == Decimal('1120.00')


def test_item_lump_sum_when_no_qty():
    li = SalesOrderItem(line_number=1, amount=Decimal('5000.00'),
                        vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('5000.00')


def test_item_to_dict_has_p56_keys_no_account():
    li = SalesOrderItem(line_number=1, quantity=Decimal('2'),
                        unit_price=Decimal('50.00'), uom_text='pcs', vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    d = li.to_dict()
    for k in ('quantity', 'unit_price', 'uom_text', 'unit_of_measure_id', 'uom_display',
              'product_id', 'product_code', 'product_name'):
        assert k in d
    # wt_id is now present (Task 3: informational WHT hint) -- only account_id stays absent,
    # since an SO still posts no journal entry / has no GL account.
    assert 'account_id' not in d
    assert 'description' not in d


def test_order_has_no_accounting_fields():
    so = SalesOrder()
    assert not hasattr(so, 'journal_entry_id')
    assert not hasattr(so, 'withholding_tax_amount')
    assert not hasattr(so, 'amount_paid')
    assert hasattr(so, 'sales_invoice_id')   # forward-compat hook present


def test_calculate_totals_sums_vat_inclusive_lines():
    so = SalesOrder()
    i1 = SalesOrderItem(line_number=1, amount=Decimal('1120.00'), vat_rate=Decimal('12'))
    i2 = SalesOrderItem(line_number=2, amount=Decimal('2240.00'), vat_rate=Decimal('12'))
    for i in (i1, i2):
        i.calculate_amounts()
    so.line_items = [i1, i2]
    so.calculate_totals()
    assert so.subtotal == Decimal('3360.00')
    assert so.total_amount == Decimal('3360.00')   # no WHT → total == subtotal


def test_item_has_delivery_date_and_site_columns():
    li = SalesOrderItem(line_number=1, amount=Decimal('100.00'), vat_rate=Decimal('0.00'),
                        delivery_date=date(2026, 8, 1), delivery_site_id=None)
    assert li.delivery_date == date(2026, 8, 1)
    assert li.delivery_site_id is None


def test_item_to_dict_includes_delivery_date_and_site_id_when_unset():
    li = SalesOrderItem(line_number=1, amount=Decimal('100.00'), vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    d = li.to_dict()
    assert d['delivery_date'] is None
    assert d['delivery_site_id'] is None
    assert d['delivery_site_name'] is None


def test_item_to_dict_delivery_date_isoformat_and_site_name_via_relationship(db_session):
    customer = Customer(code='CUST-DLV-1', name='Delivery Test Customer')
    db.session.add(customer)
    db.session.flush()
    site = CustomerDeliverySite(customer_id=customer.id, name='Main Warehouse')
    db.session.add(site)
    db.session.flush()

    so = SalesOrder(so_number='SO-DLV-TEST-1', order_date=date(2026, 7, 25),
                    customer_id=customer.id, customer_name=customer.name)
    db.session.add(so)
    db.session.flush()

    li = SalesOrderItem(sales_order_id=so.id, line_number=1, amount=Decimal('100.00'),
                        vat_rate=Decimal('0.00'), delivery_date=date(2026, 8, 1),
                        delivery_site_id=site.id)
    li.calculate_amounts()
    db.session.add(li)
    db.session.flush()

    d = li.to_dict()
    assert d['delivery_date'] == '2026-08-01'
    assert d['delivery_site_id'] == site.id
    assert d['delivery_site_name'] == 'Main Warehouse'


def test_sales_order_item_wt_id_round_trips(db_session):
    from app.withholding_tax.models import WithholdingTax
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db_session.add(wt); db_session.commit()

    from app.customers.models import Customer
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    c = Customer(code='WTC01', name='WT Customer', is_active=True)
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add_all([c, uom]); db_session.commit()
    p = Product(code='WTP01', name='WT Product', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('100.00'), is_active=True)
    db_session.add(p); db_session.commit()

    so = SalesOrder(branch_id=None, so_number='SO-WT-0001', order_date=date(2026, 7, 28),
                    customer_id=c.id, customer_name=c.name, status='draft')
    li = SalesOrderItem(line_number=1, quantity=Decimal('1'), unit_price=Decimal('100.00'),
                        product_id=p.id, amount=Decimal('100.00'), wt_id=wt.id)
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    fetched = SalesOrderItem.query.filter_by(sales_order_id=so.id).first()
    assert fetched.wt_id == wt.id
    assert fetched.withholding_tax.code == 'WC160'
    d = fetched.to_dict()
    assert d['wt_id'] == wt.id
    assert d['wt_code'] == 'WC160'


def test_sales_order_item_line_status_defaults_open(db_session):
    from app.customers.models import Customer
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    c = Customer(code='LSC01', name='Line Status Customer', is_active=True)
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add_all([c, uom]); db_session.commit()
    p = Product(code='LSP01', name='Line Status Product', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('10.00'), is_active=True)
    db_session.add(p); db_session.commit()

    so = SalesOrder(branch_id=None, so_number='SO-LS-0001', order_date=date(2026, 7, 28),
                    customer_id=c.id, customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    fetched = SalesOrderItem.query.filter_by(sales_order_id=so.id).first()
    assert fetched.line_status == 'open'
    assert fetched.closed_by_id is None
    assert fetched.closed_at is None
    assert fetched.closed_reason is None


def test_sales_order_item_closed_fields_round_trip(db_session, admin_user):
    from app.customers.models import Customer
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    from app.utils import ph_now
    c = Customer(code='LSC02', name='Line Close Customer', is_active=True)
    uom = UnitOfMeasure(code='box', name='Box', is_active=True)
    db_session.add_all([c, uom]); db_session.commit()
    p = Product(code='LSP02', name='Line Close Product', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('25.00'), is_active=True)
    db_session.add(p); db_session.commit()

    so = SalesOrder(branch_id=None, so_number='SO-LS-0002', order_date=date(2026, 7, 28),
                    customer_id=c.id, customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('5'), unit_price=Decimal('25.00'),
                        product_id=p.id, amount=Decimal('125.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    closed_ts = ph_now()
    li.line_status = 'closed'
    li.closed_by_id = admin_user.id
    li.closed_at = closed_ts
    li.closed_reason = 'Customer cancelled remaining balance'
    db_session.commit()
    db_session.expire_all()

    fetched = SalesOrderItem.query.filter_by(sales_order_id=so.id).first()
    assert fetched.line_status == 'closed'
    assert fetched.closed_by_id == admin_user.id
    assert fetched.closed_at is not None
    assert fetched.closed_at.isoformat()[:19] == closed_ts.isoformat()[:19]
    assert fetched.closed_reason == 'Customer cancelled remaining balance'

    d = fetched.to_dict()
    assert d['line_status'] == 'closed'
    assert d['closed_reason'] == 'Customer cancelled remaining balance'


def test_so_line_open_qty_zero_when_line_closed(db_session):
    from app.delivery_receipts.models import so_line_open_qty
    from app.customers.models import Customer
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    c = Customer(code='OQ01', name='Open Qty Customer', is_active=True)
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add_all([c, uom]); db_session.commit()
    p = Product(code='OQP01', name='Open Qty Product', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('10.00'), is_active=True)
    db_session.add(p); db_session.commit()

    so = SalesOrder(branch_id=None, so_number='SO-OQ-0001', order_date=date(2026, 7, 28),
                    customer_id=c.id, customer_name=c.name, status='confirmed')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    assert so_line_open_qty(li) == Decimal('10')
    li.line_status = 'closed'
    db_session.commit()
    assert so_line_open_qty(li) == Decimal('0')


def test_so_line_open_qty_zero_when_parent_so_cancelled(db_session):
    from app.delivery_receipts.models import so_line_open_qty
    from app.customers.models import Customer
    from app.products.models import Product
    from app.units_of_measure.models import UnitOfMeasure
    c = Customer(code='OQ02', name='Open Qty Customer 2', is_active=True)
    uom = UnitOfMeasure(code='pcs', name='Pieces', is_active=True)
    db_session.add_all([c, uom]); db_session.commit()
    p = Product(code='OQP02', name='Open Qty Product 2', default_unit_of_measure_id=uom.id,
                default_unit_price=Decimal('10.00'), is_active=True)
    db_session.add(p); db_session.commit()

    so = SalesOrder(branch_id=None, so_number='SO-OQ-0002', order_date=date(2026, 7, 28),
                    customer_id=c.id, customer_name=c.name, status='cancelled')
    li = SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('10.00'),
                        product_id=p.id, amount=Decimal('100.00'))
    li.calculate_amounts()
    so.line_items.append(li)
    db_session.add(so); db_session.commit()

    assert so_line_open_qty(li) == Decimal('0')
