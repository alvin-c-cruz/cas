from decimal import Decimal
from datetime import date
from app import db
from app.stock_adjustments.models import PhysicalCount, StockBalance
from app.stock_adjustments.physical_count_service import (
    snapshot_physical_count_lines, approve_physical_count)


def _setup_count(branch, product, book_qty, avg_cost, counted_qty):
    bal = StockBalance(product_id=product.id, branch_id=branch.id,
                       quantity_on_hand=Decimal(book_qty), average_unit_cost=Decimal(avg_cost),
                       total_value=Decimal(book_qty) * Decimal(avg_cost))
    db.session.add(bal)
    db.session.commit()
    pc = PhysicalCount(pc_number='PC-2026-07-0020', branch_id=branch.id,
                       count_date=date(2026, 7, 23), status='draft')
    snapshot_physical_count_lines(pc, [product])
    pc.lines[0].counted_qty = Decimal(counted_qty)
    db.session.add(pc)
    db.session.commit()
    return pc, bal


class TestApprovePhysicalCount:
    def test_posts_stock_adjustment_for_nonzero_eligible_variance(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_moving_avg, '10', '5.00', '7')

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        assert count.status == 'approved'
        assert adjustment is not None
        assert adjustment.status == 'posted'
        assert count.stock_adjustment_id == adjustment.id
        assert adjustment.reason_type == 'physical_count'
        assert len(adjustment.lines) == 1
        assert adjustment.lines[0].quantity_delta == Decimal('-3')

        refreshed = StockBalance.query.filter_by(product_id=product_moving_avg.id,
                                                  branch_id=branch_main.id).first()
        assert refreshed.quantity_on_hand == Decimal('7.0000')

    def test_zero_variance_skips_posting_but_still_approves(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_moving_avg, '10', '5.00', '10')

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        assert count.status == 'approved'
        assert adjustment is None
        assert count.stock_adjustment_id is None

    def test_no_eligible_lines_approves_with_no_adjustment(
            self, db_session, branch_main, product_fifo, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_fifo, '10', '5.00', '7')

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        assert count.status == 'approved'
        assert adjustment is None
        # FIFO's own balance is untouched -- this branch never auto-posts for it.
        refreshed = StockBalance.query.filter_by(product_id=product_fifo.id,
                                                  branch_id=branch_main.id).first()
        assert refreshed.quantity_on_hand == Decimal('10')

    def test_reposts_against_current_balance_when_it_drifted_since_the_count(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_moving_avg, '10', '5.00', '7')
        # Simulate an unrelated receipt landing AFTER the count was taken but
        # BEFORE it was approved: book qty is now 15, not the 10 snapshotted.
        bal.quantity_on_hand = Decimal('15.0000')
        db.session.commit()

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        # Variance posted is against the CURRENT balance (15), not the stale
        # snapshot (10): 7 counted - 15 current = -8, not -3.
        assert adjustment.lines[0].quantity_delta == Decimal('-8')
        assert len(count._drift_notices) == 1
        assert product_moving_avg.code in count._drift_notices[0]

    def test_approve_does_not_commit_itself(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_moving_avg, '10', '5.00', '7')
        approve_physical_count(pc, admin_user)
        db.session.rollback()

        reloaded = db.session.get(PhysicalCount, pc.id)
        assert reloaded.status == 'draft'

    def test_posts_stock_adjustment_for_positive_moving_average_variance(
            self, db_session, branch_main, product_moving_avg, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_moving_avg, '10', '5.00', '13')

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        assert adjustment is not None
        assert adjustment.status == 'posted'
        assert len(adjustment.lines) == 1
        assert adjustment.lines[0].quantity_delta == Decimal('3')
        assert adjustment.lines[0].unit_cost == Decimal('5.00')

        refreshed = StockBalance.query.filter_by(product_id=product_moving_avg.id,
                                                  branch_id=branch_main.id).first()
        assert refreshed.quantity_on_hand == Decimal('13.0000')

    def test_posts_stock_adjustment_for_positive_standard_cost_variance(
            self, db_session, branch_main, product_standard, admin_user, control_accounts):
        pc, bal = _setup_count(branch_main, product_standard, '10', '5.00', '15')

        count, adjustment = approve_physical_count(pc, admin_user)
        db.session.commit()

        assert adjustment is not None
        assert adjustment.status == 'posted'
        assert adjustment.lines[0].quantity_delta == Decimal('5')
        assert adjustment.lines[0].unit_cost is None
