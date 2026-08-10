"""write_revision appends; it never commits and never renumbers."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.amendments.service import latest_revision, write_revision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem


def _po(number='00998'):
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 5),
                       vendor_name='ACME', status='approved', notes='',
                       payment_terms='Net 30', vat_treatment='inclusive')
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('1'),
        unit_price=Decimal('10.00'), amount=Decimal('10.00'),
        line_total=Decimal('10.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
    db.session.add(po)
    db.session.commit()
    return po


class TestWriteRevision:
    def test_a_baseline_revision_is_zero(self, db_session):
        po = _po()
        rev = write_revision(po, user_id=None, baseline=True)
        db.session.commit()
        assert rev.revision_number == 0
        assert rev.document_type == 'purchase_orders'
        assert rev.document_id == po.id

    def test_second_revision_increments(self, db_session):
        po = _po()
        write_revision(po, user_id=None, baseline=True)
        db.session.commit()
        rev = write_revision(po, user_id=None, reason='corrected the vendor address')
        db.session.commit()
        assert rev.revision_number == 1
        assert rev.reason == 'corrected the vendor address'

    # -- Rev 0 is the BASELINE slot, and only a baseline write may take it ----
    #
    # M2 (final review), Major and latent. Numbering was `0 if prev is None else
    # prev + 1` with no notion of what the caller was writing, so an amendment of
    # a document that has no Rev 0 took the baseline slot: the row that is
    # supposed to hold what was APPROVED instead held the POST-CHANGE state, it
    # carried an amendment reason, and every later revision was permanently off by
    # one. No PO reaches this today (docrev_0002 backfills every approved_at IS
    # NOT NULL row), but seven more document types call this shared service in
    # slices 3-5, each with its own backfill predicate -- and the Sales Order
    # predicate's own docstring already admits it skips confirmed-then-closed
    # orders.

    def test_an_amendment_with_no_baseline_starts_at_rev_1(self, db_session):
        """The baseline slot is left EMPTY rather than filled with a lie.

        The alternative -- refusing the amendment outright -- would deny a real
        business action because of a data condition the user cannot see or fix,
        for a state that is latent today. Leaving Rev 0 unwritten is honest (there
        genuinely is no capture of the approved document), keeps `revision_number`
        meaning "the Nth change after the baseline", and stays repairable: a later
        backfill can still insert Rev 0 without renumbering anything.
        """
        po = _po()
        rev = write_revision(po, user_id=None, reason='vendor corrected the price')
        db.session.commit()

        assert rev.revision_number == 1, (
            'an amendment took the baseline slot -- Rev 0 now holds post-change '
            'state and every later revision is off by one')
        assert latest_revision('purchase_orders', po.id).revision_number == 1
        assert DocumentRevision.query.filter_by(revision_number=0).count() == 0, (
            'nothing may occupy the baseline slot but a baseline write')

    def test_the_amendment_default_is_the_safe_one(self, db_session):
        """`baseline` defaults to False on purpose.

        A slice-3 caller that forgets the flag writes Rev 1 (harmless); the
        opposite default would hand that caller the fail-open this test exists to
        close. The default is asserted, not just the explicit spelling, because
        the defect was a MISSING argument, not a wrong one.
        """
        po = _po()
        rev = write_revision(po, user_id=None)
        db.session.commit()
        assert rev.revision_number == 1

    def test_a_baseline_revision_cannot_carry_a_reason(self, db_session):
        """F6 (Task 6 review): a live Rev 0 could carry a non-null reason.

        A baseline records what was approved; it is not a change and has no
        reason. The detail panel reads exactly that: `reason` present means "an
        amendment", absent + Rev 0 means "the original approved order". A Rev 0
        with a reason renders as an amendment numbered 0 -- so this is a rendering
        contract, not tidiness. (The migration's reconstructed Rev 0 does carry a
        reason, and writes it with a raw INSERT, not through this service.)
        """
        po = _po()
        with pytest.raises(ValueError):
            write_revision(po, user_id=None, reason='an amendment reason',
                           baseline=True)

    def test_does_not_commit(self, db_session):
        po = _po()
        write_revision(po, user_id=None)
        db.session.rollback()
        assert DocumentRevision.query.count() == 0, 'write_revision must leave the txn to the caller'

    def test_snapshot_is_the_documents_own(self, db_session):
        po = _po()
        rev = write_revision(po, user_id=None)
        db.session.commit()
        assert json.loads(rev.snapshot_json) == po.build_snapshot()

    def test_unflushed_line_still_gets_an_id_in_the_snapshot(self, db_session):
        # A line appended but not yet flushed has id None, and snapshot line
        # identity depends on that id existing. write_revision flushes first.
        #
        # no_autoflush is LOAD-BEARING, not tidiness. write_revision calls
        # latest_revision() first, whose query would trigger SQLAlchemy's default
        # autoflush and assign the id anyway -- so without this wrap the test passes
        # whether or not the explicit flush exists, pinning nothing. The Sales Order
        # twin of this test (tests/integration/test_so_revision_snapshot_orm.py,
        # test_write_revisions_own_flush_does_not_depend_on_caller_autoflush) wraps it
        # for exactly this reason.
        po = _po()
        po.line_items.append(PurchaseOrderItem(
            line_number=2, description='late', quantity=Decimal('1'),
            unit_price=Decimal('1.00'), amount=Decimal('1.00'),
            line_total=Decimal('1.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0')))
        with db.session.no_autoflush:
            rev = write_revision(po, user_id=None)
        db.session.commit()
        ids = [ln['line_id'] for ln in json.loads(rev.snapshot_json)['lines']]
        assert None not in ids, 'flush-first is missing'

    def test_numbering_is_per_document(self, db_session):
        a, b = _po('00998'), _po('00999')
        write_revision(a, user_id=None, baseline=True)
        db.session.commit()
        rev_b = write_revision(b, user_id=None, baseline=True)
        db.session.commit()
        assert rev_b.revision_number == 0, 'numbering must not be global'


class TestLatestRevision:
    def test_none_when_no_revisions(self, db_session):
        po = _po()
        assert latest_revision('purchase_orders', po.id) is None

    def test_returns_the_highest(self, db_session):
        po = _po()
        write_revision(po, user_id=None, baseline=True)
        db.session.commit()
        write_revision(po, user_id=None, reason='second revision here')
        db.session.commit()
        assert latest_revision('purchase_orders', po.id).revision_number == 1
