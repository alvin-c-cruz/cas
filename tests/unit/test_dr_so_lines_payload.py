"""BUG-DR-LINES-NO-LINE-IDENTIFIER: the DR create/edit form's SO-lines
payload must carry each line's line_number so the UI can show a stable
per-line identifier when products repeat on the same SO."""
from decimal import Decimal
from datetime import date
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def test_so_lines_payload_includes_line_number(db_session, main_branch):
    from app.sales_orders.models import SalesOrder, SalesOrderItem
    from app.delivery_receipts.views import _so_lines_payload, _eligible_sales_orders
    so = SalesOrder(so_number='SO-LN-0001', order_date=date(2026, 7, 1), customer_id=1,
                    customer_name='Acme', branch_id=main_branch.id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, quantity=Decimal('10'), unit_price=Decimal('5.00'),
                                        amount=Decimal('50.00')))
    so.line_items.append(SalesOrderItem(line_number=2, quantity=Decimal('20'), unit_price=Decimal('3.00'),
                                        amount=Decimal('60.00')))
    db.session.add(so); db.session.commit()
    payload = _so_lines_payload([so])
    rows = payload[so.id]
    assert [r['line_number'] for r in rows] == [1, 2]
