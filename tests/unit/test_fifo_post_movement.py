# tests/unit/test_fifo_post_movement.py
from decimal import Decimal
import sqlalchemy as sa
from app import db
import app.stock_adjustments.service as service_module
from app.stock_adjustments.service import post_movement
from app.stock_adjustments.models import StockCostLayer, StockLayerConsumption, StockBalance
from app.users.models import User

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='fifo_test_actor').first()
    if u is None:
        u = User(username='fifo_test_actor', email='fifo_actor@test.local',
                 full_name='FIFO Test Actor', role='admin', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def test_first_receipt_bootstraps_nothing_and_creates_one_layer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                                      'test_doc', 1, 'first receipt', actor)
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('5.00')
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer.source_movement_id == mv.id
    assert layer.remaining_qty == D('10.0000')
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('10.0000')
    assert bal.average_unit_cost == D('5.00')


def test_two_receipts_then_issue_costs_at_oldest_layer(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor)
    db.session.commit()
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'issue', D('-3'), None,
                                      'test_doc', 3, 'issue', actor)
    db.session.commit()
    assert went_negative is False
    assert mv.unit_cost == D('4.00')   # costed entirely from the OLDEST (4.00) layer
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('7.0000')
    # remaining pool: (2 units @ 4.00) + (5 units @ 6.00) = 8 + 30 = 38 / 7 = 5.428571... -> 5.43
    assert bal.average_unit_cost == D('5.43')
    consumption = StockLayerConsumption.query.filter_by(movement_id=mv.id).first()
    assert consumption.qty_consumed == D('3.0000')
    assert consumption.unit_cost_at_consumption == D('4.00')


def test_issue_spanning_two_layers_costs_weighted_average(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor)
    db.session.commit()
    mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-8'), None,
                          'test_doc', 3, 'issue', actor)
    db.session.commit()
    # (5*4.00 + 3*6.00) / 8 = 38/8 = 4.75
    assert mv.unit_cost == D('4.75')
    rows = StockLayerConsumption.query.filter_by(movement_id=mv.id).order_by(
        StockLayerConsumption.id).all()
    assert len(rows) == 2
    assert rows[0].qty_consumed == D('5.0000') and rows[0].unit_cost_at_consumption == D('4.00')
    assert rows[1].qty_consumed == D('3.0000') and rows[1].unit_cost_at_consumption == D('6.00')


def test_issue_exceeding_stock_goes_negative_with_warning(db_session, product_fifo, branch_main):
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    mv, went_negative = post_movement(product_fifo, branch_main.id, 'issue', D('-8'), None,
                                      'test_doc', 2, 'issue', actor)
    db.session.commit()
    assert went_negative is True
    bal = StockBalance.query.filter_by(product_id=product_fifo.id, branch_id=branch_main.id).first()
    assert bal.quantity_on_hand == D('-3.0000')
    layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).first()
    assert layer.remaining_qty == D('-3.0000')   # the deficit landed on the only layer


def test_lost_race_retry_rereads_fifo_layers_fresh(monkeypatch, db_session, product_fifo, branch_main):
    """A lost optimistic-lock retry must re-read StockCostLayer rows FRESH --
    post_movement's lost-race branch does db.session.expire_all(), NOT just
    expire(bal), so a FIFO retry's fifo_plan_consume cannot reuse the
    identity-mapped layer objects loaded during the losing attempt.

    Setup: two receipt layers (5 @ 4.00 oldest, then 5 @ 6.00). We monkeypatch
    _claim_balance_update to lose the race exactly once (return False on the
    first call, delegate to the real implementation on the second). On that
    first, losing call we simulate a genuinely-concurrent writer that drew the
    oldest layer down from 5 to 2 -- a bulk UPDATE with
    synchronize_session=False, which mutates the DB row WITHOUT touching this
    session's identity map, exactly as an independent connection's committed
    write would look to this session (the testing DB is in-memory SQLite, so a
    literal second connection can't share it -- this is the faithful stand-in).

    With the OLD `db.session.expire(bal)`, the retry reuses the stale
    identity-mapped oldest layer (remaining still 5) and costs the whole -5
    issue at 4.00 in a single consumption row. With `expire_all()`, the retry
    re-reads (remaining 2) and costs 2 @ 4.00 + 3 @ 6.00 = 26/5 = 5.20 across
    two rows. This test asserts the fresh (5.20 / two-row) result, so it FAILS
    under the pre-fix code and passes with expire_all()."""
    actor = _actor(db_session)
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('4.00'),
                  'test_doc', 1, 'r1', actor)
    db.session.commit()
    post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('6.00'),
                  'test_doc', 2, 'r2', actor)
    db.session.commit()

    oldest = (StockCostLayer.query
              .filter_by(product_id=product_fifo.id, branch_id=branch_main.id)
              .order_by(StockCostLayer.received_at, StockCostLayer.id).first())
    oldest_id = oldest.id
    assert oldest.unit_cost == D('4.00')   # confirm we grabbed the oldest layer

    real_claim = service_module._claim_balance_update
    state = {'calls': 0}

    def fake_claim(balance_id, read_version, new_qty, new_avg, new_value):
        state['calls'] += 1
        if state['calls'] == 1:
            # lose the race AND simulate the concurrent writer that consumed 3
            # units from the oldest layer: committed at the DB level, invisible
            # to this session's identity map (synchronize_session=False).
            db.session.execute(
                sa.update(StockCostLayer)
                .where(StockCostLayer.id == oldest_id)
                .values(remaining_qty=D('2.0000'))
                .execution_options(synchronize_session=False))
            return False
        return real_claim(balance_id, read_version, new_qty, new_avg, new_value)

    monkeypatch.setattr(service_module, '_claim_balance_update', fake_claim)

    mv, went_negative = post_movement(product_fifo, branch_main.id, 'issue', D('-5'), None,
                                      'test_doc', 3, 'issue', actor)
    db.session.commit()

    assert state['calls'] == 2   # the retry path was actually exercised
    assert went_negative is False
    # fresh re-read draws 2 @ 4.00 + 3 @ 6.00 = 5.20; stale would give 4.00
    assert mv.unit_cost == D('5.20')
    rows = StockLayerConsumption.query.filter_by(movement_id=mv.id).order_by(
        StockLayerConsumption.id).all()
    assert len(rows) == 2   # stale would draw all 5 from the oldest layer -> a single row
    assert rows[0].qty_consumed == D('2.0000') and rows[0].unit_cost_at_consumption == D('4.00')
    assert rows[1].qty_consumed == D('3.0000') and rows[1].unit_cost_at_consumption == D('6.00')


def test_existing_moving_average_product_unaffected(db_session, product_tracked, branch_main):
    """product_tracked defaults to costing_method='moving_average' -- confirm
    this task's changes are FIFO-only and don't perturb the existing path."""
    actor = _actor(db_session)
    mv, _ = post_movement(product_tracked, branch_main.id, 'receipt', D('10'), D('5.00'),
                          'test_doc', 1, 'r1', actor)
    db.session.commit()
    assert mv.unit_cost == D('5.00')
    assert StockCostLayer.query.filter_by(product_id=product_tracked.id).count() == 0
