"""movement_date is the business-effective date, stored as given.

The ordering tests live here too (added in Task 4) because they share fixtures.
"""
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app import db
from app.utils import ph_now
from app.stock_adjustments.service import post_movement
from app.stock_adjustments.models import StockMovement
from app.users.models import User

pytestmark = [pytest.mark.unit]

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='effdate_actor').first()
    if u is None:
        u = User(username='effdate_actor', email='effdate@test.local',
                 full_name='Effective Date Actor', role='admin', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


class TestItIsStored:

    def test_the_supplied_date_is_persisted(self, db_session, product_fifo, branch_main):
        actor = _actor(db_session)
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                              'test_doc', 1, 'r1', actor, movement_date=date(2026, 1, 15))
        db.session.commit()
        assert db.session.get(StockMovement, mv.id).movement_date == date(2026, 1, 15)

    def test_it_is_independent_of_created_at(self, db_session, product_fifo, branch_main):
        """The whole point: the two are different facts and must not be equal
        just because a movement was posted today."""
        actor = _actor(db_session)
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                              'test_doc', 1, 'r1', actor, movement_date=date(2026, 1, 15))
        db.session.commit()
        stored = db.session.get(StockMovement, mv.id)
        assert stored.movement_date == date(2026, 1, 15)
        assert stored.created_at.date() != date(2026, 1, 15), (
            'this test is vacuous if the suite happens to run on 2026-01-15')


