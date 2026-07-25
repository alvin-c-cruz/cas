import json
import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer, CustomerDeliverySite
from app.sales_orders.models import SalesOrder
from app.sales_orders.views import _parse_and_attach_so_lines

pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.sales_orders]


def test_parser_reads_qty_uom_price_product(db_session, main_branch):
    so = SalesOrder(branch_id=main_branch.id)
    payload = json.dumps([{
        'quantity': '10',
        'unit_price': '112.00',
        'uom_id': None,
        'uom_text': 'pcs',
        'product_id': '1',
        'vat_category': None,
        'vat_rate': '12.00',
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.quantity == Decimal('10') and line.unit_price == Decimal('112.00')
    assert line.uom_text == 'pcs' and line.amount == Decimal('1120.00')
    assert line.vat_amount == Decimal('120.00')


def test_parser_persists_delivery_date_and_site(db_session, main_branch):
    """delivery_date parses via date.fromisoformat; delivery_site_id via the
    existing _int() coercion helper (Task 5), then re-checked against the SO's own
    customer (bug-review fix) -- so this test must give the site a real customer
    that matches so.customer_id, not an arbitrary unowned id."""
    customer = Customer(code='ACME01', name='Acme', is_active=True)
    db_session.add(customer)
    db_session.commit()
    site = CustomerDeliverySite(customer_id=customer.id, name='WAREHOUSE A', is_active=True)
    db_session.add(site)
    db_session.commit()

    so = SalesOrder(branch_id=main_branch.id, customer_id=customer.id)
    payload = json.dumps([{
        'quantity': '1', 'unit_price': '100.00', 'uom_id': None, 'uom_text': 'pcs',
        'product_id': '1', 'vat_category': None, 'vat_rate': '0',
        'delivery_date': '2026-08-15', 'delivery_site_id': str(site.id),
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.delivery_date == date(2026, 8, 15)
    assert line.delivery_site_id == site.id


def test_parser_drops_delivery_site_belonging_to_a_different_customer(db_session, main_branch):
    """Bug-review fix: a delivery_site_id that exists but belongs to a DIFFERENT
    customer than so.customer_id must be silently dropped to None, not persisted --
    matching this parser's tolerant style for other invalid soft-reference ids."""
    customer_a = Customer(code='ACME01', name='Acme', is_active=True)
    customer_b = Customer(code='OTHR01', name='Other Co', is_active=True)
    db_session.add_all([customer_a, customer_b])
    db_session.commit()
    foreign_site = CustomerDeliverySite(customer_id=customer_b.id, name='OTHER WAREHOUSE',
                                         is_active=True)
    db_session.add(foreign_site)
    db_session.commit()

    so = SalesOrder(branch_id=main_branch.id, customer_id=customer_a.id)
    payload = json.dumps([{
        'quantity': '1', 'unit_price': '100.00', 'uom_id': None, 'uom_text': 'pcs',
        'product_id': '1', 'vat_category': None, 'vat_rate': '0',
        'delivery_date': '2026-08-15', 'delivery_site_id': str(foreign_site.id),
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.delivery_site_id is None
    assert line.delivery_date == date(2026, 8, 15)


def test_parser_drops_delivery_site_id_that_does_not_exist(db_session, main_branch):
    """A delivery_site_id naming a row that doesn't exist at all must also be
    silently dropped, not raise."""
    customer = Customer(code='ACME01', name='Acme', is_active=True)
    db_session.add(customer)
    db_session.commit()
    so = SalesOrder(branch_id=main_branch.id, customer_id=customer.id)
    payload = json.dumps([{
        'quantity': '1', 'unit_price': '100.00', 'uom_id': None, 'uom_text': 'pcs',
        'product_id': '1', 'vat_category': None, 'vat_rate': '0',
        'delivery_date': '2026-08-15', 'delivery_site_id': '999999',
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.delivery_site_id is None


@pytest.mark.parametrize('raw_date,raw_site', [
    ('', ''),
    ('null', 'null'),
    (None, None),
])
def test_parser_blank_or_null_delivery_date_and_site_become_none(db_session, main_branch, raw_date, raw_site):
    so = SalesOrder(branch_id=main_branch.id)
    payload = json.dumps([{
        'quantity': '1', 'unit_price': '100.00', 'uom_id': None, 'uom_text': 'pcs',
        'product_id': '1', 'vat_category': None, 'vat_rate': '0',
        'delivery_date': raw_date, 'delivery_site_id': raw_site,
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.delivery_date is None
    assert line.delivery_site_id is None


def test_parser_omits_delivery_fields_entirely_still_defaults_to_none(db_session, main_branch):
    """A line dict with no delivery_date/delivery_site_id keys at all (legacy caller
    shape) must not raise -- both fields default to None via .get()."""
    so = SalesOrder(branch_id=main_branch.id)
    payload = json.dumps([{
        'quantity': '1', 'unit_price': '100.00', 'uom_id': None, 'uom_text': 'pcs',
        'product_id': '1', 'vat_category': None, 'vat_rate': '0',
    }])
    _parse_and_attach_so_lines(so, payload)
    line = so.line_items[0]
    assert line.delivery_date is None
    assert line.delivery_site_id is None
