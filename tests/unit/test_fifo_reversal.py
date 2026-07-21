from decimal import Decimal
import pytest
from app import db
from app.stock_adjustments.service import post_movement, reverse_document_movements, FifoLayerConsumedError
from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption, StockBalance, StockMovement
from app.users.models import User

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='fifo_reversal_actor').first()
    if u is None:
        u = User(username='fifo_reversal_actor', email='fifo_rev@test.local', role='admin',
                 full_name='FIFO Reversal Test Actor', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def test_reversing_untouched_receipt_zeroes_its_layer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                          'test_doc', 1, 'r1', actor)
    db.session.commit()
    reverse_document_movements('test_doc', 1, actor)
    db.session.commit()
    layer = StockCostLayer.query.filter_by(source_movement_id=mv.id).first()
    assert layer.remaining_qty == D('0.0000')
    assert layer.original_qty == D('10.0000')   # audit trail preserved
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('0.0000')


def test_reversing_partially_consumed_receipt_is_blocked(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                  'rr_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'issue', D('-4'), None,
                  'dr_doc', 2, 'shipped', actor)
    db.session.commit()
    # 4 of the original 10 units have been consumed (6 remain) -- the message
    # reports the CONSUMED amount against the ORIGINAL layer size, not the
    # remaining amount.
    with pytest.raises(FifoLayerConsumedError, match=r'4\.0000 of 10\.0000.*already been consumed'):
        reverse_document_movements('rr_doc', 1, actor)
    # nothing changed
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('6.0000')


def test_reversing_an_issue_restores_exactly_the_layers_it_drew_from(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'rr_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'rr_doc', 2, 'r2', actor)
    db.session.commit()
    issue_mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-8'), None,
                                'dr_doc', 3, 'shipped', actor)
    db.session.commit()
    layer_a = StockCostLayer.query.filter_by(unit_cost=D('4.00')).first()
    layer_b = StockCostLayer.query.filter_by(unit_cost=D('6.00')).first()
    assert layer_a.remaining_qty == D('0.0000')
    assert layer_b.remaining_qty == D('2.0000')

    reverse_document_movements('dr_doc', 3, actor)
    db.session.commit()
    assert db.session.get(StockCostLayer, layer_a.id).remaining_qty == D('5.0000')
    assert db.session.get(StockCostLayer, layer_b.id).remaining_qty == D('5.0000')
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('10.0000')


def test_reversing_a_fully_consumed_receipt_names_the_consumer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'rr_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'issue', D('-5'), None,
                  'dr_doc', 2, 'shipped', actor)
    db.session.commit()
    with pytest.raises(FifoLayerConsumedError, match='dr_doc'):
        reverse_document_movements('rr_doc', 1, actor)
