from decimal import Decimal
from app import db
from app.stock_adjustments.fifo import fifo_plan_receive, fifo_plan_consume
from app.stock_adjustments.models import StockCostLayer

D = Decimal


def _layer(product_id, branch_id, orig, remaining, cost, received_at):
    layer = StockCostLayer(product_id=product_id, branch_id=branch_id,
                           original_qty=D(orig), remaining_qty=D(remaining),
                           unit_cost=D(cost), received_at=received_at)
    db.session.add(layer)
    return layer


def test_fifo_plan_receive_just_quantizes_cost():
    assert fifo_plan_receive('5.5') == D('5.50')
    # 5.005 sits exactly halfway between 5.00/5.01; ROUND_HALF_EVEN (the default
    # quantize context, used throughout this codebase without an explicit
    # rounding= override) picks the EVEN last digit -- 5.00, not 5.01.
    assert fifo_plan_receive(D('5.005')) == D('5.00')


def test_fifo_plan_consume_single_layer_covers_request(db_session, product_fifo, branch_main):
    _layer(product_fifo.id, branch_main.id, '10', '10', '5.00', db.func.now())
    db.session.commit()
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('6'))
    assert len(plan) == 1
    layer, take = plan[0]
    assert take == D('6')
    assert cost == D('5.00')


def test_fifo_plan_consume_spans_two_layers_oldest_first(db_session, product_fifo, branch_main):
    import datetime
    older = _layer(product_fifo.id, branch_main.id, '5', '5', '4.00',
                   datetime.datetime(2026, 1, 1))
    newer = _layer(product_fifo.id, branch_main.id, '20', '20', '6.00',
                   datetime.datetime(2026, 2, 1))
    db.session.commit()
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('8'))
    assert len(plan) == 2
    assert plan[0][0].id == older.id and plan[0][1] == D('5')
    assert plan[1][0].id == newer.id and plan[1][1] == D('3')
    # weighted: (5*4.00 + 3*6.00) / 8 = 38/8 = 4.75
    assert cost == D('4.75')


def test_fifo_plan_consume_skips_drained_layers(db_session, product_fifo, branch_main):
    drained = _layer(product_fifo.id, branch_main.id, '10', '0', '3.00', db.func.now())
    open_layer = _layer(product_fifo.id, branch_main.id, '10', '10', '5.00', db.func.now())
    db.session.commit()
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('4'))
    assert len(plan) == 1
    assert plan[0][0].id == open_layer.id
    assert cost == D('5.00')


def test_fifo_plan_consume_exhaustion_creates_deficit_against_most_recent_layer(
        db_session, product_fifo, branch_main):
    import datetime
    only = _layer(product_fifo.id, branch_main.id, '5', '5', '4.00',
                  datetime.datetime(2026, 1, 1))
    db.session.commit()
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('9'))
    # 5 from the real layer, 4 as a deficit against that same (most recent) layer
    assert len(plan) == 2
    assert plan[0][0].id == only.id and plan[0][1] == D('5')
    assert plan[1][0].id == only.id and plan[1][1] == D('4')
    assert cost == D('4.00')   # all drawn at the one layer's own cost


def test_fifo_plan_consume_no_layers_at_all_deficits_at_zero_cost(db_session, product_fifo, branch_main):
    # no StockCostLayer rows exist at all -- a virgin negative issue. Matches
    # compute_new_balance's own existing zero-cost-basis fallback for a fresh
    # StockBalance under moving_average, not a new failure mode.
    plan, cost = fifo_plan_consume(product_fifo.id, branch_main.id, D('3'))
    assert len(plan) == 1
    layer, take = plan[0]
    assert take == D('3')
    assert layer.unit_cost == D('0.00')
    assert layer.original_qty == D('0.0000')
    assert cost == D('0.00')
