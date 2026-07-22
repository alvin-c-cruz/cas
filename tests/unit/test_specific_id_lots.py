from decimal import Decimal
import pytest
from app import db
from app.utils import ph_now
from app.stock_adjustments.lots import (specific_id_plan_receive, specific_id_plan_consume,
                                        specific_id_apply_receive, specific_id_apply_consume)
from app.stock_adjustments.models import StockLot, StockLotConsumption, StockMovement

D = Decimal


def test_plan_receive_normalizes_cost():
    assert specific_id_plan_receive('5') == D('5.00')
    assert specific_id_plan_receive(D('5.005')) == D('5.00')  # ROUND_HALF_EVEN


def test_plan_consume_returns_lot_and_its_own_cost(db_session, product_specific_id, branch_main):
    lot = StockLot(product_id=product_specific_id.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('10'), unit_cost=D('7.50'),
                   received_at=ph_now(), lot_reference='JO-1', source_movement_id=None)
    db.session.add(lot); db.session.commit()
    picked, unit_cost = specific_id_plan_consume(product_specific_id.id, branch_main.id, lot.id, D('4'))
    assert picked.id == lot.id
    assert unit_cost == D('7.50')


def test_plan_consume_rejects_nonexistent_lot(db_session, product_specific_id, branch_main):
    with pytest.raises(ValueError, match='does not exist'):
        specific_id_plan_consume(product_specific_id.id, branch_main.id, 999999, D('1'))


def test_plan_consume_rejects_wrong_product(db_session, product_specific_id, product_tracked, branch_main):
    lot = StockLot(product_id=product_tracked.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('10'), unit_cost=D('7.50'),
                   received_at=ph_now(), lot_reference=None, source_movement_id=None)
    db.session.add(lot); db.session.commit()
    with pytest.raises(ValueError, match='does not exist'):
        specific_id_plan_consume(product_specific_id.id, branch_main.id, lot.id, D('1'))


def test_plan_consume_rejects_exceeding_remaining_qty(db_session, product_specific_id, branch_main):
    lot = StockLot(product_id=product_specific_id.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('3'), unit_cost=D('7.50'),
                   received_at=ph_now(), lot_reference=None, source_movement_id=None)
    db.session.add(lot); db.session.commit()
    with pytest.raises(ValueError, match='only has 3.0000 units remaining'):
        specific_id_plan_consume(product_specific_id.id, branch_main.id, lot.id, D('4'))


def test_apply_receive_creates_one_lot(db_session, product_specific_id, branch_main, admin_user):
    mv = StockMovement(product_id=product_specific_id.id, branch_id=branch_main.id,
                       movement_type='receipt', quantity=D('10'), unit_cost=D('5.00'),
                       balance_qty_after=D('10'), balance_avg_cost_after=D('5.00'),
                       balance_value_after=D('50.00'), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()
    lot = specific_id_apply_receive(product_specific_id.id, branch_main.id, D('10'), D('5.00'),
                                    'Job Order #7', mv, mv.created_at)
    db.session.commit()
    assert lot.original_qty == D('10.0000')
    assert lot.remaining_qty == D('10.0000')
    assert lot.lot_reference == 'Job Order #7'
    assert lot.source_movement_id == mv.id


def test_apply_receive_blank_reference_stores_none(db_session, product_specific_id, branch_main, admin_user):
    mv = StockMovement(product_id=product_specific_id.id, branch_id=branch_main.id,
                       movement_type='receipt', quantity=D('5'), unit_cost=D('2.00'),
                       balance_qty_after=D('5'), balance_avg_cost_after=D('2.00'),
                       balance_value_after=D('10.00'), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()
    lot = specific_id_apply_receive(product_specific_id.id, branch_main.id, D('5'), D('2.00'),
                                    '', mv, mv.created_at)
    db.session.commit()
    assert lot.lot_reference is None


def test_apply_consume_decrements_lot_and_records_consumption(db_session, product_specific_id, branch_main, admin_user):
    lot = StockLot(product_id=product_specific_id.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('10'), unit_cost=D('5.00'),
                   received_at=ph_now(), lot_reference='JO-9', source_movement_id=None)
    db.session.add(lot); db.session.commit()
    mv = StockMovement(product_id=product_specific_id.id, branch_id=branch_main.id,
                       movement_type='issue', quantity=D('-4'), unit_cost=D('5.00'),
                       balance_qty_after=D('6'), balance_avg_cost_after=D('5.00'),
                       balance_value_after=D('30.00'), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()
    specific_id_apply_consume(lot, D('4'), mv)
    db.session.commit()
    assert lot.remaining_qty == D('6.0000')
    consumption = StockLotConsumption.query.filter_by(movement_id=mv.id).first()
    assert consumption.lot_id == lot.id
    assert consumption.qty_consumed == D('4.0000')
    assert consumption.unit_cost_at_consumption == D('5.00')
