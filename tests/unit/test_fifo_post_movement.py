# tests/unit/test_fifo_post_movement.py
from decimal import Decimal
from app import db
from app.stock_adjustments.service import post_movement
from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption, StockBalance
from app.users.models import User

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='fifo_test_actor').first()
    if u is None:
        u = User(username='fifo_test_actor', email='fifo_actor@test.local',
                 full_name='FIFO Test Actor', role='admin', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def test_first_receipt_bootstraps_nothing_and_creates_one_layer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                                      'test_doc', 1, 'first receipt', actor)
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('5.00')
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer.source_movement_id == mv.id
    assert layer.remaining_qty == D('10.0000')
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('10.0000')
    assert bal.average_unit_cost == D('5.00')


def test_two_receipts_then_issue_costs_at_oldest_layer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor)
    db.session.commit()
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'issue', D('-3'), None,
                                      'test_doc', 3, 'issue', actor)
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('4.00')   # costed entirely from the OLDEST (4.00) layer
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('7.0000')
    # remaining pool: (2 units @ 4.00) + (5 units @ 6.00) = 8 + 30 = 38 / 7 = 5.428571... -> 5.43
    assert bal.average_unit_cost == D('5.43')
    consumption = StockLayerConsumption.query.filter_by(movement_id=mv.id).first()
    assert consumption.qty_consumed == D('3.0000')
    assert consumption.unit_cost_at_consumption == D('4.00')


def test_issue_spanning_two_layers_costs_weighted_average(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor)
    db.session.commit()
    mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-8'), None,
                          'test_doc', 3, 'issue', actor)
    db.session.commit()
    # (5*4.00 + 3*6.00) / 8 = 38/8 = 4.75
    assert mv.unit_cost == D('4.75')
    rows = StockLayerConsumption.query.filter_by(movement_id=mv.id).order_by(
        StockLayerConsumption.id).all()
    assert len(rows) == 2
    assert rows[0].qty_consumed == D('5.0000') and rows[0].unit_cost_at_consumption == D('4.00')
    assert rows[1].qty_consumed == D('3.0000') and rows[1].unit_cost_at_consumption == D('6.00')


def test_issue_exceeding_stock_goes_negative_with_warning(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'issue', D('-8'), None,
                                      'test_doc', 2, 'issue', actor)
    db.session.commit()
    assert went_negative is True
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('-3.0000')
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer.remaining_qty == D('-3.0000')   # the deficit landed on the only layer


def test_existing_moving_average_product_unaffected(db_session, product_tracked, branch_main):
    """product_tracked defaults to costing_method='moving_average' -- confirm
    this task's changes are FIFO-only and don't perturb the existing path."""
    actor = _actor(db_session)
    mv, _ = post_movement(product_tracked, branch_main.id, 'receipt', D('10'), D('5.00'),
                          'test_doc', 1, 'r1', actor)
    db.session.commit()
    assert mv.unit_cost == D('5.00')
    assert StockCostLayer.query.filter_by(product_id=product_tracked.id).count() == 0
