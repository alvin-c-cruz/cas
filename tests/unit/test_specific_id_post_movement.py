from decimal import Decimal
import pytest
from app import db
from app.stock_adjustments.service import post_movement
from app.stock_adjustments.models import StockLot, StockLotConsumption, StockBalance
from app.users.models import User

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='spid_test_actor').first()
    if u is None:
        u = User(username='spid_test_actor', email='spid_actor@test.local',
                 full_name='Specific-ID Test Actor', role='admin', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def test_receipt_creates_one_lot_with_reference(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    mv, went_negative = post_movement(product_specific_id, branch_main.id, 'receipt', D('10'), D('5.00'),
                                      'test_doc', 1, 'r1', actor, lot_reference='Job Order #1')
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('5.00')
    lot = StockLot.query.filter_by(product_id=product_specific_id.id).first()
    assert lot.source_movement_id == mv.id
    assert lot.remaining_qty == D('10.0000')
    assert lot.lot_reference == 'Job Order #1'
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('10.0000')
    assert bal.average_unit_cost == D('5.00')


def test_issue_against_picked_lot_costs_at_that_lots_own_cost(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor, lot_reference='Batch A')
    db.session.commit()
    post_movement(product_specific_id, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor, lot_reference='Batch B')
    db.session.commit()
    batch_b = StockLot.query.filter_by(lot_reference='Batch B').first()
    mv, went_negative = post_movement(product_specific_id, branch_main.id, 'issue', D('-3'), None,
                                      'test_doc', 3, 'issue', actor, lot_id=batch_b.id)
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('6.00')   # costed from the PICKED lot (Batch B), not oldest/newest
    batch_a = StockLot.query.filter_by(lot_reference='Batch A').first()
    assert batch_a.remaining_qty == D('5.0000')   # untouched
    assert batch_b.remaining_qty == D('2.0000')
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('7.0000')
    consumption = StockLotConsumption.query.filter_by(movement_id=mv.id).first()
    assert consumption.lot_id == batch_b.id
    assert consumption.qty_consumed == D('3.0000')


def test_issue_without_a_lot_id_raises(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    with pytest.raises(ValueError, match='requires a lot to be selected'):
        post_movement(product_specific_id, branch_main.id, 'issue', D('-2'), None,
                      'test_doc', 2, 'issue', actor)


def test_issue_exceeding_picked_lots_remaining_qty_raises(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('3'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    lot = StockLot.query.filter_by(product_id=product_specific_id.id).first()
    with pytest.raises(ValueError, match='only has 3.0000 units remaining'):
        post_movement(product_specific_id, branch_main.id, 'issue', D('-5'), None,
                      'test_doc', 2, 'issue', actor, lot_id=lot.id)
    # nothing changed -- the balance claim must not commit for a rejected plan
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('3.0000')


def test_existing_moving_average_product_unaffected(db_session, product_tracked, branch_main):
    """product_tracked defaults to costing_method='moving_average' -- confirm
    this task's changes are specific-ID-only and don't perturb the existing path."""
    actor = _actor(db_session)
    mv, _ = post_movement(product_tracked, branch_main.id, 'receipt', D('10'), D('5.00'),
                          'test_doc', 1, 'r1', actor)
    db.session.commit()
    assert mv.unit_cost == D('5.00')
    assert StockLot.query.filter_by(product_id=product_tracked.id).count() == 0
