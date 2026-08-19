"""The Receiving Report's submit step, and RR in Action Items.

A receipt went draft -> approved directly, and approve is accountant-or-above,
so the staff receiver who actually counted the goods could record one and move it
nowhere. draft -> submitted -> approved mirrors the Purchase Requisition's and
Purchase Order's.

The load-bearing invariant here is NOT shared with those two: 'submitted' must
stay out of COMMITTED_STATUSES. A submitted receipt has not committed stock, so
it must not consume a purchase order line's open quantity -- otherwise submitting
a receipt would silently block a second receipt against the same order.
"""
from datetime import date

import pytest

from app import db
from app.receiving_reports.models import ReceivingReport, ReceivingReportItem
from app.settings import AppSettings

pytestmark = [pytest.mark.integration, pytest.mark.receiving_reports]


@pytest.fixture(autouse=True)
def rr_enabled(db_session):
    from app.utils.cache_helpers import clear_module_config_cache
    for k in ('products', 'purchase_orders', 'receiving_reports'):
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit()
    clear_module_config_cache()
    yield
    clear_module_config_cache()


def _login(client, user, branch):
    # Assign the branch AND open the per-user module gate: receiving_reports is
    # optional + per_user, so the instance flag alone leaves a non-full-access
    # user bounced by the module gate and every assertion passing or failing for
    # the wrong reason.
    if branch not in user.branches.all():
        user.branches.append(branch)
    if not user.has_full_access:
        perms = dict(user.get_book_permissions() or {})
        perms.update({'receiving_reports': True, 'purchase_orders': True, 'products': True})
        user.set_book_permissions(perms)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
        sess['selected_branch_id'] = branch.id


def _rr(db_session, branch, vendor, number, user_id, status='draft', with_line=True):
    rr = ReceivingReport(rr_number=number, receipt_date=date(2026, 8, 19),
                         branch_id=branch.id, vendor_id=vendor.id,
                         vendor_name=vendor.name, status=status,
                         created_by_id=user_id)
    db_session.add(rr)
    db_session.commit()
    return rr


