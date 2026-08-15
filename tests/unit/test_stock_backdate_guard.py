"""A receipt may not be dated before stock has already been issued.

Once dates drive the order, inserting a layer BEFORE layers that later issues
already consumed would mean the COGS already posted to the GL was computed
against the wrong layers. The ledger stays append-only: refuse instead.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.utils import ph_now
from app.stock_adjustments.service import post_movement, BackdatedReceiptError, reverse_document_movements
from app.users.models import User

pytestmark = [pytest.mark.unit]

D = Decimal


def _actor(db_session):
    u = User.query.filter_by(username='backdate_actor').first()
    if u is None:
        u = User(username='backdate_actor', email='backdate@test.local',
                 full_name='Backdate Actor', role='admin', is_active=True)
        u.set_password('x')
        db.session.add(u); db.session.commit()
    return u


def _stock_then_issue(db_session, product, branch, issue_date):
    """Receipt on 1 Jan, then an issue on issue_date."""
    actor = _actor(db_session)
    post_movement(product, branch.id, 'receipt', D('100'), D('5.00'),
                  'test_doc', 1, 'opening', actor, movement_date=date(2026, 1, 1))
    db.session.commit()
    post_movement(product, branch.id, 'issue', D('-10'), None,
                  'test_doc', 2, 'issue', actor, movement_date=issue_date)
    db.session.commit()
    return actor


class TestItBlocks:

    def test_a_receipt_dated_before_the_last_issue_is_refused(
            self, db_session, product_fifo, branch_main):
        actor = _stock_then_issue(db_session, product_fifo, branch_main, date(2026, 2, 1))
        with pytest.raises(BackdatedReceiptError) as e:
            post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('9.00'),
                          'test_doc', 3, 'late entry', actor,
                          movement_date=date(2026, 1, 20))
        msg = str(e.value)
        assert product_fifo.code in msg, 'the message must name the product'
        assert '2026-02-01' in msg, 'the message must name the blocking date'


class TestItsControls:
    """Five controls. Without them the guard could be a blanket freeze and every
    test above would still pass."""

    def test_a_same_day_receipt_is_allowed(self, db_session, product_fifo, branch_main):
        """Strictly-earlier, not on-or-before: a same-day receipt sorts AFTER an
        issue already posted that day (ties fall to id), so it cannot change what
        that issue consumed. Blocking it would break ordinary catch-up entry."""
        actor = _stock_then_issue(db_session, product_fifo, branch_main, date(2026, 2, 1))
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('5'), D('9.00'),
                              'test_doc', 3, 'same day', actor,
                              movement_date=date(2026, 2, 1))
        db.session.commit()
        assert mv.id is not None

    def test_an_issue_is_never_blocked(self, db_session, product_fifo, branch_main):
        actor = _stock_then_issue(db_session, product_fifo, branch_main, date(2026, 2, 1))
        mv, _ = post_movement(product_fifo, branch_main.id, 'issue', D('-5'), None,
                              'test_doc', 3, 'backdated issue', actor,
                              movement_date=date(2026, 1, 10))
        db.session.commit()
        assert mv.id is not None

    def test_a_moving_average_product_is_never_blocked(
            self, db_session, product_tracked, branch_main):
        """Scoped out deliberately: a moving-average balance snapshot is the
        average AS KNOWN when that issue posted, a defensible historical figure.
        A FIFO layer is a claim about WHICH stock was consumed, which becomes false."""
        actor = _stock_then_issue(db_session, product_tracked, branch_main,
                                  date(2026, 2, 1))
        mv, _ = post_movement(product_tracked, branch_main.id, 'receipt',
                              D('5'), D('9.00'), 'test_doc', 3, 'backdated', actor,
                              movement_date=date(2026, 1, 20))
        db.session.commit()
        assert mv.id is not None

    def test_a_product_with_no_issues_yet_is_never_blocked(
            self, db_session, product_fifo, branch_main):
        actor = _actor(db_session)
        post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                      'test_doc', 1, 'r1', actor, movement_date=date(2026, 3, 1))
        db.session.commit()
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('10'), D('5.00'),
                              'test_doc', 2, 'earlier, but nothing issued', actor,
                              movement_date=date(2026, 1, 1))
        db.session.commit()
        assert mv.id is not None

    def test_a_void_is_never_blocked(self, db_session, product_fifo, branch_main):
        """Finding S1: the missing 5th control -- exactly the one that would
        have caught Finding I1. _reverse_fifo_movement writes a void as a
        NEGATIVE movement dated today. That must NOT count toward the
        guard's floor, or void-and-re-enter (the standard correction
        workflow) permanently blocks every backdated receipt for that
        product/branch afterward, even though nothing was actually issued.

        Finding i folds in here too: a void's movement_date is an explicit
        design decision -- always TODAY, never backdated to the original
        (backdating a void would let it rewrite a closed accounting period).
        """
        actor = _actor(db_session)
        original_date = date(2026, 1, 10)
        orig, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('20'), D('5.00'),
                                'rr_doc', 10, 'RR original', actor,
                                movement_date=original_date)
        db.session.commit()

        reversals = reverse_document_movements('rr_doc', 10, actor)
        db.session.commit()
        assert len(reversals) == 1
        reversal = reversals[0]
        today = ph_now().date()
        assert reversal.movement_date == today, 'a void must be dated TODAY'
        assert reversal.movement_date != original_date, (
            'a void must never be backdated to the original document date -- '
            'that would let it rewrite a closed accounting period')

        # Re-enter the corrected receipt at the ORIGINAL date -- the standard
        # void-and-re-enter correction workflow. Must NOT be refused: nothing
        # was actually issued, so there is no COGS to protect.
        mv, _ = post_movement(product_fifo, branch_main.id, 'receipt', D('20'), D('5.50'),
                              'rr_doc', 11, 'RR corrected', actor,
                              movement_date=original_date)
        db.session.commit()
        assert mv.id is not None
