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
from app.withholding_tax.models import WithholdingTax

pytestmark = [pytest.mark.integration, pytest.mark.sales_invoices]


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _setup(client, admin_user, main_branch, wt_id=None):
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
                         vat_category='V12', vat_rate=Decimal('12'), wt_id=wt_id)
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


def test_billable_drs_includes_source_so_line_wt_id(client, db_session, admin_user, main_branch):
    """The Pull-DR JSON payload must carry each line's source SO-item wt_id, so the SI form
    can default the WT picker from it (falls back to customer default when the SO line has
    none -- that fallback is existing SI-side JS behavior, exercised by the sibling test
    below only insofar as this endpoint must emit None, not re-tested past this endpoint)."""
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db.session.add(wt); db.session.commit()
    c, p, so, soi, rev = _setup(client, admin_user, main_branch, wt_id=wt.id)
    _dr(main_branch, c, p, soi, 'DR-1')
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['drs'][0]['lines'][0]['wt_id'] == wt.id


def test_billable_drs_wt_id_none_when_so_line_has_no_wt(client, db_session, admin_user, main_branch):
    """When the source SO line has no wt_id set, the DR line's wt_id must be None (not
    omitted, not defaulted here) so the SI-side JS falls back to the customer default WT,
    unchanged from today's behavior."""
    c, p, so, soi, rev = _setup(client, admin_user, main_branch, wt_id=None)
    _dr(main_branch, c, p, soi, 'DR-1')
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['drs'][0]['lines'][0]['wt_id'] is None


def test_billable_drs_includes_source_so_line_wt_rate(client, db_session, admin_user, main_branch):
    """Regression for the whole-branch-review finding: the Pull-DR payload must carry the
    RATE alongside the wt_id, not just the id. Without the rate, si_dr_billing.js's pull()
    has no way to populate the pulled line's wt_rate, and the SI form's calculateTotals()
    gates WHT accrual entirely on item.wt_rate being truthy -- so the on-screen "Less:
    Withholding Tax" preview shows P0 for a pulled line even though wt_id (and therefore
    the WT code shown in the picker) is correctly populated. The saved SI recomputes the
    rate server-side from wt_id, so this bug is purely a client-preview mismatch -- but
    this endpoint is the one place that must supply the rate for the client to use."""
    wt = WithholdingTax(code='WC160', name='Goods - Individual', sales_name='Goods - Individual',
                        rate=Decimal('1.00'), is_active=True, tax_type='expanded')
    db.session.add(wt); db.session.commit()
    c, p, so, soi, rev = _setup(client, admin_user, main_branch, wt_id=wt.id)
    _dr(main_branch, c, p, soi, 'DR-1')
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    line = data['drs'][0]['lines'][0]
    assert line['wt_id'] == wt.id
    assert line['wt_rate'] == float(wt.rate)   # the actual rate, not None -- this is the fix


def test_billable_drs_wt_rate_none_when_so_line_has_no_wt(client, db_session, admin_user, main_branch):
    """No wt_id on the source SO line -> wt_rate must also be None, not 0 or omitted."""
    c, p, so, soi, rev = _setup(client, admin_user, main_branch, wt_id=None)
    _dr(main_branch, c, p, soi, 'DR-1')
    resp = client.get(f'/sales-invoices/billable-drs?customer_id={c.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['drs'][0]['lines'][0]['wt_rate'] is None


def test_si_dr_billing_js_pull_passes_through_wt_rate():
    """Source-level regression guard for the JS half of the fix: pull() must forward
    ln.wt_rate from the billable-drs payload, not hardcode wt_rate: null -- otherwise the
    endpoint carrying the real rate (proven above) is useless, since addLineItem()'s
    existingItem branch only takes what pull() gives it."""
    import pathlib
    js_path = (pathlib.Path(__file__).resolve().parents[2]
              / 'app' / 'static' / 'js' / 'si_dr_billing.js')
    text = js_path.read_text(encoding='utf-8')
    assert 'wt_rate: null' not in text, (
        'pull() must no longer hardcode wt_rate to null -- it must forward ln.wt_rate '
        'from the billable-drs payload')
    assert 'ln.wt_rate' in text, (
        'pull() must reference ln.wt_rate so the fetched rate reaches addLineItem()')
