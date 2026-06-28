import json
from datetime import date
from decimal import Decimal, InvalidOperation
from app import db
from app.utils import ph_now
from app.sales_orders.models import SalesOrder, SalesOrderItem


def _parse_and_attach_so_lines(so, lines_json):
    """Parse hidden-JSON line array and attach SalesOrderItem objects to *so*.
    Mirrors sales_invoices.views._parse_and_attach_line_items but with no account_id/wt.
    """
    def _dec(v):
        try:
            return Decimal(str(v)) if v not in (None, '', 'null') else None
        except (InvalidOperation, TypeError):
            return None

    def _int(v):
        try:
            return int(v) if v and str(v).strip() not in ('', 'null') else None
        except (ValueError, TypeError):
            return None

    items = json.loads(lines_json) if lines_json else []
    for idx, d in enumerate(items, start=1):
        vat_rate = _dec(d.get('vat_rate')) or Decimal('0.00')
        li = SalesOrderItem(
            line_number=idx,
            description=d.get('description', ''),
            quantity=_dec(d.get('quantity')),
            unit_price=_dec(d.get('unit_price')),
            uom_text=(d.get('uom_text') or None),
            unit_of_measure_id=_int(d.get('uom_id')),
            product_id=_int(d.get('product_id')),
            amount=Decimal(str(d.get('amount', '0') or '0')),
            vat_category=d.get('vat_category') or None,
            vat_rate=vat_rate,
        )
        li.calculate_amounts()
        so.line_items.append(li)


def generate_so_number():
    """Next SO-YYYY-MM-#### for the current PH month (suffix = max existing this month + 1)."""
    today = ph_now().date()
    prefix = f"SO-{today.year:04d}-{today.month:02d}-"
    rows = (SalesOrder.query
            .filter(SalesOrder.so_number.like(prefix + '%'))
            .with_entities(SalesOrder.so_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
