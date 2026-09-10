"""A submitted receiving report can be sent back to draft.

Owner request 2026-09-07, after PO-less receipts shipped: somebody finds the purchase
order that covered the goods AFTER the receipt was submitted. A receiving report is
editable only while `draft` and has no unsubmit, so the link could not be attached at
all -- the only exits were approve or cancel.

Scope is `submitted` only. Approved and billed are out (spec decision): approved has
posted stock and GRNI, and billed cannot even be cancelled today.
"""
from datetime import date

import pytest

from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from tests.integration.test_rr_submit import _login, rr_enabled  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]

MEMO = 'The goods were on PO-00985 after all.'


@pytest.fixture
def vendor(db_session):
    from app.vendors.models import Vendor
    v = Vendor(code='RTD-V', name='Return Test Supplier', is_active=True)
    db_session.add(v); db_session.commit()
    return v


@pytest.fixture
def product(db_session):
    from app.products.models import Product
    p = Product(code='RTD-P', name='Returned Item', track_inventory=False, is_active=True)
    db_session.add(p); db_session.commit()
    return p


def _rr(db_session, branch, vendor, product, user, status='submitted',
        number='RR-RTD-1'):
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 9, 7),
                         branch_id=branch.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, status=status,
                         created_by_id=user.id,
                         submitted_by_id=(user.id if status != 'draft' else None))
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=None, product_id=product.id,
        received_quantity=3))
    db_session.add(rr); db_session.commit()
    return rr


class TestTheSchema:

    def test_the_receipt_carries_the_memo_fields(self):
        cols = {c.key for c in ReceivingReport.__table__.columns}
        assert {'return_reason', 'returned_by_id', 'returned_at'} <= cols

    def test_the_line_carries_a_no_po_reason(self):
        cols = {c.key for c in ReceivingReportItem.__table__.columns}
        assert 'no_po_reason' in cols

    def test_every_new_column_is_nullable(self):
        """Nothing to backfill: every existing row reads NULL and behaves as before."""
        for model, names in ((ReceivingReport,
                              ('return_reason', 'returned_by_id', 'returned_at')),
                             (ReceivingReportItem, ('no_po_reason',))):
            for name in names:
                assert model.__table__.c[name].nullable is True, name

    def test_only_submitted_is_returnable(self):
        """A receiving report has no `rejected` status, unlike the requisition, so
        there is exactly one source state."""
        assert ReceivingReport.RETURN_TO_DRAFT_STATUSES == ('submitted',)


