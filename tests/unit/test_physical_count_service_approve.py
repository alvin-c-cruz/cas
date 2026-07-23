from decimal import Decimal
from app import db
from app.stock_adjustments.models import StockBalance
from app.stock_adjustments.physical_count_service import is_auto_postable_line


class TestIsAutoPostableLine:
    def test_moving_average_negative_variance_is_postable(
            self, db_session, branch_main, product_moving_avg):
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                           quantity_on_hand=Decimal('10'), average_unit_cost=Decimal('5.00'),
                           total_value=Decimal('50.00'))
        db.session.add(bal)
        db.session.commit()
        assert is_auto_postable_line(product_moving_avg, branch_main.id, Decimal('-3')) is True

    def test_moving_average_positive_variance_with_no_balance_row_is_not_postable(
            self, db_session, branch_main, product_moving_avg):
        assert is_auto_postable_line(product_moving_avg, branch_main.id, Decimal('5')) is False

    def test_moving_average_positive_variance_with_zero_average_cost_is_not_postable(
            self, db_session, branch_main, product_moving_avg):
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                           quantity_on_hand=Decimal('0'), average_unit_cost=Decimal('0'),
                           total_value=Decimal('0'))
        db.session.add(bal)
        db.session.commit()
        assert is_auto_postable_line(product_moving_avg, branch_main.id, Decimal('5')) is False

    def test_moving_average_positive_variance_with_real_average_cost_is_postable(
            self, db_session, branch_main, product_moving_avg):
        bal = StockBalance(product_id=product_moving_avg.id, branch_id=branch_main.id,
                           quantity_on_hand=Decimal('10'), average_unit_cost=Decimal('5.00'),
                           total_value=Decimal('50.00'))
        db.session.add(bal)
        db.session.commit()
        assert is_auto_postable_line(product_moving_avg, branch_main.id, Decimal('5')) is True

    def test_standard_costed_positive_variance_is_postable_without_a_balance_row(
            self, db_session, branch_main, product_standard):
        assert is_auto_postable_line(product_standard, branch_main.id, Decimal('5')) is True

    def test_fifo_product_is_never_postable(self, db_session, branch_main, product_fifo):
        assert is_auto_postable_line(product_fifo, branch_main.id, Decimal('-3')) is False

    def test_specific_id_product_is_never_postable(self, db_session, branch_main, product_specific_id):
        assert is_auto_postable_line(product_specific_id, branch_main.id, Decimal('-3')) is False
