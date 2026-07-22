# tests/unit/test_lifo_shadow_valuation.py
from datetime import datetime, date, timedelta
from decimal import Decimal
from app import db
from app.utils import ph_now
from app.stock_adjustments.lifo_shadow import current_lifo_valuation
from app.stock_adjustments.models import StockMovement

D = Decimal


def _mv(product_id, branch_id, qty, unit_cost, created_at):
    mv = StockMovement(product_id=product_id, branch_id=branch_id, movement_type='receipt' if D(qty) > 0 else 'issue',
                       quantity=D(qty), unit_cost=D(unit_cost) if unit_cost is not None else D('0'),
                       balance_qty_after=D('0'), balance_avg_cost_after=D('0'), balance_value_after=D('0'),
                       created_at=created_at)
    db.session.add(mv)
    db.session.flush()
    return mv


def test_single_receipt_no_issues_gives_one_layer(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '10', '5.00', datetime(2026, 1, 1))
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id)
    assert len(layers) == 1
    assert layers[0].qty == D('10.0000')
    assert layers[0].unit_cost == D('5.00')


def test_issue_consumes_most_recent_layer_first_lifo_order(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '5', '6.00', datetime(2026, 2, 1))
    _mv(product_lifo.id, branch_main.id, '-3', None, datetime(2026, 3, 1))
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id)
    # LIFO: the issue draws from the MOST RECENT (Feb) layer first -- the Jan layer is untouched
    assert len(layers) == 2
    jan_layer = next(l for l in layers if l.unit_cost == D('4.00'))
    feb_layer = next(l for l in layers if l.unit_cost == D('6.00'))
    assert jan_layer.qty == D('5.0000')
    assert feb_layer.qty == D('2.0000')


def test_issue_spans_two_layers_newest_first(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '5', '6.00', datetime(2026, 2, 1))
    _mv(product_lifo.id, branch_main.id, '-8', None, datetime(2026, 3, 1))
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id)
    # draws 5 from Feb (all of it) + 3 from Jan -- 2 units of the Jan layer remain
    assert len(layers) == 1
    assert layers[0].unit_cost == D('4.00')
    assert layers[0].qty == D('2.0000')


def test_exhaustion_creates_deficit_layer(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '-8', None, datetime(2026, 2, 1))
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id)
    assert len(layers) == 1
    assert layers[0].qty == D('-3.0000')
    assert layers[0].unit_cost == D('4.00')  # costed at the last-popped (only) basis


def test_as_of_date_excludes_later_movements(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '5', '6.00', datetime(2026, 6, 1))
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id, as_of_date=date(2026, 3, 1))
    assert len(layers) == 1
    assert layers[0].unit_cost == D('4.00')


def test_reversal_nets_out_with_no_special_handling(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '10', '5.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '-10', None, datetime(2026, 1, 2))  # a void's reversal
    db.session.commit()
    layers = current_lifo_valuation(product_lifo.id, branch_main.id)
    assert layers == []