class TestWhoMayReturnIt:

    def test_an_approver_may(self, client, db_session, main_branch, vendor, product,
                             admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_an_accountant_may_too(self, client, db_session, main_branch, vendor,
                                   product, admin_user, accountant_user):
        """The gate grants access on `has_full_access OR role == 'accountant'`, and
        every other approver test here uses admin_user -- which passes on the first
        half. Without this, deleting the accountant clause would break nothing that
        any test observes.

        Submitted by admin_user, not accountant_user: if the receipt were submitted
        by the accountant themselves, the submitter fallback clause would grant
        access on its own and this test would pass whether or not the accountant
        role clause exists. Using a different submitter isolates the role clause."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user,
                 number='RR-RTD-ACCT')
        _login(client, accountant_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_the_submitter_may_too(self, client, db_session, main_branch, vendor,
                                   product, staff_user):
        """Owner decision 2026-09-07: pulling back your OWN submission needs nobody
        else's authority."""
        rr = _rr(db_session, main_branch, vendor, product, staff_user)
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_an_unrelated_staff_user_may_not(self, client, db_session, main_branch,
                                             vendor, product, admin_user, staff_user):
        """CONTROL. Without this the two tests above pass on a route with no gate."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'

    def test_a_null_submitter_falls_back_to_approver_only(self, client, db_session,
                                                          main_branch, vendor, product,
                                                          admin_user, staff_user):
        """Receipts predating submitted_by_id, or seeded directly, have NULL there.
        `None == user.id` is False, so the rule fails CLOSED rather than opening the
        route to everyone."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        rr.submitted_by_id = None
        db_session.commit()
        _login(client, staff_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'


class TestWhatItRefuses:

    @pytest.mark.parametrize('status', ['draft', 'approved', 'billed', 'cancelled'])
    def test_only_a_submitted_receipt_can_be_returned(self, client, db_session,
                                                      main_branch, vendor, product,
                                                      admin_user, status):
        rr = _rr(db_session, main_branch, vendor, product, admin_user, status=status,
                 number='RR-RTD-%s' % status)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == status

    def test_a_short_memo_is_refused(self, client, db_session, main_branch, vendor,
                                     product, admin_user):
        """Matching reject/cancel: 10 characters. The memo is the whole value of the
        record afterwards."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        body = client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                           data={'return_reason': 'oops'},
                           follow_redirects=True).data.decode()
        db_session.refresh(rr)
        assert rr.status == 'submitted'
        assert 'min 10' in body


class TestWhatItRecords:

    def test_the_memo_who_and_when_are_stored(self, client, db_session, main_branch,
                                              vendor, product, admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.return_reason == MEMO
        assert rr.returned_by_id == admin_user.id
        assert rr.returned_at is not None

    def test_it_is_audit_logged_under_its_own_action(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user):
        """action='return_to_draft', not a generic 'update': the audit log's Actions
        filter is built from the distinct actions present, so a lifecycle event logged
        as an update is unfilterable and reads as an ordinary edit."""
        from app.audit.models import AuditLog
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        entry = (AuditLog.query
                 .filter_by(module='receiving_reports', action='return_to_draft',
                            record_id=rr.id)
                 .order_by(AuditLog.id.desc()).first())
        assert entry is not None
        assert MEMO in (entry.notes or '')


class TestResubmittingClearsThePreviousCycle:
    """The correction applied to purchase requisitions in fa78173a, applied here.

    A memo describes ONE correction cycle. Carrying it forward leaves a freshly
    submitted receipt still displaying "Returned to draft: ..." -- describing a
    correction that has since been made and acted on.
    """

    def _returned(self, client, db_session, main_branch, vendor, product, user):
        rr = _rr(db_session, main_branch, vendor, product, user)
        _login(client, user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.return_reason == MEMO
        return rr

    def test_the_memo_and_its_provenance_are_cleared(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user):
        rr = self._returned(client, db_session, main_branch, vendor, product, admin_user)
        client.post('/receiving-reports/%s/submit' % rr.id, follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'
        assert rr.return_reason is None
        assert rr.returned_by_id is None
        assert rr.returned_at is None

    def test_the_history_survives_in_the_audit_log(self, client, db_session, main_branch,
                                                   vendor, product, admin_user):
        """What makes clearing safe rather than destructive. If this stops holding, the
        clear becomes the deletion of the only copy."""
        from app.audit.models import AuditLog
        rr = self._returned(client, db_session, main_branch, vendor, product, admin_user)
        client.post('/receiving-reports/%s/submit' % rr.id, follow_redirects=True)
        notes = ' '.join(
            (e.notes or '') for e in
            AuditLog.query.filter_by(module='receiving_reports', record_id=rr.id).all())
        assert MEMO in notes


class TestTheDetailPage:

    def _page(self, client, rr):
        return client.get('/receiving-reports/%s' % rr.id).data.decode()

    def test_the_control_is_offered_on_a_submitted_receipt(self, client, db_session,
                                                           main_branch, vendor, product,
                                                           admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        body = self._page(client, rr)
        assert 'Return to Draft' in body
        assert 'id="returnModal"' in body

    def test_it_is_withheld_on_a_draft_receipt(self, client, db_session, main_branch,
                                               vendor, product, admin_user):
        """CONTROL. A control that can only fail is its own defect -- the route refuses
        a draft, so the page must not offer it."""
        rr = _rr(db_session, main_branch, vendor, product, admin_user, status='draft',
                 number='RR-RTD-DRAFT')
        _login(client, admin_user, main_branch)
        body = self._page(client, rr)
        # The id is checked first because it is the security-relevant fact: #returnModal
        # carries a live POST form to a privileged endpoint, and its absence is what
        # actually matters here. The label check below is only a symptom -- it happens
        # to read "Return to Draft" today, but a relabel of either button would make it
        # collide or stop colliding by accident. Pin the id so the guard does not depend
        # on that coincidence.
        assert 'id="returnModal"' not in body
        assert 'Return to Draft' not in body

    def test_it_is_withheld_from_someone_who_may_not(self, client, db_session,
                                                     main_branch, vendor, product,
                                                     admin_user, staff_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, staff_user, main_branch)
        body = self._page(client, rr)
        assert 'id="returnModal"' not in body
        assert 'Return to Draft' not in body

    def test_the_memo_is_displayed_after_a_return(self, client, db_session, main_branch,
                                                  vendor, product, admin_user):
        rr = _rr(db_session, main_branch, vendor, product, admin_user)
        _login(client, admin_user, main_branch)
        client.post('/receiving-reports/%s/return-to-draft' % rr.id,
                    data={'return_reason': MEMO}, follow_redirects=True)
        body = self._page(client, rr)
        assert 'Returned to draft:' in body
        assert MEMO in body
