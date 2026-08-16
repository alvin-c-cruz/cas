"""validate_amendment refuses what would contradict an already-consumed child."""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.validation import validate_amendment
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem


@pytest.fixture
def po(db_session):
    po = PurchaseOrder(po_number='00998', order_date=date(2026, 8, 5), status='approved',
                       vendor_name='ACME', notes='', payment_terms='Net 30',
                       vat_treatment='inclusive')
    for n, qty in ((1, '10'), (2, '10')):
        po.line_items.append(PurchaseOrderItem(
            line_number=n, description='widget', quantity=Decimal(qty),
            unit_price=Decimal('5.00'), amount=Decimal('50.00'),
            line_total=Decimal('50.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.add(po)
    db.session.commit()
    return po


def _receive(po, line, qty, status='approved'):
    rr = ReceivingReport(rr_number='RR-%s-%s' % (line.id, status),
                         receipt_date=date(2026, 8, 6), vendor_id=1,
                         vendor_name=po.vendor_name, status=status)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=line.id, received_quantity=Decimal(qty)))
    db.session.add(rr)
    db.session.commit()


def _rows(po, **qty_by_line):
    return [{'po_item_id': li.id, 'quantity': qty_by_line.get('l%d' % li.line_number, '10')}
            for li in po.line_items]


class TestValidateAmendment:
    def test_unchanged_submission_is_allowed(self, po):
        assert validate_amendment(po, _rows(po), 'po_item_id') == []

    def test_increase_is_allowed(self, po):
        _receive(po, po.line_items[0], '4')
        assert validate_amendment(po, _rows(po, l1='25'), 'po_item_id') == []

    def test_reduction_below_received_is_refused(self, po):
        _receive(po, po.line_items[0], '4')
        errors = validate_amendment(po, _rows(po, l1='3'), 'po_item_id')
        assert any('below the 4 already received' in e for e in errors)

    def test_reduction_to_exactly_received_is_allowed(self, po):
        _receive(po, po.line_items[0], '4')
        assert validate_amendment(po, _rows(po, l1='4'), 'po_item_id') == []

    def test_removing_a_received_line_is_refused(self, po):
        _receive(po, po.line_items[0], '4')
        rows = [r for r in _rows(po) if r['po_item_id'] != po.line_items[0].id]
        errors = validate_amendment(po, rows, 'po_item_id')
        assert any('already received' in e for e in errors)

    def test_removing_a_line_referenced_only_by_a_DRAFT_receipt_is_refused(self, po):
        # The floor sees 0 here; the reference check is what saves the FK.
        _receive(po, po.line_items[0], '4', status='draft')
        rows = [r for r in _rows(po) if r['po_item_id'] != po.line_items[0].id]
        errors = validate_amendment(po, rows, 'po_item_id')
        assert any('Receiving Report' in e for e in errors)

    def test_removing_an_untouched_line_is_allowed(self, po):
        rows = [r for r in _rows(po) if r['po_item_id'] != po.line_items[1].id]
        assert validate_amendment(po, rows, 'po_item_id') == []

    def test_unreadable_quantity_is_refused_not_treated_as_zero(self, po):
        errors = validate_amendment(po, _rows(po, l1='wat'), 'po_item_id')
        assert any('could not read' in e for e in errors)

    def test_out_of_range_reports_range_not_unreadable(self, po):
        errors = validate_amendment(po, _rows(po, l1='1E+9999'), 'po_item_id')
        assert any('out of range' in e for e in errors)
        assert not any('could not read' in e for e in errors)

    def test_the_message_formatter_never_raises(self, po):
        """m3 / Task 3's M1: `_qty()` did `Decimal(str(value))` unguarded, so
        `_qty(None)` and `_qty(OUT_OF_RANGE)` raised InvalidOperation.

        Every call site is guarded today, so this is unreachable through the
        route -- but it is a display helper inside a module whose headline promise
        is that it never raises, and this branch wired three more callers to it.
        A formatter that can take down the request it was called to explain is the
        wrong shape whether or not today's callers happen to avoid it.
        """
        from app.amendments.validation import OUT_OF_RANGE, _qty

        for value in (None, OUT_OF_RANGE, 'wat', object()):
            out = _qty(value)
            assert isinstance(out, str) and out, repr(value)
        # ... and the normal path is untouched: the DB scale padding is still
        # stripped, which is the only reason _qty exists.
        assert _qty(Decimal('4.0000')) == '4'
        assert _qty(Decimal('-0')) == '0'
        assert _qty(Decimal('2.5000')) == '2.5'

    def test_per_row_keying_blocks_the_sibling_absorption_exploit(self, po):
        # THE regression test. Both lines are the same product; line 1 is fully
        # received. Zeroing it while a sibling absorbs the total must NOT pass.
        _receive(po, po.line_items[0], '10')
        errors = validate_amendment(po, _rows(po, l1='0', l2='20'), 'po_item_id')
        assert errors, 'per-product aggregation would have allowed this'
        assert any('below the 10 already received' in e for e in errors)
