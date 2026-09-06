"""Approving a purchase order works, whatever its source requisitions look like.

HISTORY. From 2026-08-26 this file guarded the other half of that day's owner
decision: PULLABLE_PR admitted `submitted` so a staff purchaser could prepare an
order early, and approval was where the authorisation control lived instead.
On 2026-09-06 the owner removed that control -- see approve()'s own comment and
tests/integration/test_po_unapproved_source_not_blocking.py, which now pins the
reversal (a submitted, rejected or cancelled source no longer blocks approval).

TestApprovalIsBlocked went with it. What remains is still worth having and was
never about the removed gate:
  * TestApprovalStillWorks  -- the ordinary paths, and that Rev 0 is written
  * TestSubmitIsNotBlocked  -- submit() was deliberately never gated, so a staff
                               purchaser who may build but not approve an order
                               always has a way to hand it on

Every test asserts the resulting STATUS, not merely the flash. A guard that
renders a message and approves anyway is exactly the shape that a message-only
assertion calls passing.
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
