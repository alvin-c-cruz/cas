"""A PO line whose price (or quantity) was cleared no longer keeps its old amount (PO-AMEND).

Owner, 14 Nov 2026: "PO-AMEND yes" (triage work order 2026-08-18-open-bug-triage, BUG-PO-AMEND-STALE-AMOUNT-CELL).
The form's amount cell kept its last figure when qty or price was cleared, posted that figure, and the server kept it
because PurchaseOrderItem.calculate_amounts only recomputed when BOTH were > 0. On a PO with two or more lines the
"at least one priced line" guard still passed, so the phantom amount reached the line, the subtotal and the total.

The rule now (server and form alike): amount = qty x price. A line with a product, a quantity or a price that does
not multiply out is 0. Only a description-only line with neither quantity nor price keeps the amount it was given
(none exist on Philgen or RIC today, and the form cannot make one; kept so such a line is never zeroed silently).
"""
import json
from decimal import Decimal

import pytest

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from tests.integration.test_po_amend import (_payload, approved_po, logged_in, po_enabled,  # noqa: F401
                                             vendor_acme)

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


def _item(**kw):
    base = dict(line_number=1, description='x', vat_rate=Decimal('0'))
    base.update(kw)
    return PurchaseOrderItem(**base)


class TestTheRule:

    def test_qty_times_price(self):
        li = _item(quantity=Decimal('3'), unit_price=Decimal('2.50'), amount=Decimal('999'))
        li.calculate_amounts()
        assert li.amount == Decimal('7.50')

    @pytest.mark.parametrize('qty,price', [('5', None), (None, '12.00'), ('0', '12.00'), ('5', '0')])
    def test_a_line_that_does_not_multiply_out_is_zero(self, qty, price):
        li = _item(quantity=Decimal(qty) if qty else None, unit_price=Decimal(price) if price else None,
                   amount=Decimal('999.00'))
        li.calculate_amounts()
        assert li.amount == Decimal('0')
        assert li.line_total == Decimal('0')

    def test_a_goods_line_with_neither_is_zero(self):
        li = _item(product_id=1, quantity=None, unit_price=None, amount=Decimal('999.00'))
        li.calculate_amounts()
        assert li.amount == Decimal('0')

    def test_a_description_only_line_with_neither_keeps_its_amount(self):
        li = _item(product_id=None, quantity=None, unit_price=None, amount=Decimal('1500.00'))
        li.calculate_amounts()
        assert li.amount == Decimal('1500.00')


class TestTheAmendPath:

    def _amend(self, client, po, line_items):
        return client.post(f'/purchase-orders/{po.id}/amend', data={
            'po_number': po.po_number, 'order_date': '2026-08-05', 'vendor_id': po.vendor_id,
            'vat_treatment': 'inclusive', 'payment_terms': 'Net 30', 'notes': '',
            'amend_reason': 'second line price withdrawn by the vendor',
            'line_items': line_items, 'row_version': po.row_version}, follow_redirects=True)

    def test_clearing_one_lines_price_drops_its_amount_from_the_total(self, client, admin_user, approved_po):
        """The triage case: two lines, one price cleared, the stale amount posted with it."""
        lines = json.loads(_payload(approved_po))
        lines.append({'po_item_id': None, 'product_id': None, 'description': 'bolt', 'quantity': '3',
                      'unit_price': '2.00', 'amount': '6.00', 'vat_category': None, 'vat_rate': '0'})
        self._amend(client, approved_po, json.dumps(lines))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)
        assert len(po.line_items) == 2 and po.total_amount == Decimal('56.00'), 'precondition'

        bolt = po.line_items[1]
        stale = json.loads(_payload(po, {bolt.id: {'unit_price': '', 'amount': '6.00'}}))
        self._amend(client, po, json.dumps(stale))
        db.session.expire_all()
        po = db.session.get(PurchaseOrder, approved_po.id)

        bolt = po.line_items[1]
        assert bolt.unit_price is None
        assert bolt.amount == Decimal('0'), 'the posted 6.00 is stale and must not be kept'
        assert po.total_amount == Decimal('50.00')
