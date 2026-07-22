from decimal import Decimal
from app import db
from app.utils import ph_now
from app.stock_adjustments.fifo import (fifo_apply_receive, fifo_apply_consume,
                                        bootstrap_opening_layer_if_needed)
from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption, StockMovement, StockBalance

D = Decimal


def _movement(product_id, branch_id, qty, unit_cost):
    # unit_cost=None is passed for consumption movements in the brief's test
    # calls below (the FIFO cost comes from the layer plan, not this field),
    # but StockMovement.unit_cost is NOT NULL -- default to 0 in that case.
    mv = StockMovement(product_id=product_id, branch_id=branch_id, movement_type='receipt',
                       quantity=D(qty), unit_cost=D(unit_cost) if unit_cost is not None else D('0'),
                       balance_qty_after=D('0'), balance_avg_cost_after=D('0'),
                       balance_value_after=D('0'), created_at=ph_now())
    db.session.add(mv); db.session.flush()
    return mv


def test_fifo_apply_receive_creates_one_layer_linked_to_movement(db_session, product_fifo, branch_main):
    mv = _movement(product_fifo.id, branch_main.id, '10', '5.00')
    layer = fifo_apply_receive(product_fifo.id, branch_main.id, D('10'), D('5.00'), mv, ph_now())
    db.session.commit()
    fetched = StockCostLayer.query.filter_by(source_movement_id=mv.id).first()
    assert fetched is not None
    assert fetched.id == layer.id
    assert fetched.original_qty == D('10.0000')
    assert fetched.remaining_qty == D('10.0000')
    assert fetched.unit_cost == D('5.00')


def test_fifo_apply_consume_decrements_layers_and_writes_consumption_rows(
        db_session, product_fifo, branch_main):
    layer = StockCostLayer(product_id=product_fifo.id, branch_id=branch_main.id,
                           original_qty=D('10'), remaining_qty=D('10'),
                           unit_cost=D('5.00'), received_at=ph_now())
    db.session.add(layer); db.session.flush()
    mv = _movement(product_fifo.id, branch_main.id, '-6', None)
    fifo_apply_consume([(layer, D('6'))], mv)
    db.session.commit()
    assert db.session.get(StockCostLayer, layer.id).remaining_qty == D('4.0000')
    consumption = StockLayerConsumption.query.filter_by(movement_id=mv.id).first()
    assert consumption.layer_id == layer.id
    assert consumption.qty_consumed == D('6.0000')
    assert consumption.unit_cost_at_consumption == D('5.00')


def test_fifo_apply_consume_writes_multiple_rows_for_a_multi_layer_plan(
        db_session, product_fifo, branch_main):
    layer_a = StockCostLayer(product_id=product_fifo.id, branch_id=branch_main.id,
                             original_qty=D('5'), remaining_qty=D('5'),
                             unit_cost=D('4.00'), received_at=ph_now())
    layer_b = StockCostLayer(product_id=product_fifo.id, branch_id=branch_main.id,
                             original_qty=D('5'), remaining_qty=D('5'),
                             unit_cost=D('6.00'), received_at=ph_now())
    db.session.add_all([layer_a, layer_b]); db.session.flush()
    mv = _movement(product_fifo.id, branch_main.id, '-8', None)
    fifo_apply_consume([(layer_a, D('5')), (layer_b, D('3'))], mv)
    db.session.commit()
    assert db.session.get(StockCostLayer, layer_a.id).remaining_qty == D('0.0000')
    assert db.session.get(StockCostLayer, layer_b.id).remaining_qty == D('2.0000')
    rows = StockLayerConsumption.query.filter_by(movement_id=mv.id).order_by(
        StockLayerConsumption.id).all()
    assert len(rows) == 2
    assert rows[0].layer_id == layer_a.id and rows[0].qty_consumed == D('5.0000')
    assert rows[1].layer_id == layer_b.id and rows[1].qty_consumed == D('3.0000')


def test_bootstrap_creates_opening_layer_from_current_balance(db_session, product_fifo, branch_main):
    bal = StockBalance(product_id=product_fifo.id, branch_id=branch_main.id,
                       quantity_on_hand=D('12'), average_unit_cost=D('7.50'), total_value=D('90.00'))
    db.session.add(bal); db.session.commit()
    bootstrap_opening_layer_if_needed(product_fifo.id, branch_main.id)
    db.session.commit()
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer is not None
    assert layer.source_movement_id is None
    assert layer.original_qty == D('12')
    assert layer.remaining_qty == D('12')
    assert layer.unit_cost == D('7.50')


def test_bootstrap_is_noop_when_layers_already_exist(db_session, product_fifo, branch_main):
    existing = StockCostLayer(product_id=product_fifo.id, branch_id=branch_main.id,
                              original_qty=D('3'), remaining_qty=D('3'),
                              unit_cost=D('2.00'), received_at=ph_now())
    db.session.add(existing); db.session.commit()
    bootstrap_opening_layer_if_needed(product_fifo.id, branch_main.id)
    db.session.commit()
    assert StockCostLayer.query.filter_by(product_id=product_fifo.id).count() == 1


def test_bootstrap_is_noop_when_balance_is_zero(db_session, product_fifo, branch_main):
    bal = StockBalance(product_id=product_fifo.id, branch_id=branch_main.id,
                       quantity_on_hand=D('0'), average_unit_cost=D('0'), total_value=D('0'))
    db.session.add(bal); db.session.commit()
    bootstrap_opening_layer_if_needed(product_fifo.id, branch_main.id)
    db.session.commit()
    assert StockCostLayer.query.filter_by(product_id=product_fifo.id).count() == 0


def test_fifo_apply_consume_persists_the_no_layers_at_all_deficit_layer(
        db_session, product_fifo, branch_main):
    """fifo_plan_consume's zero-cost fallback (Task 2) builds a transient,
    never-added StockCostLayer with received_at=None when literally no
    layer exists yet. Proves fifo_apply_consume backfills received_at
    before persisting it -- without this, the flush below would raise
    IntegrityError (received_at NOT NULL)."""
    from app.stock_adjustments.fifo import fifo_plan_consume
    mv = _movement(product_fifo.id, branch_main.id, '-3', None)
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('3'))
    fifo_apply_consume(plan, mv)
    db.session.commit()
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert layer is not None
    assert layer.received_at is not None
    assert layer.remaining_qty == D('-3.0000')
