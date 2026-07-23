from decimal import Decimal
from app import db
from app.stock_adjustments.models import PhysicalCount, StockBalance
from app.stock_adjustments.physical_count_service import (
    snapshot_physical_count_lines, line_variance)


class TestSnapshotPhysicalCountLines:
    def test_snapshots_current_book_quantity(self, db_session, branch_main, product_moving_avg):
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                           quantity_on_hand=Decimal('42.0000'),
                           average_unit_cost=Decimal('5.00'), total_value=Decimal('210.00'))
        db.session.add(bal)
        db.session.commit()

        pc = PhysicalCount(pc_number='PC-2026-07-0010', branch_id=branch_main.id,
                           count_date=db.func.current_date(), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])

        assert len(pc.lines) == 1
        assert pc.lines[0].product_id == product_moving_avg.id
        assert pc.lines[0].book_qty_snapshot == Decimal('42.0000')
        assert pc.lines[0].counted_qty is None

    def test_snapshots_zero_for_a_product_with_no_balance_row(
            self, db_session, branch_main, product_moving_avg):
        pc = PhysicalCount(pc_number='PC-2026-07-0011', branch_id=branch_main.id,
                           count_date=db.func.current_date(), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])

        assert pc.lines[0].book_qty_snapshot == Decimal('0')


class TestLineVariance:
    def test_variance_none_when_not_yet_counted(self):
        from app.stock_adjustments.models import PhysicalCountLine
        line = PhysicalCountLine(book_qty_snapshot=Decimal('10.0000'), counted_qty=None)
        assert line_variance(line) is None

    def test_variance_computed_against_snapshot(self):
        from app.stock_adjustments.models import PhysicalCountLine
        line = PhysicalCountLine(book_qty_snapshot=Decimal('10.0000'), counted_qty=Decimal('7.0000'))
        assert line_variance(line) == Decimal('-3.0000')
