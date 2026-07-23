from decimal import Decimal
from app import db
from app.utils import ph_now
from app.stock_adjustments.models import StockLot, StockLotConsumption, StockMovement

D = Decimal


def test_stock_lot_round_trip(db_session, product_tracked, branch_main):
    lot = StockLot(product_id=product_tracked.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('10'), unit_cost=D('5.00'),
                   received_at=ph_now(), lot_reference='Job Order #123', source_movement_id=None)
    db.session.add(lot); db.session.commit()
    fetched = db.session.get(StockLot, lot.id)
    assert fetched.lot_reference == 'Job Order #123'
    assert fetched.remaining_qty == D('10')


def test_stock_lot_consumption_round_trip(db_session, product_tracked, branch_main, admin_user):
    lot = StockLot(product_id=product_tracked.id, branch_id=branch_main.id,
                   original_qty=D('10'), remaining_qty=D('7'), unit_cost=D('5.00'),
                   received_at=ph_now(), lot_reference=None, source_movement_id=None)
    db.session.add(lot); db.session.commit()
    mv = StockMovement(product_id=product_tracked.id, branch_id=branch_main.id,
                       movement_type='issue', quantity=D('-3'), unit_cost=D('5.00'),
                       balance_qty_after=D('7'), balance_avg_cost_after=D('5.00'),
                       balance_value_after=D('35.00'), created_by_id=admin_user.id)
    db.session.add(mv); db.session.commit()
    consumption = StockLotConsumption(movement_id=mv.id, lot_id=lot.id,
                                      qty_consumed=D('3'), unit_cost_at_consumption=D('5.00'))
    db.session.add(consumption); db.session.commit()
    fetched = db.session.get(StockLotConsumption, consumption.id)
    assert fetched.lot.lot_reference is None
    assert fetched.qty_consumed == D('3')


def test_stock_adjustment_line_carries_lot_fields(db_session, product_tracked, branch_main):
    from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine
    adj = StockAdjustment(sa_number='SA-TEST-LOT-1', branch_id=branch_main.id,
                          adjustment_date=ph_now().date(), reason_type='opening', status='draft')
    db.session.add(adj); db.session.commit()
    line = StockAdjustmentLine(adjustment_id=adj.id, product_id=product_tracked.id,
                               quantity_delta=D('5'), unit_cost=D('5.00'),
                               lot_reference='Batch A', lot_id=None)
    db.session.add(line); db.session.commit()
    fetched = db.session.get(StockAdjustmentLine, line.id)
    assert fetched.lot_reference == 'Batch A'
    assert fetched.lot_id is None
