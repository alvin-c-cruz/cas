"""Mutation-style proof the conditional UPDATE rejects a stale racer -- not just
asserted. Simulate a lost race by mutating row_version out from under a caller
that read the old version."""
from decimal import Decimal
from app import db
from app.stock_adjustments.service import _claim_balance_update  # low-level guard
from app.stock_adjustments.models import StockBalance


def test_stale_version_update_is_rejected(db_session, product_tracked, branch_main):
    bal = StockBalance(product_id=product_tracked.id, branch_id=branch_main.id,
                       quantity_on_hand=Decimal('0'), average_unit_cost=Decimal('0'),
                       total_value=Decimal('0'))
    db.session.add(bal); db.session.commit()
    stale_version = bal.row_version
    # a concurrent writer bumps the version
    db.session.execute(db.update(StockBalance).where(StockBalance.id == bal.id)
                       .values(row_version=StockBalance.row_version + 1))
    db.session.commit()
    ok = _claim_balance_update(bal.id, stale_version, Decimal('5'), Decimal('5.00'), Decimal('25.00'))
    assert ok is False   # stale token loses
