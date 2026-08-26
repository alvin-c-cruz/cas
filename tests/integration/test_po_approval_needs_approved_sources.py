"""A purchase order may not be APPROVED while a requisition behind it is unapproved.

The other half of the 2026-08-26 owner decision. PULLABLE_PR now admits
`submitted` so a staff purchaser can prepare the order early (Task 2); this is
where the approval control actually lives. Pulling is data entry, submit is how
a staff purchaser hands the order on, approval is the control -- so `submit()`
is deliberately NOT blocked and there is a test pinning that too.

Every refusal test asserts the resulting STATUS, not merely the flash. A guard
that renders a message and approves anyway is exactly the shape that a
message-only assertion calls passing.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import db
from app.amendments.models import DocumentRevision
from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem

pytestmark = [pytest.mark.integration, pytest.mark.purchase_orders]


@pytest.fixture(autouse=True)
def po_enabled(db_session):
    """purchase_orders is optional (default_enabled=False) -- without this,
    enforce_module_access 404s the route for every role, admin included."""
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'purchase_requests'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()
    yield
    clear_module_config_cache()


@pytest.fixture
def vendor_acme(db_with_data):
    from app.vendors.models import Vendor
    v = Vendor(code='V901', name='ACME', is_active=True, default_vat_category='V12DG')
    db.session.add(v)
    db.session.commit()
    return v


def _requisition(branch, status, number='SRCA-PR-1'):
    pr = PurchaseRequest(pr_number=number, request_date=date(2026, 8, 26),
                         branch_id=branch.id, status=status)
    pr.line_items.append(PurchaseRequestItem(
        line_number=1, description='widget', quantity=Decimal('2')))
    db.session.add(pr)
    db.session.commit()
    return pr


def _order(branch, vendor, pr_item=None, number='SRCA-PO-1'):
    """A priced, approvable draft PO -- optionally sourced from *pr_item*."""
    po = PurchaseOrder(po_number=number, order_date=date(2026, 8, 26), status='draft',
                       vendor_id=vendor.id, vendor_name=vendor.name, notes='',
                       payment_terms='Net 30', vat_treatment='inclusive',
                       branch_id=branch.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='widget', quantity=Decimal('2'),
        unit_price=Decimal('10.00'), amount=Decimal('20.00'),
        line_total=Decimal('20.00'), vat_rate=Decimal('0'), vat_amount=Decimal('0'),
        source_pr_item_id=(pr_item.id if pr_item else None)))
    db.session.add(po)
    db.session.commit()
    return po


def _login(client, user, branch):
    """Direct-session login, scoped to the document's branch -- _get_po_or_404
    404s unless po.branch_id == session['selected_branch_id']."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _status(po):
    return db.session.get(PurchaseOrder, po.id).status


def _revs(po):
    return DocumentRevision.query.filter_by(
        document_type='purchase_orders', document_id=po.id).all()


class TestApprovalIsBlocked:

    def test_a_submitted_source_blocks_approval(self, client, admin_user,
                                                branch_manila, vendor_acme):
        """THE case the change creates: staff pulled it before the approver signed."""
        pr = _requisition(branch_manila, 'submitted')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        resp = client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert resp.status_code == 200
        assert _status(po) == 'draft', 'the order must NOT be approved'

    def test_a_rejected_source_blocks_approval(self, client, admin_user,
                                               branch_manila, vendor_acme):
        """Pulled while submitted, then rejected. Nothing unwinds the PO lines,
        so this is the only place left to catch it."""
        pr = _requisition(branch_manila, 'rejected')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'draft'

    def test_a_cancelled_source_blocks_approval(self, client, admin_user,
                                                branch_manila, vendor_acme):
        pr = _requisition(branch_manila, 'cancelled')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'draft'

    def test_the_refusal_names_the_requisition(self, client, admin_user,
                                               branch_manila, vendor_acme):
        """The buyer has to know WHICH requisition to chase. A refusal that only
        says "a source is unapproved" leaves them opening every line."""
        pr = _requisition(branch_manila, 'submitted', number='SRCA-PR-NAMED')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        resp = client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert b'SRCA-PR-NAMED' in resp.data

    def test_a_blocked_approval_writes_no_revision(self, client, admin_user,
                                                   branch_manila, vendor_acme):
        """Rev 0 is the baseline every later amendment is measured against.
        A refused approval that still claimed the slot would give the order a
        baseline it never earned."""
        pr = _requisition(branch_manila, 'submitted')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _revs(po) == []

    def test_a_submitted_source_blocks_a_SUBMITTED_order_too(
            self, client, admin_user, branch_manila, vendor_acme):
        """approve() accepts draft OR submitted. The guard has to cover both
        entry states, not just the one the happy path uses."""
        pr = _requisition(branch_manila, 'submitted')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        po.status = 'submitted'
        db.session.commit()
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'submitted'


class TestApprovalStillWorks:
    """Controls. The guard must be invisible to every order that has nothing
    wrong with it -- a false refusal here teaches buyers to delete good lines."""

    def test_an_approved_source_approves_normally(self, client, admin_user,
                                                  branch_manila, vendor_acme):
        pr = _requisition(branch_manila, 'approved')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'approved'

    def test_a_partially_converted_source_approves_normally(
            self, client, admin_user, branch_manila, vendor_acme):
        """A POST-approval state -- the second order raised against a partly
        ordered requisition is the ordinary case, not an exception."""
        pr = _requisition(branch_manila, 'partially_converted')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'approved'

    def test_an_order_with_no_requisition_source_approves_normally(
            self, client, admin_user, branch_manila, vendor_acme):
        """THE control for the services path and for every install without the
        requisition module. source_pr_item_id is NULL on every line."""
        po = _order(branch_manila, vendor_acme, None)
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert _status(po) == 'approved'

    def test_an_approved_source_still_writes_rev_0(self, client, admin_user,
                                                   branch_manila, vendor_acme):
        """The guard sits just before the status write, so it is positioned to
        break Rev 0. Pinned rather than assumed."""
        pr = _requisition(branch_manila, 'approved')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/approve', follow_redirects=True)
        assert len(_revs(po)) == 1


class TestSubmitIsNotBlocked:

    def test_submit_still_works_with_a_submitted_source(
            self, client, admin_user, branch_manila, vendor_acme):
        """Deliberate. submit() exists so a staff purchaser -- who may build an
        order but not approve one -- has a way to hand it on. Blocking submit
        would strand the order in draft and undo the whole point of letting
        staff pull early. The control is at approval, and only there.
        """
        pr = _requisition(branch_manila, 'submitted')
        po = _order(branch_manila, vendor_acme, pr.line_items[0])
        _login(client, admin_user, branch_manila)

        client.post(f'/purchase-orders/{po.id}/submit', follow_redirects=True)
        assert _status(po) == 'submitted'