class TestSubmitStep:

    def test_staff_can_submit_a_draft(self, client, staff_user, main_branch,
                                      vl_vendor, db_session, rr_with_line):
        from app.audit.models import AuditLog
        rr = rr_with_line
        _login(client, staff_user, main_branch)
        client.post(f'/receiving-reports/{rr.id}/submit', follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'
        assert rr.submitted_by_id == staff_user.id
        assert rr.submitted_at is not None
        assert AuditLog.query.filter_by(module='receiving_reports', action='submit').first()

    def test_a_submitted_receipt_cannot_be_submitted_again(self, client, staff_user,
                                                           main_branch, db_session,
                                                           rr_with_line):
        rr = rr_with_line
        rr.status = 'submitted'
        db_session.commit()
        _login(client, staff_user, main_branch)
        resp = client.post(f'/receiving-reports/{rr.id}/submit', follow_redirects=True)
        assert b'Only a draft Receiving Report can be submitted' in resp.data

    def test_a_receipt_with_no_lines_cannot_be_submitted(self, client, staff_user,
                                                         main_branch, vl_vendor,
                                                         db_session):
        rr = _rr(db_session, main_branch, vl_vendor, 'RRS-EMPTY', staff_user.id)
        _login(client, staff_user, main_branch)
        resp = client.post(f'/receiving-reports/{rr.id}/submit', follow_redirects=True)
        assert b'Add at least one received line' in resp.data
        db_session.refresh(rr)
        assert rr.status == 'draft'

    def test_staff_still_cannot_approve(self, client, staff_user, main_branch,
                                        db_session, rr_with_line):
        """CONTROL on the authz boundary: submit opened up, approve did not."""
        rr = rr_with_line
        rr.status = 'submitted'
        db_session.commit()
        _login(client, staff_user, main_branch)
        client.post(f'/receiving-reports/{rr.id}/approve', follow_redirects=True)
        db_session.refresh(rr)
        assert rr.status == 'submitted'


class TestTemplateGates:

    def test_staff_sees_submit_but_neither_approve_nor_cancel(
            self, client, staff_user, main_branch, db_session, rr_with_line):
        """The card used to be approver-only. Widening it for Submit must not
        expose Approve or Cancel, whose routes still refuse staff."""
        rr = rr_with_line
        _login(client, staff_user, main_branch)
        body = client.get(f'/receiving-reports/{rr.id}').data.decode()
        assert f'/receiving-reports/{rr.id}/submit' in body
        assert f'/receiving-reports/{rr.id}/approve' not in body
        assert 'Cancel RR' not in body

    def test_an_approver_sees_approve_and_cancel(self, client, admin_user, main_branch,
                                                 db_session, rr_with_line):
        """CONTROL: the widening must not have taken anything away from an approver."""
        rr = rr_with_line
        _login(client, admin_user, main_branch)
        body = client.get(f'/receiving-reports/{rr.id}').data.decode()
        assert f'/receiving-reports/{rr.id}/approve' in body
        assert 'Cancel RR' in body


class TestSubmittedDoesNotCommitStock:

    def test_submitted_is_not_a_committed_status(self):
        """The invariant that separates RR's submit from PR's and PO's: a
        submitted receipt has not moved stock, so it must not consume a purchase
        order line's open quantity. If 'submitted' joined COMMITTED_STATUSES,
        submitting one receipt would silently block the next against the same
        order."""
        from app.receiving_reports.models import COMMITTED_STATUSES
        assert 'submitted' not in COMMITTED_STATUSES
        assert set(COMMITTED_STATUSES) == {'approved', 'billed'}

    def test_submitting_leaves_the_po_line_open_quantity_untouched(
            self, client, staff_user, main_branch, db_session, rr_with_line,
            rr_po_item):
        from app.receiving_reports.models import po_line_open_qty
        before = po_line_open_qty(rr_po_item)
        _login(client, staff_user, main_branch)
        client.post(f'/receiving-reports/{rr_with_line.id}/submit', follow_redirects=True)
        db_session.refresh(rr_with_line)
        assert rr_with_line.status == 'submitted'
        assert po_line_open_qty(rr_po_item) == before


class TestActionItems:

    def test_a_draft_receipt_appears_in_the_draft_list(self, accountant_user,
                                                       main_branch, db_session,
                                                       rr_with_line):
        from app.dashboard.action_items_service import gather_draft_items
        items = gather_draft_items(accountant_user, main_branch.id)
        assert any(rr_with_line.rr_number in str(i.values()) for i in items)

    def test_a_submitted_receipt_appears_in_the_approval_list(self, accountant_user,
                                                              main_branch, db_session,
                                                              rr_with_line):
        from app.dashboard.action_items_service import gather_document_approval_items
        rr_with_line.status = 'submitted'
        db_session.commit()
        items = gather_document_approval_items(accountant_user, main_branch.id)
        assert any(rr_with_line.rr_number in str(i.values()) for i in items)

    def test_receipts_are_hidden_when_the_module_is_off(self, accountant_user,
                                                        main_branch, db_session,
                                                        rr_with_line):
        """CONTROL: Action Items must never be a side channel around the module gate."""
        from app.dashboard.action_items_service import gather_draft_items
        from app.utils.cache_helpers import clear_module_config_cache
        AppSettings.set_setting('module_enabled:receiving_reports', '0')
        db_session.commit()
        clear_module_config_cache()
        items = gather_draft_items(accountant_user, main_branch.id)
        assert not any(rr_with_line.rr_number in str(i.values()) for i in items)


@pytest.fixture
def rr_po_item(db_session, main_branch, vl_vendor, admin_user):
    """An approved PO line for the receipt to receive against."""
    from decimal import Decimal
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    po = PurchaseOrder(po_number='RRS-PO-1', order_date=date(2026, 8, 19),
                       branch_id=main_branch.id, vendor_id=vl_vendor.id,
                       vendor_name=vl_vendor.name, status='approved',
                       created_by_id=admin_user.id)
    po.line_items.append(PurchaseOrderItem(
        line_number=1, description='Salt', quantity=Decimal('10'),
        unit_price=Decimal('50'), amount=Decimal('500')))
    db_session.add(po)
    db_session.commit()
    return po.line_items[0]


@pytest.fixture
def rr_with_line(db_session, main_branch, vl_vendor, staff_user, rr_po_item):
    from decimal import Decimal
    rr = ReceivingReport(rr_number='RRS-1', receipt_date=date(2026, 8, 19),
                         branch_id=main_branch.id, vendor_id=vl_vendor.id,
                         vendor_name=vl_vendor.name, status='draft',
                         created_by_id=staff_user.id)
    rr.line_items.append(ReceivingReportItem(
        line_number=1, purchase_order_item_id=rr_po_item.id,
        received_quantity=Decimal('4')))
    db_session.add(rr)
    db_session.commit()
    return rr
