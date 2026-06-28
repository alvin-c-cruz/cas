import pytest
from decimal import Decimal
from datetime import date
from app import db
from app.sales_orders.models import SalesOrder, SalesOrderItem

pytestmark = pytest.mark.usefixtures("app")


def test_item_derived_amount_and_vat():
    li = SalesOrderItem(line_number=1, description='Widget', quantity=Decimal('10'),
                        unit_price=Decimal('112.00'), vat_rate=Decimal('12.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('1120.00')        # 10 × 112.00
    assert li.vat_amount == Decimal('120.00')     # extracted from 1120 @12%
    assert li.line_total == Decimal('1120.00')


def test_item_lump_sum_when_no_qty():
    li = SalesOrderItem(line_number=1, description='x', amount=Decimal('5000.00'),
                        vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('5000.00')


def test_item_to_dict_has_p56_keys_no_account():
    li = SalesOrderItem(line_number=1, description='x', quantity=Decimal('2'),
                        unit_price=Decimal('50.00'), uom_text='pcs', vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    d = li.to_dict()
    for k in ('quantity', 'unit_price', 'uom_text', 'unit_of_measure_id', 'uom_display',
              'product_id', 'product_code', 'product_name'):
        assert k in d
    assert 'account_id' not in d and 'wt_id' not in d


def test_order_has_no_accounting_fields():
    so = SalesOrder()
    assert not hasattr(so, 'journal_entry_id')
    assert not hasattr(so, 'withholding_tax_amount')
    assert not hasattr(so, 'amount_paid')
    assert hasattr(so, 'sales_invoice_id')   # forward-compat hook present


def test_calculate_totals_sums_vat_inclusive_lines():
    so = SalesOrder()
    i1 = SalesOrderItem(line_number=1, description='a', amount=Decimal('1120.00'), vat_rate=Decimal('12'))
    i2 = SalesOrderItem(line_number=2, description='b', amount=Decimal('2240.00'), vat_rate=Decimal('12'))
    for i in (i1, i2):
        i.calculate_amounts()
    so.line_items = [i1, i2]
    so.calculate_totals()
    assert so.subtotal == Decimal('3360.00')
    assert so.total_amount == Decimal('3360.00')   # no WHT → total == subtotal
