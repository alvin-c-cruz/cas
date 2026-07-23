"""Physical Count service layer (R-03, the original slice 4). This module
never writes a StockMovement or a JE line directly -- it assembles a
StockAdjustment and hands it to the already-shipped approve_adjustment()/
void_adjustment() in service.py. See docs/superpowers/specs/
2026-07-23-stock-ledger-physical-count-design.md for the full design.
"""
from decimal import Decimal
from app.stock_adjustments.models import PhysicalCountLine, StockBalance

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
