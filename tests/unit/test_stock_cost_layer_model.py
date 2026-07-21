# tests/unit/test_stock_cost_layer_model.py
from decimal import Decimal
from app import db
from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption, StockMovement


def test_stock_cost_layer_create_and_query(db_session, product_fifo, branch_main):
    layer = StockCostLayer(
        product_id=product_fifo.id, branch_id=branch_main.id,
        original_qty=Decimal('10.0000'), remaining_qty=Decimal('10.0000'),
        unit_cost=Decimal('5.00'), received_at=db.func.now())
    db.session.add(layer); db.session.commit()
    fetched = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert fetched.remaining_qty == Decimal('10.0000')
    assert fetched.unit_cost == Decimal('5.00')
    assert fetched.source_movement_id is None
    assert fetched.product.id == product_fifo.id


def test_stock_cost_layer_negative_remaining_qty_allowed(db_session, product_fifo, branch_main):
    layer = StockCostLayer(
        product_id=product_fifo.id, branch_id=branch_main.id,
        original_qty=Decimal('0.0000'), remaining_qty=Decimal('-3.0000'),
        unit_cost=Decimal('5.00'), received_at=db.func.now())
    db.session.add(layer); db.session.commit()
    assert StockCostLayer.query.first().remaining_qty == Decimal('-3.0000')


def test_stock_layer_consumption_create_and_relationships(db_session, product_fifo, branch_main):
    layer = StockCostLayer(
        product_id=product_fifo.id, branch_id=branch_main.id,
        original_qty=Decimal('10.0000'), remaining_qty=Decimal('4.0000'),
        unit_cost=Decimal('5.00'), received_at=db.func.now())
    db.session.add(layer); db.session.flush()
    mv = StockMovement(
        product_id=product_fifo.id, branch_id=branch_main.id, movement_type='issue',
        quantity=Decimal('-6.0000'), unit_cost=Decimal('5.00'),
        balance_qty_after=Decimal('4.0000'), balance_avg_cost_after=Decimal('5.00'),
        balance_value_after=Decimal('20.00'), created_at=db.func.now())
    db.session.add(mv); db.session.flush()
    consumption = StockLayerConsumption(
        movement_id=mv.id, layer_id=layer.id,
        qty_consumed=Decimal('6.0000'), unit_cost_at_consumption=Decimal('5.00'))
    db.session.add(consumption); db.session.commit()
    fetched = StockLayerConsumption.query.first()
    assert fetched.qty_consumed == Decimal('6.0000')
    assert fetched.layer.id == layer.id
    assert fetched.movement.id == mv.id
