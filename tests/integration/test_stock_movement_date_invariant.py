"""A movement's date must equal the entry_date of the JE the same posting created.

Enforced by test rather than structurally: passing the JE into post_movement
would couple stock posting to GL posting for no gain. This also PROBES the memo
paths, whose JE dating was never verified -- if one dates its JE from something
other than memo_date, this fails and we have found a sibling GL-dating bug.
LOG that; do not fix it here. Changing a JE's date changes the books.

Every fixture document is backdated 30 days: if the document were dated today, a
movement still defaulting to today() would match its JE coincidentally and the
test would pass while proving nothing (a movement built with movement_date=None
falls back to ph_now().date() -- see post_movement's TEMPORARY scaffolding,
removed by this same task).
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import db
from app.journal_entries.models import JournalEntry
from app.products.models import Product
from app.stock_adjustments.models import StockMovement

pytestmark = [pytest.mark.integration]

D = Decimal
BACKDATE = date.today() - timedelta(days=30)


def _je_for(mv):
    je = db.session.get(JournalEntry, mv.journal_entry_id)
    assert je is not None, f'movement {mv.id} carries journal_entry_id {mv.journal_entry_id} but no JE exists'
    return je


# --- Receiving Report -------------------------------------------------------

def test_receiving_report_movement_date_matches_its_je(
        db_session, branch_main, admin_user, product_tracked, vl_vendor, make_account):
    """RR approve posts its JE at rr.receipt_date; the movement must agree."""
    from app.receiving_reports.stock_posting import post_rr_receipt
    from tests.integration.test_receiving_report_stock_posting import _assign, _approved_po, _draft_rr

    _assign('inventory_account_code', '1401', make_account)
    _assign('grni_account_code', '2015', make_account)
    po = _approved_po(db_session, branch_main, vl_vendor, product_tracked,
                       unit_price='11.20', vat_rate='12.00', qty=10)
    rr = _draft_rr(db_session, branch_main, po, received=10)
    rr.receipt_date = BACKDATE
    db.session.commit()

    post_rr_receipt(rr, admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(
        source_document_type='receiving_report', source_document_id=rr.id).one()
    je = _je_for(mv)
    assert mv.movement_date == je.entry_date, (
        'movement %d dated %s but its JE %s is dated %s'
        % (mv.id, mv.movement_date, je.entry_number, je.entry_date))
    assert mv.movement_date == BACKDATE


# --- Delivery Receipt --------------------------------------------------------

def test_delivery_receipt_movement_date_matches_its_je(
        db_session, branch_main, admin_user, product_tracked, make_account):
    """DR deliver posts its JE at dr.delivery_date; the movement must agree."""
    from app.delivery_receipts.stock_posting import post_dr_delivery
    from tests.integration.test_delivery_receipt_stock_posting import _assign, _confirmed_so, _delivered_dr
    from app.stock_adjustments.service import post_movement

    _assign('inventory_account_code', '1401', make_account)
    _assign('cogs_account_code', '61060', make_account)
    post_movement(product_tracked, branch_main.id, 'receipt', Decimal('20'), Decimal('8.00'),
                  'seed', None, 'seed stock', admin_user,
                  movement_date=BACKDATE - timedelta(days=30))
    db.session.commit()
    so = _confirmed_so(db_session, branch_main, product_tracked, qty=6)
    dr = _delivered_dr(db_session, branch_main, so, delivered_qty=6)
    dr.delivery_date = BACKDATE
    db.session.commit()

    post_dr_delivery(dr, admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(
        source_document_type='delivery_receipt', source_document_id=dr.id).one()
    je = _je_for(mv)
    assert mv.movement_date == je.entry_date, (
        'movement %d dated %s but its JE %s is dated %s'
        % (mv.id, mv.movement_date, je.entry_number, je.entry_date))
    assert mv.movement_date == BACKDATE


# --- Stock Adjustment ---------------------------------------------------------

def test_stock_adjustment_movement_date_matches_its_je(
        db_session, product_tracked, branch_main, admin_user, make_account):
    """Approve posts its JE at adjustment.adjustment_date; the movement must agree."""
    from app.stock_adjustments.service import approve_adjustment
    from app.stock_adjustments.numbering import generate_sa_number
    from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine
    from tests.integration.test_stock_adjustment_posting import _assign

    _assign('inventory_account_code', '1401', make_account)
    _assign('inventory_adjustment_account_code', '7101', make_account)
    adj = StockAdjustment(sa_number=generate_sa_number(), branch_id=branch_main.id,
                          adjustment_date=BACKDATE, reason_type='correction',
                          status='draft', created_by_id=admin_user.id)
    adj.lines.append(StockAdjustmentLine(product_id=product_tracked.id,
                                         quantity_delta=Decimal('5'), unit_cost=Decimal('4.00')))
    db.session.add(adj); db.session.commit()

    approve_adjustment(adj, admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(
        source_document_type='stock_adjustment', source_document_id=adj.id).one()
    je = _je_for(mv)
    assert mv.movement_date == je.entry_date, (
        'movement %d dated %s but its JE %s is dated %s'
        % (mv.id, mv.movement_date, je.entry_number, je.entry_date))
    assert mv.movement_date == BACKDATE


# --- Sales (Credit) Memo -------------------------------------------------------

def test_credit_memo_movement_date_matches_its_je(db_session, main_branch, admin_user):
    """A chain-verified credit-memo return posts its JE at memo.memo_date; the
    sales_return movement must agree. THIS PROBES sales_memos/je.py's JE dating --
    see module docstring."""
    from app.sales_memos.je import post_memo_je
    from app.stock_adjustments.service import post_movement
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    from tests.integration.test_credit_memo_stock_posting import (
        _full_cm_coa, _si_with_item, _so_item, _cm_item_for)

    _full_cm_coa()
    product = Product(code='INV-CMC-PROD', name='Invariant CM Product', is_active=True,
                      track_inventory=True, costing_method='moving_average')
    db.session.add(product); db.session.commit()
    post_movement(product, main_branch.id, 'receipt', Decimal('20'), Decimal('4.00'),
                  'seed', None, 'seed stock', admin_user,
                  movement_date=BACKDATE - timedelta(days=30))
    db.session.commit()
    si, si_item = _si_with_item(main_branch, product)
    so, soi = _so_item(main_branch, si.customer, product, 'SO-INV-CMC-0001')
    dr = DeliveryReceipt(branch_id=main_branch.id, dr_number='DR-INV-CMC-0001',
                         delivery_date=date(2026, 2, 8), sales_order_id=so.id,
                         customer_id=si.customer_id, customer_name=si.customer.name,
                         sales_invoice_id=si.id, status='delivered')
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=soi.id,
                                             product_id=product.id, delivered_quantity=Decimal('5')))
    db.session.add(dr); db.session.commit()
    mitem = _cm_item_for(si_item)
    memo = mitem.memo
    memo.memo_date = BACKDATE
    memo.subtotal = Decimal('22.40'); memo.vat_amount = Decimal('2.40')
    memo.total_amount = Decimal('22.40')
    db.session.commit()

    post_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(
        source_document_type='sales_memo', source_document_id=memo.id).one()
    je = _je_for(mv)
    assert mv.movement_date == je.entry_date, (
        'movement %d dated %s but its JE %s is dated %s'
        % (mv.id, mv.movement_date, je.entry_number, je.entry_date))
    assert mv.movement_date == BACKDATE


# --- Purchase (Debit) Memo -----------------------------------------------------

def test_purchase_memo_movement_date_matches_its_je(db_session, main_branch, admin_user):
    """A chain-verified debit-memo return posts its JE at memo.memo_date; the
    purchase_return movement must agree. THIS PROBES purchase_memos/je.py's JE
    dating -- see module docstring."""
    from app.purchase_memos.je import post_purchase_memo_je
    from tests.purchase_memos.test_stock_posting import _full_vdm_coa, _ap_item_from_rr, _memo_item_for

    _full_vdm_coa()
    ap_item, product = _ap_item_from_rr(db_session, main_branch, admin_user, tracked=True)
    mitem = _memo_item_for(ap_item)
    mitem.product_id = product.id
    mitem.quantity = Decimal('2')
    mitem.amount = Decimal('11.20'); mitem.line_total = Decimal('11.20')
    mitem.vat_amount = Decimal('1.20')
    memo = mitem.memo
    memo.memo_date = BACKDATE
    memo.subtotal = Decimal('11.20'); memo.vat_amount = Decimal('1.20')
    memo.total_amount = Decimal('11.20')
    db.session.commit()

    post_purchase_memo_je(memo, admin_user.id, actor=admin_user)
    db.session.commit()

    mv = StockMovement.query.filter_by(
        source_document_type='purchase_memo', source_document_id=memo.id).one()
    je = _je_for(mv)
    assert mv.movement_date == je.entry_date, (
        'movement %d dated %s but its JE %s is dated %s'
        % (mv.id, mv.movement_date, je.entry_number, je.entry_date))
    assert mv.movement_date == BACKDATE
