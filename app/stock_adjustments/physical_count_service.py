"""Physical Count service layer (R-03, the original slice 4). This module
never writes a StockMovement or a JE line directly -- it assembles a
StockAdjustment and hands it to the already-shipped approve_adjustment()/
void_adjustment() in service.py. See docs/superpowers/specs/
2026-07-23-stock-ledger-physical-count-design.md for the full design.
"""
from decimal import Decimal
from app import db
from app.stock_adjustments.models import PhysicalCountLine, StockBalance
from app.utils import ph_now

ZERO = Decimal('0')


def snapshot_physical_count_lines(count, products):
    """Create one PhysicalCountLine per product, book_qty_snapshot = that
    product's current StockBalance.quantity_on_hand in count.branch_id (0 if
    no balance row exists yet). Mutates count.lines in place; does not
    commit -- the caller owns the transaction."""
    for product in products:
        bal = (StockBalance.query
              .filter_by(product_id=product.id, branch_id=count.branch_id).first())
        book_qty = Decimal(bal.quantity_on_hand) if bal else ZERO
        count.lines.append(PhysicalCountLine(product_id=product.id, book_qty_snapshot=book_qty))


def line_variance(line):
    """Display-time variance against the SNAPSHOT (informational only --
    the count-entry and detail screens use this; approve_physical_count()
    re-reads the CURRENT balance instead, see Task 6)."""
    if line.counted_qty is None:
        return None
    return Decimal(line.counted_qty) - Decimal(line.book_qty_snapshot)


_AUTO_POST_METHODS = ('moving_average', 'standard')


def is_auto_postable_line(product, branch_id, variance):
    """A line auto-posts only if BOTH: (1) the product's costing method is
    moving_average/standard (fifo/lifo/specific_identification always route
    to manual resolution -- see the design doc), AND (2) for a POSITIVE
    variance on a moving_average product specifically, a real cost basis
    exists to value the overage at. There is no unit-cost entry field in
    this slice's count-entry UI, so the only available basis is the
    product's current average cost; if that balance doesn't exist yet or is
    <= 0, this line is not postable even though its costing method
    qualifies. 'standard' is unaffected -- it always values via
    Product.standard_cost, never the balance average."""
    method = product.costing_method or 'moving_average'
    if method not in _AUTO_POST_METHODS:
        return False
    if variance > ZERO and method == 'moving_average':
        bal = StockBalance.query.filter_by(product_id=product.id, branch_id=branch_id).first()
        if bal is None or Decimal(bal.average_unit_cost) <= ZERO:
            return False
    return True


def approve_physical_count(count, actor):
    """Re-check the CURRENT book quantity per line (not the stale snapshot --
    see is_auto_postable_line's docstring and the design doc's "Stale
    counts" section for why), split eligible vs. excluded lines, and
    auto-post ONE StockAdjustment for eligible nonzero-variance lines.
    Does not commit -- caller owns the transaction, matching
    approve_adjustment()'s own contract."""
    from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine
    from app.stock_adjustments.numbering import generate_sa_number
    from app.stock_adjustments.service import approve_adjustment

    drift_notices = []
    sa_lines = []
    for line in count.lines:
        if line.counted_qty is None:
            continue
        product = line.product
        bal = StockBalance.query.filter_by(product_id=product.id, branch_id=count.branch_id).first()
        current_qty = Decimal(bal.quantity_on_hand) if bal else ZERO
        variance = Decimal(line.counted_qty) - current_qty

        if current_qty != Decimal(line.book_qty_snapshot):
            drift_notices.append(
                f'{product.code}: book quantity changed from {line.book_qty_snapshot} '
                f'to {current_qty} since this count was taken.')

        if variance == ZERO:
            continue
        if not is_auto_postable_line(product, count.branch_id, variance):
            continue

        unit_cost = None
        if variance > ZERO and (product.costing_method or 'moving_average') != 'standard':
            unit_cost = Decimal(bal.average_unit_cost)
        sa_lines.append(StockAdjustmentLine(
            product_id=product.id, quantity_delta=variance, unit_cost=unit_cost,
            note=f'Physical Count {count.pc_number}'))

    adjustment = None
    if sa_lines:
        adjustment = StockAdjustment(
            sa_number=generate_sa_number(), branch_id=count.branch_id,
            adjustment_date=count.count_date, reason_type='physical_count',
            notes=f'Auto-generated from Physical Count {count.pc_number}',
            status='draft', created_by_id=actor.id)
        for li in sa_lines:
            adjustment.lines.append(li)
        db.session.add(adjustment)
        db.session.flush()
        approve_adjustment(adjustment, actor)
        count.stock_adjustment_id = adjustment.id

    count.status = 'approved'
    count.approved_by_id = actor.id
    count.approved_at = ph_now()
    count._drift_notices = drift_notices   # transient, read by the view for a flash
    return count, adjustment
