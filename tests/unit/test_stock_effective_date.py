"""movement_date is the business-effective date, stored as given.

The ordering tests live here too (added in Task 4) because they share fixtures.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
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
        assert layer.received_at.date() == date(2026, 1, 15)

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
