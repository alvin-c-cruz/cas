"""PurchaseOrder.build_snapshot() emits a complete, canonicalised picture of the PO."""
from datetime import date
from decimal import Decimal

from app import db
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem


def _po(db_session, branch_id=None):
    po = PurchaseOrder(po_number='00998', order_date=date(2026, 8, 5),
                       vendor_name='THAI SHIN-I INDUSTRY CO,.LTD.', status='approved',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch_id, notes='')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='S-C71-2-23 PUSHER (SUS304)',
        quantity=Decimal('1'), unit_price=Decimal('121.00'), amount=Decimal('121.00'),
        line_total=Decimal('121.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0'),
    ))
    db.session.add(po)
    db.session.commit()
    return po


class TestPurchaseOrderSnapshot:
    def test_document_type_matches_the_audit_module_name(self):
        assert PurchaseOrder.DOCUMENT_TYPE == 'purchase_orders'

    def test_header_carries_every_declared_field_even_when_null(self, db_session):
        snap = _po(db_session).build_snapshot()
        for key in PurchaseOrder.SNAPSHOT_HEADER_FIELDS:
            assert key in snap['header'], f'{key} missing -- viewer would read a default'
        assert snap['header']['po_number'] == '00998'
        assert snap['header']['order_date'] == '2026-08-05'
        assert snap['header']['expected_date'] is None

    def test_money_carries_a_display_form_alongside_the_canonical_one(self, db_session):
        po = _po(db_session)
        po.subtotal = Decimal('121.00')
        po.total_amount = Decimal('121.00')
        db.session.commit()
        snap = po.build_snapshot()
        assert snap['header']['subtotal_display'] == '121.00'
        assert snap['header']['total_amount_display'] == '121.00'

    def test_lines_carry_raw_id_and_resolved_names(self, db_session):
        snap = _po(db_session).build_snapshot()
        line = snap['lines'][0]
        assert isinstance(line['line_id'], int), 'line_id stays a raw int for exact lookups'
        assert line['quantity'] == '1'
        assert line['unit_price_display'] == '121.00'
        assert 'product_code' in line and 'product_name' in line

    def test_lines_are_ordered_by_line_number(self, db_session):
        po = _po(db_session)
        po.line_items.append(PurchaseOrderItem(
            line_number=2, description='second', quantity=Decimal('2'),
            unit_price=Decimal('6.50'), amount=Decimal('13.00'),
            line_total=Decimal('13.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
        db.session.commit()
        nums = [ln['line_number'] for ln in po.build_snapshot()['lines']]
        assert nums == ['1', '2']

    def test_dead_counters_are_not_snapshotted(self, db_session):
        # received_quantity/billed_quantity are never written by anything (see spec,
        # Out of scope). Snapshotting a permanent 0 would record a false fact.
        line = _po(db_session).build_snapshot()['lines'][0]
        assert 'received_quantity' not in line
        assert 'billed_quantity' not in line
