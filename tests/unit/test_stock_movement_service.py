from decimal import Decimal
from app import db
from app.stock_adjustments.service import post_movement, reverse_document_movements
from app.stock_adjustments.models import StockBalance

D = Decimal


def test_sequence_produces_correct_running_balance(db_session, product_tracked, branch_main, admin_user):
    # +10 @5, +10 @7 -> 20 @6 ; -5 -> 15 @6
    post_movement(product_tracked, branch_main.id, 'adjustment', D('10'), D('5.00'),
                  'stock_adjustment', 1, 'in', admin_user)
    post_movement(product_tracked, branch_main.id, 'adjustment', D('10'), D('7.00'),
                  'stock_adjustment', 2, 'in', admin_user)
    mv, went_negative = post_movement(product_tracked, branch_main.id, 'adjustment', D('-5'), None,
                                      'stock_adjustment', 3, 'out', admin_user)
    db.session.commit()
    assert not went_negative
    assert mv.balance_qty_after == D('15.0000')
    assert mv.balance_avg_cost_after == D('6.00')
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == D('15.0000')
    assert bal.total_value == D('90.00')


def test_negative_stock_flagged_but_posts(db_session, product_tracked, branch_main, admin_user):
    mv, went_negative = post_movement(product_tracked, branch_main.id, 'adjustment', D('-3'), None,
                                      'stock_adjustment', 1, 'out', admin_user)
    db.session.commit()
    assert went_negative is True
    assert mv.balance_qty_after == D('-3.0000')


def test_reverse_document_movements(db_session, product_tracked, branch_main, admin_user):
    post_movement(product_tracked, branch_main.id, 'adjustment', D('10'), D('5.00'),
                  'stock_adjustment', 7, 'in', admin_user)
    db.session.commit()
    reversals = reverse_document_movements('stock_adjustment', 7, admin_user)
    db.session.commit()
    assert len(reversals) == 1
    bal = StockBalance.query.filter_by(product_id=product_tracked.id, branch_id=branch_main.id).one()
    assert bal.quantity_on_hand == D('0.0000')
