from decimal import Decimal
import pytest
from app import db
from app.stock_adjustments.service import (post_movement, reverse_document_movements,
                                            SpecificIdLotConsumedError)
from app.stock_adjustments.models import StockLot, StockLotConsumption, StockBalance
from app.users.models import User

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='spid_reversal_actor').first()
    if u is None:
        u = User(username='spid_reversal_actor', email='spid_rev@test.local', role='admin',
                 full_name='Specific-ID Reversal Test Actor', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def test_reversing_untouched_receipt_zeroes_its_lot(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    mv, _ = post_movement(product_specific_id, branch_main.id, 'receipt', D('10'), D('5.00'),
                          'stock_adjustment', 1, 'r1', actor, lot_reference='JO-1')
    db.session.commit()
    reverse_document_movements('stock_adjustment', 1, actor)
    db.session.commit()
    lot = StockLot.query.filter_by(source_movement_id=mv.id).first()
    assert lot.remaining_qty == D('0.0000')
    assert lot.original_qty == D('10.0000')   # audit trail preserved
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('0.0000')


def test_reversing_partially_consumed_receipt_is_blocked(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('10'), D('5.00'),
                  'stock_adjustment', 1, 'r1', actor, lot_reference='JO-2')
    db.session.commit()
    lot = StockLot.query.filter_by(lot_reference='JO-2').first()
    post_movement(product_specific_id, branch_main.id, 'issue', D('-4'), None,
                  'stock_adjustment', 2, 'shipped', actor, lot_id=lot.id)
    db.session.commit()
    with pytest.raises(SpecificIdLotConsumedError, match=r'4\.0000 of 10\.0000.*already been consumed'):
        reverse_document_movements('stock_adjustment', 1, actor)
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('6.0000')   # nothing changed


def test_reversing_an_issue_restores_exactly_the_lot_it_drew_from(db_session, product_specific_id, branch_main):
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'stock_adjustment', 1, 'r1', actor, lot_reference='JO-3')
    db.session.commit()
    lot = StockLot.query.filter_by(lot_reference='JO-3').first()
    post_movement(product_specific_id, branch_main.id, 'issue', D('-3'), None,
                  'stock_adjustment', 2, 'shipped', actor, lot_id=lot.id)
    db.session.commit()
    assert lot.remaining_qty == D('2.0000')
    reverse_document_movements('stock_adjustment', 2, actor)
    db.session.commit()
    db.session.refresh(lot)
    assert lot.remaining_qty == D('5.0000')   # fully restored
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('5.0000')


def test_existing_fifo_product_reversal_unaffected(db_session, product_fifo, branch_main):
    """Confirm this task's changes are specific-ID-only and don't perturb FIFO's own reversal."""
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    reverse_document_movements('test_doc', 1, actor)
    db.session.commit()
    from app.stock_adjustments.models import StockCostLayer
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer.remaining_qty == D('0.0000')


def test_reversing_non_stock_adjustment_movement_falls_back_to_generic_reversal(db_session, product_specific_id, branch_main):
    """A void of a movement posted by a non-Stock-Adjustment document (even
    for a specific-identification product) must use the generic reversal
    path, not _reverse_specific_id_movement -- there is no
    StockLotConsumption row to look up since no lot was ever involved."""
    actor = _actor(db_session)
    post_movement(product_specific_id, branch_main.id, 'receipt', D('10'), D('5.00'),
                  'delivery_receipt', 1, 'r1', actor)
    db.session.commit()
    reverse_document_movements('delivery_receipt', 1, actor)  # must NOT raise
    db.session.commit()
    bal = StockBalance.query.filter_by(product_id=product_specific_id.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('0.0000')