class TestOrderingFollowsTheDocumentDate:
    """The core of this change. Each test posts OUT of date order on purpose --
    a chronological sequence passes even on the broken code, which is exactly
    why the original bug report's own repro came out 'correct'.
    """

    def test_fifo_consumes_the_earlier_document_date_posted_later(
            self, db_session, product_fifo, branch_main):
        actor = _actor(db_session)
        # Posted FIRST in real time, but dated LATER.
        post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('20.00'),
                      'test_doc', 1, 'february stock', actor,
                      movement_date=date(2026, 2, 1))
        db.session.commit()
        # Posted SECOND, but dated EARLIER -- this is the layer FIFO must take first.
        post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                      'test_doc', 2, 'january stock', actor,
                      movement_date=date(2026, 1, 1))
        db.session.commit()

        mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-10'), None,
                              'test_doc', 3, 'issue', actor,
                              movement_date=date(2026, 3, 1))
        db.session.commit()
        assert mv.unit_cost == D('5.00'), (
            'FIFO consumed the layer that was POSTED first rather than the one '
            'DATED first -- ordering is still keyed on created_at')

    def test_control_chronological_posting_is_unchanged(
            self, db_session, product_fifo, branch_main):
        """The path this change did NOT mean to alter. Without this, 'we changed
        ordering' and 'we broke ordering' look identical."""
        actor = _actor(db_session)
        post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                      'test_doc', 1, 'january', actor, movement_date=date(2026, 1, 1))
        db.session.commit()
        post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('20.00'),
                      'test_doc', 2, 'february', actor, movement_date=date(2026, 2, 1))
        db.session.commit()

        mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-10'), None,
                              'test_doc', 3, 'issue', actor,
                              movement_date=date(2026, 3, 1))
        db.session.commit()
        assert mv.unit_cost == D('5.00')

    def test_the_layer_carries_the_document_date_not_the_posting_time(
            self, db_session, product_fifo, branch_main):
        from app.stock_adjustments.models import StockCostLayer
        actor = _actor(db_session)
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                              'test_doc', 1, 'r', actor, movement_date=date(2026, 1, 15))
        db.session.commit()
        layer = StockCostLayer.query.filter_by(source_movement_id=mv.id).one()
        assert layer.received_at == datetime.combine(date(2026, 1, 15), time.min), (
            'the layer must carry the document date at MIDNIGHT exactly -- asserting '
            'only .date() is what let the opening-layer bootstrap bug (a full '
            'ph_now() timestamp) slip through review undetected')

    def test_lifo_takes_the_later_document_date_posted_earlier(
            self, db_session, product_lifo, branch_main):
        """The mirror image: LIFO must consume the NEWEST document date, even
        when that layer was posted BEFORE the older-dated one."""
        from app.stock_adjustments.lifo_shadow import current_lifo_valuation
        actor = _actor(db_session)
        # Posted FIRST, dated LATER -- LIFO must consume this one first.
        post_movement(product_lifo, branch_main.id, 'receipt', D('10'), D('20.00'),
                      'test_doc', 1, 'february stock', actor,
                      movement_date=date(2026, 2, 1))
        db.session.commit()
        # Posted SECOND, dated EARLIER -- must survive.
        post_movement(product_lifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                      'test_doc', 2, 'january stock', actor,
                      movement_date=date(2026, 1, 1))
        db.session.commit()
        post_movement(product_lifo, branch_main.id, 'issue', D('-10'), None,
                      'test_doc', 3, 'issue', actor, movement_date=date(2026, 3, 1))
        db.session.commit()

        layers = current_lifo_valuation(product_lifo.id, branch_main.id)
        surviving = [l for l in layers if l.qty > 0]
        assert len(surviving) == 1, 'expected exactly one surviving layer'
        assert surviving[0].unit_cost == D('5.00'), (
            'LIFO consumed the layer POSTED last rather than the one DATED last -- '
            'the replay is still ordered by created_at')

    def test_lifo_as_of_date_filters_on_the_document_date(
            self, db_session, product_lifo, branch_main):
        """_replay's end_date filter used created_at too, so an 'as of' report
        included or excluded a backdated movement by when it was keyed in."""
        from app.stock_adjustments.lifo_shadow import current_lifo_valuation
        actor = _actor(db_session)
        post_movement(product_lifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                      'test_doc', 1, 'january stock', actor,
                      movement_date=date(2026, 1, 1))
        db.session.commit()
        # Dated AFTER the cut-off, so it must be excluded even though it was
        # posted (created_at) today, which is before the cut-off in wall time.
        post_movement(product_lifo, branch_main.id, 'receipt', D('10'), D('20.00'),
                      'test_doc', 2, 'march stock', actor,
                      movement_date=date(2026, 3, 1))
        db.session.commit()

        layers = current_lifo_valuation(product_lifo.id, branch_main.id,
                                        as_of_date=date(2026, 2, 1))
        assert [l.unit_cost for l in layers] == [D('5.00')], (
            'the as-of filter is still keyed on created_at')

    def test_fifo_bootstrap_opening_layer_uses_movement_date_not_posting_time(
            self, db_session, product_fifo, branch_main):
        """Pins Finding 1: bootstrap_opening_layer_if_needed used to seed the
        opening layer at ph_now() (a full timestamp), while every real receipt
        layer is written at midnight. That made the opening layer -- which
        represents stock already on hand and MUST consume first -- sort LAST
        under FIFO's (received_at, id) order whenever a same-day receipt also
        landed at midnight.
        """
        from app.stock_adjustments.models import StockBalance, StockCostLayer
        actor = _actor(db_session)
        # Seed a pre-existing balance with a distinctive cost and ZERO layers --
        # exactly the shape bootstrap_opening_layer_if_needed exists to handle.
        bal = StockBalance(product_id=product_fifo.id, branch_id=branch_main.id,
                           quantity_on_hand=D('10'), average_unit_cost=D('1.00'),
                           total_value=D('10.00'))
        db.session.add(bal)
        db.session.commit()
        assert StockCostLayer.query.filter_by(product_id=product_fifo.id).count() == 0

        today = ph_now().date()
        # A receipt dated TODAY, posted AFTER the opening balance already existed.
        post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('99.00'),
                      'test_doc', 1, 'same-day receipt', actor, movement_date=today)
        db.session.commit()

        mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-3'), None,
                              'test_doc', 2, 'issue', actor, movement_date=today)
        db.session.commit()
        assert mv.unit_cost == D('1.00'), (
            'FIFO issue must consume the OPENING layer (cost 1.00) first -- it '
            'represents stock already on hand -- not the same-day receipt (cost '
            '99.00). Consuming the receipt means the opening layer sorted last.')

    def test_fifo_deficit_fallback_layer_dated_at_movement_effective_date(
            self, db_session, product_fifo, branch_main):
        """Drives fifo_apply_consume's deficit fallback directly: a product
        with zero layers issuing a negative qty must create its zero-cost
        fallback layer dated at the movement's effective date (midnight), not
        posting time."""
        from app.stock_adjustments.models import StockCostLayer
        actor = _actor(db_session)
        mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-4'), None,
                              'test_doc', 1, 'virgin negative issue', actor,
                              movement_date=date(2026, 4, 10))
        db.session.commit()
        layer = StockCostLayer.query.filter_by(product_id=product_fifo.id).order_by(
            StockCostLayer.id.desc()).first()
        assert layer is not None
        assert layer.received_at == datetime.combine(date(2026, 4, 10), time.min), (
            'the deficit fallback layer must be dated at the movement effective '
            'date at midnight, not posting time')

    def test_lifo_as_of_date_boundary_is_inclusive(
            self, db_session, product_lifo, branch_main):
        """A movement dated EXACTLY on as_of_date must be INCLUDED. The
        existing as-of test uses Jan 1 / Mar 1 around a Feb 1 cutoff, so a
        '<' instead of '<=' filter would still pass it -- this pins the
        boundary directly."""
        from app.stock_adjustments.lifo_shadow import current_lifo_valuation
        actor = _actor(db_session)
        post_movement(product_lifo, branch_main.id, 'receipt', D('10'), D('7.00'),
                      'test_doc', 1, 'on cutoff', actor,
                      movement_date=date(2026, 2, 1))
        db.session.commit()

        layers = current_lifo_valuation(product_lifo.id, branch_main.id,
                                        as_of_date=date(2026, 2, 1))
        assert [l.unit_cost for l in layers] == [D('7.00')], (
            'a movement dated exactly on as_of_date must be included')
