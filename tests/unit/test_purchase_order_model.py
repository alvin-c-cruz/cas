"""Unit tests for the PurchaseOrder model + PO-#### numbering (operational, posts no JE)."""
from decimal import Decimal
from app.purchase_orders.models import (
    PurchaseOrder, PurchaseOrderItem, generate_po_number, VAT_TREATMENTS,
)


def test_vat_treatments_constant():
    assert VAT_TREATMENTS == ('inclusive', 'exclusive', 'zero_rated')


def test_generate_po_number_first_of_month(db_session):
    n = generate_po_number()
    assert n.startswith('PO-')
    assert n.endswith('-0001')


def test_generate_po_number_increments(db_session):
    n1 = generate_po_number()
    po = PurchaseOrder(po_number=n1, order_date=None, status='draft')
    db_session.add(po)
    db_session.commit()
    assert generate_po_number().endswith('-0002')


def test_line_amounts_inclusive_extracts_vat(db_session):
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('2'),
                           unit_price=Decimal('56'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    assert li.amount == Decimal('112.00')          # 2 x 56, VAT-inclusive
    assert li.vat_amount == Decimal('12.00')       # 112 - 112/1.12
    assert li.line_total == Decimal('112.00')      # line_total = the inclusive amount (mirror SO)
    assert li.amount - li.vat_amount == Decimal('100.00')  # net-of-VAT


def test_totals_inclusive_extracts(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='inclusive')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('112'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.subtotal == Decimal('112.00')
    assert po.vat_amount == Decimal('12.00')
    assert po.total_amount == Decimal('112.00')


def test_totals_exclusive_adds_vat(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='exclusive')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('100'), vat_category='V12', vat_rate=Decimal('12'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.vat_amount == Decimal('12.00')
    assert po.total_amount == Decimal('112.00')


def test_totals_zero_rated(db_session):
    po = PurchaseOrder(po_number=generate_po_number(), status='draft', vat_treatment='zero_rated')
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('1'),
                           unit_price=Decimal('100'), vat_category='V0', vat_rate=Decimal('0'))
    li.calculate_amounts()
    po.line_items.append(li)
    po.calculate_totals()
    assert po.vat_amount == Decimal('0.00')
    assert po.total_amount == Decimal('100.00')


def test_received_billed_default_zero(db_session):
    li = PurchaseOrderItem(line_number=1, quantity=Decimal('5'), unit_price=Decimal('10'))
    assert (li.received_quantity or 0) == 0
    assert (li.billed_quantity or 0) == 0
