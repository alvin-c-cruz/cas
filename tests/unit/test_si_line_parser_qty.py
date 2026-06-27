import json
from datetime import date
from decimal import Decimal
from app.sales_invoices.models import SalesInvoice
from app.sales_invoices.views import _parse_and_attach_line_items


def test_parser_reads_qty_uom_price(db_session, main_branch):
    inv = SalesInvoice(
        branch_id=main_branch.id,
        invoice_number='T-001',
        invoice_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        customer_id=1,
        customer_name='Test',
    )
    payload = json.dumps([{
        'description': 'Widget',
        'quantity': '10',
        'unit_price': '112.00',
        'uom_id': None,
        'uom_text': 'pcs',
        'product_id': None,
        'vat_category': None,
        'account_id': None,
    }])
    _parse_and_attach_line_items(inv, payload)
    line = inv.line_items[0]
    assert line.quantity == Decimal('10')
    assert line.unit_price == Decimal('112.00')
    assert line.uom_text == 'pcs'
    assert line.amount == Decimal('1120.00')        # derived
