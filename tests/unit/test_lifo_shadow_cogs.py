from datetime import datetime, date
from decimal import Decimal
from app import db
from app.stock_adjustments.lifo_shadow import lifo_cogs_for_range
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


def test_variance_computed_correctly_for_an_in_range_issue(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    _mv(product_lifo.id, branch_main.id, '5', '6.00', datetime(2026, 2, 1))
    # the ACTUAL posted cost for this issue was 5.00 (whatever moving-average happened to be) --
    # LIFO would have costed it at 6.00 (the most recent layer)
    issue = _mv(product_lifo.id, branch_main.id, '-3', '5.00', datetime(2026, 3, 1))
    db.session.commit()
    lines = lifo_cogs_for_range(product_lifo.id, branch_main.id, date(2026, 3, 1), date(2026, 3, 31))
    assert len(lines) == 1
    line = lines[0]
    assert line.movement_id == issue.id
    assert line.quantity == D('3.0000')
    assert line.lifo_unit_cost == D('6.00')
    assert line.lifo_cost == D('18.00')
    assert line.actual_unit_cost == D('5.00')
    assert line.actual_cost == D('15.00')
    assert line.variance == D('3.00')   # LIFO would have cost 3.00 MORE than what was actually posted


def test_out_of_range_movements_excluded_but_still_shape_the_stack(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '4.00', datetime(2026, 1, 1))
    # this issue is BEFORE the query range -- must not appear in the result...
    _mv(product_lifo.id, branch_main.id, '-2', '4.00', datetime(2026, 1, 15))
    # ...but it correctly consumed 2 units from the Jan layer, so THIS in-range issue only has
    # 3 units of the Jan layer left to draw from
    in_range = _mv(product_lifo.id, branch_main.id, '-3', '4.00', datetime(2026, 3, 1))
    db.session.commit()
    lines = lifo_cogs_for_range(product_lifo.id, branch_main.id, date(2026, 2, 1), date(2026, 3, 31))
    assert len(lines) == 1
    assert lines[0].movement_id == in_range.id
    assert lines[0].lifo_unit_cost == D('4.00')


def test_negative_variance_when_lifo_would_cost_less(db_session, product_lifo, branch_main):
    _mv(product_lifo.id, branch_main.id, '5', '3.00', datetime(2026, 1, 1))
    issue = _mv(product_lifo.id, branch_main.id, '-2', '9.00', datetime(2026, 2, 1))
    db.session.commit()
    lines = lifo_cogs_for_range(product_lifo.id, branch_main.id, date(2026, 2, 1), date(2026, 2, 28))
    assert lines[0].lifo_cost == D('6.00')     # 2 @ 3.00
    assert lines[0].actual_cost == D('18.00')  # 2 @ 9.00 (whatever the real posting used)
    assert lines[0].variance == D('-12.00')
