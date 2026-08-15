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
