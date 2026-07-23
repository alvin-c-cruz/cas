from decimal import Decimal
from datetime import date
from app import db
from app.stock_adjustments.models import PhysicalCount, StockBalance
from app.stock_adjustments.physical_count_service import (
    snapshot_physical_count_lines, approve_physical_count, void_physical_count)


class TestVoidPhysicalCount:
    def test_voids_the_linked_adjustment_and_flips_status(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                           quantity_on_hand=Decimal('10'), average_unit_cost=Decimal('5.00'),
                           total_value=Decimal('50.00'))
        db.session.add(bal)
        db.session.commit()
        pc = PhysicalCount(pc_number='PC-2026-07-0030', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])
        pc.lines[0].counted_qty = Decimal('7')
        db.session.add(pc)
        db.session.commit()
        approve_physical_count(pc, admin_user)
        db.session.commit()
        assert pc.stock_adjustment_id is not None

        void_physical_count(pc, admin_user)
        db.session.commit()

        assert pc.status == 'voided'
        assert pc.stock_adjustment.status == 'voided'
        restored = StockBalance.query.filter_by(product_id=product_moving_avg.id,
                                                 branch_id=branch_main.id).first()
        assert restored.quantity_on_hand == Decimal('10.0000')

    def test_voiding_a_clean_count_with_no_linked_adjustment_just_flips_status(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc = PhysicalCount(pc_number='PC-2026-07-0031', branch_id=branch_main.id,
                           count_date=date(2026, 7, 23), status='draft')
        snapshot_physical_count_lines(pc, [product_moving_avg])
        pc.lines[0].counted_qty = Decimal('0')
        db.session.add(pc)
        db.session.commit()
        approve_physical_count(pc, admin_user)
        db.session.commit()
        assert pc.stock_adjustment_id is None

        void_physical_count(pc, admin_user)
        db.session.commit()

        assert pc.status == 'voided'
