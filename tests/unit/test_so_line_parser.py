import json
import pytest
from decimal import Decimal
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
