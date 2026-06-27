# tests/unit/test_line_item_qty_price.py
from decimal import Decimal
import pytest
from app.sales_invoices.models import SalesInvoiceItem
from app.accounts_payable.models import AccountsPayableItem
from app.cash_receipts.models import CRVRevenueLine
from app.cash_disbursements.models import CDVExpenseLine

pytestmark = pytest.mark.unit

LINE_CLASSES = [SalesInvoiceItem, AccountsPayableItem, CRVRevenueLine, CDVExpenseLine]


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize('Cls', LINE_CLASSES)
def test_derived_amount_from_qty_times_price(Cls):
    li = Cls(line_number=1, description='x', quantity=Decimal('10'),
             unit_price=Decimal('112.00'), vat_rate=Decimal('12.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('1120.00')          # 10 × 112.00
    assert li.vat_amount == Decimal('120.00')       # extracted from 1120 @12%
    assert li.line_total == Decimal('1120.00')


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize('Cls', LINE_CLASSES)
def test_lump_sum_when_no_qty(Cls):
    li = Cls(line_number=1, description='x', amount=Decimal('5000.00'),
             vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    assert li.amount == Decimal('5000.00')          # typed amount preserved


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize('Cls', LINE_CLASSES)
def test_to_dict_includes_new_fields(Cls):
    li = Cls(line_number=1, description='x', quantity=Decimal('2'),
             unit_price=Decimal('50.00'), uom_text='ea', vat_rate=Decimal('0.00'))
    li.calculate_amounts()
    d = li.to_dict()
    for k in ('quantity', 'unit_price', 'uom_text', 'unit_of_measure_id', 'uom_code',
              'uom_name', 'uom_display', 'product_id', 'product_code', 'product_name'):
        assert k in d
    assert d['quantity'] == 2.0 and d['unit_price'] == 50.0
    assert d['uom_display'] == 'ea'                  # free-text fallback when no FK
